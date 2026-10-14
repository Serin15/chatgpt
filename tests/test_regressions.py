import asyncio
import json
import time
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal as D
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app import __version__, instance_id
from app.assets import Assets, parse_asset
from app.desktop import our_app
from app.main import create_app
from app.news import News, parse_rss
from app.paper import break_even, fill
from tests.conftest import ADDRESS, old_signal
from tests.test_assets import FixtureAssets, cg_asset
from tests.test_news import FixtureNews, NewsFixtureProviders, rss


def test_book_break_even_recovers_all_costs(settings):
    asset = parse_asset(cg_asset())
    asset["price_usd"] = 99.5
    asset["book"] = {"bid": "99", "ask": "100", "bid_size": "100", "ask_size": "100"}
    entry = fill("buy", "50", asset, settings)
    threshold = break_even(entry, asset, settings)
    growth = D(threshold["break_even_rise_pct"]) / 100
    future = deepcopy(asset)
    future["price_usd"] = str(D("99.5") * (1 + growth))
    future["book"]["bid"] = str(D("99") * (1 + growth))
    future["book"]["ask"] = str(D("100") * (1 + growth))
    outcome = fill("sell", entry["quantity"], future, settings)
    assert abs(D(outcome["cash_change"]) - D("50")) < D("1e-20")
    assert D("2.23") < D(threshold["break_even_rise_pct"]) < D("2.24")
    assert entry["price_impact"] is None and entry["spread_fraction"] == "0.01"


@pytest.mark.parametrize("payload", [[], None, "another app", {"app_id": "other"}])
def test_unrelated_status_does_not_crash_launcher(payload):
    with patch("app.desktop.httpx.get", return_value=httpx.Response(200, json=payload)):
        assert not our_app("http://127.0.0.1:8000")


def test_launcher_requires_matching_version_and_data_directory(settings):
    payload = {
        "app_id": "pulse_crypto_research",
        "version": __version__,
        "instance_id": instance_id(settings.data_dir),
    }
    with patch("app.desktop.Settings.from_environment", return_value=settings):
        assert our_app("unused", payload)
        assert not our_app("unused", payload | {"version": "0.2.0"})
        assert not our_app("unused", payload | {"instance_id": "another-folder"})


def test_asset_watchlist_search_and_concurrent_limit(settings):
    app = create_app(settings, NewsFixtureProviders(), False, FixtureNews, FixtureAssets)
    with TestClient(app) as client:
        assert client.get("/api/assets/search?q=bitcoin").json()[0]["asset_id"] == "bitcoin"
        assert client.post("/api/assets/watch", json={"asset_id": "bitcoin"}).is_success
        assert client.get("/api/assets/bitcoin").json()["asset"]["watch"]
        client.post("/api/assets/bitcoin/unwatch", json={})
        assert not client.get("/api/assets/bitcoin").json()["asset"]["watch"]
        assets = app.state.service.assets
        with assets.store.connect() as db:
            for i in range(19):
                db.execute(
                    "INSERT INTO asset_watch VALUES(?,?)",
                    (f"fixture-{i}", datetime.now(UTC).isoformat()),
                )

        async def check_limit():
            async def quoted(asset_id):
                await asyncio.sleep(0)
                return {"asset_id": asset_id}

            assets.quote = quoted
            return await asyncio.gather(
                assets.watch("one"), assets.watch("two"), return_exceptions=True
            )

        from app.providers import ProviderError

        results = asyncio.run(check_limit())
        assert sum(isinstance(r, ProviderError) for r in results) == 1
        with assets.store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM asset_watch").fetchone()[0] == 20


@pytest.mark.parametrize("verb", ["launch", "launches", "launched", "launching"])
def test_launch_forms_and_cross_topic_dedup(store, verb):
    news = News(store, None)
    try:
        first = news.save(parse_rss(rss(f"Project {verb} a new crypto token"), "crypto")[0])
        second = news.save(parse_rss(rss(f"Project {verb} a new crypto token"), "launches")[0])
        rows = news.listing()
        assert first == second and len(rows) == 1
        assert rows[0]["category"] == "launches"
        assert set(rows[0]["topics"]) == {"crypto", "launches"}
        with store.connect() as db:
            old = datetime.fromtimestamp(time.time() - 86400 * 3, UTC).isoformat()
            db.execute("UPDATE news SET published_at=?,first_seen_at=?", (old, old))
        assert news.listing() == []
        assert len(news.listing(archive=True)) == 1
    finally:
        asyncio.run(news.close())


