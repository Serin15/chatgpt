"""Isolated UI audit. Uses test fixtures and browser response overrides only.

Run: UV_CACHE_DIR=/workspace/.cache/uv uv run --with playwright python docs/audit/reproduce_browser.py
Requires /usr/bin/chromium, like tests/browser_smoke.py. No production data or real trades.
Historical v0.2 probe: run on commit 307376d. Use tests/browser_regressions.py for v0.3.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def emit(case, **observed):
    print(json.dumps({"case": case, **observed}, ensure_ascii=False))


def main():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="pulse-audit-ui-") as folder:
        environment = os.environ.copy()
        environment["BROWSER_TEST_DATA"] = folder
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "tests.browser_fixture:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            with httpx.Client(base_url=base, timeout=1, trust_env=False) as client:
                for _ in range(100):
                    try:
                        if client.get("/api/status").is_success:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Isolated audit fixture failed to start")
            flags = {"fail_news": False, "cash": None, "rpc_error": False}
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"]
                )
                page = browser.new_page(viewport={"width": 1440, "height": 1000})

                def route_api(route):
                    path = urlsplit(route.request.url).path
                    if path == "/api/news" and flags["fail_news"]:
                        route.fulfill(status=503, json={"detail": "Isolated audit news failure"})
                        return
                    response = route.fetch()
                    payload = response.json()
                    if path == "/api/portfolio" and flags["cash"] is not None:
                        payload["cash"] = flags["cash"]
                    elif path == "/api/status" and flags["rpc_error"]:
                        payload["providers"]["rpc"] = {
                            "state": "error",
                            "error": "Isolated RPC failure",
                            "at": None,
                        }
                    elif path == "/api/assets":
                        payload.append(
                            {
                                "asset_id": "tiny-fixture",
                                "kind": "market_asset",
                                "address": "asset:tiny-fixture",
                                "name": "Tiny price fixture",
                                "symbol": "TINY",
                                "price_usd": 0.000012,
                                "volume_24h": 1000,
                                "market_cap": 100000,
                                "rank": 999,
                                "change_24h": 1,
                            }
                        )
                    elif path == "/api/assets/bitcoin/profile":
                        payload["contracts"] = {"polygon-pos": "0x" + "a" * 40}
                    route.fulfill(response=response, json=payload)

                page.route("**/api/**", route_api)
                page.goto(base)
                expect(page.locator("#cash")).to_have_text("500,00 USD")

                flags["fail_news"] = True
                flags["cash"] = "321"
                page.evaluate("load()")
                expect(page.locator("#cash")).to_have_text("500,00 USD")
                expect(page.locator("#message")).to_contain_text("Isolated audit news failure")
                emit(
                    "partial_endpoint_failure",
                    available_portfolio_cash="321",
                    displayed_cash=page.locator("#cash").inner_text(),
                )
                flags["fail_news"] = False
                page.evaluate("load()")
                expect(page.locator("#cash")).to_have_text("321,00 USD")

                flags["rpc_error"] = True
                page.evaluate("load()")
                expect(page.locator("#connection")).to_have_text("Surse monitorizate")
                emit(
                    "rpc_error_not_in_global_indicator",
                    rpc_state=page.evaluate("state.status.providers.rpc.state"),
                    indicator=page.locator("#connection").inner_text(),
                )
                flags["rpc_error"] = False

                page.locator('.nav-item[data-page="market"]').click()
                page.locator("#market-button").click()
                tiny = page.locator("#asset-rows tr").filter(has_text="Tiny price fixture")
                expect(tiny).to_be_visible()
                displayed_price = tiny.locator("td").nth(1).inner_text()
                assert displayed_price.replace("\xa0", " ") == "0,00 USD"
                emit("tiny_price_rounded_to_zero", input_price=0.000012, displayed=displayed_price)

                page.locator(".brand").click()
                assert page.evaluate("location.hash") == "#overview"
                assert page.evaluate("state.page") == "market"
                emit(
                    "brand_navigation",
                    hash=page.evaluate("location.hash"),
                    actual_page=page.evaluate("state.page"),
                )

                page.set_viewport_size({"width": 390, "height": 844})
                assert page.locator('[data-page="journal"]:visible').count() == 0
                emit("mobile_journal_navigation", visible_journal_controls=0)
                bitcoin = page.locator("#asset-rows tr").filter(has_text="Bitcoin")
                bitcoin.get_by_role("button", name="Deschide dosarul").click()
                page.get_by_role("button", name="Verifică documentele și identitatea").click()
                expect(page.locator("pre.history-row")).to_be_visible()
                width = page.evaluate("document.documentElement.scrollWidth")
                emit(
                    "mobile_contract_layout",
                    viewport=390,
                    document_width=width,
                    overflow=width > 390,
                )
                page.unroute_all(behavior="wait")
                browser.close()
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
