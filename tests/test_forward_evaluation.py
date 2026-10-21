"""Prospective declarations are immutable and never relabel historical tests."""

import json
import sqlite3

import pytest

from app import forward_evaluation
from app.daily_research import daily_report, summarize
from app.models import epoch
from tests.test_cohort_comparisons import subject
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, seed, stamp


def test_new_protocol_declares_future_cutoff_and_keeps_original_config(client_engine):
    _, engine = client_engine
    before = engine.config().model_dump(mode="json")
    c, p, cfg = seed(engine)
    with engine.store.connect() as db:
        declaration = dict(
            db.execute(
                "SELECT * FROM forward_evaluation_protocols WHERE policy_id=?", (p["id"],)
            ).fetchone()
        )
    assert epoch(declaration["test_from"]) - epoch(declaration["declared_at"]) == 86400
    assert json.loads(declaration["payload"])["policy_sha256"] == p["sha256"]
    assert engine.config().model_dump(mode="json") == before
    assert p["payload"]["config"]["test_from"] == before["test_from"]
    assert engine.policy(cfg)["id"] == p["id"]
    with engine.store.connect() as db:
        assert (
            dict(
                db.execute(
                    "SELECT * FROM forward_evaluation_protocols WHERE policy_id=?", (p["id"],)
                ).fetchone()
            )
            == declaration
        )
        for sql in [
            "UPDATE forward_evaluation_protocols SET test_from='2099-01-01'",
            "DELETE FROM forward_evaluation_protocols",
        ]:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                db.execute(sql)


def test_old_policy_with_baseline_cannot_be_enrolled_retroactively(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    # A pre-upgrade declaration fixture, deliberately without a protocol record.
    with engine.store.connect() as db:
        db.execute(
            "INSERT INTO opportunity_policies(sha256,at,payload) VALUES('legacy-no-protocol',?,?)",
            (p["at"], json.dumps(p["payload"])),
        )
        old = dict(
            db.execute(
                "SELECT * FROM opportunity_policies WHERE sha256='legacy-no-protocol'"
            ).fetchone()
        )
    old["payload"] = p["payload"]
    engine.save_observation(
        c, payload(engine, c, epoch(p["at"]) + 1), old, cfg, stamp(epoch(p["at"]) + 1)
    )
    with engine.store.connect() as db:
        forward_evaluation.register(db, old, cfg)
        assert (
            db.execute(
                "SELECT 1 FROM forward_evaluation_protocols WHERE policy_id=?", (old["id"],)
            ).fetchone()
            is None
        )


def test_forward_groups_keep_missing_loss_overlap_and_purge_boundary():
    p = {"1": {"declared_at": "2026-10-20T00:00:00Z", "test_from": "2026-10-21T00:00:00Z"}}
    firsts = {
        1: subject(signal_at="2026-10-21T00:01:00Z", selected=True),
        2: subject(signal_at="2026-10-21T00:02:00Z", selected=True, control_member=False),
        3: subject(signal_at="2026-10-21T00:03:00Z"),
        4: subject(signal_at="2026-10-20T23:55:00Z"),
        5: subject(signal_at="2026-10-19T23:59:00Z"),
    }
    rows = [{"signal_id": 1, "horizon_seconds": 300, "state": "evaluated", "pnl": "-7"}]
    result = forward_evaluation.grouped(firsts, rows, 300, "jupiter_quotes", summarize, p)["1"]
    test = result["test"]
    assert test["selected_at_first_evaluation"]["experiments"] == 2
    assert test["selected_at_first_evaluation"]["mean_net_pnl_usd"] == "-7"
    assert test["selected_at_first_evaluation"]["unresolved_or_unavailable"] == 1
    assert test["control_excluding_selected"]["experiments"] == 1
    assert test["control_excluding_selected"]["mean_net_pnl_usd"] is None
    assert test["overlap"] == 1 and test["conditional_mean_difference_usd"] is None
    assert result["purged_boundary"]["all_first_evaluations"]["experiments"] == 1
    assert result["unassigned"]["all_first_evaluations"]["experiments"] == 1
    assert firsts[1]["config_parsed"]["test_from"] == "2026-10-18T00:00:00Z"


def test_daily_future_protocol_is_read_only_and_does_not_claim_validation(
    client_engine, monkeypatch
):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    engine.save_observation(
        c, payload(engine, c, epoch(p["at"]) + 1), p, cfg, stamp(epoch(p["at"]) + 1)
    )
    monkeypatch.setattr("app.daily_research.utcnow", lambda: stamp(epoch(p["at"]) + 2))
    with engine.store.connect() as db:
        before = list(map(tuple, db.execute("SELECT * FROM forward_evaluation_protocols")))
    report = daily_report(engine)
    f = report["forward_evaluation"]
    assert f["original_cutoffs_preserved"] and not f["profitability_demonstrated"]
    assert f["protocols"][str(p["id"])]["state"] == "test_not_started"
    with engine.store.connect() as db:
        assert list(map(tuple, db.execute("SELECT * FROM forward_evaluation_protocols"))) == before


def test_reading_pre_protocol_database_does_not_create_schema():
    db = sqlite3.connect(":memory:")
    assert forward_evaluation.protocols(db, {}, "2026-10-21T00:00:00Z") == {}
    assert db.execute("SELECT name FROM sqlite_master").fetchall() == []
