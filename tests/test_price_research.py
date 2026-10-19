"""Synthetic price observations; no real execution or predictive performance claims."""

import time

import pytest

from app.daily_research import daily_report
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, seed, stamp


def observed(engine, c, at, **changes):
    p = payload(engine, c, at, **changes)
    return p | {"source_kind": "live_provider_observation"}  # Explicit fixture metadata.


def test_rejected_token_price_collapse_is_counted_without_invented_trade(
    client_engine, monkeypatch
):
    _, engine = client_engine
    c, policy, cfg = seed(engine)
    at = time.time() + 1
    engine.save_observation(c, observed(engine, c, at, unsafe=True), policy, cfg, stamp(at))
    engine.save_observation(
        c, observed(engine, c, at + 301, price=0.1, unsafe=True), policy, cfg, stamp(at + 301)
    )
    monkeypatch.setattr("app.daily_research.utcnow", lambda: stamp(at + 302))
    report = daily_report(engine)
    p = report["price_references"]["horizons"]["300"]["all_first_evaluations"]
    assert p["observed"] == 1 and p["decline_at_least_80pct"] == 1
    assert float(p["mean_price_return_pct"]) == pytest.approx(-90)
    assert p["paper_pnl_usd"] is None and p["execution_verified"] is False
    assert report["first_verdicts"] == {"REJECT": 1}


def test_first_failed_attempt_is_not_replaced_with_a_later_winner(client_engine, monkeypatch):
    _, engine = client_engine
    c, policy, cfg = seed(engine)
    at = time.time() + 1
    engine.save_observation(c, observed(engine, c, at), policy, cfg, stamp(at))
    engine.save_observation(c, {"market": None}, policy, cfg, stamp(at + 301))
    engine.save_observation(
        c, observed(engine, c, at + 320, price=10), policy, cfg, stamp(at + 320)
    )
    monkeypatch.setattr("app.daily_research.utcnow", lambda: stamp(at + 321))
    p = daily_report(engine)["price_references"]["horizons"]["300"]["all_first_evaluations"]
    assert p["observed"] == 0 and p["unavailable_or_pending"] == 1
    assert p["mean_price_return_pct"] is None
    assert p["states"] == {"horizon_quote_unavailable": 1}


@pytest.mark.parametrize("bad", ["future", "stale", "wrong_pool", "cached", "before_window"])
def test_unusable_horizon_price_is_not_a_return(client_engine, monkeypatch, bad):
    _, engine = client_engine
    c, policy, cfg = seed(engine)
    at = time.time() + 1
    engine.save_observation(c, observed(engine, c, at), policy, cfg, stamp(at))
    p = observed(engine, c, at + 301, price=4)
    if bad == "wrong_pool":
        p["market"]["pair_address"] = "different fixture pool"
    elif bad == "cached":
        p["source_kind"] = "cached_observation"
    else:
        p["market"]["observed_at"] = stamp(
            at + 302 if bad == "future" else at + 100 if bad == "stale" else at + 299
        )
    engine.save_observation(c, p, policy, cfg, stamp(at + 301))
    monkeypatch.setattr("app.daily_research.utcnow", lambda: stamp(at + 303))
    report = daily_report(engine)["price_references"]["horizons"]["300"]["all_first_evaluations"]
    assert report["observed"] == 0 and report["increase_at_least_100pct"] == 0


def test_reference_report_is_read_only_and_keeps_pending_horizons(client_engine, monkeypatch):
    _, engine = client_engine
    c, policy, cfg = seed(engine)
    at = time.time() + 1
    engine.save_observation(c, observed(engine, c, at), policy, cfg, stamp(at))
    monkeypatch.setattr("app.daily_research.utcnow", lambda: stamp(at + 1))
    with engine.store.connect() as db:
        before = [tuple(r) for r in db.execute("SELECT * FROM opportunity_outcomes")]
    p = daily_report(engine)["price_references"]["horizons"]["300"]["all_first_evaluations"]
    assert p["states"] == {"waiting": 1} and p["mean_price_return_pct"] is None
    with engine.store.connect() as db:
        assert [tuple(r) for r in db.execute("SELECT * FROM opportunity_outcomes")] == before


