"""Synthetic clocks/provider payloads, real SQLite/API/worker; no live performance claim."""

import asyncio
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.performance_cache import PerformanceReports
from app.pilot import DAYS, Pilot, latency, report
from tests.test_observation_sampling import candidate
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, stamp


def begin(engine, monkeypatch, at=None):
    at = time.time() + 2 * 86400 if at is None else at
    engine.configure(engine.config().model_copy(update={"routed_quotes_enabled": False}))
    monkeypatch.setattr("app.pilot.utcnow", lambda: stamp(at))
    pilot = Pilot(engine)
    return at, pilot.start(), pilot


def observe(engine, index, at, *, selected=True, control=False, unsafe=False, source=None):
    c = candidate(engine, index, at)
    with engine.store.connect() as db:
        db.execute("UPDATE sampling_enrollment SET control_member=? WHERE candidate_id=?",
                   (int(control), c["id"]))
    cfg = engine.config()
    p = engine.policy(cfg)
    value = payload(engine, c, at + 1, unsafe=unsafe)
    value["source_kind"] = source or "live_provider_observation"  # Explicit fixture marker.
    if not selected:
        value["decision"]["verdict"] = "MONITOR"
    engine.save_observation(c, value, p, cfg, stamp(at + 1))
    return c, p, cfg


def test_pilot_does_not_enroll_until_explicitly_started(client_engine):
    client, engine = client_engine
    assert client.get("/api/opportunities/pilot").json()["study"] is None
    assert report(engine)["report_state"] == "not_started"


def test_start_is_idempotent_and_cannot_move_dates_or_original_holdouts(client_engine, monkeypatch):
    client, engine = client_engine
    at, study, _ = begin(engine, monkeypatch)
    assert study["ends_at"] == stamp(at + DAYS * 86400)
    with engine.store.connect() as db:
        before = list(map(tuple, db.execute("SELECT * FROM forward_evaluation_protocols")))
    monkeypatch.setattr("app.pilot.utcnow", lambda: stamp(at + 1000))
    assert client.post("/api/opportunities/pilot/start").json()["study"] == study
    with engine.store.connect() as db:
        assert list(map(tuple, db.execute("SELECT * FROM forward_evaluation_protocols"))) == before
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE pilot_study SET ends_at='2099-01-01'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM pilot_study")


def test_concurrent_start_retains_one_declaration(client_engine, monkeypatch):
    _, engine = client_engine
    at, study, _ = begin(engine, monkeypatch)
    # Existing declarations must be returned across independent controllers/connections.
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: Pilot(engine).start(), range(2)))
    assert results == [study, study]


def test_exact_boundaries_and_old_candidates_do_not_become_new(client_engine, monkeypatch):
    _, engine = client_engine
    at, _, _ = begin(engine, monkeypatch)
    for i, offset in enumerate([-0.0001, 0, .0001, DAYS * 86400]):
        candidate(engine, 50000 + i, at + offset)
    p = report(engine, at + DAYS * 86400 + 10)
    assert p["totals"]["new_registrations"] == 2
    assert p["phase"] == "followup" and p["elapsed_days"] == DAYS
    assert p["totals"]["analysis_tokens"] == 0
    assert p["models"]["estimated_pool"]["300"]["all_planned"]["mean_net_pnl_usd"] is None


def test_future_signal_does_not_leak_verdict_or_selection(client_engine, monkeypatch):
    _, engine = client_engine
    at, _, _ = begin(engine, monkeypatch)
    observe(engine, 50100, at + 1)
    p = report(engine, at + 1.5)
    assert p["first_verdicts"] == {"PENDING": 1}
    assert p["totals"]["first_evaluations"] == p["totals"]["opportunity_alerts"] == 0


def test_changed_policy_is_counted_but_not_pooled_with_original(client_engine, monkeypatch):
    _, engine = client_engine
    at, study, _ = begin(engine, monkeypatch)
    engine.configure(engine.config().model_copy(update={"min_transactions_5m": 11}))
    observe(engine, 50200, at + 1)
    p = report(engine, at + 100)
    assert p["totals"]["new_registrations"] == 1
    assert p["totals"]["analysis_exclusions"] == {"changed_policy": 1}
    assert p["study"] == study


