"""Concurrent report requests share work, never persist or reuse old reports."""

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Barrier, Event

import pytest

from tests.test_opportunities import client_engine as client_engine


@pytest.mark.parametrize("fail", [False, True])
def test_concurrent_reports_share_one_computation_and_next_request_is_fresh(
    client_engine, monkeypatch, fail
):
    _, engine = client_engine
    entered, waiting, release = Event(), Event(), Event()
    calls = []

    class TrackedFuture(Future):
        def result(self, timeout=None):
            waiting.set()
            return super().result(timeout)

    def compute(_):
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
            if fail:
                raise ValueError("isolated report failure")
        return {"count": len(calls), "nested": []}

    monkeypatch.setattr("app.opportunities.Future", TrackedFuture, raising=False)
    monkeypatch.setattr("app.opportunity_outcomes.report", compute)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(engine.report)
        assert entered.wait(5)
        second = pool.submit(engine.report)
        try:
            assert waiting.wait(2), "Second request started another report instead of joining"
        finally:
            release.set()
        if fail:
            for result in [first, second]:
                with pytest.raises(ValueError, match="isolated report failure"):
                    result.result(5)
        else:
            a, b = first.result(5), second.result(5)
            assert a == b == {"count": 1, "nested": []}
            a["nested"].append("caller mutation")
            assert b["nested"] == []
    assert len(calls) == 1
    assert engine.report()["count"] == 2


def test_daily_requests_share_work_only_for_the_same_day(client_engine, monkeypatch):
    client, _ = client_engine
    entered, waiting, release = Event(), Event(), Event()
    calls = []

    class TrackedFuture(Future):
        def result(self, timeout=None):
            waiting.set()
            return super().result(timeout)

    def compute(_, day):
        calls.append(day.isoformat())
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return {"day_utc": day.isoformat(), "calculation": len(calls)}

    monkeypatch.setattr("app.opportunities.Future", TrackedFuture)
    monkeypatch.setattr("app.main.daily_report", compute)
    path = "/api/opportunities/daily?day=2026-01-01"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.get, path)
        assert entered.wait(5)
        second = pool.submit(client.get, path)
        try:
            assert waiting.wait(2), "Duplicate daily report was recomputed"
        finally:
            release.set()
        a, b = first.result(5), second.result(5)
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json() == {"day_utc": "2026-01-01", "calculation": 1}
    assert client.get(path).json()["calculation"] == 2


def test_different_daily_dates_are_not_combined(client_engine, monkeypatch):
    client, _ = client_engine
    ready = Barrier(2)

    def compute(_, day):
        ready.wait(5)
        return {"day_utc": day.isoformat()}

    monkeypatch.setattr("app.main.daily_report", compute)
    days = ["2026-01-01", "2026-01-02"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client.get, "/api/opportunities/daily?day=" + day) for day in days]
        responses = [f.result(10) for f in futures]
    assert [r.status_code for r in responses] == [200, 200]
    assert [r.json()["day_utc"] for r in responses] == days
