"""Read-only live verification of balanced observation collection on a running instance."""

import argparse
import json
import math
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.models import epoch, utcnow
from app.opportunity_sampling import SAMPLING_VERSION


def verify(url, duration):
    started = time.monotonic()
    since = time.time()
    accumulated = {"alerts": {}, "control": {}}
    last_log = -30
    with httpx.Client(base_url=url, timeout=20, trust_env=False) as client:
        status = client.get("/api/status")
        status.raise_for_status()
        status = status.json()
        if (
            status.get("app_id") != "pulse_crypto_research"
            or status.get("live_execution") is not False
        ):
            raise ValueError("Expected MemeScope with real-money trading disabled.")
        while True:
            response = client.get("/api/opportunities/coverage")
            response.raise_for_status()
            coverage = response.json()
            until = time.time()
            for group in accumulated:
                for r in coverage.get("recent_attempts", {}).get(group, []):
                    try:
                        quote, received = epoch(r["quote_observed_at"]), epoch(r["observed_at"])
                        valid = (
                            r["source_kind"] == "live_provider_observation"
                            and r["provenance"] == "prospective"
                            and isinstance(r["id"], int)
                            and isinstance(r["candidate_id"], int)
                            and all(
                                math.isfinite(v)
                                for v in (quote, received, r["due_at"], r["deadline_at"])
                            )
                            and since <= quote <= received <= until
                            and r["due_at"] <= quote <= received <= r["deadline_at"]
                        )
                        if valid:
                            accumulated[group][r["id"]] = r
                    except (ValueError, TypeError, KeyError, OverflowError):
                        continue
            examples = {group: list(rows.values()) for group, rows in accumulated.items()}
            captures = {
                group: len({(r["candidate_id"], r["quote_observed_at"]) for r in rows})
                for group, rows in examples.items()
            }
            criteria = {
                "real_money_disabled": True,
                "prospective_collection_policy": coverage.get("version") == SAMPLING_VERSION,
                "control_market_observations_in_window": captures["control"] >= 2,
                "alert_market_observations_in_window": captures["alerts"] >= 2,
                "later_exit_observed": any(r["phase"] == "exit" for r in examples["alerts"]),
                "control_price_checkpoint_observed": any(
                    r["phase"] == "checkpoint" for r in examples["control"]
                ),
            }
            elapsed = time.monotonic() - started
            if all(criteria.values()) or elapsed >= duration:
                break
            if elapsed - last_log >= 30:
                print(
                    json.dumps(
                        {
                            "elapsed_seconds": round(elapsed),
                            "criteria": criteria,
                            "groups": coverage["groups"],
                        }
                    ),
                    flush=True,
                )
                last_log = elapsed
            time.sleep(min(5, max(0, duration - elapsed)))
        ledgers = {
            a: client.get("/api/portfolio", params={"account": a}).json()
            for a in ["news", "scanner"]
        }
        result = {
            "at": utcnow(),
            "complete": all(criteria.values()),
            "criteria": criteria,
            "duration_seconds": round(elapsed),
            "validation_started_at_epoch": since,
            "validation_finished_at_epoch": until,
            "distinct_observations": captures,
            "source": "normal worker with public providers; no candidate injection or threshold changes",
            "requests": "read-only API requests",
            "coverage": coverage,
            "examples": examples,
            "manual_account_orders": {a: len(p["orders"]) for a, p in ledgers.items()},
            "note": "Only provider quotes captured and received during this verification count. Distinct market captures, not duplicate jobs, are counted. This verifies observed windows, not predictive quality, fair coverage under every future load, or real execution. Pending/failed observations remain in the report.",
        }
        return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default="http://127.0.0.1:8766")
    p.add_argument("--duration", type=int, default=900)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    parsed = urlsplit(args.url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        p.error("Use a plain loopback URL without credentials, query or fragment.")
    if not 30 <= args.duration <= 7200:
        p.error("Duration: 30..7200 seconds.")
    result = verify(args.url, args.duration)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({"complete": result["complete"], "criteria": result["criteria"]}))
    if not result["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
