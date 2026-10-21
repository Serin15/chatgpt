"""Collector/report isolation with real SQLite, explicit simulated providers."""

import asyncio

from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import source_item


def test_history_report_is_not_built_in_urgent_collection_cycle(client_engine, monkeypatch):
    _, engine = client_engine
    engine.service.discovery.save(source_item())

    def slow_history():
        raise AssertionError("Urgent collection must not wait for a full-history report")

    monkeypatch.setattr(engine.sampling, "coverage", slow_history)
    result = asyncio.run(engine.cycle(False))
    assert result["observed"] == 1


def test_cached_report_preserves_calculation_timestamp_and_reports_refresh_failure(
    client_engine, monkeypatch
):
    client, engine = client_engine
    engine.service.discovery.save(source_item())
    asyncio.run(engine.cycle(False))
    first = client.get("/api/opportunities/coverage").json()
    assert first["report_cache"]["served_from_cache"] is False
    assert first["generated_at"] == first["report_cache"]["calculated_at"]

    def failed():
        raise ValueError("Explicit fixture report failure")

    monkeypatch.setattr(engine.sampling, "coverage", failed)
    import pytest

    with pytest.raises(ValueError):
        asyncio.run(engine.run_collection_reports())
    second = client.get("/api/opportunities/coverage").json()
    assert second["generated_at"] == first["generated_at"]
    assert second["report_cache"]["served_from_cache"] is True
    assert second["report_cache"]["refresh"]["state"] == "error"
    assert second["groups"] == first["groups"]
    assert client.get("/api/opportunities").status_code == 200


def test_initial_background_report_does_not_block_api_requests(client_engine, monkeypatch):
    client, engine = client_engine
    engine.collection_refresh = {"state": "running"}

    def must_not_repeat():
        raise AssertionError("A background calculation is already in progress")

    monkeypatch.setattr(engine.sampling, "coverage", must_not_repeat)
    response = client.get("/api/opportunities/coverage")
    assert response.status_code == 503
    assert "în fundal" in response.json()["detail"]
    assert client.get("/api/opportunities").status_code == 200
