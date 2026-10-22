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

        async def news_health_details(page):
            await ready(page)
            await page.evaluate("""() => {
                state.status.news.topics.decrypt = {state:'error', at:new Date().toISOString(), error:'Fixture news proxy blocked'};
                renderHealth();
            }""")
            await page.locator("#connection").click()
            await expect(page.locator("#health-details")).to_contain_text(
                "news_decrypt", timeout=1000
            )
            await expect(page.locator("#health-details")).to_contain_text(
                "Fixture news proxy blocked", timeout=1000
            )

        async def stale_health_details(page):
            await ready(page)
            await page.evaluate("""() => {
                state.status.providers.dex = {state:'ok', at:new Date(Date.now()-360000).toISOString()};
                renderHealth();
            }""")
            await expect(page.locator("#section-alerts")).to_contain_text("dex · date vechi")
            await page.locator("#connection").click()
            await expect(page.locator("#health-components")).to_contain_text("dex: eroare / date vechi", timeout=1000)
            await expect(page.locator("#health-components")).not_to_contain_text("dex: ok")

        async def worker_health_details(page):
            await ready(page)
            await page.evaluate("""() => {
                state.status.workers = {scanner:{state:'error', started_at:new Date().toISOString(),
                    error:'Explicit fixture worker failure', restarts:2}};
                renderHealth();
            }""")
            await expect(page.locator("#section-alerts")).to_contain_text("scanner")
            await page.locator("#connection").click()
            await expect(page.locator("#health-components")).to_contain_text("Explicit fixture worker failure", timeout=1000)
            await expect(page.locator("#health-components")).to_contain_text("worker_scanner: eroare")

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

        async def health_navigation(page):
            await ready(page)
            await page.evaluate("""() => {
                state.status.routed_quotes = {state:'partial', at:new Date().toISOString(),
                    errors:['Rejected: Verificările de securitate sunt expirate.']};
                renderHealth();
            }""")
            for name in ["news", "market", "scanner", "portfolio", "journal", "sources",
                         "advanced", "overview", "opportunities"]:
                await page.locator("#connection").click()
                await expect(page.locator("#health-details")).to_be_visible()
                await page.locator(f'.nav-item[data-page="{name}"]').click()
                await expect(page.locator("#health-details")).to_be_hidden(timeout=1000)
                await expect(page.locator("#connection")).to_have_attribute("aria-expanded", "false")
                await expect(page.locator(f"#view-{name}")).to_be_in_viewport()
                await expect(page.locator("#section-alerts")).to_contain_text("routed_quotes")

        async def health_panel_bounds(page):
            await ready(page)
            await page.evaluate("""() => {
                state.status.providers = Object.fromEntries(Array.from({length:60}, (_,i) =>
                    ['fixture_source_' + i, {state:'error', at:new Date().toISOString(),
                        error:'Explicit fixture failure; preserve source details'}]));
                renderHealth();
            }""")
            await page.locator("#connection").click()
            for width, height in [(1440, 1000), (390, 844)]:
                await page.set_viewport_size({"width": width, "height": height})
                box = await page.locator("#health-details").bounding_box()
                assert box["height"] <= height / 2 + 1, box
                assert await page.locator("#health-components").evaluate(
                    "n => n.scrollHeight > n.clientHeight && getComputedStyle(n).overflowY === 'auto'"
                ), "Long component details must scroll within the panel"
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            await expect(page.locator("#health-details")).to_contain_text("fixture_source_59")

        async def health_close_and_refresh(page):
            await ready(page)
            await page.locator("#connection").click()
            await page.locator("#health-details").get_by_role("button", name="Închide").click(timeout=1000)
            await expect(page.locator("#health-details")).to_be_hidden()
            await expect(page.locator("#connection")).to_have_attribute("aria-expanded", "false")
            await page.evaluate("renderHealth()")
            await expect(page.locator("#health-details")).to_be_hidden()
            await page.locator("#connection").click()
            await page.evaluate("renderHealth()")
            await expect(page.locator("#health-details")).to_be_visible()
            await expect(page.locator("#connection")).to_have_attribute("aria-expanded", "true")
            await page.locator("#connection").click()
            await expect(page.locator("#health-details")).to_be_hidden()

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

        async def stories_without_ai(page):
            original = await (await page.request.get(base + "/api/opportunities/narratives")).json()
            candidate = (await (await page.request.get(base + "/api/opportunities")).json())[
                "items"
            ][0]
            original.update(enabled=False, ai_configured=False)
            original["story_discovery"] = {
                "tracked_contracts": 2,
                "states": {"resolved_pool": 1, "market_unavailable": 1},
            }
            original["stories"]["items"] = [
                {
                    "title": "Explicit document fixture without AI",
                    "url": "https://solana.com/fixture",
                    "publisher_reported": "Isolated fixture",
                    "published_at": candidate["discovered_at"],
                    "first_seen_at": candidate["discovered_at"],
                    "document_state": "read",
                    "contracts": [
                        {
                            "association": "exact_contract_document_mention",
                            "contract": candidate["contract"],
                            "candidate_id": candidate["id"],
                            "eligible": True,
                        }
                    ],
                }
            ]
            await page.route("**/api/opportunities/narratives", lambda r: r.fulfill(json=original))
            await ready(page)
            await expect(page.locator("#engine-narratives")).to_contain_text(
                "Explicit document fixture without AI"
            )
            await expect(page.locator("#engine-narratives")).to_contain_text("emitent neconfirmat")
            await expect(page.locator("#engine-narratives")).to_contain_text(
                "piață indisponibilă 1"
            )
            await (
                page.locator("#engine-narratives")
                .get_by_role("button", name="Cercetează tokenul")
                .click()
            )
            await expect(page.locator("#engine-detail")).to_contain_text(candidate["contract"])

        async def future_protocol(page):
            await ready(page)
            await page.wait_for_function("() => opportunityView.daily !== null")
            await page.evaluate("""() => {
              const data = structuredClone(opportunityView.daily);
              const s = {experiments:3,evaluated:1,mean_net_pnl_usd:'-7',unresolved_or_unavailable:2};
              data.forward_evaluation = {protocols:{99:{declared_at:'2026-10-21T00:00:00Z',test_from:'2026-10-22T00:00:00Z',state:'test_not_started'}},
                models:{jupiter_quotes:{300:{99:{development:{all_first_evaluations:s,selected_at_first_evaluation:s,control_excluding_selected:{...s,evaluated:0,mean_net_pnl_usd:null}}}}}}};
              renderDailyResearch(data);
            }""")
            panel = page.locator(".forward-evaluation")
            await page.locator("#engine-daily-panel > summary").click()
            await panel.locator("summary").click()
            await expect(panel).to_contain_text("Testul nu a început")
            await expect(panel).to_contain_text("1 / 3")
            await expect(panel).to_contain_text("0 / 3")
            await expect(panel).to_contain_text("-7")
            await expect(panel).to_contain_text("nu demonstrează profitabilitatea")
            await page.set_viewport_size({"width":390,"height":844})
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")

        async def daily_race_and_export(page):
            await ready(page)
            await page.wait_for_function("() => opportunityView.daily !== null")
            original = await page.evaluate("opportunityView.daily")
            started = asyncio.Event()

            async def reports(route):
                day = parse_qs(urlsplit(route.request.url).query)["day"][0]
                if day == "2026-01-01":
                    started.set()
                    await asyncio.sleep(0.35)
                value = json.loads(json.dumps(original))
                value["day_utc"] = day
                await route.fulfill(json=value)

            await page.route("**/api/opportunities/daily?*", reports)
            await page.locator("#engine-daily-panel > summary").click()
            await page.locator("#engine-daily-day").fill("2026-01-01")
            await page.locator("#engine-daily-day").dispatch_event("change")
            await asyncio.wait_for(started.wait(), timeout=2)
            await page.locator("#engine-daily-day").fill("2026-01-02")
            await page.locator("#engine-daily-day").dispatch_event("change")
            await expect(page.locator("#engine-daily h3").first).to_have_text(
                "Descoperiri 2026-01-02 UTC"
            )
            await page.wait_for_timeout(500)
            await expect(page.locator("#engine-daily h3").first).to_have_text(
                "Descoperiri 2026-01-02 UTC"
            )
            async with page.expect_download() as info:
                await page.locator("#engine-daily-export").click()
            download = await info.value
            content = json.loads(Path(await download.path()).read_text())
            assert content["day_utc"] == "2026-01-02"

        async def daily_failure_isolated(page):
            await ready(page)
            await page.wait_for_function("() => opportunityView.daily !== null")
            original_day = await page.evaluate("opportunityView.daily.day_utc")
            await page.route(
                "**/api/opportunities/daily?*",
                lambda r: r.fulfill(status=503, json={"detail": "Fixture report unavailable"}),
            )
            await page.locator("#engine-daily-panel > summary").click()
            await page.locator("#engine-daily-day").fill("2026-01-01")
            await page.locator("#engine-daily-day").dispatch_event("change")
            await expect(page.locator("#engine-errors")).to_contain_text("Bilanț zilnic")
            await expect(page.locator("#engine-daily h3").first).to_contain_text(original_day)
            await expect(page.locator("#engine-daily-export")).to_be_disabled()
            await expect(page.locator("#engine-rows tr")).to_have_count(1)

        async def daily_mobile(page):
            await page.set_viewport_size({"width": 390, "height": 844})
            await ready(page)
            await page.wait_for_function("() => opportunityView.daily !== null")
            await page.locator("#engine-daily-panel > summary").click()
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")

        async def market_reference_evidence(page):
            await ready(page)
            await page.evaluate("""() => renderEngineNarratives({items:[], enabled:false, stories:{items:[{
                title:'Explicit pool evidence fixture', url:'https://decrypt.co/fixture',
                publisher_reported:'Fixture', published_at:new Date().toISOString(),
                first_seen_at:new Date().toISOString(), document_state:'read',
                related_reports:[{publisher_reported:'Fixture A',url:'https://decrypt.co/fixture'},
                                 {publisher_reported:'Fixture B',url:'https://cointelegraph.com/fixture'}],
                contracts:[{association:'resolved_market_pair_reference', contract:'11111111111111111111111111111111',
                  payload:{market_reference:{reference_url:'https://dexscreener.com/solana/G2UuRbmVDzDFP4qyoBJrSKBXSi7d6V4bPP9tHPs36y4b',price_change_24h_reported_pct:2900}}}]
            }]}})""")
            root = page.locator("#engine-narratives")
            await expect(root).to_contain_text("Token identificat prin link de pool")
            await expect(root).to_contain_text("2900%")
            await expect(root).not_to_contain_text("blockchain neclar")
            await root.locator("details summary").click()
            await expect(root).to_contain_text("independență neconfirmată")
            await expect(root.get_by_role("link", name="Fixture B")).to_have_count(1)

        async def cohort_comparison_table(page):
            await ready(page)
            await page.wait_for_function("() => opportunityView.daily !== null")
            await page.locator("#engine-daily-panel > summary").click()
            await page.evaluate("""() => {
                const report = structuredClone(opportunityView.daily);
                const s={experiments:2,evaluated:1,unresolved_or_unavailable:1,mean_net_pnl_usd:'-2.00'};
                report.models.estimated_pool['300'].comparisons_by_policy_and_cohort={77:{test:{
                    all_first_evaluations:s,selected_at_first_evaluation:s,control_excluding_selected:s}}};
                renderDailyResearch(report);
            }""")
            panel = page.locator("#engine-daily .daily-comparisons").first
            await panel.locator("summary").click()
            await expect(panel).to_contain_text("5m · P77 · Test")
            await expect(panel).to_contain_text("1 / 2")
            await expect(panel).to_contain_text("-2,00")
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")

        async def price_comparison_table(page):
            await ready(page)
            await page.wait_for_function("() => opportunityView.daily !== null")
            await page.locator("#engine-daily-panel > summary").click()
            await page.evaluate("""() => {
                const report = structuredClone(opportunityView.daily);
                const s={planned:3,observed:1,unavailable_or_pending:2,mean_price_return_pct:'-90',
                         increase_at_least_100pct:0,decline_at_least_80pct:1};
                report.price_references={horizons:{300:{by_policy_and_cohort:{88:{test:{
                    all_first_evaluations:s,selected_at_first_evaluation:s,control_excluding_selected:s}}}}}};
                renderDailyResearch(report);
            }""")
            panel = page.locator(".price-reference-comparisons")
            await panel.locator("summary").click()
            await expect(panel).to_contain_text("5m · P88 · Test")
            await expect(panel).to_contain_text("1 / 3")
            await expect(panel).to_contain_text("-90%")
            await expect(panel).to_contain_text("Fără costuri")
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")

        async def usable_coverage(page):
            await ready(page)
            await page.evaluate("""async () => {
                const data = await (await fetch('/api/opportunities/coverage')).json();
                Object.assign(data.prospective_groups.alerts.entry,
                              {attempted:7,usable_price_observations:2,attempts_without_usable_price:5});
                renderEngineCoverage(data);
            }""")
            await expect(page.locator("#engine-coverage-summary")).to_contain_text("2 alerte")
            await page.locator("#engine-coverage-summary").evaluate(
                "n => n.parentElement.open = true"
            )
            await expect(page.locator("#engine-coverage")).to_contain_text(
                "2 cotații utilizabile / 7 încercări"
            )
            await expect(page.locator("#engine-coverage")).to_contain_text(
                "5 încercări fără preț utilizabil"
            )

        async def history_requests_are_sequential(page):
            gate, started = asyncio.Event(), asyncio.Event()
            heavy = []

            async def hold_day(route):
                started.set()
                await gate.wait()
                await route.continue_()

            page.on(
                "request",
                lambda r: (
                    heavy.append(urlsplit(r.url).path)
                    if urlsplit(r.url).path
                    in {"/api/opportunities/performance", "/api/opportunities/routes"}
                    else None
                ),
            )
            await page.route("**/api/opportunities/daily?*", hold_day)
            try:
                await page.goto(base)
                await expect(page.locator("#engine-rows tr")).to_have_count(1)
                await asyncio.wait_for(started.wait(), 3)
                assert not heavy, "History reports started concurrently: " + str(heavy)
            finally:
                gate.set()
            await page.wait_for_function("() => !opportunityView.loading && !state.loading")
            assert heavy == ["/api/opportunities/performance", "/api/opportunities/routes"]

        async def storage_capacity(page):
            await ready(page)
            await page.locator('.nav-item[data-page="journal"]').click()
            await page.locator("#storage-panel > summary").click()
            await page.locator("#storage-refresh").click()
            await expect(page.locator("#storage-status")).to_contain_text("research.sqlite3")
            await expect(page.locator("#storage-status")).to_contain_text("Arhivare automată: oprită")
            await expect(page.locator("#storage-status")).to_contain_text("KiB")
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")

        async def storage_failure(page):
            await ready(page)
            await page.route("**/api/storage", lambda r: r.fulfill(status=503, json={"detail": "Fixture storage unavailable"}))
            await page.locator('.nav-item[data-page="journal"]').click()
            await page.locator("#storage-panel > summary").click()
            await page.locator("#storage-refresh").click()
            await expect(page.locator("#storage-refresh")).to_be_enabled()
            await page.locator('.nav-item[data-page="opportunities"]').click()
            await expect(page.locator("#engine-rows tr")).to_have_count(1)

        async def bounded_monitoring(page):
            # UI-only synthetic counts; backend preservation uses real SQLite tests.
            await ready(page)
            await page.evaluate("""async () => {
                const coverage = await (await fetch('/api/opportunities/coverage')).json();
                coverage.monitoring = {dispatchable_due:5, paused_due:95, due:100, background_watch_hours:48};
                renderEngineCoverage(coverage);
            }""")
            await page.locator("#engine-coverage-summary").evaluate("n => n.parentElement.open = true")
            await expect(page.locator("#engine-coverage")).to_contain_text("5 reevaluări periodice scadente · 95 în pauză · total periodic înregistrat 100")
            value = await (await page.request.get(base + "/api/opportunities/1")).json()
            value["monitoring"] = {"state": "paused", "history_preserved": True}
            await page.route("**/api/opportunities/1", lambda r: r.fulfill(json=value))
            await page.evaluate("openOpportunity(1, false)")
            await expect(page.locator("#engine-detail")).to_contain_text("istoricul și rezultatele rămân accesibile")
            await expect(page.locator("#engine-detail")).to_contain_text("Prima descoperire")
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")

        async def cached_coverage_status(page):
            await ready(page)
            await page.evaluate("""async () => {
                const report = await (await fetch('/api/opportunities/coverage')).json();
                report.report_cache = {served_from_cache:true,calculated_at:'2020-01-01T00:00:00Z',
                    refresh:{state:'error',error:'ExplicitFixtureError'}};
                renderEngineCoverage(report);
            }""")
            await page.locator("#engine-coverage-summary").evaluate("n => n.parentElement.open = true")
            await expect(page.locator("#engine-coverage")).to_contain_text("date păstrate în cache")
            await expect(page.locator("#engine-coverage")).to_contain_text("2020")
            await expect(page.locator("#engine-coverage")).to_contain_text("Actualizare: eroare")
            await expect(page.locator("#engine-coverage")).to_contain_text("ExplicitFixtureError")

        async def mobile_workspace_navigation(page):
            await ready(page)
            await page.emulate_media(reduced_motion="reduce")
            await page.set_viewport_size({"width": 390, "height": 844})
            await page.locator("#navigation-toggle").click()
            await expect(page.locator("#workspace-navigation")).to_have_attribute("aria-modal", "true")
            assert await page.locator("#main-content").evaluate("n => n.inert")
            # Tab wraps inside the drawer, and Escape returns focus to its opener.
            await page.locator('.nav-item[data-page="sources"]').focus()
            await page.keyboard.press("Tab")
            await expect(page.locator(".brand")).to_be_focused()
            await page.keyboard.press("Escape")
            await expect(page.locator("#navigation-toggle")).to_be_focused()
            assert not await page.locator("#main-content").evaluate("n => n.inert")
            await page.locator("#mobile-more").click()
            await page.keyboard.press("Escape")
            await expect(page.locator("#mobile-more")).to_be_focused()
            for destination in ["market", "scanner", "journal", "advanced", "sources", "overview"]:
                await page.locator("#mobile-more").click()
                await page.locator(f'.nav-item[data-page="{destination}"]').click()
                await expect(page.locator(f"#view-{destination}")).to_be_visible()
                await expect(page.locator("#mobile-more")).to_have_attribute("aria-expanded", "false")
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            await page.locator('.mobile-dock [data-page="opportunities"]').click()
            await expect(page.locator('.mobile-dock [data-page="opportunities"]')).to_have_attribute("aria-current", "page")

        async def quick_filters_and_keyboard(page):
            await ready(page)
            await page.locator('[data-verdict="REJECT"]').click()
            await expect(page.locator("#engine-empty")).to_be_visible()
            await expect(page.locator("#engine-verdict")).to_have_value("REJECT")
            await expect(page.locator('[data-verdict="REJECT"]')).to_have_attribute("aria-pressed", "true")
            await page.locator("#engine-verdict").select_option("INVESTIGATE")
            await expect(page.locator("#engine-rows tr")).to_have_count(1)
            await expect(page.locator('[data-verdict="INVESTIGATE"]')).to_have_attribute("aria-pressed", "true")
            await page.locator("#candidate-title").click()
            await page.keyboard.press("/")
            await expect(page.locator("#engine-search")).to_be_focused()
            await page.keyboard.type("/")
            await expect(page.locator("#engine-search")).to_have_value("/")

        async def dossier_chart_and_unknowns(page):
            await ready(page)
            await page.evaluate("openOpportunity(1, false)")
            await expect(page.locator(".score-unknown").first).to_contain_text("Necunoscut")
            await expect(page.locator("#engine-detail")).to_contain_text("mai mare înseamnă mai riscant")
            observations = await page.evaluate("opportunityView.selection === 1")
            assert observations
            chart = page.locator("#engine-detail .engine-chart")
            await chart.focus()
            await page.keyboard.press("Home")
            first = await page.locator(".chart-readout strong").inner_text()
            await page.keyboard.press("End")
            last = await page.locator(".chart-readout strong").inner_text()
            assert first != last, (first, last)
            await expect(page.locator(".observed-chart")).to_contain_text("Extrema dintre observații rămân necunoscute")
            for width in [320, 390, 768, 1440]:
                await page.set_viewport_size({"width": width, "height": 900})
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), width

        async def chart_decline_and_gaps(page):
            await ready(page)
            await page.evaluate("""() => {
                const root = document.createElement('section'); root.id='chart-fixture'; document.body.append(root);
                engineChart([
                    {at:'2026-01-01T00:00:00Z',market:{price_usd:1}},
                    {at:'2026-01-01T00:01:00Z',market:null},
                    {at:'2026-01-01T00:02:00Z',market:{price_usd:0.5}}
                ], root);
            }""")
            path = page.locator("#chart-fixture path")
            assert (await path.get_attribute("d")).count("M") == 2
            assert "L" not in await path.get_attribute("d")
            assert await path.get_attribute("stroke") == "var(--red)"
            assert await page.locator("#chart-fixture circle").count() == 3

        async def close_dossier_during_refresh(page):
            await ready(page)
            await page.evaluate("openOpportunity(1, false)")
            gate, started = asyncio.Event(), asyncio.Event()

            async def hold(route):
                started.set()
                await gate.wait()
                await route.continue_()

            await page.route("**/api/opportunities/1", hold)
            try:
                await page.evaluate("void openOpportunity(1, false)")
                await asyncio.wait_for(started.wait(), 3)
                await page.locator(".dossier-close").click()
                await expect(page.locator("#engine-detail")).to_be_hidden()
            finally:
                gate.set()
            await page.wait_for_load_state("networkidle")
            await expect(page.locator("#engine-detail")).to_be_hidden()
            assert await page.evaluate("opportunityView.selection === null")

        async def stats_failure_is_explicit(page):
            await page.route("**/api/opportunities/performance", lambda r: r.fulfill(status=503, json={"detail":"Explicit fixture report unavailable"}))
            await page.goto(base)
            await expect(page.locator("#engine-stats")).to_have_attribute("aria-busy", "false")
            await expect(page.locator("#engine-stats")).to_contain_text("Raport indisponibil")
            await expect(page.locator("#engine-rows tr")).to_have_count(1)
            await expect(page.locator("#engine-section-errors")).to_be_visible()
            await expect(page.locator("#engine-section-errors")).to_contain_text("Performanță")
            await page.locator("#engine-status-panel > summary").click()
            await expect(page.locator("#engine-errors")).to_be_visible()
            await expect(page.locator("#engine-errors")).to_contain_text("Explicit fixture report unavailable")

        async def request_timeout_explains_recovery(page):
            await ready(page)
            # Accelerate only the request deadline; browser fetch uses an actually aborted signal.
            result = await page.evaluate("""async () => {
                const original = window.setTimeout;
                window.setTimeout = (fn, ms, ...args) => ms === 20000 ? (fn(), 0) : original(fn, ms, ...args);
                try { await api('/api/status'); return 'unexpected success'; }
                catch (error) { return error.message; }
                finally { window.setTimeout = original; }
            }""")
            assert "20 de secunde" in result and "Reîncearcă" in result, result

        async def activity_windows_keep_missing_values(page):
            await ready(page)
            await page.evaluate("""() => {
                const root=document.createElement('section');root.id='window-fixture';document.body.append(root);
                dossierActivity(root,{changes:{'5m':null,'15m':{price_change_pct:5,
                    liquidity_change_pct:-20,volume_5m_ratio:2,reported_buyers_change_pct:null,
                    baseline_at:'2026-01-01T00:00:00Z'}}});
            }""")
            panel = page.locator("#window-fixture")
            await expect(panel.locator(".activity-window").first).to_contain_text("Istoric insuficient")
            await expect(panel.locator(".activity-window").nth(1)).to_contain_text("-20.00%")
            await expect(panel.locator(".activity-window").nth(1)).to_contain_text("2×")
            await expect(panel.locator(".activity-window").nth(1)).to_contain_text("—")
            await expect(panel).to_contain_text("Extensie în ultima observație: date indisponibile")
            await page.set_viewport_size({"width": 320, "height": 844})
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")

        for name, fn in [
            ("candidate priority", layout),
            ("routed health", health),
            ("news source health details", news_health_details),
            ("stale source status is consistent in details", stale_health_details),
            ("worker failure has visible diagnostic details", worker_health_details),
            ("independent candidate loading", isolation),
            ("detail response race", detail_race),
            ("expanded evidence survives refresh", details_preserved),
            ("receipt failure isolation", receipts),
            ("browser back", browser_history),
            ("loaded pages survive refresh", pagination),
            ("component health details", health_details),
            ("health panel closes on every navigation", health_navigation),
            ("health panel has bounded desktop and mobile height", health_panel_bounds),
            ("health panel explicit close and refresh state", health_close_and_refresh),
            ("search response race", query_race),
            ("document stories without AI", stories_without_ai),
            ("future protocol, missing control and mobile layout", future_protocol),
            ("daily report race and JSON export", daily_race_and_export),
            ("daily failure preserves candidates", daily_failure_isolated),
            ("daily mobile layout", daily_mobile),
            ("pool references and repeated report evidence", market_reference_evidence),
            ("partitioned comparison and mobile layout", cohort_comparison_table),
            ("price references and mobile layout", price_comparison_table),
            ("usable prices separate from attempts", usable_coverage),
            ("live candidates before sequential history reports", history_requests_are_sequential),
            ("actual fixture database capacity and mobile layout", storage_capacity),
            ("storage failure preserves candidate workflow", storage_failure),
            ("bounded polling preserves visible history and raw totals on mobile", bounded_monitoring),
            ("cached coverage retains calculation date and refresh errors", cached_coverage_status),
            ("phone drawer focus, all destinations and return navigation", mobile_workspace_navigation),
            ("quick verdict filters and search keyboard shortcut", quick_filters_and_keyboard),
            ("dossier observed chart, unknown scores and responsive widths", dossier_chart_and_unknowns),
            ("declining chart retains gaps and isolated observations", chart_decline_and_gaps),
            ("closed dossier cannot reopen after a delayed response", close_dossier_during_refresh),
            ("failed statistics stop loading and preserve candidate access", stats_failure_is_explicit),
            ("activity windows preserve missing evidence without invented zeros", activity_windows_keep_missing_values),
            ("request deadline explains timeout and recovery in Romanian", request_timeout_explains_recovery),
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
