"""Descriptive comparisons within frozen policies/partitions, never threshold fitting."""

from decimal import Decimal

from app.models import epoch


def partition(subject, horizon):
    cfg = subject["config_parsed"]
    cutoff = cfg.get("test_from")
    try:
        when, declared = epoch(subject["signal_at"]), epoch(subject["policy_at"])
        if not cutoff or declared > when or epoch(cutoff) < declared:
            return "unassigned"
        if when >= epoch(cutoff):
            return "test"
        last = when + cfg["entry_window_seconds"] + horizon + cfg["exit_window_seconds"]
        return "purged_boundary" if last >= epoch(cutoff) else "development"
    except (ValueError, TypeError, KeyError, OverflowError):
        return "unassigned"


def comparison(rows, summarize):
    all_rows = summarize(rows)
    selected = summarize([r for r in rows if r["selected"]])
    control = summarize([r for r in rows if r["control"]])
    disjoint = summarize([r for r in rows if r["control"] and not r["selected"]])
    delta = None
    if selected["evaluated"] and disjoint["evaluated"]:
        delta = str(Decimal(selected["mean_net_pnl_usd"]) - Decimal(disjoint["mean_net_pnl_usd"]))
    return {
        "all_first_evaluations": all_rows,
        "selected_at_first_evaluation": selected,
        "prospective_fixed_control": control,
        "control_excluding_selected": disjoint,
        "overlap": sum(r["control"] and r["selected"] for r in rows),
        "conditional_mean_difference_usd": delta,
        "interpretation": "Descriptive, conditional on evaluated outcomes. Unequal coverage, token correlation and selection differences prevent a causal/profitability conclusion. No threshold optimization.",
    }


def comparisons(firsts, parsed, horizon, model, summarize):
    observed = {r["signal_id"]: r for r in parsed if r["horizon_seconds"] == horizon}
    rows = []
    for signal_id, subject in firsts.items():
        cfg = subject["config_parsed"]
        if horizon not in cfg.get("horizons_seconds", []):
            continue
        prospective = subject["provenance"] == "prospective" and epoch(
            subject["enrolled_at"]
        ) <= epoch(subject["signal_at"])
        row = dict(
            observed.get(signal_id)
            or {
                "state": "disabled_at_signal"
                if model == "jupiter_quotes" and not cfg.get("routed_quotes_enabled")
                else "model_not_enrolled",
                "pnl": None,
            }
        )
        row.update(
            selected=bool(subject["selected"]),
            control=bool(prospective and subject["control_member"]),
            policy_id=subject["policy_id"],
            cohort=partition(subject, horizon),
        )
        rows.append(row)
    return {
        str(policy): {
            cohort: comparison(
                [r for r in rows if r["policy_id"] == policy and r["cohort"] == cohort], summarize
            )
            for cohort in ["development", "test", "unassigned", "purged_boundary"]
        }
        for policy in sorted({r["policy_id"] for r in rows})
    }


def protocol(firsts, at):
    result = {}
    for s in firsts.values():
        key = str(s["policy_id"])
        cutoff = s["config_parsed"].get("test_from")
        valid = bool(cutoff and epoch(s["policy_at"]) <= min(epoch(cutoff), epoch(s["signal_at"])))
        result[key] = {
            "declared_at": s["policy_at"],
            "test_from": cutoff,
            "state": "unassigned"
            if not valid
            else "test_not_started"
            if epoch(at) < epoch(cutoff)
            else "test_window_started",
        }
    return {
        "policies": result,
        "original_declarations_preserved": True,
        "profitability_demonstrated": False,
        "note": "A test window having started is not a completed or successful experiment. New policies declared after an old cutoff remain unassigned.",
    }