def test_legacy_news_migration_preserves_ids_context_and_read_state(store):
    with store.connect() as db:
        db.executescript("""CREATE TABLE news(id INTEGER PRIMARY KEY,fingerprint TEXT UNIQUE,topic TEXT,title TEXT,url TEXT,publisher TEXT,published_at TEXT,first_seen_at TEXT);
        CREATE TABLE news_matches(news_id INTEGER,address TEXT,market TEXT,first_matched_at TEXT,updated_at TEXT,PRIMARY KEY(news_id,address));
        CREATE TABLE news_read(news_id INTEGER PRIMARY KEY,at TEXT);""")
        now = datetime.now(UTC).isoformat()
        for i, topic in [(1, "crypto"), (2, "launches")]:
            db.execute(
                "INSERT INTO news VALUES(?,?,?,?,?,?,?,?)",
                (
                    i,
                    str(i),
                    topic,
                    "Crypto launch",
                    "https://example.org/same",
                    "Fixture",
                    now,
                    now,
                ),
            )
        db.execute(
            "INSERT INTO news_matches VALUES(?,?,?,?,?)",
            (
                2,
                ADDRESS,
                json.dumps({"address": ADDRESS, "pool_created_at": "1760000000000"}),
                now,
                now,
            ),
        )
        db.execute("INSERT INTO news_read VALUES(?,?)", (2, now))
        db.execute(
            "INSERT INTO signals VALUES(?,?,?,?,?)",
            (
                1,
                ADDRESS,
                now,
                1,
                json.dumps({"news_context": {"id": 2, "title": "Original saved context"}}),
            ),
        )
    news = News(store, None)
    try:
        assert len(news.listing()) == 1 and news.listing()[0]["seen"]
        assert news.context(2, ADDRESS)["id"] == 1
        with store.connect() as db:
            assert (
                json.loads(db.execute("SELECT evidence FROM signals").fetchone()[0])[
                    "news_context"
                ]["id"]
                == 2
            )
        news.replace_matches(1, [])
    finally:
        asyncio.run(news.close())
    again = News(store, None)
    try:
        assert again.listing()[0]["matches"] == []
    finally:
        asyncio.run(again.close())


def test_malformed_market_metadata_is_controlled_and_book_provenance(store):
    async def run():
        def handler(request):
            if request.url.path.endswith("/tickers"):
                return httpx.Response(200, json={"tickers": [None]})
            if request.url.path.endswith("/bitcoin"):
                return httpx.Response(200, json={"id": "bitcoin", "links": {"repos_url": ["bad"]}})
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
            assert await assets.venues("bitcoin") == []
            from app.providers import ProviderError

            with pytest.raises(ProviderError):
                await assets.profile("bitcoin")
            quote = await assets.quote("bitcoin")
            assert (
                quote["price_source"].startswith("Coinbase")
                and quote["volume_source"] == "CoinGecko"
            )
            assert quote["price_usd"] == 99.5
            assets.save(parse_asset(cg_asset()))
            assert assets.get("bitcoin")["book"] and assets.get("bitcoin")["price_usd"] == 99.5
        finally:
            await assets.close()

    asyncio.run(run())


def test_cached_old_asset_is_explicitly_stale(store):
    assets = Assets(store)
    try:
        asset = parse_asset(cg_asset())
        asset["source_updated_at"] = "2020-01-01T00:00:00+00:00"
        assets.save(asset)
        assert assets.listing()[0]["freshness"]["fresh"] is False
    finally:
        asyncio.run(assets.close())


def test_held_detail_survives_catalog_limit_and_unknown_host_blocked(settings):
    app = create_app(settings, NewsFixtureProviders(), False, FixtureNews, FixtureAssets)
    with TestClient(app) as client:
        client.post("/api/scan")
        store = app.state.service.store
        signal = old_signal(store, store.latest(ADDRESS))
        order = client.post(
            "/api/paper/buy", json={"address": ADDRESS, "amount_usd": "5", "signal_id": signal}
        )
        assert order.is_success
        for i in range(101):
            store.add_token("isolated-fixture-" + str(i), "fixture")
        assert client.get("/api/tokens/" + ADDRESS).is_success
        assert any(t["address"] == ADDRESS for t in client.get("/api/tokens").json())
        assert (
            client.post(
                "/api/scan",
                headers={"host": "untrusted.example", "origin": "http://untrusted.example"},
            ).status_code
            == 400
        )
