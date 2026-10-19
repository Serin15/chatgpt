"""Concurrent report requests share work, never persist or reuse old reports."""

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event

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
