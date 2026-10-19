"""Forward-only independent paper experiments, including missing and rejected candidates."""

import hashlib
import json
import math
import time
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from app.cohort_comparisons import partition
from app.models import epoch, utcnow
from app.opportunity_rules import RULE_VERSION
from app.paper import Rejected, fill, require_fresh

D = Decimal


def decode(row):
    return dict(row) | json.loads(row["payload"]) if row else None


def settings_at(engine, policy):
    return replace(
        engine.service.settings,
        **{k: D(v) for k, v in policy["paper_rules"].items()},
        **policy.get("observation_rules", {}),
    )


def observation(db, candidate_id, start, end, quote_window_version=1):
    rows = db.execute(
        "SELECT * FROM opportunity_observations WHERE candidate_id=? AND at>=? AND at<=? ORDER BY at,id",
        (
            candidate_id,
            datetime.fromtimestamp(start, UTC).isoformat(),
            datetime.fromtimestamp(end, UTC).isoformat(),
        ),
    )
    for raw in rows:
        row = decode(raw)
        if quote_window_version == 2:
            try:
                # A prefetched quote is not an attempt within this window. Keep the
                # job pending; never skip an actual failed post-window request.
                if epoch(row["market"]["observed_at"]) < start:
                    continue
            except (KeyError, TypeError, ValueError, OverflowError):
                pass
        return row
    return None


def available(row, settings, not_before=None):
    if not row or not row.get("market") or not row.get("security") or not row.get("decision"):
        raise Rejected("Observation incomplete")
    snap = {"at": row["at"], "market": row["market"], "security": row["security"]}
    require_fresh(snap, settings, epoch(row["at"]))
    if not_before is not None and epoch(row["market"]["observed_at"]) < not_before:
        raise Rejected("Quote was fetched before the observation window.")
    if not row["decision"]["screening"]["paper_allowed"]:
        raise Rejected("Security/liquidity screening unavailable or rejected")


