"""Level 3 UI integration: Chromium with explicitly isolated fixture providers, not live evidence."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright


def main():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with tempfile.TemporaryDirectory() as folder:
        proc = subprocess.Popen(
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
            env=os.environ | {"BROWSER_TEST_DATA": folder, "OPPORTUNITY_FIXTURE": "1"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            url = f"http://127.0.0.1:{port}"
            for _ in range(100):
                try:
                    if httpx.get(url + "/healthz", timeout=1, trust_env=False).is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Fixture did not start")
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"]
                )
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(url)
                expect(page.locator("#view-opportunities")).to_be_visible()
                expect(page.locator("#engine-rows tr")).to_have_count(1)
                expect(page.locator("#engine-alerts")).to_contain_text("INVESTIGATE")
                page.locator("#engine-coverage-summary").click()
                expect(page.locator("#engine-coverage")).to_be_visible()
                expect(page.locator("#engine-coverage")).to_contain_text("Grup de comparație")
                expect(page.locator("#engine-coverage")).to_contain_text("termene ratate")
                page.locator("#engine-routes-summary").click()
                expect(page.locator("#engine-routes")).to_contain_text("Execuția rămâne simulată")
                page.locator("#engine-rows button").click()
                expect(page.locator("#engine-detail")).to_contain_text("Necunoscut")
                expect(page.locator("#engine-detail")).to_contain_text("evaluated")
                expect(page.locator("#engine-detail .engine-chart")).to_be_visible()
                alerts = page.request.get(url + "/api/opportunities/alerts").json()["items"]
                assert alerts[0]["delivered_in_app_at"] and not alerts[0]["seen_at"]
                page.get_by_role("button", name="Marchează citită").click()
                expect(page.locator("#engine-alerts")).to_contain_text("Citită")
                page.locator("#engine-verdict").select_option("REJECT")
                expect(page.locator("#engine-empty")).to_be_visible()
                page.locator("#engine-verdict").select_option("all")
                page.locator("#engine-search").fill("no-matching-token")
                expect(page.locator("#engine-empty")).to_be_visible()
                page.locator("#engine-search").fill("")
                page.locator("#engine-sort").select_option("recent")
                expect(page.locator("#engine-rows tr")).to_have_count(1)
                page.locator("details:has(#engine-config) > summary").click()
                page.locator("#engine-position").fill("25")
                page.locator("#engine-budget").fill("40")
                page.locator("#engine-route-budget").fill("3")
                page.locator("#engine-route-slippage").fill("75")
                page.locator("#engine-routed").uncheck()
                page.locator("#engine-config button").click()
                expect(page.locator("#message")).to_contain_text("Praguri salvate")
                assert (
                    page.request.get(url + "/api/opportunities").json()["config"]["position_usd"]
                    == 25
                )
                assert (
                    page.request.get(url + "/api/opportunities").json()["config"][
                        "observation_budget"
                    ]
                    == 40
                )
                config = page.request.get(url + "/api/opportunities").json()["config"]
                assert config["routed_quote_budget"] == 3 and config["routed_slippage_bps"] == 75
                assert config["routed_quotes_enabled"] is False
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth") == 390
                for account in ["news", "scanner"]:
                    assert not page.request.get(url + "/api/portfolio?account=" + account).json()[
                        "orders"
                    ]
                assert not errors, errors
                browser.close()
                print(
                    json.dumps(
                        {
                            "pass": True,
                            "data": "isolated fixtures",
                            "checks": [
                                "discovery list",
                                "filter/search",
                                "alert receipt and seen",
                                "unknown scores",
                                "paper outcomes",
                                "sample chart",
                                "config",
                                "collection panel and saved budget",
                                "separate Jupiter panel and saved routing policy",
                                "mobile 390px",
                                "zero ledger orders",
                            ],
                        }
                    )
                )
        finally:
            proc.terminate()
            proc.wait(timeout=10)


if __name__ == "__main__":
    main()
