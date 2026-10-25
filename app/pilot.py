"""A prospective, immutable 30-day Solana study; read-only outcome reporting."""

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from app.cohort_comparisons import comparison
from app.daily_research import summarize
from app.models import epoch, utcnow
from app.price_research import capture

VERSION = "solana-pilot-v1"
DAYS = 30


def seconds(value):
    try:
        result = epoch(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def latency(pairs, now=None):
    values, missing, invalid = [], 0, 0
    for start, end in pairs:
        if start is None or end is None:
            missing += 1
            continue
        a, b = seconds(start), seconds(end)
        if a is None or b is None or b < a or now is not None and b > now:
            invalid += 1
        else:
            values.append(b - a)
    values.sort()
    return {
        "subjects": len(values) + missing + invalid,
        "measured": len(values), "missing": missing, "invalid_clock": invalid,
        "p50_seconds": values[math.ceil(len(values) * .5) - 1] if values else None,
        "p95_seconds": values[math.ceil(len(values) * .95) - 1] if values else None,
        "max_seconds": values[-1] if values else None,
        "method": "nearest-rank empirical quantiles; receipt timestamps, not exchange execution",
    }


class Pilot:
    def __init__(self, engine):
        self.engine = engine
        with engine.store.connect() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS pilot_study(
                id INTEGER PRIMARY KEY CHECK(id=1),declared_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,sha256 TEXT NOT NULL,payload TEXT NOT NULL);
              CREATE TRIGGER IF NOT EXISTS pilot_no_update BEFORE UPDATE ON pilot_study
                BEGIN SELECT RAISE(ABORT,'Pilot declarations are immutable'); END;
              CREATE TRIGGER IF NOT EXISTS pilot_no_delete BEFORE DELETE ON pilot_study
                BEGIN SELECT RAISE(ABORT,'Pilot declarations are immutable'); END;
              CREATE INDEX IF NOT EXISTS pilot_candidate_ingestion
                ON opportunity_candidates(chain,ingested_at,id);
            """)

    @staticmethod
    def read(db):
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pilot_study'"
        ).fetchone():
            return None
        row = db.execute("SELECT * FROM pilot_study WHERE id=1").fetchone()
        return dict(row) | {"payload": json.loads(row["payload"])} if row else None

    def status(self):
        with self.engine.store.connect() as db:
            return self.read(db)

    def start(self):
        existing = self.status()
        if existing:
            return existing
        policy = self.engine.policy(self.engine.config())
        declared = utcnow()
        ends = (datetime.fromisoformat(declared) + timedelta(days=DAYS)).isoformat()
        with self.engine.store.connect() as db:
            prior = db.execute(
                "SELECT test_from FROM forward_evaluation_protocols WHERE policy_id=?",
                (policy["id"],),
            ).fetchone()
            analysis_from = max(declared, prior[0]) if prior else declared
            payload = {
                "version": VERSION, "duration_days": DAYS, "chain": "solana",
                "policy_id": policy["id"], "policy_sha256": policy["sha256"],
                "policy": policy["payload"], "analysis_from": analysis_from,
                "cohort": "new engine registrations during [declared_at, ends_at); no historical enrollment",
                "selection": "noncritical alert on the original first baseline only",
                "control": "prospective contract-hash enrollment, excluding selected tokens",
                "maturity": "signal + frozen entry window + horizon + exit window; same rule for all groups",
                "changed_policies": "retained in universe, excluded from frozen-policy comparison",
                "costs": "original independent paper outcomes, pool and Jupiter kept separate",
                "threshold_optimization": False, "real_money_execution": False,
            }
            encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False)
            fingerprint = hashlib.sha256((declared + ends + encoded).encode()).hexdigest()
            db.execute(
                "INSERT OR IGNORE INTO pilot_study VALUES(1,?,?,?,?)",
                (declared, ends, fingerprint, encoded),
            )
            return self.read(db)


COHORT = """WITH cohort AS MATERIALIZED (
  SELECT * FROM opportunity_candidates
  WHERE chain='solana' AND ingested_at>=:start AND ingested_at<:end
    AND ingested_at<=:at
) """
OBS = "CASE WHEN typeof(o.payload)='blob' THEN archive_text(o.payload) ELSE o.payload END"


def report(engine, now=None):
    at = utcnow() if now is None else datetime.fromtimestamp(now, UTC).isoformat()
    clock = seconds(at)
    with engine.store.connect() as db:
        db.execute("BEGIN")
        study = Pilot.read(db)
        if study is None:
            return {"version": VERSION, "study": None, "report_state": "not_started"}
        p = study["payload"]
        params = {"start": study["declared_at"], "end": study["ends_at"], "at": at}
        rows = db.execute(COHORT + f"""
          SELECT c.id,c.contract,c.pool,c.discovered_at,c.ingested_at,c.eligible,
            s.id AS signal_id,s.at AS signal_at,s.policy_id,s.verdict,
            json_extract(s.payload,'$.security_filter_passed') AS security_pass,
            json_extract(s.payload,'$.liquidity_filter_passed') AS liquidity_pass,
            e.provenance,e.at AS enrolled_at,e.control_member,
            json_extract({OBS},'$.source_kind') AS source_kind
          FROM cohort c LEFT JOIN opportunity_signals s ON s.id=(
            SELECT id FROM opportunity_signals WHERE candidate_id=c.id AND kind='baseline'
            ORDER BY id LIMIT 1)
          LEFT JOIN sampling_enrollment e ON e.candidate_id=c.id
          LEFT JOIN opportunity_observations o ON o.id=s.observation_id AND o.candidate_id=c.id
        """, params).fetchall()
        candidates = {r["id"]: dict(r) for r in rows}
        # Candidate ingestion is internally UTC. Do not admit a rounded future timestamp.
        candidates = {k: r for k, r in candidates.items()
                      if seconds(r["ingested_at"]) is not None
                      and seconds(study["declared_at"]) <= seconds(r["ingested_at"]) <= clock
                      and seconds(r["ingested_at"]) < seconds(study["ends_at"])}
        for row in candidates.values():
            if row["signal_id"] is not None and (
                seconds(row["signal_at"]) is None or seconds(row["signal_at"]) > clock
            ):
                for field in ["signal_id", "signal_at", "policy_id", "verdict",
                              "security_pass", "liquidity_pass", "source_kind"]:
                    row[field] = None
        alerts = [dict(r) for r in db.execute(COHORT + """
          SELECT a.*,s.at AS signal_at,s.policy_id FROM opportunity_alerts a
          JOIN cohort c ON c.id=a.candidate_id JOIN opportunity_signals s ON s.id=a.signal_id
          WHERE a.at>=:start AND a.at<:end AND a.at<=:at ORDER BY a.id
        """, params) if r["candidate_id"] in candidates
            and seconds(r["at"]) is not None and seconds(r["at"]) <= clock]
        first_alerts = {a["signal_id"]: a for a in alerts if a["severity"] != "critical"}
        alert_subjects = {}
        alerted_candidates = set()
        for alert in alerts:
            if (alert["severity"] == "critical" or alert["candidate_id"] in alerted_candidates
                    or alert["policy_id"] != p["policy_id"]
                    or seconds(alert["signal_at"]) is None
                    or seconds(alert["signal_at"]) > seconds(alert["at"])
                    or seconds(alert["signal_at"]) < seconds(p["analysis_from"])):
                continue
            alerted_candidates.add(alert["candidate_id"])
            alert_subjects[alert["signal_id"]] = alert
        firsts, exclusions = {}, Counter()
        for row in candidates.values():
            when = seconds(row["signal_at"])
            if when is None or when > clock:
                exclusions["no_first_evaluation_yet"] += 1
            elif not row["eligible"]:
                exclusions["discovery_excluded"] += 1
            elif when < seconds(study["declared_at"]) or when < seconds(row["ingested_at"]):
                exclusions["invalid_signal_clock"] += 1
            elif when >= seconds(study["ends_at"]):
                exclusions["first_evaluation_after_pilot"] += 1
            elif row["policy_id"] != p["policy_id"]:
                exclusions["changed_policy"] += 1
            elif row["source_kind"] != "live_provider_observation":
                exclusions["unverified_source_kind"] += 1
            elif (row["provenance"] != "prospective" or seconds(row["enrolled_at"]) is None
                  or seconds(row["enrolled_at"]) > when):
                exclusions["prospective_enrollment_unavailable"] += 1
            elif when < seconds(p["analysis_from"]):
                exclusions["original_holdout_not_started"] += 1
            else:
                firsts[row["signal_id"]] = row | {
                    "selected": row["signal_id"] in first_alerts,
                    "control": bool(row["control_member"]),
                }
        models, entry_pairs, alert_entry_pairs, alert_followup = {}, {}, {}, {}
        config = p["policy"]["config"]
        for name, table in [("estimated_pool", "opportunity_outcomes"),
                            ("jupiter_quotes", "routed_outcomes")]:
            outcomes = {}
            for row in db.execute(COHORT + f"""
              SELECT r.*,s.candidate_id FROM {table} r
              JOIN opportunity_signals s ON s.id=r.signal_id JOIN cohort c ON c.id=s.candidate_id
              ORDER BY r.signal_id,r.horizon_seconds
            """, params):
                if row["signal_id"] not in firsts and row["signal_id"] not in alert_subjects:
                    continue
                body = json.loads(row["payload"])
                state = row["state"]
                if seconds(row["updated_at"]) is None or seconds(row["updated_at"]) > clock:
                    state, body = "future_update_unavailable", {}
                outcomes[row["signal_id"], row["horizon_seconds"]] = (state, body)
            horizons = {}
            for horizon in config["horizons_seconds"]:
                planned = []
                for sid, subject in firsts.items():
                    mature = (seconds(subject["signal_at"]) + config["entry_window_seconds"]
                              + horizon + config["exit_window_seconds"]) <= clock
                    state, body = outcomes.get((sid, horizon), (
                        "disabled_at_signal" if name == "jupiter_quotes"
                        and not config["routed_quotes_enabled"] else "model_not_enrolled", {}
                    ))
                    if state == "pending" and mature:
                        state = "overdue_unprocessed"
                    planned.append({"state": state, "pnl": body.get("pnl_usd"),
                                    "selected": subject["selected"], "control": subject["control"],
                                    "mature": mature})
                    if name == "estimated_pool" and sid not in entry_pairs:
                        # Same entry is used for each horizon; count each token once.
                        entry_pairs[sid] = (subject["signal_at"], body.get("entry_at")
                                            if body.get("entry_quote") else None)
                matured = [r for r in planned if r["mature"]]
                horizons[str(horizon)] = {
                    "planned": len(planned), "not_yet_mature": len(planned) - len(matured),
                    "matured": len(matured), "comparison": comparison(matured, summarize),
                    "all_planned": summarize(planned),
                }
            models[name] = horizons
            alert_followup[name] = {}
            for horizon in config["horizons_seconds"]:
                planned = []
                for sid, alert in alert_subjects.items():
                    state, body = outcomes.get((sid, horizon), (
                        "disabled_at_signal" if name == "jupiter_quotes"
                        and not config["routed_quotes_enabled"] else "model_not_enrolled", {}
                    ))
                    mature = (seconds(alert["signal_at"]) + config["entry_window_seconds"]
                              + horizon + config["exit_window_seconds"]) <= clock
                    if state == "pending" and mature:
                        state = "overdue_unprocessed"
                    planned.append({"state": state, "pnl": body.get("pnl_usd"), "mature": mature})
                    if name == "estimated_pool" and sid not in alert_entry_pairs:
                        alert_entry_pairs[sid] = (alert["at"], body.get("entry_at")
                                                  if body.get("entry_quote") else None)
                alert_followup[name][str(horizon)] = {
                    "all_planned": summarize(planned),
                    "matured": summarize([r for r in planned if r["mature"]]),
                    "not_yet_mature": sum(not r["mature"] for r in planned),
                }
        coverage = collection(db, params, candidates, clock)
    opportunity_alerts = [a for a in alerts if a["severity"] != "critical"]
    delivered = [a for a in opportunity_alerts
                 if seconds(a["delivered_in_app_at"]) is not None
                 and seconds(a["delivered_in_app_at"]) <= clock]
    events = [a for a in opportunity_alerts
              if json.loads(a["payload"]).get("features", {}).get("excessive_extension")]
    elapsed = max(0, min(clock, seconds(study["ends_at"])) - seconds(study["declared_at"]))
    return {
        "version": VERSION, "study": study, "report_state": "ready", "generated_at": at,
        "phase": "waiting" if clock < seconds(study["declared_at"])
        else "collecting" if clock < seconds(study["ends_at"]) else "followup",
        "elapsed_days": elapsed / 86400, "remaining_days": max(0, DAYS - elapsed / 86400),
        "totals": {
            "new_registrations": len(candidates),
            "eligible": sum(bool(r["eligible"]) for r in candidates.values()),
            "first_evaluations": sum(seconds(r["signal_at"]) is not None
                                     and seconds(r["signal_at"]) <= clock
                                     for r in candidates.values()),
            "analysis_tokens": len(firsts), "analysis_exclusions": dict(exclusions),
            "security_pass_at_first": sum(bool(r["security_pass"]) for r in firsts.values()),
            "liquidity_pass_at_first": sum(bool(r["liquidity_pass"]) for r in firsts.values()),
            "opportunity_alerts": len(opportunity_alerts), "risk_alerts": len(alerts)-len(opportunity_alerts),
            "alerts_displayed": len(delivered),
            "initially_selected_tokens": sum(r["selected"] for r in firsts.values()),
            "control_tokens_excluding_selected": sum(r["control"] and not r["selected"]
                                                     for r in firsts.values()),
            "already_extended_alerts": len(events),
            "global_missed_opportunities": None,
        },
        "latency": {
            "registration_to_first_evaluation": latency(
                ((r["ingested_at"], r["signal_at"]) for r in candidates.values()), clock),
            "discovery_to_alert": latency(
                ((candidates[a["candidate_id"]]["discovered_at"], a["at"])
                 for a in opportunity_alerts), clock),
            "alert_to_display": latency((a["at"], a["delivered_in_app_at"]
                                        if a in delivered else None) for a in opportunity_alerts),
            "signal_to_pool_paper_entry": latency(entry_pairs.values(), clock),
            "first_alert_to_pool_paper_entry": latency(alert_entry_pairs.values(), clock),
        },
        "collection": coverage, "models": models,
        "alert_followup": alert_followup,
        "alert_followup_scope": "Descriptive first noncritical alert per newly enrolled token, including later alerts. Separate from the original first-evaluation comparison; no retrospective selection or matched-time control claim.",
        "first_candidates": [
            {"candidate_id": r["id"], "contract": r["contract"],
             "ingested_at": r["ingested_at"], "first_signal_id": r["signal_id"],
             "first_verdict": r["verdict"]}
            for r in sorted(candidates.values(), key=lambda r: r["id"])[:5]
        ],
        "first_verdicts": dict(Counter(r["verdict"] or "PENDING" for r in candidates.values())),
        "live_execution": False, "profitability_demonstrated": False,
        "limitations": [
            "Thirty elapsed days do not prove thirty days of continuous collection.",
            "Only new Solana engine registrations are enrolled; feed coverage is partial.",
            "Primary comparisons use the frozen policy, verified source kind and original holdout boundary.",
            "Only conservatively matured horizons enter comparison; unresolved outcomes remain counted.",
            "Evaluated-only means and Wilson intervals are descriptive, not causal evidence or return predictions.",
            "Pool estimates and Jupiter quotes are independent scenarios, not executed trades or one funded portfolio.",
            "A timely price observation is not a successful entry or exit; source trade timestamps may be unavailable.",
            "Later alerts do not retrospectively select an initially rejected token.",
        ],
    }


def collection(db, params, candidates, clock):
    groups = defaultdict(Counter)
    query = COHORT.rstrip() + """, work AS MATERIALIZED (
      SELECT j.*,json_extract(p.payload,'$.observation_rules.max_snapshot_age') AS max_age
      FROM observation_jobs j JOIN cohort c ON c.id=j.candidate_id
      JOIN opportunity_signals s ON s.id=j.signal_id
      JOIN opportunity_policies p ON p.id=s.policy_id
      WHERE s.at>=:start AND s.at<:end AND s.at<=:at
    ), quotes AS MATERIALIZED (
      SELECT o.id,o.at,json_extract(""" + OBS + """,'$.market.price_usd',
        '$.market.liquidity_usd','$.market.observed_at','$.source_kind',
        '$.market.address','$.market.pair_address') AS fields
      FROM opportunity_observations o WHERE o.id IN (SELECT observation_id FROM work)
    ) SELECT j.*,o.at AS observed_at,o.fields FROM work j LEFT JOIN quotes o ON o.id=j.observation_id
    """
    for row in db.execute(query, params):
        if row["candidate_id"] not in candidates:
            continue
        state = row["status"]
        if state == "pending":
            state = "missed" if row["deadline_at"] < clock else (
                "due" if row["due_at"] <= clock else "not_due")
        quote = "not_attempted"
        if state == "attempted":
            fields = json.loads(row["fields"]) if row["fields"] else [None] * 6
            subject = candidates[row["candidate_id"]]
            quote = capture(dict(zip(
                ["price_usd", "liquidity_usd", "quote_at", "source_kind", "contract", "pool"],
                fields,
            )) | {"at": row["observed_at"]}, start=row["due_at"], end=row["deadline_at"],
                now=clock, max_age=row["max_age"],
                contract=subject["contract"], pool=subject["pool"])["state"]
        for name, included in [("all", True), ("alerts", bool(row["selected"])),
                               ("control", bool(row["control_member"]) and not row["selected"])]:
            if included:
                counts = groups[name, row["phase"]]
                counts[state] += 1
                if state == "attempted":
                    counts["price:" + quote] += 1
    return {
        name: {phase: dict(counts) for (group, phase), counts in groups.items() if group == name}
        for name in ["all", "alerts", "control"]
    }
