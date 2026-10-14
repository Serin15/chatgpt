"""Audit probes against isolated fixtures; does not contact providers or change user data.

Run from the repository: .venv/bin/python docs/audit/reproduce_backend.py
The assertions reproduce the audited behavior, including known defects. They are
diagnostic evidence, not acceptance tests proving the application bug-free.
Historical v0.2 probe: run on commit 307376d. Current acceptance tests live in tests/.
"""

import asyncio
import json
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx
from fastapi.testclient import TestClient

from app import paper
from app.assets import Assets, parse_asset
from app.config import Settings
from app.desktop import our_app
from app.main import create_app
from app.models import solana_address
from app.news import News, parse_rss
from app.providers import Providers
from app.store import Store
from tests.conftest import ADDRESS, old_signal
from tests.test_assets import FixtureAssets, cg_asset
from tests.test_news import FixtureNews, NewsFixtureProviders, rss


def emit(case, **observed):
    print(json.dumps({"case": case, **observed}, ensure_ascii=False))


def base58_address(value):
    raw = value.to_bytes(32, "big")
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    encoded = ""
    while value:
        value, remainder = divmod(value, 58)
        encoded = alphabet[remainder] + encoded
    result = "1" * (len(raw) - len(raw.lstrip(b"\x00"))) + encoded
    return solana_address(result)


def news_probes(settings):
    store = Store(settings)
    news = News(store, None)
    try:
        first = parse_rss(rss("Protocol launches a new crypto token"), "crypto")[0]
        first_id = news.save(first)
        row = next(n for n in news.listing() if n["id"] == first_id)
        assert row["category"] == "ecosystem"
        emit(
            "launch_classification", title=row["title"], actual=row["category"], expected="launches"
        )

        duplicate = parse_rss(rss(first["title"]), "launches")[0]
        news.save(duplicate)
        matching = [n for n in news.listing() if n["url"] == first["url"]]
        assert len(matching) == 2
        emit("cross_topic_duplicates", identical_url_entries=len(matching))

        old = datetime.fromtimestamp(time.time() - 3 * 86400, UTC).isoformat()
        with store.connect() as db:
            db.execute("UPDATE news SET published_at=?, first_seen_at=?", (old, old))
        aged = news.listing()
        assert len(aged) == 2 and all(not n["seen"] for n in aged)
        emit("aged_news_still_listed", age_days=3, entries=len(aged), unread=True)
    finally:
        asyncio.run(news.close())