def test_original_future_holdout_is_not_moved_to_start_of_pilot(client_engine, monkeypatch):
    _, engine = client_engine
    at = time.time() + 10
    at, study, _ = begin(engine, monkeypatch, at)
    assert study["payload"]["analysis_from"] > study["declared_at"]
    observe(engine, 50300, at + 1)
    p = report(engine, at + 100)
    assert p["totals"]["analysis_exclusions"] == {"original_holdout_not_started": 1}


def test_fixture_origin_is_not_reported_as_verified_live_evidence(client_engine, monkeypatch):
    _, engine = client_engine
    at, _, _ = begin(engine, monkeypatch)
    observe(engine, 50400, at + 1, source="isolated_fixture")
    assert report(engine, at + 100)["totals"]["analysis_exclusions"] == {
        "unverified_source_kind": 1
    }


def test_pending_horizons_not_used_to_claim_early_results(client_engine, monkeypatch):
    _, engine = client_engine
    at, _, _ = begin(engine, monkeypatch)
    observe(engine, 50500, at + 1)
    horizon = report(engine, at + 100)["models"]["estimated_pool"]["300"]
    assert horizon["planned"] == horizon["not_yet_mature"] == 1
    assert horizon["comparison"]["selected_at_first_evaluation"]["experiments"] == 0
    assert horizon["comparison"]["selected_at_first_evaluation"]["mean_net_pnl_usd"] is None


def test_losses_unknown_exits_and_disjoint_control_remain_in_denominator(client_engine, monkeypatch):
    _, engine = client_engine
    at, _, _ = begin(engine, monkeypatch)
    selected, _, _ = observe(engine, 50600, at + 1, control=True)
    control, _, _ = observe(engine, 50601, at + 2, selected=False, control=True)
    with engine.store.connect() as db:
        sids = dict(db.execute("SELECT candidate_id,id FROM opportunity_signals WHERE kind='baseline'"))
        for c, state, pnl in [(selected, "evaluated", "-12.345"),
                              (control, "exit_unavailable", None)]:
            db.execute("UPDATE opportunity_outcomes SET state=?,payload=?,updated_at=? WHERE signal_id=? AND horizon_seconds=300",
                       (state, json.dumps({"pnl_usd": pnl}), stamp(at + 500), sids[c["id"]]))
    p = report(engine, at + 1000)
    h = p["models"]["estimated_pool"]["300"]["comparison"]
    assert h["selected_at_first_evaluation"]["mean_net_pnl_usd"] == "-12.345"
    assert h["control_excluding_selected"]["experiments"] == 1
    assert h["control_excluding_selected"]["unresolved_or_unavailable"] == 1
    assert h["control_excluding_selected"]["mean_net_pnl_usd"] is None
    assert h["conditional_mean_difference_usd"] is None and h["overlap"] == 1
    assert p["models"]["jupiter_quotes"]["300"]["all_planned"]["evaluated"] == 0
    assert p["profitability_demonstrated"] is False


def test_later_alert_does_not_select_original_rejected_baseline(client_engine, monkeypatch):
    _, engine = client_engine
    at, _, _ = begin(engine, monkeypatch)
    c, policy, cfg = observe(engine, 50700, at + 1, unsafe=True)
    value = payload(engine, c, at + 10)
    value["source_kind"] = "live_provider_observation"
    engine.save_observation(c, value, policy, cfg, stamp(at + 10))
    p = report(engine, at + 100)
    assert p["totals"]["opportunity_alerts"] == 1
    assert p["totals"]["initially_selected_tokens"] == 0
    assert p["alert_followup"]["estimated_pool"]["300"]["all_planned"]["experiments"] == 1
    assert p["latency"]["first_alert_to_pool_paper_entry"]["subjects"] == 1


def test_first_alert_followup_does_not_double_count_upgrades_or_risk_alerts(client_engine, monkeypatch):
    _, engine = client_engine
    at, _, _ = begin(engine, monkeypatch)
    c, policy, cfg = observe(engine, 50701, at + 1)
    risk = payload(engine, c, at + 10, unsafe=True)
    risk["source_kind"] = "live_provider_observation"
    engine.save_observation(c, risk, policy, cfg, stamp(at + 10))
    upgraded = payload(engine, c, at + 20)
    upgraded["source_kind"] = "live_provider_observation"
    upgraded["decision"]["verdict"] = "CONSIDER"
    engine.save_observation(c, upgraded, policy, cfg, stamp(at + 20))
    p = report(engine, at + 1000)
    assert p["totals"]["opportunity_alerts"] == 2 and p["totals"]["risk_alerts"] == 1
    assert p["alert_followup"]["estimated_pool"]["300"]["all_planned"]["experiments"] == 1


