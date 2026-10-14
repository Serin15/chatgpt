"""v0.3 UI regressions in temporary databases; fixtures never reach the user's ledger.

Run: uv run --with playwright python tests/browser_regressions.py
Requires /usr/bin/chromium, as does browser_smoke.py.
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


def main():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with tempfile.TemporaryDirectory() as folder:
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
            cwd=Path(__file__).resolve().parents[1],
            env=os.environ | {"BROWSER_TEST_DATA": folder},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            for _ in range(100):
                try:
                    if httpx.get(base + "/api/status", timeout=1, trust_env=False).is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Isolated fixture did not start")
            flags = {"news_failure": False, "cash": None, "rpc_failure": False}
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"]
                )
                page = browser.new_page(
                    viewport={"width": 1440, "height": 1000}, accept_downloads=True
                )
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.add_init_script("window.setInterval = () => 0")

                def route_api(route):
                    path = urlsplit(route.request.url).path
                    if path == "/api/news" and flags["news_failure"]:
                        route.fulfill(status=503, json={"detail": "Fixture news unavailable"})
                        return
                    if path == "/api/research/source":
                        route.fulfill(
                            json={
                                "excerpt_found": True,
                                "claim_verified": False,
                                "observed_at": "2026-10-14T00:00:00Z",
                                "note": "Doar text, afirmația rămâne neverificată.",
                            }
                        )
                        return
                    if route.request.method != "GET":
                        route.continue_()
                        return
                    response = route.fetch()
                    payload = response.json()
                    if path == "/api/portfolio" and flags["cash"]:
                        payload["cash"] = flags["cash"]
                    if path == "/api/status" and flags["rpc_failure"]:
                        payload["providers"]["rpc"] = {
                            "state": "error",
                            "error": "Fixture RPC failure",
                            "at": None,
                        }
                    if path == "/api/assets":
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
                    if path == "/api/assets/bitcoin/profile":
                        payload["contracts"] = {"polygon-pos": "0x" + "a" * 40}
                    route.fulfill(response=response, json=payload)

                page.route("**/api/**", route_api)
                page.goto(base)
                expect(page.locator("#cash")).to_have_text("500,00 USD")
                flags.update(news_failure=True, cash="321")
                page.evaluate("load()")
                expect(page.locator("#cash")).to_have_text("321,00 USD")
                expect(page.locator("#section-alerts")).to_contain_text("Fixture news unavailable")
                flags.update(news_failure=False, rpc_failure=True)
                page.evaluate("load()")
                expect(page.locator("#connection")).to_contain_text("componente cu eroare")
                expect(page.locator("#section-alerts")).to_contain_text("rpc")
                flags.update(rpc_failure=False, cash=None)

                page.locator('.nav-item[data-page="market"]').click()
                page.locator("#market-button").click()
                tiny = page.locator("#asset-rows tr").filter(has_text="Tiny price fixture")
                expect(tiny).to_be_visible()
                assert "0,000012" in tiny.locator("td").nth(1).inner_text()
                page.locator(".brand").click()
                expect(page.locator("#view-overview")).to_be_visible()
                assert page.evaluate("state.page") == "overview"

                page.locator('.nav-item[data-page="market"]').click()
                page.locator("#asset-query").fill("bitcoin")
                page.locator("#asset-discovery-form button").click()
                page.get_by_role("button", name="Urmărește și deschide").click()
                expect(page.locator(".evidence-panel")).to_be_visible()
                page.get_by_label("Tipul dovezii").select_option("product")
                page.get_by_label("Starea evaluării").select_option("supported")
                page.get_by_label("Afirmația evaluată").fill(
                    "Explicit isolated browser research evidence"
                )
                page.get_by_label("URL public al sursei").fill("https://blog.ethereum.org/example")
                page.get_by_label("Citat din document").fill(
                    "An explicit source excerpt used only in this fixture."
                )
                page.get_by_label("Motivul evaluării manuale").fill(
                    "Compared manually in an isolated UI test."
                )
                page.get_by_role("button", name="Compară citatul în document").click()
                expect(page.locator(".evidence-form")).to_contain_text("Citat găsit")
                page.get_by_role("button", name="Salvează dovada").click()
                expect(page.locator(".evidence-panel")).to_contain_text("SUSȚINUT · MANUAL")
                thesis = page.get_by_label("Ipoteza de intrare")
                thesis.fill("A thesis recorded before any virtual order")
                page.get_by_role("button", name="Salvează semnal").click()
                buy = page.get_by_role("button", name="Simulează intrarea")
                expect(buy).to_be_enabled(timeout=7000)
                thesis.fill("Changed hypothesis invalidates the previous signal")
                expect(buy).to_be_disabled()
                page.get_by_role("button", name="Retrage evaluarea").click()
                expect(page.locator(".evidence-panel")).to_contain_text("RETRAS")
                assert not page.request.get(base + "/api/portfolio?account=news").json()["orders"]

                page.set_viewport_size({"width": 390, "height": 844})
                expect(page.locator('.nav-item[data-page="journal"]')).to_be_visible()
                page.get_by_role("button", name="Verifică documentele și identitatea").click()
                expect(page.locator("pre.history-row")).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth") == 390
                page.locator('.nav-item[data-page="journal"]').click()
                expect(page.locator("#performance")).to_contain_text(
                    "Nu demonstrează un avantaj financiar"
                )
                with page.expect_download() as exported:
                    page.locator("#export-button").click()
                assert json.loads(Path(exported.value.path()).read_text())["signals"][0][
                    "evidence"
                ]["research_context"]["evidence"]
                with page.expect_download() as backed_up:
                    page.locator("#backup-button").click()
                assert backed_up.value.suggested_filename.endswith(".zip")
                expect(page.locator("#message")).to_contain_text("Backup complet")
                page.wait_for_function("() => !state.loading")
                page.unroute_all(behavior="wait")
                assert not errors, errors
                browser.close()
                print(
                    "PASS: partial failures, health, tiny prices, navigation, search/watch, manual evidence, signal invalidation, mobile contracts/journal, JSON export and ZIP backup"
                )
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
