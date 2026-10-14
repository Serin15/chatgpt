"""Frozen, labeled news cases. Validation is offline; model runs are explicit and bounded."""

import argparse
import asyncio
import hashlib
import json
import tempfile
from pathlib import Path

from app.ai_research import PROMPT_VERSION, AIConfig, AIResearch, relationship_gate
from app.announcements import Announcements
from app.config import Settings
from app.models import utcnow
from app.providers import ProviderError
from app.store import Store

CORPUS = Path(__file__).resolve().parents[1] / "docs/evaluation/news-cases.json"
POSITIVE = {"issuer_announcement", "listing_announcement"}


def load_cases(path=CORPUS):
    corpus = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = corpus["cases"]
    ids = set()
    groups = {}
    for case in cases:
        if case["id"] in ids or case["origin"] not in {"observed_excerpt", "synthetic"}:
            raise ValueError("ID duplicat sau proveniență invalidă.")
        ids.add(case["id"])
        partition, group = case.get("partition"), case.get("group")
        if partition not in {"development", "test"} or not group:
            raise ValueError("Lipsește partiția sau grupul documentului.")
        if group in groups and groups[group] != partition:
            raise ValueError("Data leakage: document comun între dezvoltare și test.")
        groups[group] = partition
        if not case["expected"] or not set(case["expected"]) <= POSITIVE | {
            "contradicted",
            "insufficient_evidence",
            "unrelated_or_namesake",
        }:
            raise ValueError("Etichete de evaluare invalide.")
        if not case["bundle"]["sources"][0]["content"]:
            raise ValueError("Lipsește textul sursei.")
        if case["origin"] == "observed_excerpt" and not all(
            case["provenance"].get(key) for key in ("url", "sha256", "observed_at")
        ):
            raise ValueError("Lipsește proveniența extrasului observat.")
    return cases


def metrics(cases, results):
    by_id = {r["id"]: r for r in results}
    correct = valid = positive_predictions = true_positive = false_positive = 0
    expected_positive = sum(bool(set(c["expected"]) & POSITIVE) for c in cases)
    for case in cases:
        result = by_id.get(case["id"], {})
        if result.get("state") != "completed":
            continue
        valid += 1
        predicted = result["relationship"]["effective"]
        correct += predicted in case["expected"]
        if predicted in POSITIVE:
            positive_predictions += 1
            if predicted in case["expected"]:
                true_positive += 1
            else:
                false_positive += 1
    return {
        "cases": len(cases),
        "valid_outputs": valid,
        "invalid_or_failed": len(cases) - valid,
        "correct_including_failures": correct,
        "accuracy": correct / len(cases) if cases else None,
        "positive_predictions": positive_predictions,
        "false_positive_associations": false_positive,
        "positive_precision": true_positive / positive_predictions
        if positive_predictions
        else None,
        "positive_recall": true_positive / expected_positive if expected_positive else None,
        "always_insufficient_baseline": sum("insufficient_evidence" in c["expected"] for c in cases)
        / len(cases)
        if cases
        else None,
        "note": "Eșantion mic, etichete ale autorului și scenarii sintetice. Nu este o estimare a preciziei în piață sau a randamentului.",
    }


async def run_model(cases, config):
    # Isolated research DB: no changes to the user's cash, orders, dossiers or configuration.
    results = []
    with tempfile.TemporaryDirectory(prefix="pulse-ai-evaluation-") as folder:
        store = Store(Settings(data_dir=Path(folder)))
        import httpx

        async with httpx.AsyncClient() as document_client:
            engine = AIResearch(store, Announcements(store, document_client))
            try:
                for case in cases:
                    try:
                        interpretation, usage = await engine.generate(config, case["bundle"])
                        results.append(
                            {
                                "id": case["id"],
                                "origin": case["origin"],
                                "expected": case["expected"],
                                "state": "completed",
                                "interpretation": interpretation,
                                "usage": usage,
                                "relationship": relationship_gate(interpretation, case["bundle"]),
                            }
                        )
                    except (
                        ProviderError,
                        ValueError,
                        TypeError,
                        KeyError,
                        IndexError,
                        AttributeError,
                    ):
                        results.append(
                            {
                                "id": case["id"],
                                "origin": case["origin"],
                                "state": "error",
                                "error": "Motor indisponibil sau rezultat/citări invalide.",
                            }
                        )
            finally:
                await engine.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-model",
        action="store_true",
        help="Requests real generations, potentially paid. At most 20 cases per invocation.",
    )
    parser.add_argument("--provider", choices=["ollama", "openai"])
    parser.add_argument("--model")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--partition", choices=["all", "development", "test"], default="all")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.limit <= 20:
        parser.error("--limit trebuie să fie între 1 și 20")
    cases = [
        c for c in load_cases() if args.partition == "all" or c["partition"] == args.partition
    ][: args.limit]
    report = {
        "at": utcnow(),
        "corpus_version": 2,
        "corpus_sha256": hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
        "prompt_version": PROMPT_VERSION,
        "partition": args.partition,
        "cases_validated": len(cases),
        "observed_excerpts": sum(c["origin"] == "observed_excerpt" for c in cases),
        "synthetic_cases": sum(c["origin"] == "synthetic" for c in cases),
        "model_run": False,
        "metrics": None,
        "note": "Validarea offline verifică structura și proveniența declarată a setului. Precizia AI nu a fost măsurată.",
    }
    if args.run_model:
        if not args.provider or not args.model:
            parser.error(
                "--run-model cere --provider și --model; nu folosim automat un serviciu plătit"
            )
        config = AIConfig(provider=args.provider, model=args.model)
        results = asyncio.run(run_model(cases, config))
        report.update(
            model_run=True,
            provider=config.provider,
            model=config.model,
            results=results,
            metrics=metrics(cases, results),
            partition_metrics={
                p: metrics([c for c in cases if c["partition"] == p], results)
                for p in ("development", "test")
            },
            raw_model_metrics=metrics(
                cases,
                [
                    r | {"relationship": {"effective": r["relationship"]["model_proposed"]}}
                    if r.get("state") == "completed"
                    else r
                    for r in results
                ],
            ),
            note="Rulare pe extrase înghețate. Etichetele nu sunt validate independent; raportează separat erorile, asocierile false și baseline-ul.",
        )
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output)
    if report["model_run"] and report["metrics"]["correct_including_failures"] < len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
