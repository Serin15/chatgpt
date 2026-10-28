"""UI regressions in Chromium with isolated providers and temporary paper ledgers.

Run: uv run --with playwright python tests/browser_interface.py
Optional BROWSER_AXE_PATH points to a locally installed axe-core/axe.min.js.
No production data, paid model, Telegram send or real transaction is used.
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.async_api import async_playwright, expect

PAGES = (
    "opportunities", "overview", "news", "market", "scanner", "portfolio",
    "journal", "advanced", "sources",
)
WIDTHS = (320, 390, 600, 768, 1024, 1440, 1920)


async def check(base):
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path=os.getenv("BROWSER_EXECUTABLE", "/usr/bin/chromium"),
            headless=True, args=["--no-sandbox"],
        )

        async def scenario(name, fn):
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.add_init_script("window.setInterval = () => 0")
            try:
                await page.goto(base)
                await page.wait_for_function("() => !state.loading && !opportunityView.loading")
                await fn(page)
                assert not errors, errors
                results.append({"check": name, "pass": True})
            except Exception as exc:
                results.append({"check": name, "pass": False, "error": str(exc)[:1000]})
            finally:
                await page.unroute_all(behavior="ignoreErrors")
                await page.close()

        async def fit(page):
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), (
                await page.evaluate("({width:innerWidth, content:document.documentElement.scrollWidth})")
            )

        async def navigate_to(page, name):
            if await page.locator("#mobile-more").is_visible():
                await page.locator("#mobile-more").click()
            await page.locator(f'.nav-item[data-page="{name}"]').click()
            await expect(page.locator(f"#view-{name}")).to_be_visible()
            if name == "advanced":
                await expect(page.locator("#advanced-content section")).to_have_count(4)

        async def layout(page, name):
            await navigate_to(page, name)
            for width in WIDTHS:
                await page.set_viewport_size({"width": width, "height": 900})
                await fit(page)
                clipped = await page.evaluate("""() => [...document.querySelectorAll('button')]
                    .filter(n => n.getClientRects().length && getComputedStyle(n).visibility !== 'hidden')
                    .filter(n => !n.closest('.research-sections, .verdict-filters, .table-scroll'))
                    .filter(n => n.scrollWidth > n.clientWidth + 3)
                    .map(n => n.id || n.innerText)""")
                assert not clipped, (name, width, clipped)

        for name in PAGES:
            async def fn(page, name=name):
                await layout(page, name)
            await scenario(f"{name}: seven widths, navigation and control labels", fn)

        async def large_balances(page):
            for name in ["overview", "portfolio"]:
                await navigate_to(page, name)
                await page.evaluate("""() => document.querySelectorAll('.metrics strong, .portfolio-summary strong')
                    .forEach(n => n.textContent = '123.456.789,00 USD')""")
                await page.set_viewport_size({"width": 320, "height": 900})
                await fit(page)
                assert await page.evaluate("""() => [...document.querySelectorAll('.view:not([hidden]) strong')]
                    .every(n => n.scrollWidth <= n.clientWidth + 1)""")

        async def mobile_tables(page):
            for name, rows in [("market", "asset-rows"), ("scanner", "tokens")]:
                await navigate_to(page, name)
                await expect(page.locator(f"#{rows} tr")).to_have_count(1)
                for width in [320, 390, 600]:
                    await page.set_viewport_size({"width": width, "height": 900})
                    await fit(page)
                    assert await page.locator(f"#{rows} tr").evaluate("""row => [...row.children].every(n => {
                        const r = n.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth;
                    })""")
                    assert await page.locator(f"#{rows} td").nth(1).get_attribute("data-label")
                await page.locator(f"#{rows} button").first.click()
                await expect(page.locator("#view-detail")).to_be_visible()

        async def empty_search(page):
            for name, search, empty in [("market", "asset-search", "assets-empty"),
                                         ("scanner", "search", "empty")]:
                await navigate_to(page, name)
                await page.locator(f"#{search}").fill("no-such-token-987654321")
                await expect(page.locator(f"#{empty}")).to_be_visible()
                await expect(page.locator(f"#{empty}")).to_contain_text("nu corespunde căutării")
                await page.locator(f"#{search}").fill("")
                await expect(page.locator(f"#{empty}")).to_be_hidden()

        async def keyboard_overview(page):
            await navigate_to(page, "overview")
            await page.locator(".mini-story").first.focus()
            await page.keyboard.press("Enter")
            await expect(page.locator("#view-news")).to_be_visible()
            await navigate_to(page, "overview")
            await page.set_viewport_size({"width": 390, "height": 900})
            await expect(page.locator(".market-glance")).to_be_visible()
            await page.locator(".glance-row").first.focus()
            await page.keyboard.press("Enter")
            await expect(page.locator("#view-detail")).to_be_visible()

        async def expanded_evidence(page):
            await navigate_to(page, "opportunities")
            await page.locator("#engine-alerts details").first.evaluate("n => n.open = true")
            for width in [320, 390, 768, 1440]:
                await page.set_viewport_size({"width": width, "height": 900})
                await fit(page)
                assert await page.locator("#engine-alerts details").first.evaluate("""n => {
                    const r=n.getBoundingClientRect(); return r.right<=innerWidth && n.scrollWidth<=n.clientWidth+1;
                }"""), f"Expanded alert overflows at {width}px"
            for selector in ["#engine-daily-panel", "#engine-pilot-panel"]:
                summary = page.locator(selector + " > summary")
                await page.keyboard.press("Tab")
                await summary.focus()
                assert await summary.evaluate("n => getComputedStyle(n).outlineStyle === 'solid'"), selector
                previous = await page.locator(selector).evaluate("n => n.open")
                await page.keyboard.press("Enter")
                assert await page.locator(selector).evaluate("n => n.open") != previous, selector

        async def errors_and_busy(page):
            await page.set_viewport_size({"width": 320, "height": 900})
            await page.evaluate("message('Verificare: '+ 'X'.repeat(3000))")
            await expect(page.locator("#message-close")).to_be_visible()
            await expect(page.locator("#message")).to_have_attribute("role", "alert")
            await fit(page)
            assert await page.locator("#message-text").evaluate("n => n.clientHeight <= innerHeight * .46")
            await page.locator("#message-close").click()
            await expect(page.locator("#message")).to_be_hidden()
            await navigate_to(page, "news")
            gate = asyncio.Event()

            async def pending(route):
                await gate.wait()
                await route.fulfill(status=503, json={"detail": "Sursă indisponibilă temporar"})

            await page.route("**/api/news/refresh", pending)
            try:
                await page.locator("#news-button").click()
                await expect(page.locator("#news-button")).to_be_disabled()
                await expect(page.locator("#news-button")).to_have_attribute("aria-busy", "true")
            finally:
                gate.set()
            await expect(page.locator("#news-button")).to_be_enabled()
            await expect(page.locator("#message")).to_contain_text("Sursă indisponibilă temporar")
            await expect(page.locator("#view-news")).to_be_visible()

        async def labelled_forms(page):
            await navigate_to(page, "advanced")
            for name in ["Rețeaua pentru descoperire", "Rețeaua walletului", "Orizont evaluare"]:
                await expect(page.get_by_label(name, exact=True)).to_be_visible()
            await navigate_to(page, "opportunities")
            start = page.locator("#engine-pilot-start")
            assert await start.evaluate("n => n.classList.contains('primary') && n.getBoundingClientRect().height >= 44")
            await page.set_viewport_size({"width": 390, "height": 900})
            for selector in ["#navigation-toggle", "#refresh-all", "#connection"]:
                assert await page.locator(selector).evaluate("n => n.getBoundingClientRect().height >= 44")
            await page.set_viewport_size({"width": 320, "height": 900})
            for selector in ["#engine-verdict", "#engine-sort"]:
                assert await page.locator(selector).evaluate("""n => {
                    const style=getComputedStyle(n), context=document.createElement('canvas').getContext('2d');
                    context.font=style.font;
                    return n.clientWidth >= context.measureText(n.selectedOptions[0].textContent).width
                        + parseFloat(style.paddingLeft) + parseFloat(style.paddingRight) + 20;
                }"""), f"Selected option is clipped: {selector}"

        async def header_refresh(page):
            await navigate_to(page, "opportunities")
            await page.wait_for_function("() => !opportunityView.loading")
            calls = {"news": 0, "candidates": 0}

            async def broken_market(route):
                await route.fulfill(status=503, json={"detail": "Piață temporar indisponibilă"})

            async def news(route):
                calls["news"] += 1
                await route.fulfill(json={"state": "ok"})

            async def candidates(route):
                calls["candidates"] += 1
                await route.continue_()

            await page.route("**/api/assets/refresh", broken_market)
            await page.route("**/api/news/refresh", news)
            await page.route("**/api/opportunities?*", candidates)
            await page.locator("#refresh-all").click()
            await expect(page.locator("#refresh-all")).to_be_enabled()
            await expect(page.locator("#message")).to_contain_text("Piața crypto: Piață temporar indisponibilă")
            assert calls["news"] == 1 and calls["candidates"] >= 1, calls
            await expect(page.locator("#engine-rows tr")).to_have_count(1)

        async def many_errors(page):
            await page.evaluate("""() => {
                state.status.providers = Object.fromEntries(Array.from({length:12}, (_, i) =>
                    ['source_'+i, {state:'error', error:'Explicit fixture source failure', at:new Date().toISOString()}]));
                renderHealth();
            }""")
            await page.set_viewport_size({"width": 320, "height": 900})
            warning = page.locator("#section-alerts details")
            await expect(warning).to_be_visible()
            assert not await warning.evaluate("n => n.open")
            await warning.locator("summary").click()
            await expect(warning).to_contain_text("source_11")
            await warning.locator("summary").focus()
            await page.evaluate("renderHealth()")
            assert await warning.evaluate("n => n.open")
            await expect(warning.locator("summary")).to_be_focused()
            await warning.get_by_role("button", name="Vezi starea componentelor").click()
            await expect(page.locator("#health-details")).to_be_visible()
            await expect(page.locator("#health-components")).to_contain_text("source_11")
            await fit(page)

        async def accessibility(page):
            path = os.environ.get("BROWSER_AXE_PATH")
            if not path:
                return
            # Test tooling only. Product CSP stays enforced and unchanged.
            await page.evaluate(Path(path).read_text())
            for name in PAGES + ("detail",):
                await page.set_viewport_size({"width": 1440, "height": 1000})
                if name == "detail":
                    await page.evaluate("async () => {const t=await api('/api/tokens'); await openToken(t[0].address)}")
                else:
                    await navigate_to(page, name)
                await page.evaluate("document.querySelectorAll('.view:not([hidden]) details').forEach(n=>n.open=true)")
                for width in [390, 1440]:
                    await page.set_viewport_size({"width": width, "height": 1000})
                    violations = await page.evaluate("""async () => {
                        const r = await axe.run(document, {runOnly:{type:'tag', values:['wcag2a','wcag2aa','wcag21aa']}});
                        return r.violations.map(v=>({id:v.id, nodes:v.nodes.map(n=>n.target)}));
                    }""")
                    assert not violations, (name, width, violations)

        for name, fn in [
            ("large financial values fit 320px", large_balances),
            ("market and scanner actions remain in view on phones", mobile_tables),
            ("empty search explains results and recovers", empty_search),
            ("overview links work with keyboard and market remains on phones", keyboard_overview),
            ("expanded alert evidence fits; summaries have keyboard focus", expanded_evidence),
            ("long errors are dismissible; pending and failed buttons recover", errors_and_busy),
            ("visible form labels and touch targets", labelled_forms),
            ("header refresh updates candidates and isolates failed sources", header_refresh),
            ("many source failures stay compact with complete accessible details", many_errors),
        ]:
            await scenario(name, fn)
        if os.environ.get("BROWSER_AXE_PATH"):
            await scenario("axe WCAG A/AA: ten views, expanded panels, phone and desktop", accessibility)
        await browser.close()
    print(json.dumps({"data": "isolated fixtures", "checks": results}, ensure_ascii=False))
    return all(r["pass"] for r in results)


def main():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with tempfile.TemporaryDirectory() as folder:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "tests.browser_fixture:app",
             "--host", "127.0.0.1", "--port", str(port)],
            cwd=Path(__file__).resolve().parents[1],
            env=os.environ | {"BROWSER_TEST_DATA": folder, "OPPORTUNITY_FIXTURE": "1"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            for _ in range(100):
                try:
                    if httpx.get(base + "/healthz", timeout=1, trust_env=False).is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError("Fixture did not start")
            # Only the disposable fixture receives these simulated provider requests.
            for endpoint in ["/api/news/refresh", "/api/assets/refresh", "/api/scan"]:
                response = httpx.post(base + endpoint, json={}, timeout=10, trust_env=False)
                response.raise_for_status()
            return 0 if asyncio.run(check(base)) else 1
        finally:
            proc.terminate()
            proc.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
