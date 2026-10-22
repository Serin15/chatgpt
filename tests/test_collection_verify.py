"""The live collection check needs evidence captured during its own run."""

import time

import httpx

from app.collection_verify import verify
from app.opportunity_sampling import SAMPLING_VERSION
from tests.test_opportunities import stamp


def run(monkeypatch, *, historical=False, duplicate_capture=False, repeated_quote=False):
    now = round(time.time(), 6)
    clock = [now]
    monkeypatch.setattr("app.collection_verify.time.time", lambda: clock[0])
    captured = now - 60 if historical else now

    def rows(group):
        return [
            {
                "id": group * 10 + i,
                "candidate_id": group * 100 + (0 if duplicate_capture or repeated_quote else i),
                "phase": phase,
                "source_kind": "live_provider_observation",
                "quote_observed_at": stamp(captured),
                "observed_at": stamp(captured + i if repeated_quote else captured),
                "due_at": now - 120,
                "deadline_at": now + 120,
                "provenance": "prospective",
            }
            for i, phase in enumerate(["entry", "exit" if group == 1 else "checkpoint"])
        ]

    coverage = {
        "version": SAMPLING_VERSION,
        "groups": {},
        "recent_attempts": {"alerts": rows(1), "control": rows(2)},
    }
    original = httpx.Client

    def response(request):
        assert request.method == "GET"
        if request.url.path == "/api/status":
            return httpx.Response(
                200, json={"app_id": "pulse_crypto_research", "live_execution": False}
            )
        if request.url.path == "/api/opportunities/coverage":
            if repeated_quote:
                clock[0] = now + 2
            return httpx.Response(200, json=coverage)
        if request.url.path == "/api/portfolio":
            return httpx.Response(200, json={"orders": []})
        raise AssertionError(request.url)

    monkeypatch.setattr(
        "app.collection_verify.httpx.Client",
        lambda **kw: original(transport=httpx.MockTransport(response), **kw),
    )
    return verify("http://127.0.0.1:8767", 0)


def test_historical_recent_rows_do_not_pass_a_new_live_verification(monkeypatch):
    result = run(monkeypatch, historical=True)
    assert result["complete"] is False
    assert not result["criteria"]["later_exit_observed"]


def test_two_jobs_on_the_same_capture_are_not_two_market_observations(monkeypatch):
    assert run(monkeypatch, duplicate_capture=True)["complete"] is False


def test_repeated_quote_with_different_receipt_times_is_not_independent_evidence(monkeypatch):
    assert run(monkeypatch, repeated_quote=True)["complete"] is False


def test_actual_in_run_distinct_captures_can_pass(monkeypatch):
    result = run(monkeypatch)
    assert result["complete"]
    assert result["distinct_observations"] == {"alerts": 2, "control": 2}
    assert result["manual_account_orders"] == {"news": 0, "scanner": 0}
