"""Independent forward Jupiter quote scenarios. Never constructs or submits a transaction."""

import asyncio
import hashlib
import json
import logging
from collections import Counter
from decimal import Decimal
from pathlib import Path

from app.errors import ProviderError
from app.jupiter import Jupiter
from app.models import epoch, utcnow
from app.opportunity_outcomes import available, observation, settings_at, summary
from app.paper import Rejected, require_fresh, validate_execution

VERSION = "jupiter-forward-v2"
SOURCE_SHA256 = hashlib.sha256(
    b"".join(
        Path(__file__).with_name(n).read_bytes() for n in ["opportunity_routes.py", "jupiter.py"]
    )
).hexdigest()
QUOTE_TIMEOUT = 20
# Audited upgrades preserve costs, gates and observation-window durations.
# All other unknown component versions remain unavailable.
COMPATIBLE_EXECUTION_SOURCES = {
    "560d51daa5b729eceb99c7d68c684318527083251276cb0298defe5ddf9eedc2",
    # v0.9.1 only preserves Rejected instead of misclassifying it as a schema error.
    # Successful quote validation, fill math and all route execution methods are unchanged.
    "ffaa54a7035d561267aa57f0634865ce5c7fa36ebbd89a95d7928ff75eda65d7",
    # v0.13.2 uses UTC, preserves fractional deadlines and rejects
    # fractional/boolean provider integer fields.
    # Valid quote math/costs/windows are unchanged. No grace period, retries
    # or rewriting of terminal results; unknown implementations still stop.
    "7f7dae89b7e9f79ff350b046112243f379a2025f5941b4bf75b6c62677becb42",
    # v0.13.3 adds opt-in prefetch handling for new policies only. Missing
    # window version keeps the original strict first-record selection.
    "fe46e95ea88180be8f23662d47dfac23276d4b24e7e96c5ceec9d1c6cb61d828",
}
log = logging.getLogger(__name__)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


