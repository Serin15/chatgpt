"""Read-only live story-to-outcome verification against a normally running local engine."""

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.models import epoch, utcnow
from app.story_markets import validated_reference


def assess(detail, lookup, alerts, evidence_kind="direct_contract"):
    discovery = detail.get("discovery", {})
    source = discovery.get("story_evidence", {})
    document = bool(source.get("source_sha256") and source.get("document_observed_at"))
    via_market = evidence_kind == "market_reference"
    basis = (
        "news_market_pair_reference_not_launch"
        if via_market
        else "exact_contract_news_mention_not_launch"
    )
    if via_market:
        try:
            ref = validated_reference(source["market_reference"])
            document = bool(
                document
                and ref["qualifies_for_discovery"]
                and ref["base_contract"] == detail["contract"]
                and epoch(ref["observed_at"]) <= epoch(detail["discovered_at"])
            )
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            document = False
    discovered = bool(
        document
        and discovery.get("discovery_basis") == basis
        and epoch(detail["discovered_at"])
        >= max(epoch(source["evidence_indexed_at"]), epoch(source["document_observed_at"]))
    )

    def matching(narrative, at):
        return any(
            s.get("news_id") == source.get("news_id")
            and s.get("source_sha256") == source.get("source_sha256")
            and s.get("evidence_indexed_at")
            and epoch(s["evidence_indexed_at"]) <= epoch(at)
            and (not via_market or s.get("market_reference") == source.get("market_reference"))
            for s in narrative.get("market_references" if via_market else "supported", [])
        )

    signals = [
        s
        for s in detail.get("signals", [])
        if s["kind"] != "discovery" and matching(s.get("payload", {}).get("narrative", {}), s["at"])
    ]
    observations = detail.get("observations", [])
    enriched = any(
        o.get("market")
        and o.get("security", {}).get("rpc")
        and o.get("source_kind") == "live_provider_observation"
        for o in observations
    )
    signal_ids = {s["id"] for s in signals}
    selected = [
        a
        for a in alerts
        if a["candidate_id"] == detail["id"]
        and a.get("payload", {}).get("signal_id") in signal_ids
        and a.get("severity") != "critical"
    ]
    baseline = min((epoch(s["at"]) for s in signals), default=float("inf"))
    outcomes = [
        o
        for o in detail.get("outcomes", [])
        if o["state"] == "evaluated"
        and o.get("signal_id") in signal_ids
        and o.get("payload", {}).get("exit_at")
        and epoch(o["payload"]["exit_at"]) > baseline
        and epoch(o["payload"]["exit_at"]) <= time.time()
        and o["payload"].get("actual_hold_seconds", 0) >= o.get("horizon_seconds", float("inf"))
        and o["payload"].get("pnl_usd") is not None
    ]
    return {
        "real_document_contract_reference": document,
        "candidate_discovered_from_document": discovered and lookup["state"] == "resolved_pool",
        "market_and_security_observed": enriched,
        "stored_signal_with_narrative_and_verdict": any(
            s["verdict"] in {"REJECT", "MONITOR", "INVESTIGATE", "CONSIDER"} for s in signals
        ),
        "eligible_alert_generated": bool(selected),
        "in_app_delivery_receipt": any(a.get("delivered_in_app_at") for a in selected),
        "later_outcome_evaluated": bool(outcomes),
    }


def verify(url, duration, evidence_kind="direct_contract"):
    started, errors = time.monotonic(), []
    criteria = {
        name: False
        for name in [
            "real_document_contract_reference",
            "candidate_discovered_from_document",
            "market_and_security_observed",
            "stored_signal_with_narrative_and_verdict",
            "eligible_alert_generated",
            "in_app_delivery_receipt",
            "later_outcome_evaluated",
        ]
    }
    sources, stories, chosen, details, totals = {}, {}, None, None, None
    try:
        with httpx.Client(base_url=url, timeout=15, trust_env=False) as client:
            while True:

                def get(path):
                    response = client.get(path)
                    response.raise_for_status()
                    return response.json()

                status = get("/api/status")
                if (
                    status.get("app_id") != "pulse_crypto_research"
                    or status.get("live_execution") is not False
                ):
                    raise ValueError("Unexpected application or live execution state")
                sources = status.get("news", {}).get("topics", {})
                stories = get("/api/opportunities/narratives")
                alerts = get("/api/opportunities/alerts")["items"]
                jobs = stories.get("story_discovery", {}).get("recent_lookups", [])
                # Retain one candidate across polls. Never combine criteria from
                # different tokens or turn a name-only association into evidence.
                if chosen and criteria["eligible_alert_generated"]:
                    jobs = [chosen]
                best = -1
                for job in jobs:
                    if job["state"] != "resolved_pool" or not job.get("candidate_id"):
                        continue
                    d = get("/api/opportunities/" + str(job["candidate_id"]))
                    c = assess(d, job, alerts, evidence_kind)
                    if sum(c.values()) > best:
                        criteria, details, chosen = c, d, job
                        best = sum(c.values())
                remaining = duration - (time.monotonic() - started)
                if all(criteria.values()) or remaining <= 0:
                    break
                time.sleep(min(5, remaining))
            # The aggregate is ancillary to the proof. Read it once, rather
            # than rebuilding the complete historical report every five seconds.
            aggregate = client.get("/api/opportunities/performance", timeout=60)
            aggregate.raise_for_status()
            totals = aggregate.json()["totals"]
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
        errors.append(
            type(exc).__name__
            + (
                f" HTTP {exc.response.status_code}"
                if isinstance(exc, httpx.HTTPStatusError)
                else ": verification interrupted; remaining criteria unverified"
            )
        )
    return {
        "at": utcnow(),
        "complete": all(criteria.values()) and not errors,
        "evidence_kind": evidence_kind,
        "criteria": criteria,
        "errors": errors,
        "duration_seconds": round(time.monotonic() - started),
        "source_status": sources,
        "stories": stories,
        "candidate": details,
        "universe_totals": totals,
        "operations": "GET only; no injected stories/tokens, thresholds changed, receipt POSTs, messages sent or trades placed",
        "coverage": "Most recent 20 document lookup jobs; once selected, one candidate is followed throughout the run. Absence is unverified, not proof no opportunity exists.",
        "note": "Paper outcomes are simulated. Delivery receipts do not prove a human read the alert. This command does not verify browser rendering or profitability.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--duration", type=int, default=90)
    parser.add_argument(
        "--evidence-kind",
        choices=["direct_contract", "market_reference"],
        default="direct_contract",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    url = urlsplit(args.url)
    if (
        url.scheme not in {"http", "https"}
        or url.hostname not in {"localhost", "127.0.0.1"}
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        parser.error("Use a plain loopback URL without credentials or extra path/query/fragment.")
    if not 0 <= args.duration <= 7200:
        parser.error("Duration must be 0..7200 seconds.")
    proof = verify(args.url, args.duration, args.evidence_kind)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "complete": proof["complete"],
                "criteria": proof["criteria"],
                "errors": proof["errors"],
            }
        )
    )
    if not proof["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
