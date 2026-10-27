"""Real fixture SQLite/reader subprocess; no Jupiter calls or real swaps."""

import asyncio
from copy import deepcopy

import pytest

from app.performance_cache import PerformanceReports
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, seed


@pytest.mark.parametrize("warm", [False, True])
def test_routes_api_reads_snapshot_without_starting_inline_history_work(
    client_engine, monkeypatch, warm
):
    client, engine = client_engine
    expected = engine.routes.report()
    cache = client.app.state.routed_reports = PerformanceReports(engine)
    cache.kind = "routes"
    if warm:
        cache._publish(expected, cache._begin(), "fixture_read_only")

    def forbidden():
        raise AssertionError("HTTP requests must not compute full routed history")

    monkeypatch.setattr(engine.routes, "report", forbidden)
    response = client.get("/api/opportunities/routes")
    assert response.status_code == (200 if warm else 503)
    if warm:
        body = response.json()
        assert body["entry_states"] == expected["entry_states"]
        assert body["report_cache"]["served_from_cache"] is True
    else:
        assert "în fundal" in response.json()["detail"]
    assert client.get("/api/opportunities").status_code == 200


def test_routes_reader_subprocess_matches_inline_report_and_preserves_research(client_engine):
    _, engine = client_engine
    candidate, policy, config = seed(engine)
    engine.save_observation(candidate, payload(engine, candidate, 1), policy, config)
    expected = deepcopy(engine.routes.report())
    with engine.store.connect() as db:
        before = [tuple(r) for r in db.execute("SELECT * FROM opportunity_signals")]
    cache = PerformanceReports(engine)
    cache.kind = "routes"
    asyncio.run(cache.calculate_external())
    actual = cache.read()
    actual.pop("report_cache")
    actual.pop("generated_at")
    assert actual == expected
    with engine.store.connect() as db:
        assert [tuple(r) for r in db.execute("SELECT * FROM opportunity_signals")] == before
