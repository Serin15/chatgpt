"""SQL filters/ranking must read the same logical payload after cold archival."""

import json
import sqlite3
import time

import pytest

from app.archive_codec import encode
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, seed


def test_rank_search_and_verdict_filters_support_archived_latest_observation(client_engine):
    client, engine = client_engine
    candidate, policy, config = seed(engine)
    engine.save_observation(candidate, payload(engine, candidate, time.time()), policy, config)
    before = client.get("/api/opportunities?sort=rank&verdict=INVESTIGATE").json()
    with engine.store.connect() as db:
        row = db.execute(
            "SELECT id,payload FROM opportunity_observations ORDER BY id DESC LIMIT 1"
        ).fetchone()
        packed = encode(row["payload"])
        assert isinstance(packed, bytes)
        # Reproduce the previous query failure on the actual archive codec.
        with pytest.raises(sqlite3.OperationalError, match="malformed JSON"):
            db.execute("SELECT json_extract(?,'$.decision.verdict')", (packed,)).fetchone()
        db.execute("UPDATE opportunity_observations SET payload=? WHERE id=?", (packed, row["id"]))
    after = client.get("/api/opportunities?sort=rank&verdict=INVESTIGATE")
    assert after.status_code == 200
    assert [v["id"] for v in after.json()["items"]] == [v["id"] for v in before["items"]]
    assert after.json()["items"][0]["latest"] == json.loads(row["payload"])
    name = before["items"][0]["latest"]["market"]["symbol"]
    searched = client.get("/api/opportunities", params={"q": name, "verdict": "INVESTIGATE"})
    assert searched.status_code == 200 and len(searched.json()["items"]) == 1