def update_outcomes(engine, now=None):
    now = time.time() if now is None else now
    updated = 0
    with engine.store.connect() as db:
        engine.sampling.expire(db, now)
        rows = db.execute(
            "SELECT o.*,s.candidate_id,s.at AS signal_at,s.payload AS signal_payload,s.observation_id FROM opportunity_outcomes o JOIN opportunity_signals s ON s.id=o.signal_id WHERE o.state='pending' ORDER BY o.updated_at,s.id,o.horizon_seconds LIMIT 2000"
        ).fetchall()
        for row in rows:
            signal = json.loads(row["signal_payload"])
            policy = signal["policy"]["payload"]
            config = policy["config"]
            settings = settings_at(engine, policy)
            quote_window_version = policy.get("forward_quote_window_version", 1)
            signal_at = epoch(row["signal_at"])
            end = min(now, signal_at + config["entry_window_seconds"])
            entry = observation(
                db,
                row["candidate_id"],
                signal_at + settings.min_signal_delay,
                end,
                quote_window_version,
            )
            payload = {
                "pnl_usd": None,
                "signal_at": row["signal_at"],
                "horizon_seconds": row["horizon_seconds"],
                "execution_verified": False,
                "model": "independent_estimated_pool_scenario",
                "policy_id": signal["policy"]["id"],
            }
            from app.opportunities import PAPER_SOURCE_SHA256

            if policy.get("paper_source_sha256") not in (None, PAPER_SOURCE_SHA256):
                payload["reason"] = (
                    "Frozen cost implementation differs from the installed version; no result calculated."
                )
                db.execute(
                    "UPDATE observation_jobs SET status='cancelled',reason='cost_model_unavailable' WHERE signal_id=? AND status='pending'",
                    (row["signal_id"],),
                )
                db.execute(
                    "UPDATE opportunity_outcomes SET state='cost_model_unavailable',payload=?,updated_at=? WHERE signal_id=? AND horizon_seconds=?",
                    (json.dumps(payload), utcnow(), row["signal_id"], row["horizon_seconds"]),
                )
                updated += 1
                continue
            state = "pending"
            if entry is None:
                if now >= signal_at + config["entry_window_seconds"]:
                    state = "missing_forward_entry"
            else:
                payload.update(
                    entry_observation_id=entry["id"],
                    entry_at=entry["at"],
                    entry_delay_seconds=round(epoch(entry["at"]) - signal_at),
                )
                try:
                    available(
                        entry,
                        settings,
                        signal_at + settings.min_signal_delay
                        if policy.get("sampling_version")
                        else None,
                    )
                    buy = fill("buy", str(config["position_usd"]), entry["market"], settings)
                    payload["entry_quote"] = buy
                except (Rejected, ValueError, TypeError, KeyError, ArithmeticError):
                    state = "entry_unavailable"
                    payload["unavailable_reason"] = (
                        "provider_quote_missing"
                        if not entry.get("market")
                        else "security_liquidity_cost_or_timestamp_gate"
                    )
                if state == "pending":
                    target = epoch(entry["at"]) + row["horizon_seconds"]
                    payload["target_at_epoch"] = target
                    exit_row = observation(
                        db,
                        row["candidate_id"],
                        target,
                        min(now, target + config["exit_window_seconds"]),
                        quote_window_version,
                    )
                    if exit_row is None:
                        if now >= target + config["exit_window_seconds"]:
                            state = "missing_forward_exit"
                    else:
                        payload.update(
                            exit_observation_id=exit_row["id"],
                            exit_at=exit_row["at"],
                            actual_hold_seconds=round(epoch(exit_row["at"]) - epoch(entry["at"])),
                        )
                        try:
                            available(
                                exit_row,
                                settings,
                                target if policy.get("sampling_version") else None,
                            )
                            sale = fill("sell", buy["quantity"], exit_row["market"], settings)
                            payload.update(
                                exit_quote=sale,
                                pnl_usd=str(D(sale["cash_change"]) + D(buy["cash_change"])),
                                entry_cost_usd=str(-D(buy["cash_change"])),
                                price_return_pct=(
                                    exit_row["market"]["price_usd"] / entry["market"]["price_usd"]
                                    - 1
                                )
                                * 100,
                                economically_possible_in_model=True,
                            )
                            state = "evaluated"
                        except (Rejected, ValueError, TypeError, KeyError, ArithmeticError):
                            state = "exit_unavailable"
                            payload["unavailable_reason"] = (
                                "provider_quote_missing"
                                if not exit_row.get("market")
                                else "security_liquidity_cost_or_timestamp_gate"
                            )
                            payload["economically_possible_in_model"] = None
                    samples = [
                        decode(r)
                        for r in db.execute(
                            "SELECT * FROM opportunity_observations WHERE candidate_id=? AND at>=? AND at<=? ORDER BY at,id",
                            (
                                row["candidate_id"],
                                entry["at"],
                                datetime.fromtimestamp(min(now, target), UTC).isoformat(),
                            ),
                        )
                    ]
                    priced = [r for r in samples if r.get("market")]
                    if priced:
                        returns = [
                            (r["market"]["price_usd"] / entry["market"]["price_usd"] - 1) * 100
                            for r in priced
                        ]
                        stamps = sorted(epoch(r["at"]) for r in samples)
                        payload.update(
                            mfe_observed_pct=max(0, *returns),
                            mae_observed_pct=min(0, *returns),
                            priced_observations=len(priced),
                            failed_observations=len(samples) - len(priced),
                            max_observed_gap_seconds=max(
                                [b - a for a, b in zip(stamps, stamps[1:])], default=None
                            ),
                            unobserved_tail_seconds=max(0, min(now, target) - max(stamps)),
                            extrema_scope="Sampled prices through the horizon; true intra-interval extrema are unknown.",
                        )
            engine.sampling.sync_outcome(db, row, payload, state, config)
            db.execute(
                "UPDATE opportunity_outcomes SET state=?,payload=?,updated_at=? WHERE signal_id=? AND horizon_seconds=?",
                (
                    state,
                    json.dumps(payload, allow_nan=False),
                    utcnow(),
                    row["signal_id"],
                    row["horizon_seconds"],
                ),
            )
            updated += 1
    return updated


