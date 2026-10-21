"""Read-only price references. Price changes are neither fills nor net returns."""

import json
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal

from app.cohort_comparisons import partition


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Timezone required")
    return parsed.timestamp()


def capture(row, *, start, end, now, max_age, contract, pool):
    """Validate the declared capture, without claiming independent API verification."""
    if row is None or row.get("price_usd") is None:
        return {"state": "quote_unavailable"}
    try:
        if (
            isinstance(max_age, bool)
            or not isinstance(max_age, (int, float))
            or not 0 < max_age <= 86400
        ):
            return {"state": "freshness_policy_unknown"}
        at, quoted = timestamp(row["at"]), timestamp(row["quote_at"])
        if at > now or quoted > at:
            return {"state": "future_capture"}
        if not start <= at <= end:
            return {"state": "observation_outside_window"}
        if quoted < start:
            return {"state": "quote_before_window"}
        if at - quoted > max_age:
            return {"state": "stale_quote"}
        if row.get("contract") != contract or row.get("pool") != pool:
            return {"state": "identity_mismatch"}
        if row.get("source_kind") != "live_provider_observation":
            return {"state": "source_kind_unverified"}
        values = []
        for key in ["price_usd", "liquidity_usd"]:
            value = row[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return {"state": "invalid_value"}
            value = Decimal(str(value))
            if not value.is_finite() or value < 0 or key == "price_usd" and value == 0:
                return {"state": "invalid_value"}
            values.append(value)
        return {"state": "observed", "price": values[0], "liquidity": values[1]}
    except (ValueError, TypeError, KeyError, OverflowError, ArithmeticError):
        return {"state": "invalid_capture"}


def coverage_states(db, now):
    def state(fields, at, start, end, age, contract, pool):
        values = json.loads(fields) if fields else [None] * 6
        return capture(
            dict(
                zip(
                    ["price_usd", "liquidity_usd", "quote_at", "source_kind", "contract", "pool"],
                    values,
                )
            )
            | {"at": at},
            start=start,
            end=end,
            now=now,
            max_age=age,
            contract=contract,
            pool=pool,
        )["state"]

    db.create_function("capture_price_state", 7, state, deterministic=True)
    return [
        dict(r)
        for r in db.execute("""
        WITH quotes AS MATERIALIZED (
          SELECT id,candidate_id,at,json_extract(archive_text(payload),'$.market.price_usd',
            '$.market.liquidity_usd','$.market.observed_at','$.source_kind',
            '$.market.address','$.market.pair_address') AS fields
          FROM opportunity_observations WHERE id IN (
            SELECT observation_id FROM observation_jobs WHERE status='attempted'
            AND (selected=1 OR control_member=1)
          )
        )
        SELECT j.phase,j.selected,j.control_member,e.provenance,
        capture_price_state(o.fields,o.at,
          j.due_at,j.deadline_at,json_extract(p.payload,'$.observation_rules.max_snapshot_age'),
          c.contract,c.pool) AS price_state,count(*) AS n
        FROM observation_jobs j JOIN opportunity_candidates c ON c.id=j.candidate_id
        LEFT JOIN sampling_enrollment e ON e.candidate_id=c.id
        LEFT JOIN quotes o ON o.id=j.observation_id AND o.candidate_id=c.id
        LEFT JOIN opportunity_signals s ON s.id=j.signal_id
        LEFT JOIN opportunity_policies p ON p.id=s.policy_id
        WHERE j.status='attempted' AND (j.selected=1 OR j.control_member=1)
        GROUP BY j.phase,j.selected,j.control_member,e.provenance,price_state
    """)
    ]


def summarize(rows):
    values = [Decimal(r["price_return_pct"]) for r in rows if r["state"] == "observed"]
    return {
        "planned": len(rows),
        "observed": len(values),
        "unavailable_or_pending": len(rows) - len(values),
        "states": dict(Counter(r["state"] for r in rows)),
        "observed_fraction": len(values) / len(rows) if rows else None,
        "mean_price_return_pct": str(sum(values) / len(values)) if values else None,
        "increase_at_least_100pct": sum(v >= 100 for v in values),
        "decline_at_least_80pct": sum(v <= -80 for v in values),
        "zero_exit_liquidity_quotes": sum(
            r.get("exit_liquidity_usd") is not None and Decimal(r["exit_liquidity_usd"]) == 0
            for r in rows
        ),
        "paper_pnl_usd": None,
        "execution_verified": False,
    }


def reference_report(db, cohort, params, firsts):
    by_candidate = defaultdict(list)
    query = (
        cohort
        + """SELECT o.id,o.candidate_id,o.at,
        json_extract(archive_text(o.payload),'$.market.observed_at','$.market.price_usd',
        '$.market.liquidity_usd','$.market.address','$.market.pair_address',
        '$.source_kind') AS capture_fields
        FROM opportunity_observations o JOIN cohort c ON c.id=o.candidate_id
        WHERE research_epoch(o.at)<=:at
        ORDER BY o.candidate_id,research_epoch(o.at),o.id"""
    )
    if firsts:
        for r in db.execute(query, params):
            row = dict(r)
            fields = json.loads(row.pop("capture_fields"))
            row.update(
                zip(
                    ["quote_at", "price_usd", "liquidity_usd", "contract", "pool", "source_kind"],
                    fields,
                )
            )
            by_candidate[r["candidate_id"]].append((timestamp(r["at"]), row))
    timelines = {
        key: ([r[0] for r in rows], [r[1] for r in rows]) for key, rows in by_candidate.items()
    }
    horizons = defaultdict(list)
    for signal_id, subject in firsts.items():
        cfg = subject["config_parsed"]
        when = timestamp(subject["signal_at"])
        age = subject["reference_max_age"]
        initial = {
            key: subject.get("initial_" + key)
            for key in [
                "at",
                "quote_at",
                "price_usd",
                "liquidity_usd",
                "source_kind",
                "contract",
                "pool",
            ]
        }
        initial_capture = capture(
            initial,
            start=when - age if isinstance(age, (int, float)) else when,
            end=when,
            now=when,
            max_age=age,
            contract=subject["contract"],
            pool=subject["pool"],
        )
        times, observations = timelines.get(subject["id"], ([], []))
        for horizon in cfg["horizons_seconds"]:
            target = when + horizon
            deadline = target + cfg["exit_window_seconds"]
            position = bisect_left(times, target)
            while (
                subject.get("reference_quote_window_version") == 2
                and position < len(times)
                and times[position] <= deadline
            ):
                try:
                    if timestamp(observations[position]["quote_at"]) < target:
                        position += 1
                        continue
                except (ValueError, TypeError, OverflowError):
                    pass
                break
            row = (
                observations[position]
                if position < len(times) and times[position] <= deadline
                else None
            )
            output = {
                "signal_id": signal_id,
                "candidate_id": subject["id"],
                "policy_id": subject["policy_id"],
                "cohort": partition(subject, horizon),
                "selected": bool(subject["selected"]),
                "control": bool(
                    subject["control_member"]
                    and subject["provenance"] == "prospective"
                    and timestamp(subject["enrolled_at"]) <= when
                ),
                "initial_observation_id": subject["initial_observation_id"],
                "horizon_observation_id": row["id"] if row else None,
                "price_return_pct": None,
            }
            if initial_capture["state"] != "observed":
                output["state"] = "baseline_" + initial_capture["state"]
            elif params["at"] < target or row is None and params["at"] <= deadline:
                output["state"] = "waiting"
            elif row is None:
                output["state"] = "missing_horizon_observation"
            else:
                end = capture(
                    row,
                    start=target,
                    end=deadline,
                    now=params["at"],
                    max_age=age,
                    contract=subject["contract"],
                    pool=subject["pool"],
                )
                output["state"] = (
                    "observed" if end["state"] == "observed" else "horizon_" + end["state"]
                )
                if end["state"] == "observed":
                    output.update(
                        price_return_pct=str((end["price"] / initial_capture["price"] - 1) * 100),
                        exit_liquidity_usd=str(end["liquidity"]),
                        initial_price_usd=str(initial_capture["price"]),
                        horizon_price_usd=str(end["price"]),
                        horizon_observed_at=row["at"],
                        horizon_quote_at=row["quote_at"],
                    )
            horizons[str(horizon)].append(output)

    def groups(rows):
        return {
            "all_first_evaluations": summarize(rows),
            "selected_at_first_evaluation": summarize([r for r in rows if r["selected"]]),
            "control_excluding_selected": summarize(
                [r for r in rows if r["control"] and not r["selected"]]
            ),
        }

    return {
        "version": "first-signal-reference-v1",
        "horizons": {
            h: groups(rows)
            | {
                "items": rows,
                "by_policy_and_cohort": {
                    str(p): {
                        c: groups([r for r in rows if r["policy_id"] == p and r["cohort"] == c])
                        for c in ["development", "test", "unassigned", "purged_boundary"]
                    }
                    for p in sorted({r["policy_id"] for r in rows})
                },
            }
            for h, rows in sorted(horizons.items(), key=lambda item: int(item[0]))
        },
        "paper_pnl_usd": None,
        "execution_verified": False,
        "profitability_demonstrated": False,
        "note": "Baseline is the first signal's own observation, known by its decision time. Use the first recorded attempt at/after signal+horizon within the frozen exit window. Policies with forward_quote_window_version=2 skip only quotes demonstrably fetched before that window; actual post-window failures are never replaced with later winners. Legacy policies retain first-record selection. Declared live capture metadata is not independent API verification. Price changes ignore costs and cannot establish executable entry/exit, profit, interval extrema or global missed opportunities. Missing/rejected candidates remain counted; original paper policies and outcomes are unchanged.",
    }
