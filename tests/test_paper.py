import time
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from app.paper import Rejected, buy, fill, sell
from app.store import Store
from tests.conftest import OTHER, old_signal, snapshot


def test_roundtrip_loses_fees_at_unchanged_price(settings, store):
    snap = snapshot(settings)
    order = buy(store, snap, old_signal(store, snap), "5", settings)
    assert D(store.portfolio()["cash"]) == D("94.99")
    exit_order = sell(store, order["position_id"], snap, settings)
    assert D(exit_order["pnl"]) < D("-0.049")
    assert D(store.portfolio()["cash"]) < D("99.951")
    assert not order["execution_verified"]
    assert D("1.0") < D(order["break_even_rise_pct"]) < D("1.1")
    assert len(store.portfolio()["orders"]) == 2
    # Startup does not reset balances or records.
    assert Store(settings).portfolio() == store.portfolio()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-5", "0", "garbage"])
def test_invalid_amounts_do_not_change_balance(settings, store, value):
    snap = snapshot(settings)
    with pytest.raises(Rejected):
        buy(store, snap, old_signal(store, snap), value, settings)
    assert store.portfolio()["cash"] == "100"
    assert not store.portfolio()["positions"]


def test_allocation_includes_network_cost(settings, store):
    snap = snapshot(settings)
    with pytest.raises(Rejected, match="Alocarea"):
        buy(store, snap, old_signal(store, snap), "20", settings)
    assert store.portfolio()["cash"] == "100"


def test_total_exposure_limit(settings, store):
    for n, address in enumerate(["one", "two", "three", "four"]):
        snap = snapshot(settings, address=address)
        if n < 3:
            buy(store, snap, old_signal(store, snap), "15", settings)
        else:
            with pytest.raises(Rejected, match="Expunerea"):
                buy(store, snap, old_signal(store, snap), "15", settings)
    assert len(store.portfolio()["positions"]) == 3


def test_duplicate_signal_is_not_reusable(settings, store):
    snap = snapshot(settings)
    signal_id = old_signal(store, snap)
    order = buy(store, snap, signal_id, "5", settings)
    sell(store, order["position_id"], snap, settings)
    cash = store.portfolio()["cash"]
    with pytest.raises(Rejected, match="deja utilizat"):
        buy(store, snap, signal_id, "5", settings)
    assert store.portfolio()["cash"] == cash


@pytest.mark.parametrize("age", [0, 121])
def test_signal_delay_and_expiry(settings, store, age):
    snap = snapshot(settings)
    with pytest.raises(Rejected, match="prea nou sau expirat"):
        buy(store, snap, old_signal(store, snap, age=age), "5", settings)


def test_cannot_fill_with_snapshot_before_signal(settings, store):
    snap = snapshot(settings)
    signal_id = old_signal(store, snap)
    snap["at"] = datetime.fromtimestamp(time.time() - 30, UTC).isoformat()
    with pytest.raises(Rejected, match="după semnal"):
        buy(store, snap, signal_id, "5", settings)


def test_stale_market_data_rejected(settings, store):
    snap = snapshot(settings)
    snap["at"] = datetime.fromtimestamp(time.time() - 121, UTC).isoformat()
    with pytest.raises(Rejected, match="expirat"):
        buy(store, snap, old_signal(store, snap), "5", settings)


def test_liquidity_collapse_preserves_open_position(settings, store):
    snap = snapshot(settings)
    order = buy(store, snap, old_signal(store, snap), "5", settings)
    before = deepcopy(store.portfolio())
    snap["market"]["liquidity_usd"] = 0
    with pytest.raises(Rejected):
        sell(store, order["position_id"], snap, settings)
    assert store.portfolio() == before


def test_unknown_sellability_does_not_credit_proceeds(settings, store):
    snap = snapshot(settings)
    order = buy(store, snap, old_signal(store, snap), "5", settings)
    snap["analysis"]["paper_allowed"] = False
    with pytest.raises(Rejected, match="sellability"):
        sell(store, order["position_id"], snap, settings)
    assert store.portfolio()["cash"] == "94.99"
    assert store.portfolio()["positions"][0]["closed_at"] is None


def test_price_impact_limit(settings):
    with pytest.raises(Rejected, match="Impactul"):
        fill("buy", "1000", snapshot(settings)["market"], settings)


def test_realized_daily_loss_blocks_next_buy(settings, store):
    snap = snapshot(settings)
    entry = buy(store, snap, old_signal(store, snap), "15", settings)
    snap["market"]["price_usd"] = 0.1
    sell(store, entry["position_id"], snap, settings)
    new = snapshot(settings, address=OTHER)
    with pytest.raises(Rejected, match="zilnică"):
        buy(store, new, old_signal(store, new), "5", settings)


def test_initial_capital_50_changes_allocation(settings):
    smaller = replace(settings, initial_balance=D(50))
    store = Store(smaller)
    snap = snapshot(smaller)
    with pytest.raises(Rejected, match="Alocarea"):
        buy(store, snap, old_signal(store, snap), "10", smaller)


def test_restart_preserves_original_paper_capital(settings, store):
    changed = replace(settings, initial_balance=D(50))
    assert Store(changed).initial_balance == D(100)


def test_concurrent_same_signal_cannot_double_spend(settings, store):
    from concurrent.futures import ThreadPoolExecutor

    snap = snapshot(settings)
    signal_id = old_signal(store, snap)

    def submit():
        try:
            buy(store, snap, signal_id, "5", settings)
            return "filled"
        except Rejected:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: submit(), range(2))) == ["filled", "rejected"]
    assert store.portfolio()["cash"] == "94.99"
    assert len(store.portfolio()["positions"]) == 1
