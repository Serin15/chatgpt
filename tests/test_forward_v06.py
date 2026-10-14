"""Simulated timestamp fixtures: validate temporal accounting, not market profitability."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.forward import Forward
from tests.conftest import ADDRESS, snapshot

BASE = 1700000000


def stamp(seconds):
    return datetime.fromtimestamp(BASE + seconds, UTC).isoformat()


def setup_forward(store, settings, evidence=None):
    rules = {
        key: str(getattr(settings, key))
        for key in (
            "swap_fee",
            "network_fee_usd",
            "reference_fee",
            "reference_slippage",
            "max_price_impact",
            "min_liquidity",
        )
    }
    payload = {"rules_at_signal": rules, "paper_execution_mode": "pool"}
    if evidence is not None:
        payload = evidence
    with store.connect() as db:
        db.execute(
            "INSERT INTO signals(address,at,snapshot_id,evidence) VALUES(?,?,?,?)",
            (ADDRESS, stamp(0), 1, json.dumps(payload)),
        )
    service = SimpleNamespace(
        settings=settings,
        paper_store=lambda account: store,
        performance=SimpleNamespace(report=lambda account: {"max_observed_drawdown_pct": None}),
    )
    return Forward(service)


def receipt(store, settings, seconds, price):
    snap = snapshot(settings, price_usd=price)
    snap["at"] = snap["market"]["observed_at"] = stamp(seconds)
    snap["security"]["observed_at"] = stamp(seconds)
    snap["analysis"]["paper_allowed"] = True
    with store.connect() as db:
        row = db.execute(
            "INSERT INTO snapshots(address,at,market,security,analysis) VALUES(?,?,?,?,?)",
            (
                ADDRESS,
                snap["at"],
                json.dumps(snap["market"]),
                json.dumps(snap["security"]),
                json.dumps(snap["analysis"]),
            ),
        )
        return row.lastrowid


def test_first_receipts_not_best_price_and_future_is_ignored(store, settings):
    forward = setup_forward(store, settings)
    receipt(store, settings, -1, 0.01)
    receipt(store, settings, 1, 0.01)
    entry = receipt(store, settings, 4, 1)
    receipt(store, settings, 5, 0.01)
    exit_id = receipt(store, settings, 304, 1)
    receipt(store, settings, 305, 100)
    receipt(store, settings, 1000, 10000)
    result = forward.report(horizon_seconds=300, now=BASE + 500)["results"][0]
    assert result["state"] == "evaluated"
    assert (result["entry_snapshot_id"], result["exit_snapshot_id"]) == (entry, exit_id)
    assert Decimal(result["pnl_usd"]) < 0


def test_overlapping_development_window_is_purged(store, settings):
    forward = setup_forward(store, settings)
    receipt(store, settings, 4, 1)
    receipt(store, settings, 304, 1)
    result = forward.report(split_at=stamp(350), horizon_seconds=300, now=BASE + 500)
    assert result["results"][0]["state"] == "purged_at_split_boundary"
    assert result["cohorts"]["development"]["unresolved"] == 1
    assert result["cohorts"]["test"]["loss_signal_rate"] is None


def test_legacy_and_jupiter_signals_never_receive_fabricated_costs_or_routes(store, settings):
    forward = setup_forward(store, settings, {"paper_execution_mode": "jupiter"})
    receipt(store, settings, 4, 1)
    receipt(store, settings, 304, 1)
    assert (
        forward.report(horizon_seconds=300, now=BASE + 500)["results"][0]["state"]
        == "requires_recorded_forward_routed_quotes"
    )
    with store.connect() as db:
        db.execute("UPDATE signals SET evidence='{}'")
    assert (
        forward.report(horizon_seconds=300, now=BASE + 500)["results"][0]["state"]
        == "missing_frozen_cost_rules"
    )


def test_invalid_saved_rules_do_not_crash_report(store, settings):
    forward = setup_forward(store, settings, {"rules_at_signal": {"unexpected": "NaN"}})
    receipt(store, settings, 4, 1)
    receipt(store, settings, 304, 1)
    assert (
        forward.report(horizon_seconds=300, now=BASE + 500)["results"][0]["state"]
        == "untradable_or_incomplete_evidence"
    )
