"""Audit browser regressions against isolated providers; never live-data evidence."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from playwright.async_api import async_playwright, expect


async def check(base):
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=os.getenv("BROWSER_EXECUTABLE", "/usr/bin/chromium"),
            headless=True,
            args=["--no-sandbox"],
        )

        async def scenario(name, fn):
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.add_init_script("window.setInterval = () => 0")
            try:
                await fn(page)
                assert not errors, errors
                results.append({"check": name, "pass": True})
            except Exception as exc:
                results.append({"check": name, "pass": False, "error": str(exc)[:600]})
            finally:
                await page.unroute_all(behavior="ignoreErrors")
                await page.close()

        async def ready(page):
            await page.goto(base)
            await expect(page.locator("#engine-rows tr")).to_have_count(1)
            await page.wait_for_function("() => !opportunityView.loading && !state.loading")

        async def layout(page):
            await ready(page)
            await page.locator("#engine-coverage-summary").evaluate(
                "n => n.parentElement.open = true"
            )
            row = await page.locator("#engine-rows").bounding_box()
            coverage = await page.locator("#engine-coverage-summary").bounding_box()
            assert row["y"] < coverage["y"], "Technical panel displaces the candidate list"

        async def health(page):
            await ready(page)
            await page.evaluate("""() => {
                state.status.routed_quotes = {state:'partial', at:new Date().toISOString(),
                                              errors:['Fixture Jupiter unavailable']};
                state.status.announcement_analysis = {state:'error', at:new Date().toISOString(),
                    error:{'developers.circle.com':'Fixture document HTTP 404'}};
                renderHealth();
            }""")
            await expect(page.locator("#connection")).to_contain_text("eroare", timeout=1000)
            await expect(page.locator("#section-alerts")).to_contain_text("routed", timeout=1000)
            await page.locator("#connection").click()
            await expect(page.locator("#health-details")).to_contain_text(
                "Fixture document HTTP 404", timeout=1000
            )

        async def isolation(page):
            gate = asyncio.Event()

            async def delay(route):
                await gate.wait()
                await route.continue_()

            await page.route("**/api/opportunities/routes", delay)
            try:
                await page.goto(base)
                await expect(page.locator("#engine-rows tr")).to_have_count(1, timeout=1500)
            finally:
                gate.set()

        async def detail_race(page):
            await ready(page)
            first = await (await page.request.get(base + "/api/opportunities/1")).json()

            async def delayed(route):
                await asyncio.sleep(0.35)
                await route.fulfill(json=first)

            async def second(route):
                value = json.loads(json.dumps(first))
                value["id"] = 2
                value["observations"][-1]["market"]["name"] = "Second selected candidate"
                await route.fulfill(json=value)

            await page.route("**/api/opportunities/1", delayed)
            await page.route("**/api/opportunities/2", second)
            await page.evaluate(
                "Promise.all([openOpportunity(1, false), openOpportunity(2, false)])"
            )
            await expect(page.locator("#engine-detail h2")).to_have_text(
                "Second selected candidate", timeout=1000
            )

        async def details_preserved(page):
            await ready(page)
            await page.evaluate("openOpportunity(1, false)")
            await page.locator("#engine-detail details").first.evaluate("n => n.open = true")
            await page.evaluate("openOpportunity(1, false)")
            assert await page.locator("#engine-detail details").first.evaluate("n => n.open")

        async def receipts(page):
            await ready(page)
            await page.route(
                "**/api/opportunities/alerts/999/receipt",
                lambda r: r.fulfill(status=503, json={"detail": "Fixture receipt failure"}),
            )
            await page.evaluate("""async () => {
                const items = (await api('/api/opportunities/alerts')).items;
                const a = {...items[0], id:999, delivered_in_app_at:null};
                try { await renderEngineAlerts([a, {...items[0], id:998, delivered_in_app_at:'stored'}]); }
                catch {}
            }""")
            await expect(page.locator("#engine-alerts .engine-alert")).to_have_count(
                2, timeout=1000
            )

        async def browser_history(page):
            await ready(page)
            await page.locator('.nav-item[data-page="market"]').click()
            await page.locator('.nav-item[data-page="news"]').click()
            await page.go_back()
            await expect(page.locator("#view-market")).to_be_visible(timeout=1000)

        async def pagination(page):
            await ready(page)
            response = await (await page.request.get(base + "/api/opportunities")).json()

            async def pages(route):
                value = json.loads(json.dumps(response))
                before = parse_qs(urlsplit(route.request.url).query).get("before")
                ids = [2, 1] if before else [4, 3]
                value["items"] = [value["items"][0] | {"id": i} for i in ids]
                value["next_cursor"] = None if before else 3
                value["matching_total"] = 4
                await route.fulfill(json=value)

            await page.route("**/api/opportunities?*", pages)
            await page.locator("#engine-sort").select_option("recent")
            await expect(page.locator("#engine-rows tr")).to_have_count(2)
            await page.locator("#engine-more").click()
            await expect(page.locator("#engine-rows tr")).to_have_count(4)
            await page.evaluate("renderOpportunities()")
            await expect(page.locator("#engine-rows tr")).to_have_count(4)

        async def health_details(page):
            await ready(page)
            await page.locator("#connection").click()
            await expect(page.locator("#health-details")).to_be_visible(timeout=1000)
            await expect(page.locator("#health-details")).to_contain_text("routed_quotes")

        async def query_race(page):
            await ready(page)
            response = await (await page.request.get(base + "/api/opportunities")).json()
            first_started = asyncio.Event()

            async def candidates(route):
                value = json.loads(json.dumps(response))
                query = parse_qs(urlsplit(route.request.url).query).get("q", [""])[0]
                if query == "first":
                    first_started.set()
                    await asyncio.sleep(0.4)
                value["items"][0]["latest"]["market"]["symbol"] = query
                await route.fulfill(json=value)

            await page.route("**/api/opportunities?*", candidates)
            await page.locator("#engine-search").fill("first")
            await asyncio.wait_for(first_started.wait(), timeout=2)
            await page.locator("#engine-search").fill("second")
            await expect(page.locator("#engine-rows tr")).to_contain_text("second")
            await page.wait_for_timeout(500)
            await expect(page.locator("#engine-rows tr")).to_contain_text("second")

        for name, fn in [
            ("candidate priority", layout),
            ("routed health", health),
            ("independent candidate loading", isolation),
            ("detail response race", detail_race),
            ("expanded evidence survives refresh", details_preserved),
            ("receipt failure isolation", receipts),
            ("browser back", browser_history),
            ("loaded pages survive refresh", pagination),
            ("component health details", health_details),
            ("search response race", query_race),
        ]:
            await scenario(name, fn)
        await browser.close()
    print(json.dumps({"data": "isolated fixtures", "checks": results}, ensure_ascii=False))
    return all(r["pass"] for r in results)


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
            base = f"http://127.0.0.1:{port}"
            for _ in range(100):
                try:
                    if httpx.get(base + "/healthz", timeout=1, trust_env=False).is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Fixture did not start")
            return 0 if asyncio.run(check(base)) else 1
        finally:
            proc.terminate()
            proc.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
