"""Projection/legacy equivalence on real SQLite, including cold and dirty history."""

import json
import sqlite3
import time

import pytest

from app.archive_codec import encode
from app.performance_reporting import report
from app.storage import archive_database, logical_manifest
from tests.test_observation_sampling import candidate
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, seed, stamp


@pytest.mark.parametrize("ranked,query,verdict", [
    (False, "", "all"), (True, "", "all"), (False, "missing", "all"),
    (True, "știre", "all"), (False, "", "MONITOR"), (True, "", "REJECT"),
])
def test_catalog_matches_legacy_listing_exactly(client_engine, monkeypatch, ranked, query, verdict):
    client, engine = client_engine
    clock = time.time()
    for i in range(12):
        c = candidate(engine, 73000 + i, clock - 1000)
        p, cfg = engine.policy(engine.config()), engine.config()
        at = clock - (500 if i % 3 == 0 else 2)
        value = payload(engine, c, at, unsafe=i % 2 == 0)
        value["market"]["name"] = "Știre Straße " + str(i)
        engine.save_observation(c, value, p, cfg, stamp(at))
    monkeypatch.setattr("app.opportunities.time.time", lambda: clock)
    original = engine.listing(5, None, ranked, query, verdict)
    actual = client.app.state.catalog.listing(5, None, ranked, query, verdict)
    assert actual == original
    if actual["next_cursor"]:
        assert client.app.state.catalog.listing(5, actual["next_cursor"], ranked, query, verdict) == engine.listing(5, actual["next_cursor"], ranked, query, verdict)


def test_search_uses_projection_without_decoding_unrelated_large_observations(client_engine, monkeypatch):
    client, engine = client_engine
    c, p, cfg = seed(engine)
    value = payload(engine, c, time.time())
    value["unused_provider_payload"] = "fixture " * 20000
    engine.save_observation(c, value, p, cfg)
    client.app.state.catalog.refresh()
    with engine.store.connect() as db:
        db.execute("UPDATE opportunity_candidates SET next_due=next_due+1 WHERE id=?", (c["id"],))
    decoded = []
    from app.archive_codec import decode

    def watch(value):
        if isinstance(value, str) and "unused_provider_payload" in value:
            decoded.append(True)
        return decode(value)

    monkeypatch.setattr("app.archive_codec.decode", watch)
    response = client.get("/api/opportunities", params={"q": "unmatched phrase"})
    assert response.status_code == 200 and response.json()["matching_total"] == 0
    assert decoded == []


def test_native_triggers_cover_raw_sql_updates_and_deletes(client_engine):
    client, engine = client_engine
    c, p, cfg = seed(engine)
    engine.save_observation(c, payload(engine, c, time.time()), p, cfg)
    catalog = client.app.state.catalog
    catalog.refresh()
    # Plain sqlite3 has no application UDFs; enqueuing must still work.
    with sqlite3.connect(engine.store.path) as db:
        db.execute("UPDATE opportunity_candidates SET discovery=json_set(discovery,'$.name','Unicode STRASSE') WHERE id=?", (c["id"],))
    assert catalog.listing(query="straße")["matching_total"] == 1
    with sqlite3.connect(engine.store.path) as db:
        db.execute("DELETE FROM opportunity_observations WHERE candidate_id=?", (c["id"],))
    result = catalog.listing()
    assert result["items"][0]["latest"] is None
    with sqlite3.connect(engine.store.path) as db:
        db.execute("DELETE FROM opportunity_candidates WHERE id=?", (c["id"],))
    assert catalog.listing()["matching_total"] == 0


@pytest.mark.parametrize("dirty", [False, True])
def test_full_report_matches_legacy_on_cached_and_pending_subjects(client_engine, monkeypatch, dirty):
    client, engine = client_engine
    c, p, cfg = seed(engine)
    clock = time.time()
    monkeypatch.setattr("app.opportunity_sampling.utcnow", lambda: stamp(clock))
    monkeypatch.setattr("app.opportunity_sampling.time.time", lambda: clock)
    engine.save_observation(c, payload(engine, c, clock - 1000), p, cfg, stamp(clock - 1000))
    engine.update_outcomes(clock)
    catalog = client.app.state.catalog
    catalog.refresh()
    if dirty:
        engine.save_observation(c, payload(engine, c, clock - 1, price=3), p, cfg, stamp(clock - 1))
    actual = report(engine, clock)
    monkeypatch.setattr("app.performance_reporting.catalog_available", lambda _: False)
    assert actual == report(engine, clock)


def test_archival_keeps_logical_history_identical_and_cache_rebuilds(client_engine):
    client, engine = client_engine
    c, p, cfg = seed(engine)
    clock = time.time()
    for at in [clock - 10 * 86400, clock - 2]:
        engine.save_observation(c, payload(engine, c, at), p, cfg, stamp(at))
    catalog = client.app.state.catalog
    catalog.refresh()
    before = logical_manifest(engine.store.path)
    archive_database(engine.store.path, stamp(clock - 3 * 86400))
    assert before == logical_manifest(engine.store.path)
    assert catalog.listing()["items"]
    assert before == logical_manifest(engine.store.path)


def test_latest_cold_blob_is_readable_and_refresh_preserves_payload(client_engine):
    client, engine = client_engine
    c, p, cfg = seed(engine)
    value = payload(engine, c, time.time())
    value["repeated"] = "fixture " * 20000
    engine.save_observation(c, value, p, cfg)
    with engine.store.connect() as db:
        row = db.execute("SELECT id,payload FROM opportunity_observations").fetchone()
        db.execute("UPDATE opportunity_observations SET payload=? WHERE id=?", (encode(row["payload"]), row["id"]))
    assert client.app.state.catalog.listing(query="unmatched")["matching_total"] == 0
    assert client.app.state.catalog.listing()["items"][0]["latest"] == json.loads(row["payload"])


def test_projection_read_allows_writer_and_retries_a_changed_subject(client_engine, monkeypatch):
    client, engine = client_engine
    c, _, _ = seed(engine)
    from app.archive_codec import decode

    wrote = []

    def concurrent_write(value):
        if not wrote and isinstance(value, str) and "Explicit fixture" in value:
            with sqlite3.connect(engine.store.path, timeout=.05) as other:
                other.execute("UPDATE opportunity_candidates SET discovery=json_set(discovery,'$.name','Updated while reading') WHERE id=?", (c["id"],))
            wrote.append(True)
        return decode(value)

    monkeypatch.setattr("app.archive_codec.decode", concurrent_write)
    client.app.state.catalog.refresh()
    assert wrote and client.app.state.catalog.status()["pending_subjects"] == 1
    assert client.app.state.catalog.listing(query="updated while reading")["matching_total"] == 1


def test_busy_refresh_overlays_new_data_without_stale_search_or_count(client_engine):
    client, engine = client_engine
    c, p, cfg = seed(engine)
    engine.save_observation(c, payload(engine, c, time.time()), p, cfg)
    catalog = client.app.state.catalog
    catalog.refresh()
    with engine.store.connect() as db:
        db.execute("UPDATE opportunity_candidates SET discovery=json_set(discovery,'$.name','Changed during refresh') WHERE id=?", (c["id"],))
    assert catalog.lock.acquire(blocking=False)
    try:
        result = client.get("/api/opportunities", params={"q":"changed during refresh","sort":"rank"})
        assert result.status_code == 200 and result.json()["matching_total"] == 1
    finally:
        catalog.lock.release()
