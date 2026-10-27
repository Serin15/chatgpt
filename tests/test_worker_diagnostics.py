"""Actual supervisor restart on a fixture app; no network or paid integrations."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.opportunities import Opportunities
from app.performance import Performance
from app.performance_cache import PerformanceReports
from app.service import Service
from app.workers import supervise
from tests.test_assets import FixtureAssets
from tests.test_news import FixtureNews, NewsFixtureProviders


def test_recovered_worker_retains_failure_type_time_and_sanitized_log(settings, monkeypatch, caplog):
    calls = []

    async def blocked(self):
        await asyncio.Event().wait()

    async def flaky(self):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("/private/fixture/path?token=fixture-secret")
        await asyncio.Event().wait()

    monkeypatch.setattr(Service, "run", flaky)
    for cls, method in [(Service, "run_intelligence"), (FixtureNews, "run"),
                        (FixtureAssets, "run"), (Performance, "run"),
                        (Opportunities, "run_collection_reports"), (PerformanceReports, "run")]:
        monkeypatch.setattr(cls, method, blocked)
    app = create_app(settings, NewsFixtureProviders(), True, FixtureNews, FixtureAssets)
    with TestClient(app) as client:
        deadline = time.monotonic() + 8
        while len(calls) < 2 and time.monotonic() < deadline:
            time.sleep(.02)
        worker = client.get("/api/status").json()["workers"]["scanner"]
        assert worker["state"] == "running" and worker["error"] is None
        assert worker["restarts"] == 1
        assert worker["last_error"] == "RuntimeError"
        assert worker["last_error_at"] is not None
        assert "RuntimeError" in caplog.text
        assert "fixture-secret" not in caplog.text


def test_repeated_failures_have_bounded_history_and_cancellation_stops_retries():
    async def run():
        workers, calls = {}, []
        recovered = asyncio.Event()

        async def flaky():
            calls.append(True)
            if len(calls) <= 8:
                raise TimeoutError("explicit fixture")
            recovered.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(supervise("fixture", flaky, workers, retry_seconds=0))
        await recovered.wait()
        assert len(workers["fixture"]["error_history"]) == 5
        assert workers["fixture"]["restarts"] == 8
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(calls) == 9 and workers["fixture"]["state"] == "stopped"
        assert workers["fixture"]["last_error"] == "TimeoutError"

    asyncio.run(run())


def test_cancel_during_backoff_keeps_failure_history_without_retrying():
    async def run():
        workers, calls = {}, []

        async def fail():
            calls.append(True)
            raise ValueError("explicit fixture")

        task = asyncio.create_task(supervise("fixture", fail, workers, retry_seconds=60))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert calls == [True] and workers["fixture"]["state"] == "stopped"
        assert workers["fixture"]["last_error"] == "ValueError"

    asyncio.run(run())
