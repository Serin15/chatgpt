"""Forward cohorts from observations actually collected after a signal, never future backfills."""

import json
import time
from datetime import UTC, datetime
from decimal import Decimal

from app.models import epoch
from app.paper import Rejected, fill, require_fresh

D = Decimal


class Forward:
    def __init__(self, service):
        self.service = service

    def report(self, account="news", split_at=None, horizon_seconds=3600, now=None):
        now = time.time() if now is None else now
        split = epoch(split_at) if split_at else None
        if split_at and (datetime.fromisoformat(split_at).tzinfo is None or split > now):
            raise ValueError(
                "Separarea dezvoltare/test cere un timestamp cu fus orar, fără dată viitoare."
            )
        if horizon_seconds not in {300, 3600, 86400, 604800}:
            raise ValueError("Orizont acceptat: 5 minute, 1 oră, 1 zi sau 7 zile.")
        store = self.service.paper_store(account)
        with store.connect() as db:
            total = db.execute("SELECT count(*) FROM signals").fetchone()[0]
            signals = db.execute("SELECT * FROM signals ORDER BY id DESC LIMIT 1000").fetchall()
        results = []
        for signal in reversed(signals):
            at = epoch(signal["at"])
            if at > now:
                results.append({"id": signal["id"], "state": "invalid_future_signal"})
                continue
            cohort = "unassigned" if split is None else "development" if at < split else "test"
            result = {
                "id": signal["id"],
                "address": signal["address"],
                "at": signal["at"],
                "cohort": cohort,
                "state": "pending",
                "pnl_usd": None,
            }
            if now < at + horizon_seconds:
                results.append(result)
                continue
            with store.connect() as db:
                entries = db.execute(
                    "SELECT * FROM snapshots WHERE address=? AND at>=? AND at<=? ORDER BY at,id LIMIT 1",
                    (
                        signal["address"],
                        datetime.fromtimestamp(at + 3, UTC).isoformat(),
                        datetime.fromtimestamp(min(at + 120, now), UTC).isoformat(),
                    ),
                ).fetchall()
            if not entries:
                result["state"] = "missing_forward_entry"
                results.append(result)
                continue
            entry = store.unpack(entries[0])
            entry_time = epoch(entry["at"])
            target = entry_time + horizon_seconds
            if cohort == "development" and split is not None and target + 120 >= split:
                result["state"] = "purged_at_split_boundary"
                results.append(result)
                continue
            if target > now:
                result["state"] = "pending"
                results.append(result)
                continue
            with store.connect() as db:
                exits = db.execute(
                    "SELECT * FROM snapshots WHERE address=? AND at>=? AND at<=? ORDER BY at,id LIMIT 1",
                    (
                        signal["address"],
                        datetime.fromtimestamp(target, UTC).isoformat(),
                        datetime.fromtimestamp(min(target + 120, now), UTC).isoformat(),
                    ),
                ).fetchall()
            if not exits:
                result["state"] = "missing_forward_exit"
                results.append(result)
                continue
            exit_snapshot = store.unpack(exits[0])
            result.update(
                entry_observed_at=entry["at"],
                exit_observed_at=exit_snapshot["at"],
                entry_snapshot_id=entry["id"],
                exit_snapshot_id=exit_snapshot["id"],
            )
            evidence = json.loads(signal["evidence"])
            if evidence.get("paper_execution_mode") == "jupiter":
                result["state"] = "requires_recorded_forward_routed_quotes"
                results.append(result)
                continue
            rules = evidence.get("rules_at_signal")
            if not rules:
                result["state"] = "missing_frozen_cost_rules"
                results.append(result)
                continue
            from dataclasses import replace

            try:
                keys = {
                    "swap_fee",
                    "network_fee_usd",
                    "reference_fee",
                    "reference_slippage",
                    "max_price_impact",
                    "min_liquidity",
                }
                if not isinstance(rules, dict) or set(rules) != keys:
                    raise ValueError("Incomplete frozen cost rules")
                costs = {k: D(v) for k, v in rules.items()}
                if any(not v.is_finite() or v < 0 for v in costs.values()):
                    raise ValueError("Invalid frozen cost rules")
                settings = replace(self.service.settings, **costs)
                for observation in (entry, exit_snapshot):
                    require_fresh(observation, settings, epoch(observation["at"]))
                    if not observation["analysis"]["paper_allowed"]:
                        raise Rejected("Observation rejected by saved risk evidence")
                buy = fill("buy", "50", entry["market"], settings)
                if buy.get("book") and not exit_snapshot["market"].get("book"):
                    raise Rejected("Missing book exit")
                sell = fill("sell", buy["quantity"], exit_snapshot["market"], settings)
                pnl = D(sell["cash_change"]) + D(buy["cash_change"])
                result.update(
                    state="evaluated",
                    pnl_usd=str(pnl),
                    entry_cost=str(-D(buy["cash_change"])),
                    execution_models=[buy["model"], sell["model"]],
                    execution_verified=False,
                )
            except (Rejected, ValueError, TypeError, KeyError, ArithmeticError):
                result["state"] = "untradable_or_incomplete_evidence"
            results.append(result)
        cohorts = {}
        for cohort in ("development", "test", "unassigned"):
            group = [r for r in results if r.get("cohort") == cohort]
            evaluated = [r for r in group if r["state"] == "evaluated"]
            losses = sum(D(r["pnl_usd"]) <= 0 for r in evaluated)
            cohorts[cohort] = {
                "signals": len(group),
                "evaluated": len(evaluated),
                "unresolved": len(group) - len(evaluated),
                "net_pnl_independent_experiments_usd": str(
                    sum((D(r["pnl_usd"]) for r in evaluated), D(0))
                ) if evaluated else None,
                "loss_signal_rate": losses / len(evaluated) if evaluated else None,
                "sample_sufficient_for_profitability_claim": False,
            }
        return {
            "account": account,
            "split_at": split_at,
            "horizon_seconds": horizon_seconds,
            "signals_total": total,
            "history_truncated": total > len(signals),
            "cohorts": cohorts,
            "results": results,
            "manual_portfolio_drawdown_pct": self.service.performance.report(account)[
                "max_observed_drawdown_pct"
            ],
            "false_signal_definition": "Independent $50 experiment with net PnL <= 0 at the selected horizon; not a labeled false news association",
            "point_in_time_policy": "First stored receipt after signal+3s, then first receipt after entry+horizon, each within 120s. No downloaded historical prices or favorable observation selection.",
            "note": "Experimente independente, nu equity al unei strategii cu poziții suprapuse. Erorile, disparițiile și lipsa datelor rămân în numărătoare. Cohorta test se alege înaintea reglajelor; sistemul nu antrenează un model și nu demonstrează profitabilitate.",
        }
