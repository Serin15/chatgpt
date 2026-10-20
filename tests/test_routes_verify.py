"""The read-only checker cannot assemble a successful proof from unrelated records."""

import copy
import time

import httpx
import pytest

from app.routes_verify import verify
from tests.test_opportunities import stamp


def candidate():
    at = time.time() - 1000

    def quote(side, observed, cash):
        return {
            "address": "token",
            "model": "jupiter_quote_conservative_min_out",
            "side": side,
            "quote_observed_at": stamp(observed),
            "cash_change": cash,
            "quantity": "10",
            "requested_size": "50" if side == "buy" else "10",
            "jupiter_quote": {"contextSlot": 42},
        }

    buy, sell = quote("buy", at + 4, "-50.01"), quote("sell", at + 305, "48.01")
    return {
        "id": 7,
        "contract": "token",
        "observations": [
            {
                "id": 3,
                "at": stamp(at + 3),
                "source_kind": "live_provider_observation",
                "market": {"address": "token"},
                "security": {"rpc": {"slot": 1}},
            }
        ],
        "routed": {
            "entries": [
                {
                    "signal_id": 9,
                    "entry_state": "filled",
                    "entry_at": buy["quote_observed_at"],
                    "entry_payload": buy,
                    "entry_attempt_id": 11,
                    "policy": {"source_sha256": "a" * 64},
                }
            ],
            "outcomes": [
                {
                    "signal_id": 9,
                    "state": "evaluated",
                    "horizon_seconds": 300,
                    "payload": {
                        "entry_at": buy["quote_observed_at"],
                        "exit_at": sell["quote_observed_at"],
                        "pnl_usd": "-2",
                        "entry_attempt_id": 11,
                        "exit_attempt_id": 12,
                        "exit_quote": sell,
                    },
                }
            ],
            "attempts": [
                {
                    "id": 11,
                    "signal_id": 9,
                    "phase": "entry",
                    "status": "quoted",
                    "observation_id": 3,
                },
                {
                    "id": 12,
                    "signal_id": 9,
                    "phase": "exit",
                    "horizon_seconds": 300,
                    "status": "quoted",
                    "observation_id": 4,
                },
            ],
        },
    }


def run(monkeypatch, candidates):
    original_client = httpx.Client

    def response(request):
        assert request.method == "GET"
        path = request.url.path
        if path == "/api/status":
            return httpx.Response(
                200, json={"app_id": "pulse_crypto_research", "live_execution": False}
            )
        if path == "/api/opportunities/routes":
            return httpx.Response(
                200,
                json={
                    "recent_attempts": [{"candidate_id": c["id"]} for c in candidates],
                    "status": {"state": "ok"},
                    "entry_states": {},
                },
            )
        if path == "/api/portfolio":
            return httpx.Response(200, json={"orders": []})
        key = int(path.rsplit("/", 1)[1])
        return httpx.Response(200, json=next(c for c in candidates if c["id"] == key))

    monkeypatch.setattr(
        "app.routes_verify.httpx.Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(response), **kwargs),
    )
    return verify("http://127.0.0.1:8767", 0)


def test_checker_accepts_one_linked_past_quote_scenario(monkeypatch):
    assert run(monkeypatch, [candidate()])["complete"]


def test_checker_does_not_combine_two_candidates(monkeypatch):
    first, second = candidate(), candidate()
    first["routed"]["outcomes"] = []
    second["id"] = 8
    second["routed"]["entries"] = []
    assert not run(monkeypatch, [first, second])["complete"]


def test_checker_requires_outcome_from_the_same_signal(monkeypatch):
    c = candidate()
    c["routed"]["outcomes"][0]["signal_id"] = 10
    assert not run(monkeypatch, [c])["complete"]


def test_checker_rejects_future_outcome(monkeypatch):
    c = candidate()
    c["routed"]["outcomes"][0]["payload"]["exit_at"] = stamp(time.time() + 3600)
    assert not run(monkeypatch, [c])["complete"]


@pytest.mark.parametrize("result", [None, "NaN", "Infinity"])
def test_checker_requires_a_finite_net_result(monkeypatch, result):
    c = candidate()
    c["routed"]["outcomes"][0]["payload"]["pnl_usd"] = result
    assert not run(monkeypatch, [c])["complete"]


def test_checker_requires_the_recorded_entry_attempt(monkeypatch):
    c = candidate()
    c["routed"]["attempts"] = [copy.deepcopy(c["routed"]["attempts"][-1])]
    assert not run(monkeypatch, [c])["complete"]
