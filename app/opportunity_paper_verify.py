"""Real quote check in a disposable ledger; the source instance is only read.

Usage: python -m app.opportunity_paper_verify --url http://127.0.0.1:8001
This tests a manual workflow, not predictive performance or actual execution.
"""

import argparse
import json
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import utcnow


def verify(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username or parsed.password or parsed.query or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Verificarea acceptă doar o instanță locală, fără credențiale în URL.")
    result = {
        "started_at": utcnow(), "data": "live_provider_quotes",
        "fills": "virtual_estimated_pool_in_disposable_ledger",
        "source_access": "GET_only", "live_execution": False,
        "checks": {},
    }
    with httpx.Client(base_url=url, timeout=30, trust_env=False) as source:
        def get(path, **kwargs):
            response = source.get(path, **kwargs)
            response.raise_for_status()
            return response.json()

        health = get("/healthz")
        if health.get("app_id") != "pulse_crypto_research" or health.get("live_execution") is not False:
            raise ValueError("Instanța nu este MemeScope cu execuția reală dezactivată.")
        result["source"] = {k: health[k] for k in ["app_id", "version", "instance_id"]}
        before = {a: get("/api/portfolio", params={"account": a}) for a in ["news", "scanner"]}
        rows = get("/api/opportunities", params={"sort": "rank", "verdict": "INVESTIGATE", "limit": 1})["items"]
        if not rows:
            result["blocked"] = "Nu există un candidat INVESTIGATE; pragurile nu au fost relaxate."
            return result
        # Fixed first candidate; do not retry different tokens until one succeeds.
        candidate = get(f"/api/opportunities/{rows[0]['id']}")
        observation = candidate["observations"][-1]
        result["candidate"] = {
            "id": candidate["id"], "contract": candidate["contract"], "chain": candidate["chain"],
            "discovered_at": candidate["discovered_at"], "source_observation_at": observation["at"],
            "note": "Existing real candidate; not claimed as newly discovered during this verification.",
        }
        with tempfile.TemporaryDirectory(prefix="memescope-manual-verify-") as folder:
            # No production credentials/settings are written into this directory.
            with TestClient(create_app(Settings(data_dir=Path(folder)), run_scanner=False)) as client:
                service = client.app.state.service
                if service.jupiter.enabled:
                    raise ValueError("Această verificare cere modul paper pool; verifică Jupiter separat, fără fallback.")
                with service.store.connect() as db:
                    columns = [r[1] for r in db.execute("PRAGMA table_info(opportunity_candidates)")]
                    values = [json.dumps(candidate[k]) if k == "discovery" else candidate[k] for k in columns]
                    db.execute(f"INSERT INTO opportunity_candidates({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", values)
                    columns = [r[1] for r in db.execute("PRAGMA table_info(opportunity_observations)")]
                    db.execute(f"INSERT INTO opportunity_observations({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", [observation[k] for k in columns])
                    for signal in candidate["signals"]:
                        columns = [r[1] for r in db.execute("PRAGMA table_info(opportunity_signals)")]
                        values = [json.dumps(signal[k]) if k == "payload" else signal[k] for k in columns]
                        db.execute(f"INSERT INTO opportunity_signals({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", values)
                response = client.post(f"/api/opportunities/{candidate['id']}/paper-signal", json={
                    "observation_id": observation["id"], "account": "news", "amount_usd": "50",
                    "thesis": "Live verification in isolated disposable ledger; no production order.",
                })
                result["prepare_http"] = response.status_code
                result["checks"]["manual_signal"] = response.status_code == 200
                if response.status_code != 200:
                    result["blocked"] = response.json().get("detail")
                else:
                    saved = response.json()
                    result["fresh_snapshot"] = saved["snapshot"]
                    result["cost_preview"] = saved["cost_preview"]
                    time.sleep(saved["min_delay_seconds"] + .1)
                    response = client.post("/api/paper/buy", json={
                        "address": candidate["contract"], "signal_id": saved["id"],
                        "account": "news", "amount_usd": "50",
                    })
                    result["buy_http"] = response.status_code
                    result["checks"]["virtual_entry"] = response.status_code == 200
                    if response.status_code == 200:
                        entry = response.json()
                        result["entry"] = entry
                        response = client.post(f"/api/paper/positions/{entry['position_id']}/sell?account=news", json={})
                        result["sell_http"] = response.status_code
                        result["checks"]["virtual_exit"] = response.status_code == 200
                        result["exit"] = response.json()
                        ledger = client.get("/api/portfolio?account=news").json()
                        result["ledger"] = ledger
                        result["checks"]["origin_preserved"] = ledger["positions"][0]["opportunity"]["candidate_id"] == candidate["id"]
                        result["checks"]["net_result_recorded"] = ledger["positions"][0]["pnl"] is not None
                    else:
                        result["blocked"] = response.json().get("detail")
        after = {a: get("/api/portfolio", params={"account": a}) for a in before}
        result["checks"]["production_ledgers_unchanged"] = all(
            all(before[a][k] == after[a][k] for k in ["cash", "positions", "orders"]) for a in before
        )
    result["finished_at"] = utcnow()
    result["passed"] = len(result["checks"]) == 6 and all(result["checks"].values())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.url)
    except httpx.HTTPStatusError as exc:
        result = {"passed": False, "blocked": f"Sursa locală a returnat HTTP {exc.response.status_code}."}
    except (ValueError, httpx.RequestError) as exc:
        result = {"passed": False, "blocked": type(exc).__name__}
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k in {"checks", "passed", "blocked", "candidate"}}, ensure_ascii=False))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
