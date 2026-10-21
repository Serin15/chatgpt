"""Bound background polling, never history, cohort membership or promised outcomes."""

import json
import time
from datetime import UTC, datetime, timedelta

from app.models import epoch

VERSION = "bounded-background-v1"
SECURITY_ALLOCATION_VERSION = "early-security-reserve-v1"


class SecurityBudget:
    """Reserve part of the existing API budget without reordering quote deadlines.

    Earlier background work cannot spend the slots reserved for still-unvisited
    early candidates. Later work can borrow slots released by cached/missing or
    illiquid early observations. Failed provider calls still spend their slot.
    """

    def __init__(self, rows, config, cycles=0, now=None):
        now = time.time() if now is None else now
        self.total = self.left = config.security_budget
        self.priority = set()
        for row in rows:
            try:
                early = 0 <= now - epoch(row["ingested_at"]) <= config.active_watch_seconds
            except (ValueError, TypeError, OverflowError):
                early = False
            if early or row.get("last_attempt_at") is None:
                self.priority.add(row["id"])
        self.pending = self.priority.copy()
        self.reserved = min(len(self.priority), (self.total + 2) // 3)
        if self.total == 1 and cycles % 2:
            self.reserved = 0
        self.initial_reserve = self.reserved
        self.priority_used = 0

    def visit(self, candidate_id):
        self.pending.discard(candidate_id)

    def take(self, candidate_id):
        early = candidate_id in self.priority
        if self.left <= 0 or (not early and self.left <= min(self.reserved, len(self.pending))):
            return False
        self.left -= 1
        if early:
            self.priority_used += 1
            self.reserved = max(0, self.reserved - 1)
        return True

    def report(self):
        return {
            "version": SECURITY_ALLOCATION_VERSION,
            "budget": self.total,
            "reserved_for_early": self.initial_reserve,
            "used": self.total - self.left,
            "early_used": self.priority_used,
            "other_used": self.total - self.left - self.priority_used,
            "unspent": self.left,
            "note": "Provider attempts, including failures; not completed security checks. Original risk and freshness gates remain required.",
        }


# Small, indexed sets are materialized once; no payload decoder or Python UDF
# runs for every candidate. All statements are read-only, including status GETs.
SQL = """WITH
promises(candidate_id) AS MATERIALIZED (
    SELECT candidate_id FROM observation_jobs WHERE status='pending' AND deadline_at>=:clock
    UNION
    SELECT s.candidate_id FROM opportunity_outcomes o
      JOIN opportunity_signals s ON s.id=o.signal_id WHERE o.state='pending'
    UNION
    SELECT e.candidate_id FROM routed_outcomes o
      JOIN routed_experiments e ON e.signal_id=o.signal_id WHERE o.state IN ('pending','collecting')
    UNION
    SELECT candidate_id FROM routed_experiments WHERE entry_state IN ('entry_pending','collecting')
),
due_promises(candidate_id) AS MATERIALIZED (
    SELECT DISTINCT candidate_id FROM observation_jobs
    WHERE status='pending' AND due_at<=:clock AND deadline_at>=:clock
),
manual_contracts(address) AS MATERIALIZED (
    SELECT address FROM tokens WHERE watch=1
    UNION SELECT address FROM positions WHERE closed_at IS NULL
    UNION SELECT value FROM json_each(:news_holdings)
),
story_candidates(candidate_id) AS MATERIALIZED (
    SELECT c.id FROM story_pool_lookups l
      JOIN opportunity_candidates c ON c.chain='solana' AND c.contract=l.contract
    WHERE l.state='existing_candidate'
      AND julianday(json_extract(l.payload,'$.last_checked_at'))
        BETWEEN julianday(:active_from) AND julianday(:at)
      AND (json_extract(l.payload,'$.current_evidence.association')='exact_contract_document_mention'
        OR (json_extract(l.payload,'$.current_evidence.association')='resolved_market_pair_reference'
          AND json_extract(l.payload,'$.current_evidence.market_reference.qualifies_for_discovery')=1))
),
monitoring AS (
    SELECT c.id,c.next_due,c.last_attempt_at,c.ingested_at,
      c.id IN (SELECT candidate_id FROM promises) AS has_promises,
      c.id IN (SELECT candidate_id FROM due_promises) AS has_due_promises,
      CASE
        WHEN c.eligible=0 THEN 'excluded'
        WHEN c.last_attempt_at IS NULL THEN 'awaiting_first_observation'
        WHEN c.contract IN (SELECT address FROM manual_contracts) THEN 'manual_watch'
        WHEN c.id IN (SELECT candidate_id FROM story_candidates) THEN 'reactivated'
        WHEN julianday(c.ingested_at)>=julianday(:active_from) THEN 'active'
        WHEN c.id IN (SELECT candidate_id FROM promises) THEN 'followup'
        WHEN julianday(c.ingested_at) IS NULL THEN 'metadata_unknown'
        WHEN julianday(c.ingested_at)>=julianday(:background_from) THEN 'background'
        ELSE 'paused'
      END AS state
    FROM opportunity_candidates c
) """

REASONS = {
    "excluded": "discovery_exclusion",
    "awaiting_first_observation": "first_observation_required",
    "manual_watch": "watchlist_or_open_paper_position",
    "reactivated": "recent_contract_document_reference_not_endorsement",
    "active": "within_active_observation_window",
    "followup": "promised_observation_or_unresolved_result",
    "metadata_unknown": "ingestion_timestamp_unavailable",
    "background": "within_bounded_background_window",
    "paused": "background_window_finished_no_open_promises",
}


def parameters(engine, config, now=None):
    now = time.time() if now is None else now
    at = datetime.fromtimestamp(now, UTC)
    # Both paper ledgers can hold Solana tokens. Holdings remain monitored even
    # if their original discovery is old; no balance or position is modified.
    with engine.service.news_paper.connect() as db:
        holdings = [
            row[0] for row in db.execute("SELECT address FROM positions WHERE closed_at IS NULL")
        ]
    return {
        "clock": now,
        "at": at.isoformat(),
        "active_from": (at - timedelta(seconds=config.active_watch_seconds)).isoformat(),
        "background_from": (at - timedelta(hours=config.background_watch_hours)).isoformat(),
        "news_holdings": json.dumps(holdings),
    }


def candidates(engine, db, config, ids, now=None):
    if not ids:
        return {}
    params = parameters(engine, config, now)
    params.update({f"id{i}": value for i, value in enumerate(ids)})
    names = ",".join(f":id{i}" for i in range(len(ids)))
    result = {}
    for row in db.execute(SQL + f"SELECT * FROM monitoring WHERE id IN ({names})", params):
        until = None
        try:
            until = datetime.fromtimestamp(
                epoch(row["ingested_at"]) + config.background_watch_hours * 3600, UTC
            ).isoformat()
        except (ValueError, TypeError, OverflowError):
            pass
        result[row["id"]] = {
            "version": VERSION,
            "state": row["state"],
            "reason": REASONS[row["state"]],
            "has_open_promises": bool(row["has_promises"]),
            "background_until": until,
            "background_watch_hours": config.background_watch_hours,
            "history_preserved": True,
            "not_a_new_launch": True,
        }
    return result


def summary(engine, config=None, now=None):
    config = config or engine.config()
    params = parameters(engine, config, now)
    with engine.store.connect() as db:
        rows = db.execute(
            SQL
            + """SELECT state,count(*) AS candidates,
                sum(next_due<=:clock) AS due,
                sum(last_attempt_at IS NULL) AS not_enriched,
                sum(has_due_promises) AS promised_due,
                sum(has_due_promises AND next_due>:clock) AS promised_outside_periodic,
                min(CASE WHEN next_due<=:clock THEN next_due END) AS oldest
              FROM monitoring GROUP BY state""",
            params,
        ).fetchall()
    included = [row for row in rows if row["state"] != "excluded"]
    dispatchable = [row for row in included if row["state"] != "paused"]

    def delay(subjects):
        oldest = min((r["oldest"] for r in subjects if r["oldest"] is not None), default=None)
        return round(max(0, params["clock"] - oldest)) if oldest is not None else 0

    return {
        "version": VERSION,
        "due": sum(r["due"] for r in included),
        "dispatchable_due": sum(r["due"] for r in dispatchable),
        "paused_due": sum(r["due"] for r in included if r["state"] == "paused"),
        "promised_due_candidates": sum(r["promised_due"] for r in included),
        "promised_due_outside_periodic_queue": sum(
            r["promised_outside_periodic"] for r in included
        ),
        "not_enriched": sum(r["not_enriched"] for r in included),
        "oldest_due_delay_seconds": delay(included),
        "dispatchable_oldest_due_delay_seconds": delay(dispatchable),
        "background_watch_hours": config.background_watch_hours,
        "active_watch_seconds": config.active_watch_seconds,
        "counts_by_state": {
            r["state"]: {"candidates": r["candidates"], "due": r["due"]} for r in rows
        },
        "history_preserved": True,
        "capacity_note": "Due totals describe periodic candidate polling and retain paused background candidates. Promised jobs may bypass that schedule and are counted separately. Promises, first observations, watchlists and paper holdings are protected. API capacity can still cause missed deadlines; missing outcomes remain unknown.",
    }