class Routes:
    def __init__(self, engine):
        self.engine, self.store = engine, engine.store
        self.lock = asyncio.Lock()
        self.status = {"state": "unverified", "at": None, "cycles": 0}
        with self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS routed_experiments(signal_id INTEGER PRIMARY KEY,candidate_id INTEGER NOT NULL,at TEXT NOT NULL,policy TEXT NOT NULL,selected INTEGER NOT NULL DEFAULT 0,control_member INTEGER NOT NULL,entry_state TEXT NOT NULL,reason TEXT,entry_at TEXT,entry_payload TEXT,entry_attempt_id INTEGER);
                CREATE TABLE IF NOT EXISTS routed_outcomes(signal_id INTEGER NOT NULL,horizon_seconds INTEGER NOT NULL,target_at REAL,state TEXT NOT NULL,payload TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(signal_id,horizon_seconds));
                CREATE TABLE IF NOT EXISTS routed_attempts(id INTEGER PRIMARY KEY,signal_id INTEGER NOT NULL,phase TEXT NOT NULL,horizon_seconds INTEGER NOT NULL,started_at TEXT NOT NULL,completed_at TEXT,status TEXT NOT NULL,observation_id INTEGER NOT NULL,payload TEXT NOT NULL,UNIQUE(signal_id,phase,horizon_seconds));
                CREATE INDEX IF NOT EXISTS routed_entry_due ON routed_experiments(entry_state,at);
                CREATE INDEX IF NOT EXISTS routed_exit_due ON routed_outcomes(state,target_at);
                CREATE TABLE IF NOT EXISTS routed_runtime(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL);
            """)
            row = db.execute("SELECT payload FROM routed_runtime WHERE id=1").fetchone()
            if row:
                self.status = json.loads(row[0])

    def policy(self, config):
        return {
            "version": VERSION,
            "source_sha256": SOURCE_SHA256,
            "enabled": config.routed_quotes_enabled,
            "position_usd": str(config.position_usd),
            "slippage_bps": config.routed_slippage_bps,
            "entry_window_seconds": config.entry_window_seconds,
            "exit_window_seconds": config.exit_window_seconds,
            "horizons_seconds": config.horizons_seconds,
            "paper_rules": self.engine.service.frozen_rules(),
            "observation_rules": {
                k: getattr(self.engine.service.settings, k)
                for k in ["min_signal_delay", "max_snapshot_age"]
            },
            "quote_timeout_seconds": QUOTE_TIMEOUT,
            "model": "independent_jupiter_min_out_scenario",
            "execution_verified": False,
            "timestamp_clock": "utc_capture_clock_v1",
            "quote_schema_version": 2,
            "forward_quote_window_version": 2,
            "note": "USDC conversion and network fees are configured assumptions. Routes and min outputs are observed quotes, not executed fills. No fallback to estimated pool results.",
        }

    def enroll(self, db, candidate_id, signal_id, at, kind, decision, policy):
        p = dict(policy["payload"]["routed_policy"]) | {
            "opportunity_policy_id": policy["id"],
            "declared_at": policy["at"],
            "test_from": policy["payload"]["config"]["test_from"],
        }
        e = db.execute(
            "SELECT control_member FROM sampling_enrollment WHERE candidate_id=?", (candidate_id,)
        ).fetchone()
        state = "entry_pending" if p["enabled"] else "disabled_at_signal"
        if p["enabled"] and (
            decision["verdict"] == "REJECT"
            or not decision.get("screening", {}).get("paper_allowed")
        ):
            state = "entry_rejected"
        reason = (
            "original_risk_gate"
            if state == "entry_rejected"
            else state
            if state == "disabled_at_signal"
            else None
        )
        db.execute(
            "INSERT INTO routed_experiments(signal_id,candidate_id,at,policy,control_member,entry_state,reason) VALUES(?,?,?,?,?,?,?)",
            (
                signal_id,
                candidate_id,
                at,
                encoded(p),
                int(bool(e and e[0] and kind == "baseline")),
                state,
                reason,
            ),
        )
        for h in p["horizons_seconds"]:
            db.execute(
                "INSERT INTO routed_outcomes VALUES(?,?,NULL,?,?,?)",
                (
                    signal_id,
                    h,
                    "pending" if state == "entry_pending" else state,
                    encoded(
                        {
                            "pnl_usd": None,
                            "execution_verified": False,
                            "model": p["model"],
                            "reason": reason,
                        }
                    ),
                    utcnow(),
                ),
            )

    @staticmethod
    def fail_entry(db, signal_id, state, reason):
        db.execute(
            "UPDATE routed_experiments SET entry_state=?,reason=? WHERE signal_id=?",
            (state, reason, signal_id),
        )
        db.execute(
            "UPDATE routed_outcomes SET state=?,payload=json_set(payload,'$.reason',?),updated_at=? WHERE signal_id=? AND state IN ('pending','collecting')",
            (state, reason, utcnow(), signal_id),
        )

    def recover(self, db, now):
        # A lost/ambiguous request is terminal. Never retry until a better quote appears.
        db.create_function("routed_epoch", 1, epoch, deterministic=True)
        rows = db.execute(
            "SELECT * FROM routed_attempts WHERE status='collecting' AND routed_epoch(started_at)<?",
            (now - QUOTE_TIMEOUT - 10,),
        ).fetchall()
        for a in rows:
            db.execute(
                "UPDATE routed_attempts SET status='interrupted',completed_at=?,payload=? WHERE id=?",
                (utcnow(), encoded({"reason": "worker_interrupted", "pnl_usd": None}), a["id"]),
            )
            if a["phase"] == "entry":
                self.fail_entry(db, a["signal_id"], "entry_unavailable", "worker_interrupted")
            else:
                db.execute(
                    "UPDATE routed_outcomes SET state='exit_unavailable',payload=json_set(payload,'$.reason','worker_interrupted'),updated_at=? WHERE signal_id=? AND horizon_seconds=?",
                    (utcnow(), a["signal_id"], a["horizon_seconds"]),
                )

    def ready(self):
        now = epoch(utcnow())
        ready = []
        with self.store.connect() as db:
            self.recover(db, now)
            entries = db.execute(
                "SELECT e.*,c.contract FROM routed_experiments e JOIN opportunity_candidates c ON c.id=e.candidate_id WHERE e.entry_state='entry_pending' ORDER BY e.at LIMIT 2000"
            ).fetchall()
            exits = db.execute(
                "SELECT e.*,c.contract,o.horizon_seconds,o.target_at FROM routed_outcomes o JOIN routed_experiments e ON e.signal_id=o.signal_id JOIN opportunity_candidates c ON c.id=e.candidate_id WHERE e.entry_state='filled' AND o.state='pending' AND o.target_at<=? ORDER BY o.target_at LIMIT 2000",
                (now,),
            ).fetchall()
            for row in [*entries, *exits]:
                r = dict(row)
                p = json.loads(r["policy"])
                phase = "exit" if "target_at" in r else "entry"
                due = (
                    r["target_at"]
                    if phase == "exit"
                    else epoch(r["at"]) + p["observation_rules"]["min_signal_delay"]
                )
                deadline = (
                    due + p["exit_window_seconds"]
                    if phase == "exit"
                    else epoch(r["at"]) + p["entry_window_seconds"]
                )
                reason = None
                if p["source_sha256"] not in {SOURCE_SHA256, *COMPATIBLE_EXECUTION_SOURCES}:
                    reason = "cost_model_unavailable"
                elif now > deadline:
                    reason = "quote_deadline_missed"
                if reason:
                    if phase == "entry":
                        self.fail_entry(db, r["signal_id"], "entry_unavailable", reason)
                    else:
                        db.execute(
                            "UPDATE routed_outcomes SET state='exit_unavailable',payload=json_set(payload,'$.reason',?),updated_at=? WHERE signal_id=? AND horizon_seconds=?",
                            (reason, utcnow(), r["signal_id"], r["horizon_seconds"]),
                        )
                    continue
                if now < due:
                    continue
                obs = observation(
                    db,
                    r["candidate_id"],
                    due,
                    min(now, deadline),
                    p.get("forward_quote_window_version", 1),
                )
                if obs is None:
                    continue
                ready.append(
                    r
                    | {
                        "phase": phase,
                        "horizon_seconds": r.get("horizon_seconds", 0),
                        "due": due,
                        "deadline": deadline,
                        "frozen": p,
                        "observation": obs,
                    }
                )
        return sorted(ready, key=lambda r: (r["deadline"], r["signal_id"], r["horizon_seconds"]))

    def choose(self, ready, budget):
        result = []
        seen = set()
        groups = ["selected", "control_member"]
        if self.status.get("cycles", 0) % 2:
            groups.reverse()
        while len(result) < max(1, budget // 2):
            changed = False
            for group in groups:
                r = next(
                    (
                        r
                        for r in ready
                        if r[group]
                        and (r["signal_id"], r["phase"], r["horizon_seconds"]) not in seen
                    ),
                    None,
                )
                if r:
                    result.append(r)
                    seen.add((r["signal_id"], r["phase"], r["horizon_seconds"]))
                    changed = True
                if len(result) >= max(1, budget // 2):
                    break
            if not changed:
                break
        for r in ready:
            key = (r["signal_id"], r["phase"], r["horizon_seconds"])
            if key not in seen and len(result) < budget:
                result.append(r)
                seen.add(key)
        return result

    def claim(self, r):
        with self.store.connect() as db:
            if r["phase"] == "entry":
                changed = db.execute(
                    "UPDATE routed_experiments SET entry_state='collecting' WHERE signal_id=? AND entry_state='entry_pending'",
                    (r["signal_id"],),
                ).rowcount
            else:
                changed = db.execute(
                    "UPDATE routed_outcomes SET state='collecting' WHERE signal_id=? AND horizon_seconds=? AND state='pending'",
                    (r["signal_id"], r["horizon_seconds"]),
                ).rowcount
            if not changed:
                return None
            a = db.execute(
                "INSERT INTO routed_attempts(signal_id,phase,horizon_seconds,started_at,status,observation_id,payload) VALUES(?,?,?,?,?,?,?)",
                (
                    r["signal_id"],
                    r["phase"],
                    r["horizon_seconds"],
                    utcnow(),
                    "collecting",
                    r["observation"]["id"],
                    encoded({"pnl_usd": None, "execution_verified": False}),
                ),
            )
            return a.lastrowid

    def finish(self, r, attempt_id, quote, error=None):
        at = utcnow()
        with self.store.connect() as db:
            changed = db.execute(
                "UPDATE routed_attempts SET completed_at=?,status=?,payload=? WHERE id=? AND status='collecting'",
                (
                    at,
                    "unavailable" if error else "quoted",
                    encoded({"reason": error, "quote": quote, "execution_verified": False}),
                    attempt_id,
                ),
            ).rowcount
            if not changed:
                return
            if error:
                if r["phase"] == "entry":
                    self.fail_entry(db, r["signal_id"], "entry_unavailable", error)
                else:
                    db.execute(
                        "UPDATE routed_outcomes SET state='exit_unavailable',payload=json_set(payload,'$.reason',?,'$.attempt_id',?),updated_at=? WHERE signal_id=? AND horizon_seconds=?",
                        (error, attempt_id, at, r["signal_id"], r["horizon_seconds"]),
                    )
                return
            if r["phase"] == "entry":
                entry_at = quote["quote_observed_at"]
                db.execute(
                    "UPDATE routed_experiments SET entry_state='filled',entry_at=?,entry_payload=?,entry_attempt_id=? WHERE signal_id=?",
                    (entry_at, encoded(quote), attempt_id, r["signal_id"]),
                )
                for h in r["frozen"]["horizons_seconds"]:
                    target = epoch(entry_at) + h
                    db.execute(
                        "UPDATE routed_outcomes SET target_at=?,payload=json_set(payload,'$.entry_attempt_id',?,'$.entry_at',?,'$.entry_cost_usd',?),updated_at=? WHERE signal_id=? AND horizon_seconds=? AND state='pending'",
                        (
                            target,
                            attempt_id,
                            entry_at,
                            str(-Decimal(quote["cash_change"])),
                            at,
                            r["signal_id"],
                            h,
                        ),
                    )
                    self.engine.sampling.job(
                        db,
                        r["candidate_id"],
                        r["signal_id"],
                        "routed_exit",
                        h,
                        target,
                        target + r["frozen"]["exit_window_seconds"],
                        bool(r["selected"]),
                        bool(r["control_member"]),
                    )
            else:
                entry = json.loads(r["entry_payload"])
                pnl = Decimal(quote["cash_change"]) + Decimal(entry["cash_change"])
                payload = {
                    "pnl_usd": str(pnl),
                    "entry_cost_usd": str(-Decimal(entry["cash_change"])),
                    "entry_at": r["entry_at"],
                    "exit_at": quote["quote_observed_at"],
                    "entry_attempt_id": r["entry_attempt_id"],
                    "exit_attempt_id": attempt_id,
                    "actual_hold_seconds": epoch(quote["quote_observed_at"]) - epoch(r["entry_at"]),
                    "entry_quote": entry,
                    "exit_quote": quote,
                    "execution_verified": False,
                    "model": "independent_jupiter_min_out_scenario",
                }
                db.execute(
                    "UPDATE routed_outcomes SET state='evaluated',payload=?,updated_at=? WHERE signal_id=? AND horizon_seconds=?",
                    (encoded(payload), at, r["signal_id"], r["horizon_seconds"]),
                )

    async def collect(self, r):
        attempt_id = self.claim(r)
        if attempt_id is None:
            return
        quote = None
        error = None
        try:
            settings = settings_at(self.engine, r["frozen"])
            obs = r["observation"]
            available(obs, settings, r["due"])
            require_fresh(
                {"at": obs["at"], "market": obs["market"], "security": obs["security"]},
                settings,
                epoch(utcnow()),
            )
            if obs["decision"]["verdict"] == "REJECT":
                raise Rejected("risk_gate")
            size = (
                r["frozen"]["position_usd"]
                if r["phase"] == "entry"
                else json.loads(r["entry_payload"])["quantity"]
            )
            side = "buy" if r["phase"] == "entry" else "sell"
            # Share the HTTP connection pool, but use immutable signal-time costs.
            source = Jupiter(
                settings, self.engine.service.onchain, self.engine.service.jupiter.client
            )
            quote = await asyncio.wait_for(
                source.fill(side, size, r["contract"], r["frozen"]["slippage_bps"]),
                timeout=r["frozen"]["quote_timeout_seconds"],
            )
            now = epoch(utcnow())
            validate_execution(quote, side, size, {"address": r["contract"]}, now)
            if not r["due"] <= epoch(quote["quote_observed_at"]) <= now <= r["deadline"]:
                raise Rejected("quote_outside_window")
            require_fresh(
                {"at": obs["at"], "market": obs["market"], "security": obs["security"]},
                settings,
                now,
            )
        except asyncio.CancelledError:
            self.finish(r, attempt_id, None, "worker_interrupted")
            raise
        except (
            ProviderError,
            Rejected,
            ValueError,
            TypeError,
            KeyError,
            ArithmeticError,
            TimeoutError,
        ) as exc:
            error = f"{type(exc).__name__}: {str(exc)[:240]}"
        self.finish(r, attempt_id, quote, error)
        return error

    async def cycle(self):
        async with self.lock:
            try:
                ready = self.ready()
                cfg = self.engine.config()
                chosen = (
                    self.choose(ready, cfg.routed_quote_budget) if cfg.routed_quotes_enabled else []
                )
                errors = []
                for r in chosen:
                    error = await self.collect(r)
                    if error:
                        errors.append(error)
                self.status = {
                    "state": ("partial" if errors else "ok")
                    if cfg.routed_quotes_enabled
                    else "disabled",
                    "at": utcnow(),
                    "cycles": self.status.get("cycles", 0) + 1,
                    "attempted": len(chosen),
                    "ready": len(ready),
                    "errors": sorted(set(errors)),
                }
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("Routed quote collection failed: %s", type(exc).__name__)
                self.status = {
                    "state": "error",
                    "at": utcnow(),
                    "error": type(exc).__name__,
                    "cycles": self.status.get("cycles", 0),
                }
            with self.store.connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO routed_runtime VALUES(1,?)", (encoded(self.status),)
                )
        return self.status

    def detail(self, candidate_id):
        with self.store.connect() as db:
            entries = [
                dict(r)
                | {
                    "policy": json.loads(r["policy"]),
                    "entry_payload": json.loads(r["entry_payload"]) if r["entry_payload"] else None,
                }
                for r in db.execute(
                    "SELECT * FROM routed_experiments WHERE candidate_id=? ORDER BY signal_id",
                    (candidate_id,),
                )
            ]
            outcomes = [
                dict(r) | {"payload": json.loads(r["payload"])}
                for r in db.execute(
                    "SELECT o.* FROM routed_outcomes o JOIN routed_experiments e ON e.signal_id=o.signal_id WHERE e.candidate_id=? ORDER BY o.signal_id,o.horizon_seconds",
                    (candidate_id,),
                )
            ]
            attempts = [
                dict(r) | {"payload": json.loads(r["payload"])}
                for r in db.execute(
                    "SELECT a.* FROM routed_attempts a JOIN routed_experiments e ON e.signal_id=a.signal_id WHERE e.candidate_id=? ORDER BY a.id",
                    (candidate_id,),
                )
            ]
        return {
            "entries": entries,
            "outcomes": outcomes,
            "attempts": attempts,
            "execution_verified": False,
        }

    def report(self):
        with self.store.connect() as db:
            db.create_function("routed_epoch", 1, epoch, deterministic=True)
            states = {
                r["entry_state"]: r["n"]
                for r in db.execute(
                    "SELECT entry_state,count(*) AS n FROM routed_experiments GROUP BY entry_state"
                )
            }
            rows = [
                dict(r) | {"payload": json.loads(r["payload"])}
                for r in db.execute(
                    "SELECT o.*,e.selected,e.control_member,e.policy,e.at AS signal_at,s.kind FROM routed_outcomes o JOIN routed_experiments e ON e.signal_id=o.signal_id JOIN opportunity_signals s ON s.id=o.signal_id"
                )
            ]
            reasons = dict(
                Counter(
                    r["reason"]
                    for r in db.execute(
                        "SELECT reason FROM routed_experiments WHERE reason IS NOT NULL"
                    )
                )
            )
            legacy = db.execute(
                "SELECT count(*) FROM opportunity_signals s WHERE s.kind='baseline' AND NOT EXISTS(SELECT 1 FROM routed_experiments e WHERE e.signal_id=s.id)"
            ).fetchone()[0]
            recent = [
                dict(r) | {"payload": json.loads(r["payload"])}
                for r in db.execute(
                    "SELECT a.*,e.candidate_id,c.contract FROM routed_attempts a JOIN routed_experiments e ON e.signal_id=a.signal_id JOIN opportunity_candidates c ON c.id=e.candidate_id ORDER BY a.id DESC LIMIT 10"
                )
            ]
            attempts = [
                dict(r)
                for r in db.execute(
                    "SELECT phase,status,count(*) AS n FROM routed_attempts GROUP BY phase,status"
                )
            ]
            overdue_entries = db.execute(
                "SELECT count(*) FROM routed_experiments WHERE entry_state='entry_pending' AND routed_epoch(at)+json_extract(policy,'$.entry_window_seconds')<?",
                (epoch(utcnow()),),
            ).fetchone()[0]
            overdue_exits = db.execute(
                "SELECT count(*) FROM routed_outcomes o JOIN routed_experiments e ON e.signal_id=o.signal_id WHERE o.state='pending' AND o.target_at+json_extract(e.policy,'$.exit_window_seconds')<?",
                (epoch(utcnow()),),
            ).fetchone()[0]
        for row in rows:
            policy = json.loads(row.pop("policy"))
            row["policy_id"] = policy["opportunity_policy_id"]
            cutoff = policy.get("test_from")
            signal_at = epoch(row["signal_at"])
            latest_end = (
                signal_at
                + policy["entry_window_seconds"]
                + row["horizon_seconds"]
                + policy["exit_window_seconds"]
            )
            row["split"] = (
                "unassigned"
                if not cutoff
                or not policy.get("declared_at")
                or epoch(cutoff) < epoch(policy["declared_at"])
                else "test"
                if signal_at >= epoch(cutoff)
                else "purged_boundary"
                if latest_end >= epoch(cutoff)
                else "development"
            )
        horizons = {}
        for h in sorted({r["horizon_seconds"] for r in rows}):
            same = [r for r in rows if r["horizon_seconds"] == h]
            horizons[str(h)] = {
                "all_first_evaluations": summary([r for r in same if r["kind"] == "baseline"]),
                "alerts": summary([r for r in same if r["selected"]]),
                "fixed_control": summary(
                    [r for r in same if r["kind"] == "baseline" and r["control_member"]]
                ),
                "by_policy": {
                    str(p): summary(
                        [r for r in same if r["kind"] == "baseline" and r["policy_id"] == p]
                    )
                    for p in sorted({r["policy_id"] for r in same})
                },
                "by_split": {
                    s: summary([r for r in same if r["kind"] == "baseline" and r["split"] == s])
                    for s in ["development", "test", "purged_boundary", "unassigned"]
                },
            }
        return {
            "version": VERSION,
            "status": self.status,
            "enabled": self.engine.config().routed_quotes_enabled,
            "entry_states": states,
            "entry_failure_reasons": reasons,
            "legacy_baselines_not_measured": legacy,
            "horizons": horizons,
            "recent_attempts": recent,
            "attempt_counts": attempts,
            "overdue_unprocessed": {"entries": overdue_entries, "exits": overdue_exits},
            "execution_verified": False,
            "note": "Separate Jupiter quote experiments; no pool fallback or historical backfill. Min-out quotes are hypothetical fills, not guaranteed execution. Network/conversion fees are assumptions; missing exits have null PnL. Quote route need not use the discovery pool. Groups can overlap; incomplete coverage and small samples do not establish profitability.",
        }
