"""Daily cohort accounting on explicit fixtures; no provider performance claims."""

import time
from datetime import UTC, datetime, timedelta

from app.daily_research import daily_report, summarize
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, seed, stamp


def test_empty_daily_report_is_unknown_not_profit_zero(client_engine):
    client, _ = client_engine
    p = client.get("/api/opportunities/daily").json()
    assert p["totals"]["discovered"] == 0 and p["models"]["estimated_pool"] == {}
    assert p["profitability_demonstrated"] is False
    assert summarize([])["net_pnl_independent_experiments_usd"] is None


def test_daily_date_validation(client_engine):
    client, _ = client_engine
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()
    assert client.get("/api/opportunities/daily?day=" + tomorrow).status_code == 422
    assert client.get("/api/opportunities/daily?day=invalid").status_code == 422


def test_unobserved_and_rejected_candidates_stay_in_universe(client_engine, monkeypatch):
    _, engine = client_engine
    engine.configure(engine.config().model_copy(update={"routed_quotes_enabled": True}))
    c, policy, cfg = seed(engine)
    first = daily_report(engine)
    assert first["totals"]["eligible_without_first_evaluation"] == 1
    at = time.time() + 1
    engine.save_observation(c, payload(engine, c, at, unsafe=True), policy, cfg, stamp(at))
    monkeypatch.setattr("app.daily_research.utcnow", lambda: stamp(at + 1))
    p = daily_report(engine)
    assert p["totals"]["discovered"] == 1 and p["first_verdicts"] == {"REJECT": 1}
    assert p["totals"]["security_pass_at_first_evaluation"] == 0
    assert p["models"]["jupiter_quotes"]["300"]["all_first_evaluations"]["states"] == {
        "entry_rejected": 1
    }


def test_daily_outcomes_keep_models_separate_and_preserve_losses(client_engine, monkeypatch):
    _, engine = client_engine
    c, policy, cfg = seed(engine)
    at = time.time() + 1
    for offset, price in [(0, 1), (4, 1), (304, 0.5)]:
        engine.save_observation(
            c, payload(engine, c, at + offset, price=price), policy, cfg, stamp(at + offset)
        )
    engine.update_outcomes(at + 400)
    monkeypatch.setattr("app.daily_research.utcnow", lambda: stamp(at + 401))
    p = daily_report(engine)
    pool = p["models"]["estimated_pool"]["300"]["all_first_evaluations"]
    routed = p["models"]["jupiter_quotes"]["300"]["all_first_evaluations"]
    assert pool["evaluated"] == 1 and float(pool["net_pnl_independent_experiments_usd"]) < 0
    assert routed["evaluated"] == 0 and routed["net_pnl_independent_experiments_usd"] is None
    assert p["models"]["estimated_pool"]["300"]["cohorts"]["unassigned"]["experiments"] == 1


def test_old_day_report_is_cohort_not_fake_historical_snapshot(client_engine, monkeypatch):
    _, engine = client_engine
    c, _, _ = seed(engine)
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    old = datetime.combine(yesterday, datetime.min.time(), UTC).isoformat()
    with engine.store.connect() as db:
        db.execute("UPDATE opportunity_candidates SET discovered_at=? WHERE id=?", (old, c["id"]))
    p = daily_report(engine, yesterday)
    assert p["totals"]["discovered"] == 1
    assert daily_report(engine)["totals"]["discovered"] == 0
    assert "Not a historical as-of snapshot" in p["outcome_scope"]


def test_daily_read_never_expires_or_mutates_jobs(client_engine, monkeypatch):
    _, engine = client_engine
    c, policy, cfg = seed(engine)
    at = time.time() + 1
    engine.save_observation(c, payload(engine, c, at), policy, cfg, stamp(at))
    with engine.store.connect() as db:
        before = [tuple(r) for r in db.execute("SELECT * FROM opportunity_outcomes")]
    monkeypatch.setattr("app.daily_research.utcnow", lambda: stamp(at + 1000))
    p = daily_report(engine)
    assert p["models"]["estimated_pool"]["300"]["all_first_evaluations"]["states"] == {
        "overdue_unprocessed": 1
    }
    with engine.store.connect() as db:
        assert [tuple(r) for r in db.execute("SELECT * FROM opportunity_outcomes")] == before


def test_invalid_evaluated_pnl_stays_unknown():
    s = summarize([{"state": "evaluated", "pnl": "NaN"}, {"state": "evaluated", "pnl": None}])
    assert s["experiments"] == 2 and s["evaluated"] == 0
    assert s["net_pnl_independent_experiments_usd"] is None


def test_report_does_not_round_future_capture_into_the_present(client_engine, monkeypatch):
    _, engine = client_engine
    c, _, _ = seed(engine)
    day = datetime.now(UTC).date().isoformat()
    with engine.store.connect() as db:
        db.execute(
            "UPDATE opportunity_candidates SET discovered_at=? WHERE id=?",
            (day + "T12:00:00.000200+00:00", c["id"]),
        )
    monkeypatch.setattr("app.daily_research.utcnow", lambda: day + "T12:00:00.000100+00:00")
    assert daily_report(engine)["totals"]["discovered"] == 0


def test_later_alert_does_not_retroactively_select_the_first_evaluation(client_engine, monkeypatch):
    _, engine = client_engine
    c, policy, cfg = seed(engine)
    at = time.time() + 1
    engine.save_observation(c, payload(engine, c, at, unsafe=True), policy, cfg, stamp(at))
    engine.save_observation(c, payload(engine, c, at + 1), policy, cfg, stamp(at + 1))
    monkeypatch.setattr("app.daily_research.utcnow", lambda: stamp(at + 2))
    p = daily_report(engine)
    assert p["totals"]["opportunity_alerts"] == 1
    assert p["totals"]["selected_at_first_evaluation"] == 0


def test_control_overlap_and_frozen_future_split_are_reported(client_engine, monkeypatch):
    _, engine = client_engine
    c, _, cfg = seed(engine)
    at = time.time() + 1
    cfg = cfg.model_copy(update={"test_from": datetime.fromtimestamp(at + 2000, UTC)})
    engine.configure(cfg)
    policy = engine.policy(cfg)
    engine.save_observation(c, payload(engine, c, at), policy, cfg, stamp(at))
    with engine.store.connect() as db:
        db.execute(
            "UPDATE sampling_enrollment SET control_member=1 WHERE candidate_id=?", (c["id"],)
        )
    monkeypatch.setattr("app.daily_research.utcnow", lambda: stamp(at + 2))
    p = daily_report(engine)["models"]["estimated_pool"]
    assert p["300"]["selected_control_overlap"] == 1
    assert p["300"]["cohorts"]["development"]["experiments"] == 1
    assert p["3600"]["cohorts"]["purged_boundary"]["experiments"] == 1
    assert p["300"]["cohorts"]["test"]["experiments"] == 0
