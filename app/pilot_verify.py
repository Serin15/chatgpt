"""Read-only verification of an already activated pilot on the normal local instance."""

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.models import epoch, utcnow


def verify(url, duration):
    started = time.monotonic()
    chosen, study, initial_detail = None, None, None
    last_log = -30
    with httpx.Client(base_url=url, timeout=20, trust_env=False) as client:
        status = client.get("/api/status")
        status.raise_for_status()
        status = status.json()
        if status.get("app_id") != "pulse_crypto_research" or status.get("live_execution") is not False:
            raise ValueError("Expected MemeScope with real-money execution disabled.")
        while True:
            response = client.get("/api/opportunities/pilot")
            response.raise_for_status()
            data = response.json()
            if data.get("study") is None:
                raise ValueError("Start the 30-day pilot in the application first.")
            study = study or data["study"]
            if study != data["study"]:
                raise ValueError("Pilot declaration changed during verification.")
            if chosen is None:
                for row in data.get("first_candidates", []):
                    if row["first_signal_id"] is not None:
                        chosen = row
                        initial_detail = client.get(
                            "/api/opportunities/" + str(chosen["candidate_id"])
                        ).json()
                        break
            detail = client.get("/api/opportunities/" + str(chosen["candidate_id"])).json() if chosen else None
            primary = data.get("models", {}).get("estimated_pool", {}).get("300", {})
            compare = primary.get("comparison", {})
            criteria = {
                "real_money_disabled": status["live_execution"] is False,
                "immutable_thirty_day_window": epoch(study["ends_at"]) - epoch(study["declared_at"]) == 30 * 86400,
                "report_ready_and_fresh": data.get("report_state") == "ready"
                and not data.get("report_cache", {}).get("stale", False),
                "new_stored_token_evaluated": bool(detail and chosen and
                    epoch(study["declared_at"]) <= epoch(detail["ingested_at"]) < epoch(study["ends_at"])
                    and any(s["id"] == chosen["first_signal_id"] for s in detail["signals"])
                    and any(o.get("source_kind") == "live_provider_observation"
                            for o in detail["observations"])),
                "later_observation_preserved": bool(detail and initial_detail and
                    detail["observations_total"] > initial_detail["observations_total"]),
                "matured_selected_comparison_available": compare.get(
                    "selected_at_first_evaluation", {}).get("experiments", 0) > 0,
                "matured_disjoint_control_available": compare.get(
                    "control_excluding_selected", {}).get("experiments", 0) > 0,
            }
            elapsed = time.monotonic() - started
            if all(criteria.values()) or elapsed >= duration:
                break
            if elapsed - last_log >= 30:
                print(json.dumps({"elapsed_seconds": round(elapsed), "criteria": criteria}), flush=True)
                last_log = elapsed
            time.sleep(min(5, max(0, duration - elapsed)))
        return {
            "at": utcnow(), "complete": all(criteria.values()), "criteria": criteria,
            "duration_seconds": round(elapsed), "report": data,
            "chosen_without_outcome_filter": chosen, "initial_detail": initial_detail,
            "latest_detail": detail, "requests": "read-only loopback API requests",
            "note": "This verifies early pilot plumbing and preserved unknowns, not a completed 30-day study, profitable results, or a successful trade. No candidate injection, threshold changes, messages or orders.",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--duration", type=int, default=1200)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    url = urlsplit(args.url)
    if (url.scheme not in {"http", "https"} or url.hostname not in {"127.0.0.1", "localhost"}
            or url.username or url.password or url.query or url.fragment):
        parser.error("Use a plain loopback URL without credentials, query or fragment.")
    if not 60 <= args.duration <= 7200:
        parser.error("Duration: 60..7200 seconds.")
    result = verify(args.url, args.duration)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"complete": result["complete"], "criteria": result["criteria"]}))
    if not result["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
