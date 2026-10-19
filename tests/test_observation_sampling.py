"""Prospective sampling regressions. Isolated fixture data, no external calls."""

import copy
import hashlib
import json
import time

import pytest

from app.models import epoch
from app.opportunities import Opportunities
from app.opportunity_rules import EngineConfig
from app.opportunity_sampling import SAMPLING_VERSION, control_member
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, seed, source_item, stamp


def legacy_policy(engine, policy):
    """Construct a separate, consistently hashed pre-v2 policy fixture."""
    from app.opportunities import encode

    value = copy.deepcopy(policy["payload"])
    value.pop("forward_quote_window_version", None)
    digest = hashlib.sha256(encode(value).encode()).hexdigest()
    with engine.store.connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO opportunity_policies(sha256,at,payload) VALUES(?,?,?)",
            (digest, stamp(time.time()), encode(value)),
        )
        row = db.execute("SELECT * FROM opportunity_policies WHERE sha256=?", (digest,)).fetchone()
    return dict(row) | {"payload": value}


def address(i):
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    raw = i.to_bytes(32, "big")
    n = int.from_bytes(raw, "big")
    chars = ""
    while n:
        n, r = divmod(n, 58)
        chars = alphabet[r] + chars
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + chars


def candidate(engine, i, at, selected=False, control=None):
    contract = address(i)
    with engine.store.connect() as db:
        row = db.execute(
            "INSERT INTO opportunity_candidates(chain,contract,pool,discovered_at,ingested_at,discovery,eligible,next_due) VALUES('solana',?,?,?,?,?,1,?)",
            (
                contract,
                address(i + 100000),
                stamp(at),
                stamp(at),
                json.dumps(source_item(at) | {"contract": contract}),
                at + 86400,
            ),
        )
        cid = row.lastrowid
        engine.sampling.enroll(db, cid, contract, stamp(at))
    return engine.detail(cid) | {"discovery": source_item(at) | {"contract": contract}}


def scheduled(engine, i, at, selected=False, control=False, phase="entry", horizon=0, due=None):
    c = candidate(engine, i, at)
    policy = engine.policy(engine.config())
    v = payload(engine, c, at)
    with engine.store.connect() as db:
        sid = engine._signal(
            db, c["id"], None, stamp(at), "baseline", v["decision"], policy, engine.config()
        )
        db.execute(
            "UPDATE observation_jobs SET selected=?,control_member=?,due_at=?,deadline_at=? WHERE signal_id=?",
            (int(selected), int(control), due if due is not None else at + 3, at + 180, sid),
        )
        if phase == "exit":
            db.execute(
                "UPDATE observation_jobs SET phase='exit',horizon_seconds=? WHERE signal_id=?",
                (horizon, sid),
            )
    return c, sid


