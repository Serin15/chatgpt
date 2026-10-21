"""Immutable prospective holdouts, separate from historical configured cutoffs."""

import json
from datetime import UTC, datetime, timedelta

from app.cohort_comparisons import comparisons
from app.models import epoch, utcnow

VERSION = "prospective-holdout-v1"


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS forward_evaluation_protocols(
          policy_id INTEGER PRIMARY KEY,declared_at TEXT NOT NULL,
          test_from TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS forward_evaluation_no_update
          BEFORE UPDATE ON forward_evaluation_protocols BEGIN
          SELECT RAISE(ABORT,'Evaluation declarations are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS forward_evaluation_no_delete
          BEFORE DELETE ON forward_evaluation_protocols BEGIN
          SELECT RAISE(ABORT,'Evaluation declarations are immutable'); END;
    """)


def register(db, policy, config):
    # Never enroll a policy after any of its original baseline signals exist.
    # The caller creates the declaration in the policy transaction, before ingest.
    if (
        db.execute(
            "SELECT 1 FROM forward_evaluation_protocols WHERE policy_id=?", (policy["id"],)
        ).fetchone()
        or db.execute(
            "SELECT 1 FROM opportunity_signals WHERE policy_id=? AND kind='baseline' LIMIT 1",
            (policy["id"],),
        ).fetchone()
    ):
        return
    declared = utcnow()
    explicit = config.test_from
    configured_future = explicit is not None and explicit.timestamp() > epoch(declared)
    cutoff = explicit if configured_future else datetime.fromisoformat(declared) + timedelta(days=1)
    db.execute(
        "INSERT OR IGNORE INTO forward_evaluation_protocols VALUES(?,?,?,?)",
        (
            policy["id"],
            declared,
            cutoff.astimezone(UTC).isoformat(),
            json.dumps(
                {
                    "version": VERSION,
                    "policy_sha256": policy["sha256"],
                    "cutoff_basis": "configured_future"
                    if configured_future
                    else "24h_after_declaration",
                    "costs": "original frozen per-signal costs; independent paper experiments",
                    "control": "prospective contract-hash enrollment; exclude selected from comparison",
                    "boundary": "purge entry+horizon+exit windows crossing test_from",
                    "threshold_optimization": False,
                },
                sort_keys=True,
            ),
        ),
    )


def protocols(db, firsts, at):
    # Older read-only databases may predate this table; never create it in GET/export.
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='forward_evaluation_protocols'"
    ).fetchone():
        return {}
    policies = {s["policy_id"] for s in firsts.values()}
    result = {}
    for row in db.execute("SELECT * FROM forward_evaluation_protocols ORDER BY policy_id"):
        if row["policy_id"] not in policies or epoch(row["declared_at"]) > epoch(at):
            continue
        result[str(row["policy_id"])] = dict(row) | {
            "payload": json.loads(row["payload"]),
            "state": "test_not_started"
            if epoch(at) < epoch(row["test_from"])
            else "collecting_test",
        }
    return result


def grouped(firsts, parsed, horizon, model, summarize, declarations):
    subjects = {}
    for sid, s in firsts.items():
        p = declarations.get(str(s["policy_id"]))
        if p is None:
            continue
        # Reporting view only: original signals, policies and legacy partition
        # results are unchanged. Pre-declaration signals remain unassigned.
        subjects[sid] = s | {
            "policy_at": p["declared_at"],
            "config_parsed": s["config_parsed"] | {"test_from": p["test_from"]},
        }
    return comparisons(subjects, parsed, horizon, model, summarize)