def wilson(wins, n):
    if not n:
        return None
    z = 1.96
    p = wins / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [max(0, centre - radius), min(1, centre + radius)]


def summary(rows):
    measured = [r for r in rows if r["state"] == "evaluated"]
    pnl = [D(r["payload"]["pnl_usd"]) for r in measured]
    wins = sum(v > 0 for v in pnl)
    return {
        "experiments": len(rows),
        "evaluated": len(measured),
        "unresolved_or_unavailable": len(rows) - len(measured),
        "states": dict(Counter(r["state"] for r in rows)),
        "profitable_after_costs": wins,
        "loss_rate_among_evaluated": sum(v < 0 for v in pnl) / len(pnl) if pnl else None,
        "unprofitable_rate_among_evaluated": (len(pnl) - wins) / len(pnl) if pnl else None,
        "net_pnl_independent_experiments_usd": str(sum(pnl, D(0))) if pnl else None,
        "mean_net_pnl_usd": str(sum(pnl, D(0)) / len(pnl)) if pnl else None,
        "win_rate_95pct_wilson_approx": wilson(wins, len(pnl)),
        "uncertainty_note": "Missing outcomes excluded from PnL, retained in denominator/coverage. Interval assumes independent binary outcomes; correlated tokens can invalidate that assumption.",
        "profitability_demonstrated": False,
    }