def test_failed_attempt_is_distinct_from_usable_price_coverage(client_engine):
    _, engine = client_engine
    c, policy, cfg = seed(engine)
    at = time.time() - 20
    engine.save_observation(c, observed(engine, c, at - 2), policy, cfg, stamp(at - 2))
    with engine.store.connect() as db:
        sid = db.execute("SELECT id FROM opportunity_signals WHERE kind='baseline'").fetchone()[0]
        engine.sampling.job(db, c["id"], sid, "checkpoint", 300, at - 1, at + 10, control=True)
    engine.save_observation(c, {"market": None}, policy, cfg, stamp(at))
    p = engine.sampling.coverage()["groups"]["control"]["checkpoint"]
    assert p["attempted"] == 1
    assert p["usable_price_observations"] == 0
    assert p["attempts_without_usable_price"] == 1


def test_reference_v2_skips_prefetch_then_keeps_first_losing_capture(client_engine, monkeypatch):
    _, engine = client_engine
    c, policy, cfg = seed(engine)
    at = time.time() + 1
    engine.save_observation(c, observed(engine, c, at), policy, cfg, stamp(at))
    early = observed(engine, c, at + 301, price=100)
    early["market"]["observed_at"] = stamp(at + 299)
    engine.save_observation(c, early, policy, cfg, stamp(at + 301))
    engine.save_observation(
        c, observed(engine, c, at + 302, price=0.5), policy, cfg, stamp(at + 302)
    )
    engine.save_observation(
        c, observed(engine, c, at + 303, price=10), policy, cfg, stamp(at + 303)
    )
    monkeypatch.setattr("app.daily_research.utcnow", lambda: stamp(at + 304))
    p = daily_report(engine)["price_references"]["horizons"]["300"]["all_first_evaluations"]
    assert p["observed"] == 1 and float(p["mean_price_return_pct"]) == -50


def test_zero_liquidity_is_price_evidence_but_not_a_trade(client_engine, monkeypatch):
    _, engine = client_engine
    c, policy, cfg = seed(engine)
    at = time.time() + 1
    engine.save_observation(c, observed(engine, c, at), policy, cfg, stamp(at))
    engine.save_observation(
        c, observed(engine, c, at + 301, liquidity=0), policy, cfg, stamp(at + 301)
    )
    monkeypatch.setattr("app.daily_research.utcnow", lambda: stamp(at + 302))
    p = daily_report(engine)["price_references"]["horizons"]["300"]["all_first_evaluations"]
    assert p["observed"] == 1 and p["zero_exit_liquidity_quotes"] == 1
    assert p["paper_pnl_usd"] is None


def test_risk_rejection_does_not_hide_an_actual_price_capture(client_engine):
    _, engine = client_engine
    c, policy, cfg = seed(engine)
    at = time.time() - 20
    engine.save_observation(c, observed(engine, c, at, unsafe=True), policy, cfg, stamp(at))
    with engine.store.connect() as db:
        sid = db.execute("SELECT id FROM opportunity_signals WHERE kind='baseline'").fetchone()[0]
        engine.sampling.job(db, c["id"], sid, "checkpoint", 300, at + 1, at + 10, control=True)
    engine.save_observation(c, observed(engine, c, at + 2, unsafe=True), policy, cfg, stamp(at + 2))
    p = engine.sampling.coverage()["groups"]["control"]["checkpoint"]
    assert p["attempted"] == p["usable_price_observations"] == 1
    assert p["attempts_without_usable_price"] == 0
    assert (
        engine.detail(c["id"])["observations"][0]["decision"]["screening"]["paper_allowed"] is False
    )
