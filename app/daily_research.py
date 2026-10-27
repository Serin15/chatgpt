"""UTC discovery cohorts and outcomes known now, not reconstructed historical snapshots."""

import json
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from app import forward_evaluation
from app.cohort_comparisons import comparisons, partition, protocol
from app.models import epoch, utcnow
from app.opportunity_outcomes import wilson
from app.price_research import reference_report


def report_epoch(value):
    try:
        return epoch(value)
    except (ValueError, TypeError, OverflowError):
        return None


def summarize(rows):
    states, values = Counter(), []
    for row in rows:
        state, value = row["state"], None
        if state == "evaluated":
            try:
                value = Decimal(str(row["pnl"]))
                if not value.is_finite():
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                state = "invalid_evaluated_pnl"
        states[state] += 1
        if state == "evaluated":
            values.append(value)
    return {
        "experiments": len(rows),
        "evaluated": len(values),
        "unresolved_or_unavailable": len(rows) - len(values),
        "states": dict(states),
        "profitable_after_costs": sum(v > 0 for v in values),
        "nonprofitable_after_costs": sum(v <= 0 for v in values),
        "nonprofitable_rate_among_evaluated": sum(v <= 0 for v in values) / len(values)
        if values
        else None,
        "evaluated_fraction": len(values) / len(rows) if rows else None,
        "win_fraction_sensitivity_bounds_all_planned": [
            sum(v > 0 for v in values) / len(rows),
            (sum(v > 0 for v in values) + len(rows) - len(values)) / len(rows),
        ]
        if rows
        else None,
        "net_pnl_independent_experiments_usd": str(sum(values, Decimal(0))) if values else None,
        "mean_net_pnl_usd": str(sum(values, Decimal(0)) / len(values)) if values else None,
        "worst_net_pnl_usd": str(min(values)) if values else None,
        "best_net_pnl_usd": str(max(values)) if values else None,
        "win_rate_95pct_wilson_approx": wilson(sum(v > 0 for v in values), len(values)),
    }