def report(engine):
    with engine.store.connect() as db:
        totals = {
            key: db.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for key, table in [
                ("discovered", "opportunity_candidates"),
                ("signals", "opportunity_signals"),
                ("alerts", "opportunity_alerts"),
                ("observations", "opportunity_observations"),
            ]
        }
        totals["eligible"] = db.execute(
            "SELECT count(*) FROM opportunity_candidates WHERE eligible=1"
        ).fetchone()[0]
        totals["eligible_without_first_evaluation"] = db.execute(
            "SELECT count(*) FROM opportunity_candidates c WHERE eligible=1 AND NOT EXISTS(SELECT 1 FROM opportunity_signals s WHERE s.candidate_id=c.id AND s.kind='baseline')"
        ).fetchone()[0]
        totals["risk_update_alerts"] = db.execute(
            "SELECT count(*) FROM opportunity_alerts WHERE severity='critical'"
        ).fetchone()[0]
        totals["delivered_in_app"] = db.execute(
            "SELECT count(*) FROM opportunity_alerts WHERE delivered_in_app_at IS NOT NULL"
        ).fetchone()[0]
        totals["telegram_acknowledged"] = db.execute(
            "SELECT count(*) FROM opportunity_alerts WHERE telegram_state='acknowledged_by_api'"
        ).fetchone()[0]
        candidates = db.execute(
            """SELECT c.id,json_extract(c.discovery,'$.price_usd') AS initial_price,
            json_extract(o.payload,'$.market.price_usd') AS price,
            json_extract(o.payload,'$.market.observed_at') AS market_at,
            json_extract(o.payload,'$.security.observed_at') AS security_at,
            json_extract(o.payload,'$.decision.verdict') AS verdict,
            json_extract(o.payload,'$.decision.security_filter_passed') AS security_pass,
            json_extract(o.payload,'$.decision.liquidity_filter_passed') AS liquidity_pass
            FROM opportunity_candidates c LEFT JOIN opportunity_observations o ON o.id=(
                SELECT id FROM opportunity_observations WHERE candidate_id=c.id ORDER BY id DESC LIMIT 1)"""
        ).fetchall()
        rows = db.execute(
            """SELECT o.signal_id,o.horizon_seconds,o.state,json_extract(o.payload,'$.pnl_usd') AS pnl,
            s.kind,s.at AS signal_at,s.observation_id,a.id AS alert_id,c.contract,
            e.control_member,e.provenance AS enrollment_provenance,e.at AS enrolled_at,
            json_extract(s.payload,'$.policy.id') AS policy_id,
            json_extract(s.payload,'$.policy.at') AS policy_at,
            json_extract(s.payload,'$.policy.payload.config.test_from') AS test_from,
            json_extract(s.payload,'$.policy.payload.config.entry_window_seconds') AS entry_window,
            json_extract(s.payload,'$.policy.payload.config.exit_window_seconds') AS exit_window
            FROM opportunity_outcomes o JOIN opportunity_signals s ON s.id=o.signal_id
            JOIN opportunity_candidates c ON c.id=s.candidate_id
            LEFT JOIN opportunity_alerts a ON a.signal_id=s.id AND a.severity!='critical'
            LEFT JOIN sampling_enrollment e ON e.candidate_id=c.id ORDER BY s.id,o.horizon_seconds"""
        ).fetchall()
        parsed = []
        for r in rows:
            row = dict(r)
            row["payload"] = {"pnl_usd": row.pop("pnl")}
            row["config_parsed"] = {
                "test_from": row.pop("test_from"),
                "entry_window_seconds": row.pop("entry_window"),
                "exit_window_seconds": row.pop("exit_window"),
            }
            row["cohort"] = partition(row, r["horizon_seconds"])
            row.pop("config_parsed")
            parsed.append(row)
        latest = []
        for r in candidates:
            latest.append(
                {
                    "id": r["id"],
                    "initial_price": r["initial_price"],
                    "price": r["price"],
                    "decision": {
                        "verdict": r["verdict"] or "PENDING",
                        "security_filter_passed": r["security_pass"],
                        "liquidity_filter_passed": r["liquidity_pass"],
                    },
                    "security_fresh": bool(
                        r["security_at"]
                        and 0
                        <= time.time() - epoch(r["security_at"])
                        <= engine.service.settings.max_snapshot_age
                    ),
                    "fresh": bool(
                        r["market_at"]
                        and 0
                        <= time.time() - epoch(r["market_at"])
                        <= engine.service.settings.max_snapshot_age
                    ),
                }
            )
        alert_rows = db.execute(
            "SELECT json_extract(payload,'$.features.excessive_extension') AS extended FROM opportunity_alerts"
        ).fetchall()
        initial = db.execute(
            """SELECT s.id,
            json_extract(o.payload,'$.features.changes.5m.volume_5m_ratio') AS volume_ratio,
            json_extract(o.payload,'$.features.excessive_extension') AS extended,
            json_array_length(o.payload,'$.narrative.supported') AS narrative_count,
            json_extract(o.payload,'$.decision.security_filter_passed') AS security_pass,
            json_extract(o.payload,'$.decision.liquidity_filter_passed') AS liquidity_pass,
            json_extract(o.payload,'$.decision.verdict') AS verdict
            FROM opportunity_signals s JOIN opportunity_observations o ON o.id=s.observation_id WHERE s.kind='baseline'"""
        ).fetchall()
    horizons = {}
    for h in sorted({r["horizon_seconds"] for r in parsed}):
        baseline = [r for r in parsed if r["horizon_seconds"] == h and r["kind"] == "baseline"]
        horizons[str(h)] = {
            "all_eligible_first_evaluations": summary(baseline),
            "selected_at_first_evaluation": summary(
                [r for r in baseline if r["alert_id"] is not None]
            ),
            "deterministic_20pct_baseline": summary(
                [
                    r
                    for r in baseline
                    if int(hashlib.sha256(r["contract"].encode()).hexdigest()[:8], 16) % 5 == 0
                ]
            ),
            "later_alert_experiments": summary(
                [
                    r
                    for r in parsed
                    if r["horizon_seconds"] == h
                    and r["kind"] != "baseline"
                    and r["alert_id"] is not None
                ]
            ),
            "cohorts": {
                c: summary([r for r in baseline if r["cohort"] == c])
                for c in ["development", "test", "unassigned", "purged_boundary"]
            },
            "policies": {
                str(p): summary([r for r in baseline if r["policy_id"] == p])
                for p in sorted({r["policy_id"] for r in baseline})
            },
            "prospective_comparison": {
                "selected_at_first_evaluation": summary(
                    [
                        r
                        for r in baseline
                        if r["enrollment_provenance"] == "prospective"
                        and epoch(r["enrolled_at"]) <= epoch(r["signal_at"])
                        and r["alert_id"] is not None
                    ]
                ),
                "fixed_control": summary(
                    [
                        r
                        for r in baseline
                        if r["enrollment_provenance"] == "prospective"
                        and epoch(r["enrolled_at"]) <= epoch(r["signal_at"])
                        and r["control_member"]
                    ]
                ),
                "overlapping_experiments": sum(
                    r["enrollment_provenance"] == "prospective"
                    and epoch(r["enrolled_at"]) <= epoch(r["signal_at"])
                    and bool(r["control_member"])
                    and r["alert_id"] is not None
                    for r in baseline
                ),
                "note": "Control assigned before screening, including rejected tokens and any overlapping alerts. Legacy history is excluded. Observation coverage and executable paper results are separate.",
            },
        }
    diagnostics = {}
    for name, predicate in [
        (
            "volume_acceleration_ge_2",
            lambda p: (p["volume_ratio"] or 0) >= 2,
        ),
        ("excessive_extension", lambda p: p["extended"]),
        ("contract_narrative", lambda p: bool(p["narrative_count"])),
    ]:
        ids = {p["id"] for p in initial if predicate(p)}
        diagnostics[name] = {
            str(h): summary(
                [r for r in parsed if r["horizon_seconds"] == h and r["signal_id"] in ids]
            )
            for h in sorted({r["horizon_seconds"] for r in parsed})
        }
    return {
        "rule_version": RULE_VERSION,
        "totals": totals,
        "sampling": engine.sampling.coverage(),
        "first_evaluation_security_pass": sum(bool(p["security_pass"]) for p in initial),
        "first_evaluation_liquidity_pass": sum(bool(p["liquidity_pass"]) for p in initial),
        "first_evaluation_verdicts": dict(Counter(p["verdict"] for p in initial)),
        "current_security_pass": sum(
            bool(r["fresh"] and r["security_fresh"] and r["decision"].get("security_filter_passed"))
            for r in latest
        ),
        "current_liquidity_pass": sum(
            bool(r["fresh"] and r["decision"].get("liquidity_filter_passed")) for r in latest
        ),
        "current_verdicts": dict(Counter(r["decision"].get("verdict", "PENDING") for r in latest)),
        "known_current_price_collapses_ge_80pct": sum(
            r["price"] is not None
            and (r["initial_price"] or 0) > 0
            and r["price"] / r["initial_price"] <= 0.2
            for r in latest
        ),
        "known_current_appreciation_ge_100pct": sum(
            r["price"] is not None
            and (r["initial_price"] or 0) > 0
            and r["price"] / r["initial_price"] >= 2
            for r in latest
        ),
        "alerts_already_extended_at_signal": sum(bool(r["extended"]) for r in alert_rows),
        "confirmed_unsellable": None,
        "missed_opportunities": None,
        "horizons": horizons,
        "exploratory_signal_diagnostics": diagnostics,
        "note": "Partial provider discovery universe, not all launches. Follow-up prioritizes alerts, so comparative coverage is unequal and missingness can bias comparisons. No global missed-opportunity rate. Historical or missing prices are never filled with future data. Independent experiments are not a capital-constrained strategy or demonstrated profit.",
        "live_execution": False,
    }
