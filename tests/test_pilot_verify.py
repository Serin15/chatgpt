"""Verification criteria with an explicit synthetic HTTP service, never live proof."""

import httpx
import pytest

from app.pilot_verify import verify


def transport(monkeypatch, *, active=True, changed=False):
    import app.pilot_verify as module

    real = httpx.Client
    calls, details = [], []
    study = {"declared_at":"2026-10-25T10:00:00+00:00",
             "ends_at":"2026-11-24T10:00:00+00:00", "sha256":"explicit-fixture"}
    n = [0]

    def handle(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/status":
            return httpx.Response(200, json={"app_id":"pulse_crypto_research","live_execution":False})
        if request.url.path == "/api/opportunities/pilot":
            n[0] += 1
            frozen = study | ({"sha256":"changed-fixture"} if changed and n[0] > 1 else {})
            return httpx.Response(200, json={
                "study":frozen if active else None,"report_state":"ready",
                "first_candidates":[{"candidate_id":1,"first_signal_id":2}],
                "models":{"estimated_pool":{"300":{"comparison":{
                    "selected_at_first_evaluation":{"experiments":0 if changed else 1},
                    "control_excluding_selected":{"experiments":1},
                }}}},
            })
        details.append(1)
        return httpx.Response(200, json={
            "ingested_at":"2026-10-25T10:01:00+00:00","signals":[{"id":2}],
            "observations":[{"source_kind":"live_provider_observation"}],
            "observations_total":len(details),"outcomes":[{"pnl_usd":None}],
        })

    monkeypatch.setattr(module.httpx, "Client", lambda **kw: real(
        **kw, transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    return calls


def test_verifier_can_confirm_plumbing_without_inventing_a_profitable_outcome(monkeypatch):
    calls = transport(monkeypatch)
    result = verify("http://127.0.0.1:8000", 60)
    assert result["complete"] and all(result["criteria"].values())
    assert result["latest_detail"]["outcomes"][0]["pnl_usd"] is None
    assert all(method == "GET" for method, _ in calls)


def test_verifier_requires_explicitly_activated_pilot(monkeypatch):
    transport(monkeypatch, active=False)
    with pytest.raises(ValueError, match="Start the 30-day pilot"):
        verify("http://127.0.0.1:8000", 60)


def test_verifier_rejects_a_changed_declaration(monkeypatch):
    transport(monkeypatch, changed=True)
    with pytest.raises(ValueError, match="declaration changed"):
        verify("http://127.0.0.1:8000", 60)
