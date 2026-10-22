"""Forward-only independent paper experiments, including missing and rejected candidates."""

import json
import math
import time
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from app.models import epoch, utcnow
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
        # Expiry is a short write. Do not retain its writer lock while decoding
        # and calculating up to 2,000 historical outcomes after downtime.
        db.commit()
        rows = db.execute(
            """SELECT o.*,s.candidate_id,s.at AS signal_at,s.payload AS signal_payload,s.observation_id
            FROM opportunity_outcomes o JOIN opportunity_signals s ON s.id=o.signal_id
            WHERE o.state='pending' AND (
              json_extract(o.payload,'$.entry_quote') IS NULL
              OR coalesce(json_type(o.payload,'$.target_at_epoch'),'null') NOT IN ('integer','real')
              OR json_extract(o.payload,'$.target_at_epoch')<=?
              OR julianday((SELECT at FROM opportunity_observations
                  WHERE candidate_id=s.candidate_id ORDER BY id DESC LIMIT 1))>julianday(o.updated_at)
            ) ORDER BY o.updated_at,s.id,o.horizon_seconds LIMIT 2000""",
            (now,),
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
                db.commit()
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
            # The outcome and its sampling jobs commit together. Release the
            # writer before the next calculation so receipts and ingestion work.
            db.commit()
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
    from app.performance_reporting import report as calculate_report

    return calculate_report(engine, time.time())
