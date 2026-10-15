"""Read-only live verification of forward Jupiter paper quotes on an existing normal instance."""

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.models import epoch, utcnow


def verify(url, duration):
    started = time.monotonic()
    criteria = {
        "real_money_disabled": False,
        "real_candidate_and_market_observations": False,
        "routed_buy_quote_stored": False,
        "later_routed_sell_and_net_outcome": False,
        "frozen_policy_and_attempt_history": False,
    }
    detail = None
    report = {}
    seen = set()
    last_log = -30
    with httpx.Client(base_url=url, trust_env=False, timeout=30) as c:
        status = c.get("/api/status")
        status.raise_for_status()
        status = status.json()
        if (
            status.get("app_id") != "pulse_crypto_research"
            or status.get("live_execution") is not False
        ):
            raise ValueError("Expected MemeScope with real-money execution disabled.")
        criteria["real_money_disabled"] = True
        while True:
            response = c.get("/api/opportunities/routes")
            response.raise_for_status()
            report = response.json()
            candidates = list(dict.fromkeys(a["candidate_id"] for a in report["recent_attempts"]))
            for candidate_id in candidates:
                response = c.get(f"/api/opportunities/{candidate_id}")
                response.raise_for_status()
                d = response.json()
                routed = d["routed"]
                if detail is None:
                    detail = d
                seen.add(candidate_id)
                live = any(
                    o.get("source_kind") == "live_provider_observation" for o in d["observations"]
                )
                entry = next(
                    (
                        e
                        for e in routed["entries"]
                        if e["entry_state"] == "filled"
                        and e["entry_payload"].get("jupiter_quote", {}).get("contextSlot")
                    ),
                    None,
                )
                evaluated = next(
                    (
                        o
                        for o in routed["outcomes"]
                        if o["state"] == "evaluated"
                        and o["horizon_seconds"] == 300
                        and epoch(o["payload"]["exit_at"]) >= epoch(o["payload"]["entry_at"]) + 300
                    ),
                    None,
                )
                if live:
                    criteria["real_candidate_and_market_observations"] = True
                if entry:
                    detail = d
                    criteria["routed_buy_quote_stored"] = True
                    criteria["frozen_policy_and_attempt_history"] = bool(
                        entry["policy"].get("source_sha256") and routed["attempts"]
                    )
                if evaluated:
                    detail = d
                    criteria["later_routed_sell_and_net_outcome"] = True
                    break
            elapsed = time.monotonic() - started
            if all(criteria.values()) or elapsed >= duration:
                break
            if elapsed - last_log >= 30:
                print(
                    json.dumps(
                        {
                            "elapsed_seconds": round(elapsed),
                            "criteria": criteria,
                            "routing_status": report["status"],
                            "entry_states": report["entry_states"],
                        }
                    ),
                    flush=True,
                )
                last_log = elapsed
            time.sleep(min(5, max(0, duration - elapsed)))
        portfolios = {
            a: c.get("/api/portfolio", params={"account": a}).json() for a in ["news", "scanner"]
        }
    return {
        "at": utcnow(),
        "complete": all(criteria.values()),
        "criteria": criteria,
        "duration_seconds": round(elapsed),
        "requests": "GET only; normal running worker, no token injection, no threshold changes, no ledger orders",
        "report": report,
        "candidate": detail,
        "candidate_ids_examined": sorted(seen),
        "manual_orders": {a: len(p["orders"]) for a, p in portfolios.items()},
        "note": "A successful quote scenario is not executed or guaranteed. FX/network/conversion assumptions remain visible. No profitability claim.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8767")
    parser.add_argument("--duration", type=int, default=900)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    u = urlsplit(args.url)
    if (
        u.scheme not in {"http", "https"}
        or u.hostname not in {"127.0.0.1", "localhost"}
        or u.username
        or u.password
        or u.query
        or u.fragment
    ):
        parser.error("Use a plain loopback URL without credentials/query/fragment.")
    if not 30 <= args.duration <= 7200:
        parser.error("Duration: 30..7200 seconds.")
    proof = verify(args.url, args.duration)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({"complete": proof["complete"], "criteria": proof["criteria"]}))
    if not proof["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
