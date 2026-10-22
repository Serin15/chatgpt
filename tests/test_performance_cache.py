"""Reports use real fixture SQLite and explicit fake clocks/providers, never live quotes."""

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
from threading import Event
from types import SimpleNamespace

import pytest

from app.errors import ProviderError
from app.opportunity_outcomes import summary
from app.performance_cache import PerformanceReports
from app.performance_reporting import Aggregate, report
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, seed


def test_streamed_summary_preserves_exact_decimal_costs_and_missing_denominator():
    rows = [
        {"state": state, "payload": {"pnl_usd": value}}
        for state, value in [
            ("evaluated", "1234567890123456789012345678"),
            ("evaluated", "0.000000000000000007"),
            ("pending", None),
            ("evaluated", "-1234567890123456789012345678"),
            ("evaluated", "-0.123456789123456789"),
            ("evaluated", "0"),
            ("entry_unavailable", None),
            ("exit_unavailable", None),
        ]
    ]
    aggregate = Aggregate()
    for row in rows:
        aggregate.add(
            row["state"],
            Decimal(row["payload"]["pnl_usd"]) if row["state"] == "evaluated" else None,
        )
    assert aggregate.result() == summary(rows)


def test_report_uses_original_embedded_policy_and_preserves_unavailable_results(client_engine):
    import time

    _, engine = client_engine
    candidate, policy, config = seed(engine)
    at = time.time() - 1000
    engine.save_observation(candidate, payload(engine, candidate, at), policy, config)
    with engine.store.connect() as db:
        sid = db.execute("SELECT id FROM opportunity_signals WHERE kind='baseline'").fetchone()[0]
        db.execute(
            "UPDATE opportunity_outcomes SET state='exit_unavailable' WHERE signal_id=?", (sid,)
        )
        before = [tuple(r) for r in db.execute("SELECT * FROM opportunity_signals")]
    result = report(engine)
    for horizon in config.horizons_seconds:
        group = result["horizons"][str(horizon)]
        assert group["all_eligible_first_evaluations"]["states"] == {"exit_unavailable": 1}
        assert group["all_eligible_first_evaluations"]["mean_net_pnl_usd"] is None
        assert str(policy["id"]) in group["policies"]
    with engine.store.connect() as db:
        assert [tuple(r) for r in db.execute("SELECT * FROM opportunity_signals")] == before


def test_cold_report_api_is_fast_and_never_starts_a_duplicate_calculation(
    client_engine, monkeypatch
):
    client, engine = client_engine
    cache = client.app.state.performance_reports = PerformanceReports(engine)
    entered, release = Event(), Event()
    calls = []

    def compute():
        calls.append(1)
        entered.set()
        assert release.wait(3)
        return {"totals": {"discovered": 1}, "nested": []}

    monkeypatch.setattr(engine, "report", compute)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(cache.calculate)
        assert entered.wait(2)
        try:
            response = client.get("/api/opportunities/performance")
            assert response.status_code == 503
            assert "în fundal" in response.json()["detail"]
            assert client.get("/api/opportunities").status_code == 200
            assert calls == [1] and not future.done()
        finally:
            release.set()
        future.result(3)
    a = client.get("/api/opportunities/performance").json()
    a["nested"].append("caller mutation")
    b = client.get("/api/opportunities/performance").json()
    assert b["nested"] == [] and calls == [1]
    assert b["report_cache"]["served_from_cache"] is True


def test_refresh_failure_retains_last_complete_snapshot_and_exposes_error(
    client_engine, monkeypatch
):
    _, engine = client_engine
    cache = PerformanceReports(engine)
    monkeypatch.setattr(engine, "report", lambda: {"totals": {"discovered": 11}})
    cache.calculate()
    first = cache.read()

    def failure():
        raise ValueError("Explicit fixture calculation error")

    monkeypatch.setattr(engine, "report", failure)
    with pytest.raises(ValueError):
        cache.calculate()
    latest = cache.read()
    assert latest["totals"] == first["totals"]
    assert latest["generated_at"] == first["generated_at"]
    assert latest["report_cache"]["calculated_at"] == first["report_cache"]["calculated_at"]
    assert latest["report_cache"]["refresh"]["state"] == "error"


