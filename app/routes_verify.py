"""Read-only live verification of forward Jupiter paper quotes on an existing normal instance."""

import argparse
import json
import time
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.models import epoch, utcnow


def assess(detail, signal_id=None):
    """Select one linked, already observed scenario; never merge signal evidence."""
    best = {
        "real_candidate_and_market_observations": False,
        "routed_buy_quote_stored": False,
        "later_routed_sell_and_net_outcome": False,
        "frozen_policy_and_attempt_history": False,
    }
    selected = None
    now = epoch(utcnow())
    routed = detail["routed"]
    observations = {o["id"]: o for o in detail["observations"]}
    attempts = {a["id"]: a for a in routed["attempts"]}
    for entry in routed["entries"]:
        sid = entry["signal_id"]
        if signal_id is not None and sid != signal_id:
            continue
        current = dict.fromkeys(best, False)
        try:
            attempt = attempts.get(entry.get("entry_attempt_id"), {})
            observation = observations.get(attempt.get("observation_id"), {})
            current["real_candidate_and_market_observations"] = bool(
                observation.get("source_kind") == "live_provider_observation"
                and observation.get("market", {}).get("address") == detail["contract"]
                and observation.get("security")
                and epoch(observation["at"]) <= now
            )
            buy = entry.get("entry_payload") or {}
            entry_at = epoch(buy["quote_observed_at"])
            current["routed_buy_quote_stored"] = bool(
                entry["entry_state"] == "filled"
                and buy["address"] == detail["contract"]
                and buy["side"] == "buy"
                and type(buy["jupiter_quote"].get("contextSlot")) is int
                and buy["jupiter_quote"]["contextSlot"] > 0
                and epoch(observation["at"]) <= entry_at <= now
                and epoch(entry["entry_at"]) == entry_at
                and current["real_candidate_and_market_observations"]
            )
            current["frozen_policy_and_attempt_history"] = bool(
                current["routed_buy_quote_stored"]
                and entry["policy"].get("source_sha256")
                and attempt.get("signal_id") == sid
                and attempt.get("phase") == "entry"
                and attempt.get("status") == "quoted"
            )
            if current["frozen_policy_and_attempt_history"]:
                for outcome in routed["outcomes"]:
                    if (
                        outcome["signal_id"] != sid
                        or outcome["state"] != "evaluated"
                        or outcome["horizon_seconds"] != 300
                    ):
                        continue
                    payload = outcome["payload"]
                    exit_attempt = attempts.get(payload.get("exit_attempt_id"), {})
                    sell = payload.get("exit_quote") or {}
                    pnl = Decimal(payload["pnl_usd"])
                    exit_at = epoch(payload["exit_at"])
                    current["later_routed_sell_and_net_outcome"] = bool(
                        pnl.is_finite()
                        and payload.get("entry_attempt_id") == attempt.get("id")
                        and epoch(payload["entry_at"]) == entry_at
                        and entry_at + 300 <= exit_at <= now
                        and exit_attempt.get("signal_id") == sid
                        and exit_attempt.get("phase") == "exit"
                        and exit_attempt.get("status") == "quoted"
                        and exit_attempt.get("horizon_seconds") == 300
                        and sell.get("address") == detail["contract"]
                        and sell.get("side") == "sell"
                        and type(sell.get("jupiter_quote", {}).get("contextSlot")) is int
                        and sell["jupiter_quote"]["contextSlot"] > 0
                        and epoch(sell["quote_observed_at"]) == exit_at
                        and Decimal(sell["requested_size"]) == Decimal(buy["quantity"])
                        and pnl == Decimal(sell["cash_change"]) + Decimal(buy["cash_change"])
                    )
                    if current["later_routed_sell_and_net_outcome"]:
                        break
        except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError):
            pass  # Missing/invalid proof stays incomplete, never zero loss.
        if sum(current.values()) > sum(best.values()):
            best, selected = current, sid
    return best, selected


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
    errors = []
    portfolios = None
    chosen_signal = None
    try:
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
                candidates = list(
                    dict.fromkeys(a["candidate_id"] for a in report["recent_attempts"])
                )
                if chosen_signal is not None:
                    candidates = [detail["id"]]
                for candidate_id in candidates:
                    response = c.get(f"/api/opportunities/{candidate_id}")
                    response.raise_for_status()
                    d = response.json()
                    seen.add(candidate_id)
                    candidate_criteria, sid = assess(d, chosen_signal)
                    if (
                        chosen_signal is not None
                        or sum(candidate_criteria.values()) > sum(criteria.values()) - 1
                    ):
                        criteria = {"real_money_disabled": True, **candidate_criteria}
                        detail = d
                        if candidate_criteria["frozen_policy_and_attempt_history"]:
                            chosen_signal = sid
                    if all(criteria.values()) or chosen_signal is not None:
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
                a: c.get("/api/portfolio", params={"account": a}).json()
                for a in ["news", "scanner"]
            }
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
        # Preserve partial criteria without logging URLs, credentials or treating unknown orders as zero.
        errors.append(
            type(exc).__name__
            + (
                f" HTTP {exc.response.status_code}"
                if isinstance(exc, httpx.HTTPStatusError)
                else ": Verification interrupted; remaining criteria are unverified."
            )
        )
    return {
        "at": utcnow(),
        "complete": all(criteria.values()) and not errors,
        "errors": errors,
        "criteria": criteria,
        "duration_seconds": round(time.monotonic() - started),
        "requests": "GET only; normal running worker, no token injection, no threshold changes, no ledger orders",
        "report": report,
        "candidate": detail,
        "verified_signal_id": chosen_signal,
        "coverage": "Recent candidate attempts; once an entry is linked, one candidate and signal are followed. Stored historical evidence does not by itself verify a new software version.",
        "candidate_ids_examined": sorted(seen),
        "manual_orders": {a: len(p["orders"]) for a, p in portfolios.items()}
        if portfolios is not None
        else None,
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