async def market_probes(settings):
    store = Store(settings)

    def handler(request):
        if "coinbase" in request.url.host:
            return httpx.Response(
                200,
                json={
                    "bids": [["99", "100", 1]],
                    "asks": [["100", "100", 1]],
                    "time": datetime.now(UTC).isoformat(),
                },
            )
        return httpx.Response(200, json=[cg_asset()])

    assets = Assets(store, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        old = parse_asset(cg_asset())
        old |= {
            "asset_id": "old-asset",
            "address": "asset:old-asset",
            "name": "Old fixture",
            "source_updated_at": "2020-01-01T00:00:00+00:00",
            "observed_at": "2020-01-01T00:00:00+00:00",
        }
        assets.save(old)
        status = await assets.refresh()
        assert status["state"] == "ok"
        assert any(a["asset_id"] == "old-asset" for a in assets.listing())
        emit("stale_catalog_entry", catalog_state=status["state"], stale_asset_retained=True)

        quote = await assets.quote("bitcoin")
        assert quote["price_usd"] == 99.5 and quote["source"] == "CoinGecko"
        emit(
            "mixed_price_provenance",
            reported_source=quote["source"],
            actual_price_source=quote["book"]["source"],
            price=quote["price_usd"],
        )

        fill = paper.fill("buy", "50", quote, settings)
        spread = Decimal("1") - Decimal("99") / Decimal("100")
        assert Decimal(fill["price_impact"]) == spread
        emit(
            "spread_reported_as_impact",
            reported=fill["price_impact"],
            actual_metric="bid/ask spread",
        )

        breakeven = paper.break_even(fill, quote, settings)
        growth = Decimal(breakeven["break_even_rise_pct"]) / 100
        future = deepcopy(quote)
        future["price_usd"] = str(Decimal(str(quote["price_usd"])) * (1 + growth))
        future["book"]["bid"] = str(Decimal(quote["book"]["bid"]) * (1 + growth))
        future["book"]["ask"] = str(Decimal(quote["book"]["ask"]) * (1 + growth))
        exit_at_threshold = paper.fill("sell", fill["quantity"], future, settings)
        pnl = Decimal(fill["cash_change"]) + Decimal(exit_at_threshold["cash_change"])
        assert pnl < Decimal("-.25")
        actual_growth = (
            Decimal(breakeven["break_even_price_estimate"]) / Decimal(quote["book"]["bid"]) - 1
        ) * 100
        emit(
            "book_break_even_underestimated",
            reported_rise_pct=breakeven["break_even_rise_pct"],
            required_rise_pct_with_constant_relative_spread=str(actual_growth),
            pnl_at_reported_threshold=str(pnl),
        )
    finally:
        await assets.close()


def malformed_provider_probe(settings):
    def factory(store):
        def handler(request):
            if request.url.path.endswith("/tickers"):
                return httpx.Response(200, json={"tickers": [None]})
            if request.url.path.endswith("/bitcoin"):
                return httpx.Response(
                    200, json={"id": "bitcoin", "links": {"repos_url": ["bad-shape"]}}
                )
            return httpx.Response(200, json=[cg_asset()])

        return Assets(store, httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    app = create_app(settings, NewsFixtureProviders(), False, FixtureNews, factory)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post("/api/assets/refresh").status_code == 200
        venues = client.get("/api/assets/bitcoin/venues")
        profile = client.get("/api/assets/bitcoin/profile")
        assert venues.status_code == 500 and profile.status_code == 500
        assert client.get("/api/portfolio?account=news").json()["cash"] == "500"
        emit(
            "malformed_metadata",
            venues_status=venues.status_code,
            profile_status=profile.status_code,
            balances_unchanged=True,
        )


def held_detail_probe(settings):
    app = create_app(settings, NewsFixtureProviders(), False, FixtureNews, FixtureAssets)
    with TestClient(app) as client:
        assert client.post("/api/scan").is_success
        store = app.state.service.store
        signal = old_signal(store, store.latest(ADDRESS))
        buy = client.post(
            "/api/paper/buy", json={"address": ADDRESS, "amount_usd": "5", "signal_id": signal}
        )
        assert buy.is_success
        for i in range(2, 103):
            store.add_token(base58_address(i), "explicit_audit_fixture")
        listing = client.get("/api/tokens").json()
        detail = client.get(f"/api/tokens/{ADDRESS}")
        assert len(listing) == 100 and all(t["address"] != ADDRESS for t in listing)
        assert detail.status_code == 404
        portfolio = client.get("/api/portfolio").json()
        assert portfolio["positions"][0]["closed_at"] is None
        exit_response = client.post(f"/api/paper/positions/{buy.json()['position_id']}/sell")
        assert exit_response.is_success
        emit(
            "held_token_evicted_from_detail",
            listed=len(listing),
            detail_status=detail.status_code,
            position_preserved=True,
            separate_exit_still_works=True,
        )


def host_probe(settings):
    app = create_app(settings, NewsFixtureProviders(), False, FixtureNews, FixtureAssets)
    with TestClient(app, base_url="http://untrusted-host.example") as client:
        response = client.post(
            "/api/scan",
            headers={"origin": "http://untrusted-host.example", "sec-fetch-site": "same-origin"},
        )
        assert response.status_code == 200
        emit(
            "host_not_restricted",
            request_status=response.status_code,
            real_browser_rebinding_tested=False,
        )


def chronology_schema_probe(settings):
    async def candidates():
        payload = {
            "pairs": [
                {
                    "chainId": "solana",
                    "baseToken": {"address": ADDRESS, "name": "Claude fixture", "symbol": "CLAUDE"},
                    "pairCreatedAt": "1760000000000",
                    "priceUsd": "1",
                    "liquidity": {"usd": 50000},
                }
            ]
        }
        provider = Providers(
            settings,
            httpx.AsyncClient(
                transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
            ),
        )
        try:
            return await provider.search("claude")
        finally:
            await provider.close()

    matches = asyncio.run(candidates())
    assert isinstance(matches[0]["pool_created_at"], str)
    app = create_app(settings, NewsFixtureProviders(), False, FixtureNews, FixtureAssets)
    with TestClient(app, raise_server_exceptions=False) as client:
        news = app.state.service.news
        news_id = news.save(parse_rss(rss("Claude reports a crypto launch"), "claude")[0])
        news.save_matches(news_id, matches)
        assert client.get("/api/news").status_code == 500
        assert client.get("/api/portfolio?account=news").is_success
        emit("untyped_pool_date_breaks_feed", news_status=500, portfolio_status=200)


def desktop_schema_probe():
    with patch("app.desktop.httpx.get", return_value=httpx.Response(200, json=[])):
        try:
            our_app("http://127.0.0.1:8000")
        except AttributeError:
            emit(
                "unrelated_service_breaks_launcher",
                status_payload="JSON array",
                exception="AttributeError",
            )
        else:
            raise AssertionError("Audited launcher defect no longer reproduces")


def concurrent_exit_probe(settings):
    app = create_app(settings, NewsFixtureProviders(), False, FixtureNews, FixtureAssets)
    with TestClient(app) as client:
        client.post("/api/scan")
        store = app.state.service.store
        snapshot = store.latest(ADDRESS)
        entry = paper.buy(store, snapshot, old_signal(store, snapshot), "5", settings)
        cash_before = Decimal(store.portfolio()["cash"])

        def close_once(_):
            try:
                return paper.sell(store, entry["position_id"], snapshot, settings)
            except paper.Rejected:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            filled = [r for r in pool.map(close_once, range(8)) if r is not None]
        assert len(filled) == 1
        portfolio = store.portfolio()
        assert Decimal(portfolio["cash"]) == cash_before + Decimal(filled[0]["cash_change"])
        assert len(portfolio["orders"]) == 2
        assert Decimal(portfolio["cash"]) == store.initial_balance + Decimal(filled[0]["pnl"])
        emit("concurrent_exit_integrity", attempts=8, fills=1, cash_conservation=True)


def main():
    with tempfile.TemporaryDirectory(prefix="pulse-audit-") as folder:
        root = Path(folder)
        news_probes(Settings(data_dir=root / "news"))
        asyncio.run(market_probes(Settings(data_dir=root / "market")))
        malformed_provider_probe(Settings(data_dir=root / "schema"))
        held_detail_probe(Settings(data_dir=root / "holdings"))
        host_probe(Settings(data_dir=root / "host"))
        chronology_schema_probe(Settings(data_dir=root / "chronology"))
        desktop_schema_probe()
        concurrent_exit_probe(Settings(data_dir=root / "concurrency"))


if __name__ == "__main__":
    main()
