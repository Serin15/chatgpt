"""Acceptance regressions for defects reproduced on 2a5d0d3 before implementation."""

import asyncio
import json

import httpx
import pytest

from app.ai_research import AIConfig
from app.announcements import inspect_contract
from app.assets import Assets
from app.news import canonical_url
from app.providers import ProviderError, Providers
from tests.conftest import ADDRESS
from tests.test_ai_research import CONTENT, answer, make_engine
from tests.test_announcements import document
from tests.test_assets import cg_asset
from tests.test_providers import pair


def test_one_invalid_pool_does_not_hide_a_valid_pool(settings):
    async def run():
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[None, pair()]))
        )
        providers = Providers(settings, client)
        try:
            assert (await providers.market(ADDRESS)).address == ADDRESS
        finally:
            await providers.close()

    asyncio.run(run())


def test_malformed_high_liquidity_pool_does_not_hide_valid_lower_pool(settings):
    async def run():
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200, json=[pair(liquidity=90000, marketCap="invalid"), pair(liquidity=50000)]
                )
            )
        )
        providers = Providers(settings, client)
        try:
            assert (await providers.market(ADDRESS)).liquidity_usd == 50000
        finally:
            await providers.close()

    asyncio.run(run())


def test_one_invalid_profile_does_not_stop_discovery(settings):
    async def run():
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json=[None, {"chainId": "solana", "tokenAddress": ADDRESS}]
                )
            )
        )
        providers = Providers(settings, client)
        try:
            assert await providers.discover() == [ADDRESS]
        finally:
            await providers.close()

    asyncio.run(run())


def test_one_invalid_catalog_item_does_not_discard_valid_market(store):
    async def run():
        assets = Assets(
            store,
            httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(200, json=[None, cg_asset()])
                )
            ),
        )
        try:
            assert (await assets.refresh())["state"] == "ok"
            assert assets.get("bitcoin")
        finally:
            await assets.close()

    asyncio.run(run())


def test_url_parameter_order_does_not_duplicate_news():
    assert canonical_url("https://example.org/story?b=2&a=1&utm_source=x") == canonical_url(
        "https://example.org/story?a=1&b=2"
    )


def test_truncated_ollama_generation_is_not_accepted_as_complete(store):
    async def run():
        research, engine = make_engine(
            store,
            lambda r: httpx.Response(
                200,
                json={
                    "done": True,
                    "done_reason": "length",
                    "message": {"content": json.dumps(answer())},
                },
            ),
        )
        try:
            with pytest.raises(ProviderError):
                await engine.generate(
                    AIConfig(provider="ollama", model="test-model"),
                    {"sources": [{"id": "D1", "content": CONTENT}]},
                )
        finally:
            await engine.close()
            await research.close()

    asyncio.run(run())


def test_plain_text_testnet_contract_is_not_mainnet_evidence():
    parsed = document(f"<main><p>Solana devnet contract {ADDRESS}</p></main>")
    assert not inspect_contract(parsed, "solana", ADDRESS)["chain_supported"]


def test_testnet_section_does_not_approve_a_mainnet_token():
    parsed = document(
        f"<main><h2>Testnet</h2><table><tr><td>Solana</td><td>{ADDRESS}</td></tr></table></main>"
    )
    assert not inspect_contract(parsed, "solana", ADDRESS)["chain_supported"]


def test_news_retains_general_asset_association_when_dex_search_fails(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.test_assets import FixtureAssets
    from tests.test_news import FixtureNews, NewsFixtureProviders, article

    class News(FixtureNews):
        async def feed(self, topic):
            return (
                [article("claude", "Claude launches a Bitcoin crypto research tool")]
                if topic == "claude"
                else []
            )

    class Provider(NewsFixtureProviders):
        async def search(self, query):
            raise ProviderError("Fixture DEX unavailable")

    with TestClient(
        create_app(
            settings, Provider(), run_scanner=False, news_factory=News, assets_factory=FixtureAssets
        )
    ) as client:
        client.post("/api/assets/refresh")
        client.post("/api/news/refresh")
        items = client.get("/api/news").json()
        assert any(m["market"]["address"] == "asset:bitcoin" for m in items[0]["matches"])
