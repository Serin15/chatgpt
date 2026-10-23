"""Exact-contract lookup must not scan every pool on the chain."""

import json

from app.discovery import Discovery
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import source_item

QUERY = "SELECT payload FROM discovered_pools WHERE chain='solana' AND contract=? AND json_extract(payload,'$.promotion') IS NOT NULL ORDER BY last_seen_at DESC LIMIT 1"


def test_contract_lookup_preserves_latest_promotion_and_uses_contract_index(client_engine):
    _, engine = client_engine
    original = source_item()
    engine.service.discovery.save(original | {"promotion": {"fixture": "first"}})
    engine.service.discovery.save(
        original | {"pool": original["contract"], "promotion": {"fixture": "latest"}}
    )
    with engine.store.connect() as db:
        db.execute("DROP INDEX IF EXISTS discovered_pools_contract")
        db.execute(
            "UPDATE discovered_pools SET last_seen_at='2030-01-01T00:00:00+00:00' WHERE pool=?",
            (original["contract"],),
        )
        before = [tuple(r) for r in db.execute(QUERY, (original["contract"],))]
        assert json.loads(before[0][0])["promotion"]["fixture"] == "latest"
    # Idempotent upgrade on an existing database, not a fresh empty schema.
    Discovery(engine.store, client=engine.service.discovery.client)
    with engine.store.connect() as db:
        after = [tuple(r) for r in db.execute(QUERY, (original["contract"],))]
        plan = [r[3] for r in db.execute("EXPLAIN QUERY PLAN " + QUERY, (original["contract"],))]
    assert before == after
    assert any("contract=?" in detail for detail in plan), plan
