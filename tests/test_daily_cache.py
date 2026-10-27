"""SQLite/subprocess regressions with explicit fixture providers, not live signals."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest

from app.daily_cache import MAX_DAYS, DailyReports
from app.daily_research import daily_report
from app.models import utcnow
from app.performance_worker import ReadEngine
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, seed


def report(day, count=17):
    return {
        "version": "daily-discovery-v1",
        "day_utc": day.isoformat(),
        "generated_at": utcnow(),
        "totals": {"discovered": count},
        "models": {},
    }


def fake_calculator(monkeypatch, value=None, error=None):
    async def calculate(worker):
        if error:
            raise error
        worker._publish(value or report(worker.day), worker._begin(), "isolated_read_only_process")

    monkeypatch.setattr("app.daily_cache.PerformanceReports.calculate_external", calculate)


def calculate(cache, day):
    cache.request(day)
    assert asyncio.run(cache.calculate_next())
    return cache.request(day)


def test_daily_http_does_not_wait_for_an_expensive_report(client_engine, monkeypatch):
    client, engine = client_engine
    cache = client.app.state.daily_reports = DailyReports(engine)
    entered, release = Event(), Event()
    calls = []

    async def slow(worker):
        calls.append(1)
        clocks = worker._begin()
        entered.set()
        assert await asyncio.to_thread(release.wait, 5)
        worker._publish(report(worker.day), clocks, "isolated_read_only_process")

    monkeypatch.setattr("app.daily_cache.PerformanceReports.calculate_external", slow)
    assert client.get("/api/opportunities/daily").status_code == 202
    with ThreadPoolExecutor(max_workers=2) as pool:
        work = pool.submit(asyncio.run, cache.calculate_next())
        try:
            assert entered.wait(2)
            response = pool.submit(client.get, "/api/opportunities/daily").result(2)
            assert response.status_code == 202
            assert not work.done() and calls == [1]
            assert client.get("/api/opportunities").status_code == 200
            assert len(cache.pending) == 0
        finally:
            release.set()
        work.result(4)
    assert client.get("/api/opportunities/daily").json()["totals"]["discovered"] == 17


def test_snapshot_survives_restart_without_new_generated_timestamp(client_engine, monkeypatch):
    _, engine = client_engine
    cache = DailyReports(engine)
    fake_calculator(monkeypatch)
    original = calculate(cache, cache.today())
    restored = DailyReports(engine).request(cache.today())
    assert restored["generated_at"] == original["generated_at"]
    assert restored["report_cache"]["snapshot_at"] == original["generated_at"]
    assert restored["totals"] == original["totals"]
    restored["totals"]["discovered"] = -5
    assert cache.request(cache.today())["totals"]["discovered"] == 17


def test_refresh_failure_retains_dated_data_and_diagnostics_across_restart(
    client_engine, monkeypatch
):
    _, engine = client_engine
    cache = DailyReports(engine, refresh_seconds=0)
    fake_calculator(monkeypatch)
    original = calculate(cache, cache.today())
    fake_calculator(monkeypatch, error=ValueError("must-not-leak-secret-or-path"))
    failed = calculate(cache, cache.today())
    assert failed["generated_at"] == original["generated_at"]
    assert failed["totals"] == original["totals"]
    restored = DailyReports(engine)
    result = restored.request(cache.today())
    assert result["report_cache"]["refresh"]["last_error"] == "ValueError"
    assert "must-not-leak" not in json.dumps(result)
    assert restored.status()["state"] == "error"
    fake_calculator(monkeypatch)
    result = calculate(restored, cache.today())
    assert result["report_cache"]["refresh"]["state"] == "ok"
    assert result["report_cache"]["refresh"]["last_error"] == "ValueError"


def test_failed_cold_calculation_is_not_an_empty_successful_report(client_engine, monkeypatch):
    _, engine = client_engine
    cache = DailyReports(engine)
    fake_calculator(monkeypatch, error=TimeoutError("private message"))
    result = calculate(cache, cache.today())
    assert result["report_state"] == "preparing" and "totals" not in result
    restored = DailyReports(engine).request(cache.today())
    assert restored["report_cache"]["refresh"]["last_error"] == "TimeoutError"


def test_stale_snapshot_and_future_clock_remain_explicit(client_engine, monkeypatch):
    _, engine = client_engine
    cache = DailyReports(engine)
    value = report(cache.today())
    value["generated_at"] = "2020-01-01T00:00:00+00:00"
    fake_calculator(monkeypatch, value)
    assert calculate(cache, cache.today())["report_cache"]["stale"]
    cache.entries[cache.today().isoformat()]["data"]["generated_at"] = "2099-01-01T00:00:00+00:00"
    assert cache.request(cache.today())["report_cache"]["stale"]


def test_queue_is_bounded_and_duplicates_do_not_spawn_extra_work(client_engine):
    _, engine = client_engine
    cache = DailyReports(engine)
    today = cache.today()
    for _ in range(10):
        cache.request(today)
    assert len(cache.pending) == 1
    for days in range(1, MAX_DAYS):
        cache.request(today - timedelta(days=days))
    result = cache.request(today - timedelta(days=MAX_DAYS))
    assert result["report_cache"]["refresh"]["state"] == "busy"
    assert len(cache.entries) == len(cache.pending) == MAX_DAYS
    with pytest.raises(ValueError):
        cache.request(today + timedelta(days=1))


def test_lru_eviction_never_deletes_research_rows(client_engine, monkeypatch):
    _, engine = client_engine
    candidate, policy, config = seed(engine)
    import time

    engine.save_observation(candidate, payload(engine, candidate, time.time()), policy, config)
    cache = DailyReports(engine)
    fake_calculator(monkeypatch)
    with engine.store.connect() as db:
        before = [tuple(r) for r in db.execute("SELECT * FROM opportunity_signals")]
    for days in range(MAX_DAYS + 3):
        calculate(cache, cache.today() - timedelta(days=days))
    assert len(cache.entries) == MAX_DAYS
    with cache._connect() as db:
        assert db.execute("SELECT count(*) FROM reports").fetchone()[0] == MAX_DAYS
    with engine.store.connect() as db:
        assert before == [tuple(r) for r in db.execute("SELECT * FROM opportunity_signals")]


def test_cache_corruption_does_not_stop_fresh_calculations(client_engine, monkeypatch):
    _, engine = client_engine
    cache = DailyReports(engine)
    cache.path.write_bytes(b"explicit corrupt disposable cache")
    restored = DailyReports(engine)
    assert restored.persistence_error == "DatabaseError"
    fake_calculator(monkeypatch)
    assert calculate(restored, cache.today())["totals"]["discovered"] == 17
    assert restored.status()["state"] == "partial"


def test_replaced_source_database_does_not_reuse_an_unrelated_cached_report(
    client_engine, monkeypatch
):
    _, engine = client_engine
    cache = DailyReports(engine)
    fake_calculator(monkeypatch)
    calculate(cache, cache.today())
    replacement = engine.store.path.with_suffix(".replacement")
    import sqlite3

    with engine.store.connect() as source, sqlite3.connect(replacement) as target:
        source.backup(target)
    replacement.replace(engine.store.path)
    restored = DailyReports(engine)
    assert restored.identity != cache.identity
    assert restored.request(cache.today())["report_state"] == "preparing"


def test_real_read_only_daily_worker_matches_direct_report_and_keeps_study_intact(
    client_engine, monkeypatch
):
    _, engine = client_engine
    candidate, policy, config = seed(engine)
    import time

    engine.save_observation(candidate, payload(engine, candidate, time.time() - 5), policy, config)
    at = utcnow()
    monkeypatch.setattr("app.daily_research.utcnow", lambda: at)
    expected = daily_report(engine)
    reader = ReadEngine(
        engine.store.path, engine.service.news_paper.path, engine.service.settings.max_snapshot_age
    )
    assert daily_report(reader) == expected
    with engine.store.connect() as db:
        before = [tuple(r) for r in db.execute("SELECT * FROM opportunity_signals")]
    cache = DailyReports(engine)
    result = calculate(cache, cache.today())
    assert result["totals"] == expected["totals"]
    assert result["first_verdicts"] == expected["first_verdicts"]
    assert result["report_cache"]["calculation_mode"] == "isolated_read_only_process"
    assert result["generated_at"] == result["report_cache"]["snapshot_at"]
    with engine.store.connect() as db:
        assert before == [tuple(r) for r in db.execute("SELECT * FROM opportunity_signals")]


def test_interrupted_refresh_keeps_last_complete_snapshot(client_engine, monkeypatch):
    _, engine = client_engine
    cache = DailyReports(engine, refresh_seconds=0)
    fake_calculator(monkeypatch)
    original = calculate(cache, cache.today())

    async def interrupted(worker):
        raise asyncio.CancelledError()

    monkeypatch.setattr("app.daily_cache.PerformanceReports.calculate_external", interrupted)
    cache.request(cache.today())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cache.calculate_next())
    assert cache.active is None
    restored = DailyReports(engine).request(cache.today())
    assert restored["generated_at"] == original["generated_at"]
    assert restored["report_cache"]["refresh"]["state"] == "interrupted"


def test_crash_during_refresh_restores_interruption_instead_of_permanent_running(
    client_engine, monkeypatch
):
    _, engine = client_engine
    cache = DailyReports(engine)
    fake_calculator(monkeypatch)
    original = calculate(cache, cache.today())
    key = cache.today().isoformat()
    entry = cache.entries[key]
    entry["refresh"]["state"] = "running"
    cache._persist(key, entry)
    restored = DailyReports(engine).request(cache.today())
    assert restored["generated_at"] == original["generated_at"]
    assert restored["report_cache"]["refresh"]["state"] == "interrupted"
    assert restored["report_cache"]["refresh"]["last_error"] == "InterruptedRefresh"


def test_cancelled_daily_job_reaps_real_child_and_persists_diagnostics(client_engine, monkeypatch):
    import sys

    _, engine = client_engine
    cache = DailyReports(engine)
    cache.request(cache.today())
    original = asyncio.create_subprocess_exec
    children = []

    async def run():
        started = asyncio.Event()

        async def slow(*args, **kwargs):
            child = await original(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
            children.append(child)
            started.set()
            return child

        monkeypatch.setattr(asyncio, "create_subprocess_exec", slow)
        task = asyncio.create_task(cache.calculate_next())
        try:
            await asyncio.wait_for(started.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            for child in children:
                if child.returncode is None:
                    child.kill()
                    await child.wait()

    asyncio.run(run())
    assert cache.active is None and children[0].returncode is not None
    restored = DailyReports(engine).request(cache.today())
    assert restored["report_cache"]["refresh"]["last_error"] == "CancelledError"


@pytest.mark.parametrize("problem", ["oversized", "nonfinite"])
def test_invalid_large_report_never_replaces_last_complete_snapshot(
    client_engine, monkeypatch, problem
):
    _, engine = client_engine
    cache = DailyReports(engine, refresh_seconds=0)
    fake_calculator(monkeypatch)
    original = calculate(cache, cache.today())
    value = report(cache.today(), count=99)
    if problem == "oversized":
        monkeypatch.setattr("app.daily_cache.MAX_BYTES", 12000)
        value["details"] = "x" * 20000
    else:
        value["bad"] = float("nan")
    fake_calculator(monkeypatch, value)
    result = calculate(cache, cache.today())
    assert result["totals"] == original["totals"]
    assert result["generated_at"] == original["generated_at"]
    assert result["report_cache"]["refresh"]["last_error"] == "ValueError"


def test_background_scheduling_does_not_copy_a_complete_report_every_tick(
    client_engine, monkeypatch
):
    import app.daily_cache as module

    _, engine = client_engine
    cache = DailyReports(engine)
    fake_calculator(monkeypatch)
    calculate(cache, cache.today())
    original = module.deepcopy

    def guarded(value):
        assert value is not cache.entries[cache.today().isoformat()]["data"], (
            "Idle worker copied the full report"
        )
        return original(value)

    async def stop():
        raise asyncio.CancelledError()

    monkeypatch.setattr(module, "deepcopy", guarded)
    monkeypatch.setattr(cache, "calculate_next", stop)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cache.run())


def test_http_reuses_complete_encoded_generation_and_updates_only_metadata(
    client_engine, monkeypatch
):
    import app.daily_cache as module

    client, engine = client_engine
    cache = client.app.state.daily_reports = DailyReports(engine)
    fake_calculator(monkeypatch)
    expected = calculate(cache, cache.today())
    original = module.deepcopy

    def guarded(value):
        assert value is not cache.entries[cache.today().isoformat()]["data"], (
            "HTTP rebuilt the full report"
        )
        return original(value)

    monkeypatch.setattr(module, "deepcopy", guarded)
    response = client.get("/api/opportunities/daily")
    assert response.status_code == 200
    result = response.json()
    assert {k: v for k, v in result.items() if k != "report_cache"} == {
        k: v for k, v in expected.items() if k != "report_cache"
    }
    cache.entries[cache.today().isoformat()]["refresh"].update(state="error", error="TimeoutError")
    updated = client.get("/api/opportunities/daily").json()
    assert updated["report_cache"]["refresh"]["error"] == "TimeoutError"
    assert updated["totals"] == expected["totals"]