def test_control_fixed_before_scores_and_survives_restart(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    e = engine.sampling.enrollment(c["id"])
    assert e["provenance"] == "prospective"
    assert bool(e["control_member"]) == control_member(c["contract"])
    engine.save_observation(c, payload(engine, c, time.time() + 1, price=100), p, cfg)
    assert Opportunities(engine.service).sampling.enrollment(c["id"]) == e
    assert engine.detail(c["id"])["sampling_enrollment"] == e


def test_control_reject_gets_entry_even_with_background_not_due(client_engine):
    _, engine = client_engine
    now = time.time() - 10
    c, sid = scheduled(engine, 202, now, control=True)
    due = engine.due(engine.config().model_copy(update={"observation_budget": 2}))
    assert c["id"] in {r["id"] for r in due}
    assert due[0]["collection_lane"] == "protected_followup"
    assert due[0]["next_due"] > time.time()


def test_protected_capacity_shared_under_heavy_alert_backlog(client_engine):
    _, engine = client_engine
    now = time.time() - 10
    alerts = {scheduled(engine, 300 + i, now, selected=True)[0]["id"] for i in range(20)}
    controls = {scheduled(engine, 400 + i, now, control=True)[0]["id"] for i in range(20)}
    due = engine.due(engine.config().model_copy(update={"observation_budget": 12}))
    primary = due[:6]
    assert len([r for r in primary if r["id"] in alerts]) == 3
    assert len([r for r in primary if r["id"] in controls]) == 3
    assert len({r["id"] for r in due}) == 12


def test_single_slot_alternates_groups_and_overlapping_subject_costs_one_slot(client_engine):
    _, engine = client_engine
    now = time.time() - 10
    a, _ = scheduled(engine, 500, now, selected=True)
    c, _ = scheduled(engine, 501, now, control=True)
    cfg = engine.config().model_copy(update={"observation_budget": 1})
    engine.status["cycles"] = 0
    assert [r["id"] for r in engine.due(cfg)] == [a["id"]]
    engine.status["cycles"] = 1
    assert [r["id"] for r in engine.due(cfg)] == [c["id"]]
    with engine.store.connect() as db:
        db.execute("UPDATE observation_jobs SET control_member=1 WHERE candidate_id=?", (a["id"],))
    due = engine.due(cfg.model_copy(update={"observation_budget": 4}))
    assert len(due) == len({r["id"] for r in due}) == 2


def test_job_waits_until_exit_horizon_and_uses_earliest_deadline(client_engine):
    _, engine = client_engine
    now = time.time()
    future, _ = scheduled(
        engine, 600, now, selected=True, phase="exit", horizon=3600, due=now + 3600
    )
    later, _ = scheduled(engine, 601, now - 10, selected=True)
    soon, _ = scheduled(engine, 602, now - 100, selected=True)
    due = engine.due(engine.config().model_copy(update={"observation_budget": 1}))
    assert due[0]["id"] == soon["id"]
    assert future["id"] not in {r["id"] for r in due}


def test_provider_failure_is_observed_failure_not_profit_or_missing_collection(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    now = time.time() + 1
    v = payload(engine, c, now)
    engine.save_observation(c, v, p, cfg, stamp(now))
    engine.save_observation(c, {"market": None, "error": "isolated outage"}, p, cfg, stamp(now + 4))
    engine.update_outcomes(now + 10)
    out = engine.detail(c["id"])["outcomes"][0]
    assert out["state"] == "entry_unavailable" and out["payload"]["pnl_usd"] is None
    assert out["payload"]["collection"]["reason"] == "provider_quote_unavailable"
    cov = engine.sampling.coverage()
    assert cov["groups"]["alerts"]["entry"]["attempted"] == 1
    assert cov["groups"]["alerts"]["entry"]["missed"] == 0


def test_unserved_deadline_and_late_response_are_explicit(client_engine):
    _, engine = client_engine
    now = time.time() - 500
    c, sid = scheduled(engine, 700, now, selected=True)
    d, sid2 = scheduled(engine, 701, now, control=True)
    with engine.store.connect() as db:
        db.execute(
            "UPDATE observation_jobs SET last_dispatch_at=? WHERE signal_id=?", (now + 5, sid2)
        )
    engine.due(engine.config())
    engine.update_outcomes()
    with engine.store.connect() as db:
        reasons = {
            r["signal_id"]: r["reason"]
            for r in db.execute("SELECT signal_id,reason FROM observation_jobs")
        }
    assert reasons[sid] == "capacity_or_worker_gap"
    assert reasons[sid2] == "collection_finished_after_deadline"
    for c in [c, d]:
        out = engine.detail(c["id"])["outcomes"][0]
        assert out["state"] == "missing_forward_entry"
        assert out["payload"]["pnl_usd"] is None
        assert out["payload"]["collection"]["status"] == "missed"


def test_control_exit_is_scheduled_from_actual_first_entry(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    now = time.time() + 1
    engine.save_observation(c, payload(engine, c, now), p, cfg, stamp(now))
    with engine.store.connect() as db:
        db.execute("UPDATE observation_jobs SET control_member=1")
    engine.save_observation(c, payload(engine, c, now + 4), p, cfg, stamp(now + 4))
    engine.update_outcomes(now + 5)
    with engine.store.connect() as db:
        exits = [dict(r) for r in db.execute("SELECT * FROM observation_jobs WHERE phase='exit'")]
    assert len(exits) == 3
    assert all(
        r["due_at"] == pytest.approx(now + 4 + r["horizon_seconds"], rel=0, abs=0.00001)
        for r in exits
    )
    assert all(r["control_member"] and r["selected"] for r in exits)
    engine.save_observation(c, payload(engine, c, now + 304, price=1.1), p, cfg, stamp(now + 304))
    engine.update_outcomes(now + 305)
    assert engine.detail(c["id"])["outcomes"][0]["state"] == "evaluated"


def test_prefetched_quote_cannot_be_a_post_signal_fill(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    p = legacy_policy(engine, p)
    now = time.time() + 1
    engine.save_observation(c, payload(engine, c, now), p, cfg, stamp(now))
    early = payload(engine, c, now + 4)
    early["market"]["observed_at"] = stamp(now + 1)
    engine.save_observation(c, early, p, cfg, stamp(now + 4))
    engine.update_outcomes(now + 5)
    out = engine.detail(c["id"])["outcomes"][0]
    assert out["state"] == "entry_unavailable" and out["payload"]["pnl_usd"] is None
    assert out["payload"]["collection"]["reason"] == "quote_before_window"


def test_aged_candidate_polled_less_frequently_without_changing_signal(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    now = time.time()
    c["ingested_at"] = stamp(now - cfg.active_watch_seconds - 1)
    engine.save_observation(c, payload(engine, c, now), p, cfg, stamp(now))
    d = engine.detail(c["id"])
    assert d["next_due"] == pytest.approx(now + cfg.background_interval_seconds, rel=0, abs=0.00001)
    assert d["signals"][1]["payload"]["policy"]["payload"]["config"]["position_usd"] == 50
    assert d["outcomes"][0]["state"] == "pending"


def test_legacy_migration_does_not_invent_balanced_historical_cohorts(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    now = time.time()
    engine.save_observation(c, payload(engine, c, now), p, cfg, stamp(now))
    with engine.store.connect() as db:
        db.execute("DELETE FROM sampling_metadata")
        db.execute("DELETE FROM sampling_enrollment")
        db.execute("DELETE FROM observation_jobs")
    restarted = Opportunities(engine.service)
    assert restarted.sampling.enrollment(c["id"])["provenance"] == "legacy"
    report = restarted.report()["horizons"]["300"]["prospective_comparison"]
    assert report["fixed_control"]["experiments"] == 0
    assert report["selected_at_first_evaluation"]["experiments"] == 0
    assert restarted.detail(c["id"])["signals"][1]["payload"]["policy"] == p


def test_coverage_api_distinguishes_pending_from_zero_success(client_engine):
    client, engine = client_engine
    c, p, cfg = seed(engine)
    engine.save_observation(c, payload(engine, c, time.time()), p, cfg)
    r = client.get("/api/opportunities/coverage")
    assert r.is_success
    d = r.json()
    assert d["version"] == SAMPLING_VERSION
    assert d["groups"]["alerts"]["entry"]["pending"] == 1
    assert d["groups"]["alerts"]["entry"]["observed_attempt_rate"] is None
    assert d["enrollment"][0]["provenance"] == "prospective"


def test_control_report_preserves_rejected_members_and_overlap(client_engine):
    _, engine = client_engine
    i = next(i for i in range(2000, 2100) if control_member(address(i)))
    now = time.time() + 1
    c = candidate(engine, i, now)
    p = engine.policy(engine.config())
    cfg = engine.config()
    engine.save_observation(c, payload(engine, c, now, unsafe=True), p, cfg, stamp(now))
    engine.save_observation(c, payload(engine, c, now + 4, unsafe=True), p, cfg, stamp(now + 4))
    engine.update_outcomes(now + 10)
    report = engine.report()["horizons"]["300"]["prospective_comparison"]
    assert report["fixed_control"]["experiments"] == 1
    assert report["fixed_control"]["states"] == {"entry_unavailable": 1}
    assert report["fixed_control"]["net_pnl_independent_experiments_usd"] is None
    assert report["selected_at_first_evaluation"]["experiments"] == 0
    j = next(i for i in range(2100, 2200) if control_member(address(i)))
    d = candidate(engine, j, now)
    engine.save_observation(d, payload(engine, d, now), p, cfg, stamp(now))
    report = engine.report()["horizons"]["300"]["prospective_comparison"]
    assert report["fixed_control"]["experiments"] == 2
    assert report["overlapping_experiments"] == 1


def test_migration_recovers_future_exit_without_rewriting_policy(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    now = time.time() + 1
    engine.save_observation(c, payload(engine, c, now), p, cfg, stamp(now))
    engine.save_observation(c, payload(engine, c, now + 4), p, cfg, stamp(now + 4))
    engine.update_outcomes(now + 5)
    with engine.store.connect() as db:
        db.execute("DELETE FROM sampling_metadata")
        db.execute("DELETE FROM sampling_enrollment")
        db.execute("DELETE FROM observation_jobs")
    restart = Opportunities(engine.service)
    with restart.store.connect() as db:
        jobs = [dict(r) for r in db.execute("SELECT * FROM observation_jobs WHERE phase='exit'")]
    assert len(jobs) == 3
    assert all(
        j["due_at"] == pytest.approx(now + 4 + j["horizon_seconds"], rel=0, abs=0.00001)
        for j in jobs
    )
    assert all(j["selected"] for j in jobs)
    assert restart.detail(c["id"])["signals"][1]["payload"]["policy"] == p


def test_custom_config_survives_default_budget_migration(client_engine):
    _, engine = client_engine
    old = engine.config().model_copy(update={"observation_budget": 30, "position_usd": 25})
    engine.configure(old)
    with engine.store.connect() as db:
        db.execute("DELETE FROM sampling_metadata")
    restarted = Opportunities(engine.service)
    assert restarted.config().observation_budget == 30
    assert restarted.config().position_usd == 25
    with engine.store.connect() as db:
        legacy = EngineConfig(observation_budget=30).model_dump(mode="json")
        legacy.pop("active_watch_seconds")
        legacy.pop("background_interval_seconds")
        db.execute("UPDATE opportunity_config SET payload=?", (json.dumps(legacy),))
        db.execute("DELETE FROM sampling_metadata")
    restarted = Opportunities(engine.service)
    assert restarted.config().observation_budget == 60
    assert restarted.config().position_usd == 50


def test_early_exit_quote_rejected_even_when_processing_finishes_late(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    p = legacy_policy(engine, p)
    now = time.time() + 1
    engine.save_observation(c, payload(engine, c, now), p, cfg, stamp(now))
    engine.save_observation(c, payload(engine, c, now + 4), p, cfg, stamp(now + 4))
    engine.update_outcomes(now + 5)
    late = payload(engine, c, now + 305, price=10)
    late["market"]["observed_at"] = stamp(now + 303)
    engine.save_observation(c, late, p, cfg, stamp(now + 305))
    engine.update_outcomes(now + 306)
    out = engine.detail(c["id"])["outcomes"][0]
    assert out["state"] == "exit_unavailable" and out["payload"]["pnl_usd"] is None
    assert out["payload"]["collection"]["reason"] == "quote_before_window"


def test_v2_prefetch_does_not_consume_job_and_first_actual_failure_is_final(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    now = time.time() + 1
    engine.save_observation(c, payload(engine, c, now), p, cfg, stamp(now))
    early = payload(engine, c, now + 4)
    early["market"]["observed_at"] = stamp(now + 1)
    engine.save_observation(c, early, p, cfg, stamp(now + 4))
    engine.update_outcomes(now + 5)
    assert engine.detail(c["id"])["outcomes"][0]["state"] == "pending"
    with engine.store.connect() as db:
        job = db.execute("SELECT * FROM observation_jobs WHERE phase='entry'").fetchone()
        assert job["status"] == "pending" and job["observation_id"] is None
    engine.save_observation(c, {"market": None}, p, cfg, stamp(now + 6))
    engine.save_observation(c, payload(engine, c, now + 7, price=10), p, cfg, stamp(now + 7))
    engine.update_outcomes(now + 8)
    out = engine.detail(c["id"])["outcomes"][0]
    assert out["state"] == "entry_unavailable"
    assert out["payload"]["pnl_usd"] is None
    assert out["payload"]["entry_at"] == stamp(now + 6)


def test_v2_exit_skips_prefetch_but_keeps_first_actual_losing_quote(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    now = time.time() + 1
    engine.save_observation(c, payload(engine, c, now), p, cfg, stamp(now))
    engine.save_observation(c, payload(engine, c, now + 4), p, cfg, stamp(now + 4))
    engine.update_outcomes(now + 5)
    early = payload(engine, c, now + 305, price=10)
    early["market"]["observed_at"] = stamp(now + 303)
    engine.save_observation(c, early, p, cfg, stamp(now + 305))
    engine.update_outcomes(now + 306)
    assert engine.detail(c["id"])["outcomes"][0]["state"] == "pending"
    engine.save_observation(c, payload(engine, c, now + 307, price=0.5), p, cfg, stamp(now + 307))
    engine.save_observation(c, payload(engine, c, now + 308, price=20), p, cfg, stamp(now + 308))
    engine.update_outcomes(now + 309)
    out = engine.detail(c["id"])["outcomes"][0]
    assert out["state"] == "evaluated"
    assert out["payload"]["exit_at"] == stamp(now + 307)
    assert float(out["payload"]["pnl_usd"]) < 0


def test_read_only_coverage_reports_expired_deadline_before_worker_runs(client_engine):
    client, engine = client_engine
    c, sid = scheduled(engine, 900, time.time() - 500, selected=True)
    result = client.get("/api/opportunities/coverage").json()
    assert result["groups"]["alerts"]["entry"]["missed"] == 1
    assert result["groups"]["alerts"]["entry"]["pending"] == 0
    assert result["groups"]["alerts"]["entry"]["observed_attempt_rate"] == 0
    with engine.store.connect() as db:
        assert (
            db.execute("SELECT status FROM observation_jobs WHERE signal_id=?", (sid,)).fetchone()[
                0
            ]
            == "pending"
        )


def test_report_does_not_count_expired_security_as_a_current_pass(client_engine):
    from app.opportunity_rules import evaluate

    _, engine = client_engine
    c, p, cfg = seed(engine)
    now = time.time()
    at = now - 60
    v = payload(engine, c, at)
    v["security"]["observed_at"] = stamp(now - 150)
    v["decision"] = evaluate(
        v["market"],
        v["security"],
        v["features"],
        v["narrative"],
        v["wallet"],
        engine.service.settings,
        cfg,
        stamp(at),
    )
    assert v["decision"]["security_filter_passed"]
    engine.save_observation(c, v, p, cfg, stamp(at))
    report = engine.report()
    assert report["current_security_pass"] == 0
    assert report["current_liquidity_pass"] == 1


def test_control_checkpoints_created_before_screening_and_survive_rejection(client_engine):
    _, engine = client_engine
    i = next(i for i in range(3000, 3100) if control_member(address(i)))
    contract = address(i)
    engine.service.discovery.save(
        source_item() | {"contract": contract, "pool": address(i + 100000)}
    )
    p = engine.policy(engine.config())
    engine.ingest(p)
    cid = engine.listing()["items"][0]["id"]
    c = engine.detail(cid)
    with engine.store.connect() as db:
        checkpoints = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM observation_jobs WHERE candidate_id=? AND phase='checkpoint'", (cid,)
            )
        ]
    assert len(checkpoints) == 3
    assert all(
        r["due_at"]
        == pytest.approx(
            epoch(c["discovered_at"]) + r["horizon_seconds"],
            rel=0,
            abs=0.00001,
        )
        for r in checkpoints
    )
    at = time.time() + 1
    engine.save_observation(c, payload(engine, c, at, unsafe=True), p, engine.config(), stamp(at))
    engine.save_observation(
        c, payload(engine, c, at + 4, unsafe=True), p, engine.config(), stamp(at + 4)
    )
    engine.update_outcomes(at + 5)
    assert engine.detail(cid)["outcomes"][0]["state"] == "entry_unavailable"
    checkpoint = next(r for r in checkpoints if r["horizon_seconds"] == 300)
    at = checkpoint["due_at"] + 1
    engine.save_observation(
        c, payload(engine, c, at, price=2, unsafe=True), p, engine.config(), stamp(at)
    )
    coverage = engine.sampling.coverage()
    assert coverage["groups"]["control"]["checkpoint"]["attempted"] == 1
    assert engine.detail(cid)["outcomes"][0]["payload"]["pnl_usd"] is None