def test_latency_and_projection_are_read_only_and_preserve_gaps(client_engine, monkeypatch):
    _, engine = client_engine
    at, _, _ = begin(engine, monkeypatch)
    observe(engine, 50800, at + 1)
    with engine.store.connect() as db:
        before = list(map(tuple, db.execute("SELECT * FROM observation_jobs")))
    p = report(engine, at + 1000)
    assert p["latency"]["registration_to_first_evaluation"]["p50_seconds"] == 1
    assert p["latency"]["alert_to_display"]["missing"] == 1
    assert p["latency"]["signal_to_pool_paper_entry"]["p50_seconds"] is None
    assert any(v.get("missed") for v in p["collection"]["all"].values())
    with engine.store.connect() as db:
        assert list(map(tuple, db.execute("SELECT * FROM observation_jobs"))) == before
    assert latency([(stamp(at), stamp(at - 1)), (None, stamp(at))]) == {
        "subjects": 2, "measured": 0, "missing": 1, "invalid_clock": 1,
        "p50_seconds": None, "p95_seconds": None, "max_seconds": None,
        "method": "nearest-rank empirical quantiles; receipt timestamps, not exchange execution",
    }


def test_worker_reports_pilot_using_read_only_database_and_frozen_policy(client_engine, monkeypatch):
    client, engine = client_engine
    at, study, _ = begin(engine, monkeypatch, time.time() - 10)
    cache = client.app.state.performance_reports = PerformanceReports(engine)
    asyncio.run(cache.calculate_external())
    p = client.get("/api/opportunities/pilot").json()
    assert p["study"] == study and p["report_state"] == "ready"
    assert p["report_cache"]["calculation_mode"] == "isolated_read_only_process"
    assert client.get("/api/portfolio?account=news").json()["orders"] == []


def test_old_cache_never_hides_a_newly_started_pilot(client_engine, monkeypatch):
    client, engine = client_engine
    cache = client.app.state.performance_reports = PerformanceReports(engine)
    cache._publish({"pilot": {"study": None, "report_state": "not_started"}}, cache._begin(), "fixture")
    _, study, _ = begin(engine, monkeypatch)
    p = client.get("/api/opportunities/pilot").json()
    assert p == {"study": study, "report_state": "preparing"}


def test_pilot_failure_does_not_discard_other_cached_reports(client_engine, monkeypatch):
    client, engine = client_engine
    begin(engine, monkeypatch)
    cache = client.app.state.performance_reports = PerformanceReports(engine)
    cache._publish({"totals": {"discovered": 123}, "pilot": {"report_state": "error"}},
                   cache._begin(), "fixture")
    assert client.get("/api/opportunities/pilot").status_code == 503
    assert client.get("/api/opportunities/performance").json()["totals"]["discovered"] == 123
    assert client.get("/api/opportunities").status_code == 200


def test_entry_latency_counts_each_token_once_and_validates_real_window(client_engine, monkeypatch):
    _, engine = client_engine
    at, _, _ = begin(engine, monkeypatch)
    c, policy, cfg = observe(engine, 50900, at + 1)
    value = payload(engine, c, at + 5)
    value["source_kind"] = "live_provider_observation"
    engine.save_observation(c, value, policy, cfg, stamp(at + 5))
    engine.update_outcomes(at + 10)
    p = report(engine, at + 20)
    assert p["latency"]["signal_to_pool_paper_entry"]["subjects"] == 1
    assert p["latency"]["signal_to_pool_paper_entry"]["p50_seconds"] == 3
    assert p["collection"]["all"]["entry"]["price:observed"] == 1


def test_pilot_endpoints_retain_hosted_authentication_and_csrf(client_engine):
    client, engine = client_engine
    engine.service.auth.password = "explicit-fixture-only-password"
    assert client.get("/api/opportunities/pilot").status_code == 401
    assert client.post("/api/opportunities/pilot/start").status_code == 401
    session = client.post("/api/auth/login", json={"password": "explicit-fixture-only-password"})
    assert session.status_code == 200
    assert client.post("/api/opportunities/pilot/start").status_code == 403
    assert client.post("/api/opportunities/pilot/start", headers={
        "x-pulse-csrf": session.json()["csrf"]
    }).status_code == 200
