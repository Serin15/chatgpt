"""Prospective control enrollment and deadline-based observation work. No trading."""

import json
import time
from collections import Counter, deque

from app.models import epoch, utcnow
from app.opportunity_rules import EngineConfig

SAMPLING_VERSION = "balanced-deadlines-v1"


def control_member(contract):
    import hashlib

    return int(hashlib.sha256(contract.encode()).hexdigest()[:8], 16) % 5 == 0


class Sampling:
    def __init__(self, engine):
        self.engine, self.store = engine, engine.store
        with self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sampling_metadata(id INTEGER PRIMARY KEY CHECK(id=1),at TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sampling_enrollment(candidate_id INTEGER PRIMARY KEY,at TEXT NOT NULL,control_member INTEGER NOT NULL,provenance TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS observation_jobs(id INTEGER PRIMARY KEY,candidate_id INTEGER NOT NULL,signal_id INTEGER NOT NULL,phase TEXT NOT NULL,horizon_seconds INTEGER NOT NULL,due_at REAL NOT NULL,deadline_at REAL NOT NULL,selected INTEGER NOT NULL DEFAULT 0,control_member INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'pending',observation_id INTEGER,reason TEXT,last_dispatch_at REAL,UNIQUE(signal_id,phase,horizon_seconds));
                CREATE INDEX IF NOT EXISTS observation_jobs_due ON observation_jobs(status,due_at,deadline_at);
                CREATE INDEX IF NOT EXISTS observation_jobs_subject ON observation_jobs(candidate_id,status);
                CREATE INDEX IF NOT EXISTS opportunity_candidates_due ON opportunity_candidates(next_due,id);
                CREATE INDEX IF NOT EXISTS opportunity_outcomes_pending ON opportunity_outcomes(state,updated_at);
            """)
            if db.execute("SELECT 1 FROM sampling_metadata").fetchone():
                return
            config = engine.config()
            # Only upgrade the old, entirely unchanged preset. Custom budgets and
            # financial risk settings are preserved.
            upgraded = config == EngineConfig(observation_budget=30)
            if upgraded:
                config = config.model_copy(update={"observation_budget": 60})
                db.execute(
                    "UPDATE opportunity_config SET at=?,payload=? WHERE id=1",
                    (utcnow(), config.model_dump_json()),
                )
            now = time.time()
            at = utcnow()
            for c in db.execute("SELECT id,contract FROM opportunity_candidates").fetchall():
                self.enroll(db, c["id"], c["contract"], at, "legacy")
            # Historical decisions and results remain unchanged. Old low-priority
            # polling must not fill every cycle before any new token is enriched.
            db.execute(
                "UPDATE opportunity_candidates SET next_due=max(next_due,CAST(strftime('%s',last_attempt_at) AS REAL)+?) WHERE last_attempt_at IS NOT NULL AND CAST(strftime('%s',ingested_at) AS REAL)<?",
                (config.background_interval_seconds, now - config.active_watch_seconds),
            )
            # Recover already promised future horizons, with their original policy.
            rows = db.execute(
                "SELECT o.*,s.candidate_id,s.at AS signal_at,s.payload AS signal_payload FROM opportunity_outcomes o JOIN opportunity_signals s ON s.id=o.signal_id WHERE o.state='pending'"
            ).fetchall()
            for row in rows:
                p = json.loads(row["payload"])
                policy = json.loads(row["signal_payload"])["policy"]["payload"]
                cfg = policy["config"]
                selected = bool(
                    db.execute(
                        "SELECT 1 FROM opportunity_alerts WHERE signal_id=? AND severity!='critical'",
                        (row["signal_id"],),
                    ).fetchone()
                )
                target = p.get("target_at_epoch")
                if (
                    target is not None
                    and p.get("entry_quote")
                    and target + cfg["exit_window_seconds"] >= now
                ):
                    self.job(
                        db,
                        row["candidate_id"],
                        row["signal_id"],
                        "exit",
                        row["horizon_seconds"],
                        target,
                        target + cfg["exit_window_seconds"],
                        selected,
                    )
                elif (
                    not p.get("entry_quote")
                    and epoch(row["signal_at"]) + cfg["entry_window_seconds"] >= now
                ):
                    self.job(
                        db,
                        row["candidate_id"],
                        row["signal_id"],
                        "entry",
                        0,
                        epoch(row["signal_at"])
                        + policy.get("observation_rules", {}).get("min_signal_delay", 3),
                        epoch(row["signal_at"]) + cfg["entry_window_seconds"],
                        selected,
                    )
            db.execute(
                "INSERT INTO sampling_metadata VALUES(1,?,?)",
                (
                    at,
                    json.dumps(
                        {
                            "version": SAMPLING_VERSION,
                            "old_default_budget_upgraded": upgraded,
                            "legacy_outcomes_recovered": True,
                        }
                    ),
                ),
            )

    @staticmethod
    def enroll(db, candidate_id, contract, at, provenance="prospective"):
        db.execute(
            "INSERT OR IGNORE INTO sampling_enrollment VALUES(?,?,?,?)",
            (candidate_id, at, int(control_member(contract)), provenance),
        )

    @staticmethod
    def enrolled_control(db, candidate_id):
        row = db.execute(
            "SELECT control_member FROM sampling_enrollment WHERE candidate_id=?", (candidate_id,)
        ).fetchone()
        return bool(row and row[0])

    @staticmethod
    def job(
        db, candidate_id, signal_id, phase, horizon, due, deadline, selected=False, control=None
    ):
        if control is None:
            e = db.execute(
                "SELECT control_member FROM sampling_enrollment WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
            control = bool(e and e[0])
        db.execute(
            "INSERT OR IGNORE INTO observation_jobs(candidate_id,signal_id,phase,horizon_seconds,due_at,deadline_at,selected,control_member) VALUES(?,?,?,?,?,?,?,?)",
            (candidate_id, signal_id, phase, horizon, due, deadline, int(selected), int(control)),
        )

    @staticmethod
    def expire(db, now):
        db.execute(
            "UPDATE observation_jobs SET status='missed',reason=CASE WHEN last_dispatch_at IS NULL THEN 'capacity_or_worker_gap' ELSE 'collection_finished_after_deadline' END WHERE status='pending' AND deadline_at<?",
            (now,),
        )

    def choose(self, config):
        now = time.time()
        with self.store.connect() as db:
            self.expire(db, now)

            def ready(condition):
                return deque(
                    db.execute(
                        "SELECT c.*,min(j.deadline_at) AS collection_deadline FROM observation_jobs j JOIN opportunity_candidates c ON c.id=j.candidate_id WHERE c.eligible=1 AND j.status='pending' AND j.due_at<=? AND j.deadline_at>=? AND "
                        + condition
                        + " GROUP BY c.id ORDER BY collection_deadline,c.id LIMIT ?",
                        (now, now, config.observation_budget * 2),
                    ).fetchall()
                )

            selected, controls = ready("j.selected=1"), ready("j.control_member=1")
            queues = [selected, controls]
            if self.engine.status.get("cycles", 0) % 2:
                queues.reverse()
            chosen = []
            ids = set()

            def take(rows, limit, lane):
                if limit <= 0:
                    return
                added = 0
                for r in rows:
                    if r["id"] in ids:
                        continue
                    chosen.append(
                        dict(r) | {"discovery": json.loads(r["discovery"]), "collection_lane": lane}
                    )
                    ids.add(r["id"])
                    added += 1
                    if added >= limit:
                        break

            # Equal opportunities to use the protected slots; overlapping subjects
            # consume one quote. Unused slots can be borrowed by the other group.
            while len(chosen) < max(1, config.observation_budget // 2) and any(queues):
                for q in queues:
                    if len(chosen) >= max(1, config.observation_budget // 2):
                        break
                    while q and q[0]["id"] in ids:
                        q.popleft()
                    if q:
                        take([q.popleft()], 1, "protected_followup")
            fresh = db.execute(
                "SELECT * FROM opportunity_candidates WHERE eligible=1 AND last_attempt_at IS NULL AND next_due<=? AND json_extract(discovery,'$.imported_from_cache')=0 ORDER BY discovered_at,id LIMIT ?",
                (now, config.observation_budget + len(ids)),
            ).fetchall()
            take(
                fresh,
                min(
                    max(1, config.observation_budget // 3), config.observation_budget - len(chosen)
                ),
                "discovery",
            )
            if len(chosen) < config.observation_budget:
                take(ready("1=1"), config.observation_budget - len(chosen), "other_followup")
            if len(chosen) < config.observation_budget:
                rows = db.execute(
                    "SELECT * FROM opportunity_candidates WHERE eligible=1 AND next_due<=? ORDER BY next_due,id LIMIT ?",
                    (now, config.observation_budget + len(ids)),
                ).fetchall()
                take(rows, config.observation_budget - len(chosen), "background")
        return chosen

    def dispatch(self, candidates):
        now = time.time()
        with self.store.connect() as db:
            db.executemany(
                "UPDATE observation_jobs SET last_dispatch_at=? WHERE candidate_id=? AND status='pending' AND due_at<=? AND deadline_at>=?",
                [(now, c["id"], now, now) for c in candidates],
            )

    @staticmethod
    def record(db, candidate_id, observation_id, payload, at):
        t = epoch(at)
        m = payload.get("market")
        s = payload.get("security") or {}
        reason = "quote_received" if m else "provider_quote_unavailable"
        if m and (payload.get("decision") or {}).get("screening", {}).get("critical"):
            reason = "risk_or_liquidity_gate"
        elif m and (not s.get("rpc") or not s.get("goplus")):
            reason = "security_evidence_unavailable"
        elif m and not (payload.get("decision") or {}).get("screening", {}).get("paper_allowed"):
            reason = "risk_or_liquidity_gate"
        db.execute(
            "UPDATE observation_jobs SET status='attempted',observation_id=?,reason=CASE WHEN ? IS NOT NULL AND ?>=due_at THEN ? WHEN ? IS NOT NULL THEN 'quote_before_window' ELSE ? END WHERE candidate_id=? AND status='pending' AND due_at<=? AND deadline_at>=?",
            (
                observation_id,
                epoch(m["observed_at"]) if m else None,
                epoch(m["observed_at"]) if m else None,
                reason,
                epoch(m["observed_at"]) if m else None,
                reason,
                candidate_id,
                t,
                t,
            ),
        )

    def enrollment(self, candidate_id):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM sampling_enrollment WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
        return dict(row) | {"version": SAMPLING_VERSION} if row else None

    @staticmethod
    def sync_outcome(db, row, payload, state, config):
        entry = db.execute(
            "SELECT * FROM observation_jobs WHERE signal_id=? AND phase='entry'",
            (row["signal_id"],),
        ).fetchone()
        if entry and payload.get("entry_quote"):
            target = payload["target_at_epoch"]
            Sampling.job(
                db,
                row["candidate_id"],
                row["signal_id"],
                "exit",
                row["horizon_seconds"],
                target,
                target + config["exit_window_seconds"],
                bool(entry["selected"]),
                bool(entry["control_member"]),
            )
        phase = "exit" if payload.get("entry_quote") else "entry"
        h = row["horizon_seconds"] if phase == "exit" else 0
        job = db.execute(
            "SELECT * FROM observation_jobs WHERE signal_id=? AND phase=? AND horizon_seconds=?",
            (row["signal_id"], phase, h),
        ).fetchone()
        if job:
            obs_id = payload.get(
                "exit_observation_id" if phase == "exit" else "entry_observation_id"
            )
            if obs_id:
                db.execute(
                    "UPDATE observation_jobs SET status='attempted',observation_id=?,reason=coalesce(reason,?) WHERE id=?",
                    (obs_id, "evaluated" if state == "evaluated" else state, job["id"]),
                )
            payload["collection"] = {
                "phase": phase,
                "job_id": job["id"],
                "status": "attempted" if obs_id else job["status"],
                "reason": job["reason"] or (state if state != "pending" else None),
                "deadline_at_epoch": job["deadline_at"],
            }

    def coverage(self):
        with self.store.connect() as db:
            meta = db.execute("SELECT * FROM sampling_metadata WHERE id=1").fetchone()
            enrollment = [
                dict(r)
                for r in db.execute(
                    "SELECT e.provenance,e.control_member,count(*) AS n,sum(c.last_attempt_at IS NULL) AS never_observed FROM sampling_enrollment e JOIN opportunity_candidates c ON c.id=e.candidate_id WHERE c.eligible=1 GROUP BY e.provenance,e.control_member"
                )
            ]
            jobs = [
                dict(r)
                for r in db.execute(
                    "SELECT phase,reported_status AS status,reported_reason AS reason,selected,control_member,provenance,count(*) AS n FROM (SELECT j.*,e.provenance,CASE WHEN status='pending' AND deadline_at<? THEN 'missed' ELSE status END AS reported_status,CASE WHEN status='pending' AND deadline_at<? THEN CASE WHEN last_dispatch_at IS NULL THEN 'capacity_or_worker_gap' ELSE 'collection_finished_after_deadline' END ELSE reason END AS reported_reason FROM observation_jobs j LEFT JOIN sampling_enrollment e ON e.candidate_id=j.candidate_id) GROUP BY phase,reported_status,reported_reason,selected,control_member,provenance",
                    (time.time(), time.time()),
                )
            ]
            due = db.execute(
                "SELECT count(*) AS jobs,count(DISTINCT candidate_id) AS candidates,min(deadline_at) AS earliest FROM observation_jobs WHERE status='pending' AND due_at<=? AND deadline_at>=?",
                (time.time(), time.time()),
            ).fetchone()
            recent = {}
            for name, field in [("alerts", "selected"), ("control", "control_member")]:
                query = (
                    "SELECT j.id,j.candidate_id,c.contract,c.chain,e.provenance,j.signal_id,j.phase,j.horizon_seconds,j.due_at,j.deadline_at,j.reason,o.at AS observed_at,json_extract(o.payload,'$.market.observed_at') AS quote_observed_at,json_extract(o.payload,'$.source_kind') AS source_kind FROM observation_jobs j JOIN opportunity_candidates c ON c.id=j.candidate_id JOIN sampling_enrollment e ON e.candidate_id=c.id JOIN opportunity_observations o ON o.id=j.observation_id WHERE j.status='attempted' AND j."
                    + field
                    + "=1 AND e.provenance='prospective' "
                )
                recent[name] = [
                    dict(r) for r in db.execute(query + "ORDER BY o.id DESC,j.id DESC LIMIT 5")
                ]
                for phase in ["exit", "checkpoint", "routed_exit"]:
                    if not any(r["phase"] == phase for r in recent[name]):
                        latest = db.execute(
                            query + "AND j.phase=? ORDER BY o.id DESC,j.id DESC LIMIT 1", (phase,)
                        ).fetchone()
                        if latest:
                            recent[name].append(dict(latest))
        scopes = {}
        for scope, subjects in [
            ("groups", jobs),
            ("prospective_groups", [r for r in jobs if r["provenance"] == "prospective"]),
            ("legacy_groups", [r for r in jobs if r["provenance"] == "legacy"]),
        ]:
            groups = {}
            for name, key in [("alerts", "selected"), ("control", "control_member")]:
                rows = [r for r in subjects if r[key]]
                by_phase = {}
                for phase in ["entry", "exit", "checkpoint", "routed_exit"]:
                    counts = Counter()
                    for r in rows:
                        if r["phase"] == phase:
                            counts[r["status"]] += r["n"]
                    attempted = counts["attempted"]
                    resolved = attempted + counts["missed"]
                    by_phase[phase] = {
                        "scheduled": sum(counts.values()),
                        "attempted": attempted,
                        "missed": counts["missed"],
                        "pending": counts["pending"],
                        "cancelled": counts["cancelled"],
                        "observed_attempt_rate": attempted / resolved if resolved else None,
                    }
                groups[name] = by_phase
            scopes[scope] = groups
        reasons = Counter()
        prospective_reasons = Counter()
        for r in jobs:
            if r["reason"]:
                reasons[r["reason"]] += r["n"]
                if r["provenance"] == "prospective":
                    prospective_reasons[r["reason"]] += r["n"]
        return {
            "version": SAMPLING_VERSION,
            "activated_at": meta["at"],
            "generated_at": utcnow(),
            "policy": json.loads(meta["payload"]),
            "enrollment": enrollment,
            **scopes,
            "reasons": dict(reasons),
            "prospective_reasons": dict(prospective_reasons),
            "due": dict(due),
            "recent_attempts": recent,
            "note": "Control membership fixed at discovery by contract hash, independent of score/return. Legacy data are not prospectively balanced. Groups may overlap. An observation attempt is not a successful fill; capacity and provider gaps remain explicit.",
        }
