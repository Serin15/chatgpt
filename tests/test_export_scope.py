"""Exports load referenced manual history, never unrelated research snapshots."""

import json

from app import archive_codec
from app.models import utcnow
from tests.conftest import ADDRESS, market, security
from tests.test_opportunities import client_engine as client_engine


def test_empty_manual_export_does_not_decode_unrelated_research_payloads(client_engine, monkeypatch):
    client, engine = client_engine
    marker = json.dumps({"unused_fixture":"x" * 50000})
    with engine.store.connect() as db:
        db.execute("INSERT INTO snapshots(address,at,market,security,analysis) VALUES(?,?,?,?,?)",
                   (ADDRESS,utcnow(),marker,"{}","{}"))
    decoded = []
    original = archive_codec.decode

    def observe(value):
        if value == marker:
            decoded.append(True)
        return original(value)

    monkeypatch.setattr(archive_codec, "decode", observe)
    result = client.get("/api/export?account=scanner")
    assert result.status_code == 200
    assert result.json()["snapshots"] == [] and result.json()["orders"] == []
    assert decoded == [], "Unrelated research history was read for an empty manual account"


def test_export_preserves_referenced_snapshot_and_original_signal(client_engine):
    client, engine = client_engine
    first = engine.store.save_snapshot(market(ADDRESS),security(),{"paper_allowed":True})
    engine.store.save_snapshot(market(ADDRESS,price_usd=2),security(),{"paper_allowed":True})
    with engine.store.connect() as db:
        db.execute("INSERT INTO signals(address,at,snapshot_id,evidence) VALUES(?,?,?,?)",
                   (ADDRESS,utcnow(),first,json.dumps({"thesis":"original fixture thesis"})))
    data = client.get("/api/export?account=scanner").json()
    assert [s["id"] for s in data["snapshots"]] == [first]
    assert data["signals"][0]["evidence"]["thesis"] == "original fixture thesis"
