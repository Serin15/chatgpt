"""Executable live acceptance run. Starts the real worker; never injects a token or places orders."""

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from app.models import utcnow


def verify(url, duration, browser_path=None):
    started = time.monotonic()
    evidence = {
        "real_data": True,
        "live_execution": False,
        "orders_placed": 0,
        "manual_candidate_injection": False,
        "url_scope": "loopback test instance",
    }
    browser = context = page = playwright = None
    browser_error = None
    try:
        if browser_path:
            try:
                from playwright.sync_api import sync_playwright

                playwright = sync_playwright().start()
                browser = playwright.chromium.launch(
                    executable_path=browser_path,
                    headless=True,
                    args=["--no-sandbox"] if sys.platform != "win32" else [],
                )
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                page.goto(url + "/#opportunities")
            except Exception as exc:
                browser_error = type(exc).__name__
        with httpx.Client(base_url=url, timeout=15, trust_env=False) as client:
            chosen = None
            chosen_alert_id = None
            finished = None
            report = {}
            last_log = -30
            while time.monotonic() - started < duration:
                listing = client.get("/api/opportunities?sort=rank&limit=200")
                listing.raise_for_status()
                listing = listing.json()
                alerts = client.get("/api/opportunities/alerts").json()["items"]
                alerts = [a for a in alerts if a["severity"] != "critical"]
                if alerts:
                    # Prefer an alert with observed forward fills. Historical missing
                    # entry rows remain failures, not acceptance evidence.
                    eligible = []
                    for a in alerts:
                        tracked = client.get("/api/opportunities/" + str(a["candidate_id"])).json()
                        quality = max(
                            (
                                2
                                if o["state"] == "evaluated"
                                else 1
                                if o["state"] == "pending"
                                else 0
                                for o in tracked["outcomes"]
                                if o["signal_id"] == a["signal_id"] and o["horizon_seconds"] == 300
                            ),
                            default=0,
                        )
                        eligible.append((quality, a["id"], a["candidate_id"]))
                    _, chosen_alert_id, chosen = max(eligible)
                    detail = client.get("/api/opportunities/" + str(chosen)).json()
                    selected_alert = next(a for a in alerts if a["id"] == chosen_alert_id)
                    if page:
                        page.wait_for_timeout(100)
                        if not selected_alert["delivered_in_app_at"]:
                            page.evaluate("renderOpportunities()")
                        matching = page.locator(f'[data-alert-id="{selected_alert["id"]}"]')
                        if matching.count():
                            matching.get_by_role("button", name="Deschide semnalul").click()
                    outcomes = [
                        o
                        for o in detail["outcomes"]
                        if o["signal_id"] == selected_alert["signal_id"]
                        and o["horizon_seconds"] == 300
                    ]
                    finished = next((o for o in outcomes if o["state"] == "evaluated"), None)
                    latest_alerts = client.get("/api/opportunities/alerts").json()["items"]
                    delivered = next(a for a in latest_alerts if a["id"] == selected_alert["id"])[
                        "delivered_in_app_at"
                    ]
                    if finished and delivered and len(detail["observations"]) >= 2:
                        break
                if time.monotonic() - started - last_log >= 30:
                    last_log = time.monotonic() - started
                    print(
                        json.dumps(
                            {
                                "elapsed_seconds": round(last_log),
                                "candidates_on_page": len(listing["items"]),
                                "alerts": len(alerts),
                                "engine_state": listing["status"]["state"],
                            }
                        ),
                        flush=True,
                    )
                if page:
                    page.wait_for_timeout(5000)
                else:
                    time.sleep(5)
            report = client.get("/api/opportunities/performance").json()
            alerts = client.get("/api/opportunities/alerts").json()["items"]
            if chosen is None and listing["items"]:
                chosen = next(
                    (i["id"] for i in listing["items"] if i["latest"]), listing["items"][0]["id"]
                )
            detail = client.get("/api/opportunities/" + str(chosen)).json() if chosen else None
            selected_alert = next((a for a in alerts if a["id"] == chosen_alert_id), None)
            observations = (detail or {}).get("observations", [])
            collected = any(
                o.get("market")
                and o.get("security", {}).get("rpc")
                and o.get("security", {}).get("goplus")
                for o in observations
            )
            dashboard = False
            if page and chosen:
                page.evaluate("(id)=>openOpportunity(id,false)", chosen)
                dashboard = (
                    page.locator("#engine-detail").is_visible()
                    and (detail["contract"] in page.locator("#engine-detail").inner_text())
                    and "Rezultate păstrate" in page.locator("#engine-detail").inner_text()
                    and (not finished or "evaluated" in page.locator("#engine-detail").inner_text())
                )
            criteria = {
                "1_real_token_discovered": bool(detail),
                "2_market_and_security_collected": collected,
                "3_features_and_scores": any(
                    o.get("features") and o.get("decision", {}).get("scores") for o in observations
                ),
                "4_explained_verdict": any(
                    o.get("decision", {}).get("verdict") for o in observations
                ),
                "5_persisted_signal": bool((detail or {}).get("signals")),
                "6_eligible_alert_displayed_and_receipted": bool(
                    selected_alert and selected_alert["delivered_in_app_at"]
                ),
                "7_later_observation_and_evaluated_5m_paper_outcome": bool(
                    finished and len(observations) >= 2
                ),
                "8_dashboard_displays_candidate_and_outcomes": dashboard,
            }
            evidence.update(
                at=utcnow(),
                criteria=criteria,
                complete=all(criteria.values()),
                duration_seconds=round(time.monotonic() - started),
                candidate=detail,
                alert=selected_alert,
                performance=report,
                browser_error=browser_error,
                telegram_live_verified=bool(
                    selected_alert and selected_alert["telegram_state"] == "acknowledged_by_api"
                ),
                blockers=[]
                if all(criteria.values())
                else [
                    "No qualifying alert/terminal observation/browser within the observation period; see individual criteria. Do not relax risk thresholds to force acceptance."
                ],
            )
            for account, balance in [("news", "500"), ("scanner", "100")]:
                p = client.get("/api/portfolio", params={"account": account}).json()
                assert p["cash"] == balance and p["orders"] == []
            return evidence
    finally:
        if browser:
            browser.close()
        if playwright:
            playwright.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=int, default=900)
    parser.add_argument(
        "--browser",
        help="Path to an installed Chromium browser; requires playwright Python package.",
    )
    parser.add_argument(
        "--existing-url",
        help="Read a running isolated instance; never use this against another user account.",
    )
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 30 <= args.duration <= 7200:
        parser.error("Duration must be 30..7200 seconds.")
    from urllib.parse import urlsplit

    if args.existing_url and urlsplit(args.existing_url).hostname not in {"127.0.0.1", "localhost"}:
        parser.error("Verification only supports loopback instances.")
    process = None
    with tempfile.TemporaryDirectory(prefix="memescope-live-") as directory:
        log_path = args.output.with_suffix(".server.log")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w") as log:
            try:
                url = args.existing_url
                if not url:
                    with socket.socket() as probe:
                        probe.bind(("127.0.0.1", 0))
                        port = probe.getsockname()[1]
                    environment = os.environ.copy()
                    environment["DATA_DIR"] = str((args.data_dir or Path(directory)).resolve())
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "uvicorn",
                            "app.main:app",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(port),
                        ],
                        env=environment,
                        cwd=Path(__file__).resolve().parents[1],
                        stdout=log,
                        stderr=log,
                    )
                    url = f"http://127.0.0.1:{port}"
                    for _ in range(100):
                        try:
                            if httpx.get(url + "/healthz", timeout=1, trust_env=False).is_success:
                                break
                        except httpx.HTTPError:
                            pass
                        if process.poll() is not None:
                            raise RuntimeError(
                                "Live verification server exited; inspect the saved server log."
                            )
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("Live verification server did not become ready.")
                evidence = verify(url, args.duration, args.browser)
                args.output.write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8",
                )
                print(
                    json.dumps(
                        {
                            "complete": evidence["complete"],
                            "criteria": evidence["criteria"],
                            "telegram_live_verified": evidence["telegram_live_verified"],
                        }
                    )
                )
                if not evidence["complete"]:
                    raise SystemExit(1)
            finally:
                if process:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == "__main__":
    main()