def daily_report(engine, day: date | None = None):
    today = datetime.now(UTC).date()
    day = day or today
    if day > today:
        raise ValueError("Alege ziua UTC curentă sau o zi trecută.")
    start = datetime.combine(day, datetime.min.time(), UTC)
    end = start + timedelta(days=1)
    at = utcnow()
    now = epoch(at)
    params = {"start": start.timestamp(), "end": end.timestamp(), "at": now}
    cohort = """WITH cohort AS (
        SELECT id,contract,pool,eligible FROM opportunity_candidates WHERE chain='solana'
        AND research_epoch(discovered_at)>=:start
        AND research_epoch(discovered_at)<:end
        AND research_epoch(discovered_at)<=:at) """
    with engine.store.connect() as db:
        db.execute("BEGIN")
        db.create_function("research_epoch", 1, report_epoch, deterministic=True)
        candidates = db.execute(
            cohort
            + """
            SELECT c.id,c.contract,c.pool,c.eligible,s.id AS signal_id,s.verdict,s.at AS signal_at,s.policy_id,
            json_extract(s.payload,'$.policy.payload.observation_rules.max_snapshot_age') AS reference_max_age,
            json_extract(s.payload,'$.policy.payload.forward_quote_window_version') AS reference_quote_window_version,
            b.id AS initial_observation_id,b.at AS initial_at,
            json_extract(CASE WHEN typeof(b.payload)='blob' THEN archive_text(b.payload) ELSE b.payload END,'$.market.observed_at') AS initial_quote_at,
            json_extract(CASE WHEN typeof(b.payload)='blob' THEN archive_text(b.payload) ELSE b.payload END,'$.market.price_usd') AS initial_price_usd,
            json_extract(CASE WHEN typeof(b.payload)='blob' THEN archive_text(b.payload) ELSE b.payload END,'$.market.liquidity_usd') AS initial_liquidity_usd,
            json_extract(CASE WHEN typeof(b.payload)='blob' THEN archive_text(b.payload) ELSE b.payload END,'$.market.address') AS initial_contract,
            json_extract(CASE WHEN typeof(b.payload)='blob' THEN archive_text(b.payload) ELSE b.payload END,'$.market.pair_address') AS initial_pool,
            json_extract(CASE WHEN typeof(b.payload)='blob' THEN archive_text(b.payload) ELSE b.payload END,'$.source_kind') AS initial_source_kind,
            json_extract(s.payload,'$.policy.at') AS policy_at,
            json_extract(s.payload,'$.policy.payload.config') AS config,
            json_extract(s.payload,'$.security_filter_passed') AS security_pass,
            json_extract(s.payload,'$.liquidity_filter_passed') AS liquidity_pass,
            e.control_member,e.provenance,e.at AS enrolled_at,
            EXISTS(SELECT 1 FROM opportunity_alerts a WHERE a.signal_id=s.id AND a.severity!='critical'
                   AND research_epoch(a.at)<=:at) AS selected
            FROM cohort c LEFT JOIN opportunity_signals s ON s.id=(
                SELECT min(id) FROM opportunity_signals WHERE candidate_id=c.id AND kind='baseline'
                AND research_epoch(at)<=:at)
            LEFT JOIN sampling_enrollment e ON e.candidate_id=c.id
            LEFT JOIN opportunity_observations b ON b.id=s.observation_id AND b.candidate_id=c.id""",
            params,
        ).fetchall()
        alerts = db.execute(
            cohort
            + """
            SELECT a.severity,count(*) AS n,
            sum(a.delivered_in_app_at IS NOT NULL AND research_epoch(a.delivered_in_app_at)<=:at) AS delivered
            FROM opportunity_alerts a JOIN cohort c ON c.id=a.candidate_id
            WHERE research_epoch(a.at)<=:at GROUP BY a.severity""",
            params,
        ).fetchall()
        models = {}
        firsts = {r["signal_id"]: dict(r) for r in candidates if r["signal_id"] is not None}
        for subject in firsts.values():
            subject["config_parsed"] = json.loads(subject["config"])
        declarations = forward_evaluation.protocols(db, firsts, at)
        forward_models = {}
        for name, table in [
            ("estimated_pool", "opportunity_outcomes"),
            ("jupiter_quotes", "routed_outcomes"),
        ]:
            outcomes = db.execute(
                cohort
                + f"""
                SELECT o.signal_id,o.horizon_seconds,o.state,json_extract(o.payload,'$.pnl_usd') AS pnl,
                       o.updated_at FROM {table} o JOIN opportunity_signals s ON s.id=o.signal_id
                JOIN cohort c ON c.id=s.candidate_id WHERE s.kind='baseline'
                AND research_epoch(s.at)<=:at""",
                params,
            ).fetchall()
            parsed = []
            for outcome in outcomes:
                row = dict(outcome)
                subject = firsts.get(row["signal_id"])
                if subject is None:
                    continue
                cfg = subject["config_parsed"]
                when = epoch(subject["signal_at"])
                cohort_name = partition(subject, row["horizon_seconds"])
                if epoch(row["updated_at"]) > now:
                    row.update(state="future_update_unavailable", pnl=None)
                elif (
                    row["state"] == "pending"
                    and now
                    > when
                    + cfg["entry_window_seconds"]
                    + row["horizon_seconds"]
                    + cfg["exit_window_seconds"]
                ):
                    row.update(state="overdue_unprocessed", pnl=None)
                prospective = (
                    subject["provenance"] == "prospective" and epoch(subject["enrolled_at"]) <= when
                )
                row.update(
                    selected=bool(subject["selected"]),
                    control=bool(prospective and subject["control_member"]),
                    policy_id=subject["policy_id"],
                    cohort=cohort_name,
                )
                parsed.append(row)
            horizons = {}
            forward_horizons = {}
            configured_horizons = {
                h for s in firsts.values() for h in s["config_parsed"].get("horizons_seconds", [])
            }
            for horizon in sorted({r["horizon_seconds"] for r in parsed} | configured_horizons):
                rows = [r for r in parsed if r["horizon_seconds"] == horizon]
                observed_ids = {r["signal_id"] for r in rows}
                horizons[str(horizon)] = {
                    "all_first_evaluations": summarize(rows),
                    "selected_at_first_evaluation": summarize([r for r in rows if r["selected"]]),
                    "prospective_fixed_control": summarize([r for r in rows if r["control"]]),
                    "selected_control_overlap": sum(r["selected"] and r["control"] for r in rows),
                    "comparisons_by_policy_and_cohort": comparisons(
                        firsts, parsed, horizon, name, summarize
                    ),
                    "first_evaluations_without_model_rows": sum(
                        horizon in s["config_parsed"].get("horizons_seconds", [])
                        and signal_id not in observed_ids
                        for signal_id, s in firsts.items()
                    ),
                    "cohorts": {
                        c: summarize([r for r in rows if r["cohort"] == c])
                        for c in ["development", "test", "unassigned", "purged_boundary"]
                    },
                    "policies": {
                        str(p): summarize([r for r in rows if r["policy_id"] == p])
                        for p in sorted({r["policy_id"] for r in rows})
                    },
                }
                forward_horizons[str(horizon)] = forward_evaluation.grouped(
                    firsts, parsed, horizon, name, summarize, declarations
                )
            models[name] = horizons
            forward_models[name] = forward_horizons
        price_references = reference_report(db, cohort, params, firsts)
    return {
        "version": "daily-discovery-v1",
        "day_utc": day.isoformat(),
        "generated_at": at,
        "cohort_start": start.isoformat(),
        "cohort_end_exclusive": end.isoformat(),
        "outcome_scope": "Discovery cohort for this UTC day; outcomes known at generated_at. Not a historical as-of snapshot.",
        "totals": {
            "discovered": len(candidates),
            "eligible": sum(r["eligible"] for r in candidates),
            "excluded": sum(not r["eligible"] for r in candidates),
            "first_evaluations": len(firsts),
            "eligible_without_first_evaluation": sum(
                r["eligible"] and r["signal_id"] is None for r in candidates
            ),
            "security_pass_at_first_evaluation": sum(bool(r["security_pass"]) for r in candidates),
            "liquidity_pass_at_first_evaluation": sum(
                bool(r["liquidity_pass"]) for r in candidates
            ),
            "selected_at_first_evaluation": sum(r["selected"] for r in candidates),
            "opportunity_alerts": sum(r["n"] for r in alerts if r["severity"] != "critical"),
            "risk_alerts": sum(r["n"] for r in alerts if r["severity"] == "critical"),
            "alerts_displayed_in_app": sum(r["delivered"] for r in alerts),
        },
        "first_verdicts": dict(Counter(r["verdict"] or "PENDING" for r in candidates)),
        "models": models,
        "price_references": price_references,
        "evaluation_protocol": protocol(firsts, at),
        "forward_evaluation": {
            "version": forward_evaluation.VERSION,
            "protocols": declarations,
            "models": forward_models,
            "original_cutoffs_preserved": True,
            "profitability_demonstrated": False,
            "note": "Separate prospectively declared protocol, not reassignment of legacy tests. Missing and rejected candidates remain counted; selected and comparison control are disjoint. No threshold fitting or profitability conclusion.",
        },
        "live_execution": False,
        "profitability_demonstrated": False,
        "limitations": [
            "Partial discovery feeds; global missed opportunities cannot be measured.",
            "Missing, rejected and unavailable results stay in their denominator; PnL is unknown.",
            "Candidates without first evaluations remain counted, without invented experiments.",
            "Later alerts do not retrospectively select a first evaluation. Selected and control groups can overlap.",
            "Independent simulations are not one capital-constrained portfolio; no portfolio drawdown is inferred.",
            "Wilson intervals assume independent outcomes; correlated tokens and unequal coverage limit comparisons.",
            "Thresholds are not optimized on this report; unassigned data are not a holdout.",
            "Nonprofitable means net paper PnL <= 0 among evaluated results, not a verified false factual claim. Sensitivity bounds assume all unknown outcomes fail/succeed; they are not predictions.",
        ],
    }