def test_staleness_includes_computation_time_and_failed_cold_start_is_explicit(
    client_engine, monkeypatch
):
    import app.performance_cache as module

    _, engine = client_engine
    cache = PerformanceReports(engine)
    clock = [100.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def compute():
        clock[0] += 130
        return {"totals": {"discovered": 12}}

    monkeypatch.setattr(engine, "report", compute)
    cache.calculate()
    assert cache.read()["report_cache"]["stale"] is True
    assert cache.read()["report_cache"]["seconds_since_calculation"] == 0
    empty = PerformanceReports(engine)
    empty.refresh = {"state": "error"}
    with pytest.raises(ProviderError, match="nu a putut"):
        empty.read()


def test_cache_timestamp_and_body_are_from_same_published_generation(client_engine, monkeypatch):
    import app.performance_cache as module

    _, engine = client_engine
    cache = PerformanceReports(engine)
    monkeypatch.setattr(engine, "report", lambda: {"totals": {"discovered": 11}})
    cache.calculate()
    old = cache.snapshot
    new = deepcopy(old)
    new["data"]["totals"]["discovered"] = 99
    new["generated_at"] = "2030-01-01T00:00:00Z"

    def publish_during_copy(value):
        if value is old["data"]:
            cache.snapshot = new
        return deepcopy(value)

    monkeypatch.setattr(module, "deepcopy", publish_during_copy)
    response = cache.read()
    assert response["totals"]["discovered"] == 11
    assert response["generated_at"] == old["generated_at"]
    assert cache.read()["totals"]["discovered"] == 99


def test_real_read_only_subprocess_preserves_database_and_returns_full_report(client_engine):
    client, engine = client_engine
    candidate, policy, config = seed(engine)
    import time

    engine.save_observation(candidate, payload(engine, candidate, time.time()), policy, config)
    with engine.store.connect() as db:
        before = [tuple(row) for row in db.execute("SELECT * FROM opportunity_signals")]
        schema = db.execute("PRAGMA schema_version").fetchone()[0]
    cache = PerformanceReports(engine)
    asyncio.run(cache.calculate_external())
    result = cache.read()
    assert result["totals"]["discovered"] == 1
    assert result["horizons"]["300"]["all_eligible_first_evaluations"]["experiments"] == 1
    assert result["report_cache"]["calculation_mode"] == "isolated_read_only_process"
    with engine.store.connect() as db:
        assert before == [tuple(row) for row in db.execute("SELECT * FROM opportunity_signals")]
        assert db.execute("PRAGMA schema_version").fetchone()[0] == schema
    assert not client.get("/api/portfolio?account=news").json()["orders"]


def test_cancelled_report_terminates_and_reaps_its_real_subprocess(client_engine, monkeypatch):
    _, engine = client_engine
    cache = PerformanceReports(engine)
    original = asyncio.create_subprocess_exec
    processes = []

    async def run():
        started = asyncio.Event()

        async def slow_child(*args, **kwargs):
            child = await original(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
            processes.append(child)
            started.set()
            return child

        monkeypatch.setattr(asyncio, "create_subprocess_exec", slow_child)
        task = asyncio.create_task(cache.calculate_external())
        try:
            await asyncio.wait_for(started.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            for process in processes:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        assert processes[0].returncode is not None

    asyncio.run(run())
    assert cache.refresh["state"] == "error"


def test_report_worker_cannot_write_or_create_a_missing_database(client_engine, tmp_path):
    import sqlite3

    from app.performance_worker import ReadStore

    _, engine = client_engine
    with ReadStore(engine.store.path).connect() as db:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("UPDATE account SET balance='999999' WHERE id=1")
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        with ReadStore(missing).connect():
            pass
    assert not missing.exists()


def test_report_subprocess_handles_database_paths_with_spaces_unicode_and_hash(
    client_engine, tmp_path
):
    import sqlite3

    _, engine = client_engine
    seed(engine)
    folder = tmp_path / "studiu crypto știri #1"
    folder.mkdir()
    for store, name in [
        (engine.store, "cercetare locală.sqlite3"),
        (engine.service.news_paper, "paper separat.sqlite3"),
    ]:
        target = folder / name
        with store.connect() as source, sqlite3.connect(target) as destination:
            source.backup(destination)
        store.path = target
    cache = PerformanceReports(engine)
    asyncio.run(cache.calculate_external())
    assert cache.read()["totals"]["discovered"] == 1
