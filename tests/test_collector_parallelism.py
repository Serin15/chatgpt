"""Independent providers overlap; budgets, precedence and cancellation stay strict."""

import asyncio

import pytest

from app.errors import ProviderError
from tests.conftest import market
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import seed


def test_market_sources_overlap_without_changing_precedence_or_request_count(
    client_engine, monkeypatch
):
    _, engine = client_engine
    candidate, _, _ = seed(engine)
    calls = []

    async def run():
        pool_started, gecko_started = asyncio.Event(), asyncio.Event()

        async def pool(_, rows):
            calls.append("pool")
            pool_started.set()
            await asyncio.wait_for(gecko_started.wait(), 0.5)
            return {(candidate["pool"], candidate["contract"]): {"source": "pool", "price_usd": 1}}

        async def gecko(_, rows):
            calls.append("gecko")
            gecko_started.set()
            await asyncio.wait_for(pool_started.wait(), 0.5)
            return {(candidate["pool"], candidate["contract"]): {"source": "gecko", "price_usd": 2}}

        monkeypatch.setattr("app.opportunities.pool_markets", pool)
        monkeypatch.setattr("app.opportunities.gecko_markets", gecko)
        errors = []
        rows = [row async for row in engine.market_candidates([candidate], errors)]
        assert rows[0][1] == {"source": "gecko", "price_usd": 2}
        assert not errors

    asyncio.run(run())
    assert sorted(calls) == ["gecko", "pool"]


@pytest.mark.parametrize("failed", ["pool", "gecko"])
def test_failed_provider_does_not_discard_independent_valid_source(
    client_engine, monkeypatch, failed
):
    _, engine = client_engine
    c, _, _ = seed(engine)
    value = market(c["contract"]).model_dump()

    async def pool(*args):
        if failed == "pool":
            raise ProviderError("Explicit fixture outage")
        return {(c["pool"], c["contract"]): value}

    async def gecko(*args):
        if failed == "gecko":
            raise ProviderError("Explicit fixture outage")
        return {(c["pool"], c["contract"]): value}

    monkeypatch.setattr("app.opportunities.pool_markets", pool)
    monkeypatch.setattr("app.opportunities.gecko_markets", gecko)

    async def run():
        errors = []
        rows = [row async for row in engine.market_candidates([c], errors)]
        assert rows[0][1] == value
        assert len(errors) == 1

    asyncio.run(run())


def test_discovery_and_paid_exposure_overlap_and_keep_separate_failures(client_engine, monkeypatch):
    _, engine = client_engine

    async def run():
        pools_started, boosts_started = asyncio.Event(), asyncio.Event()

        async def pools(chain, page):
            assert chain == "solana" and page == 2
            pools_started.set()
            await asyncio.wait_for(boosts_started.wait(), 0.5)

        async def boosts():
            boosts_started.set()
            await asyncio.wait_for(pools_started.wait(), 0.5)
            raise ProviderError("Explicit fixture paid feed outage")

        monkeypatch.setattr(engine.service.discovery, "refresh", pools)
        monkeypatch.setattr(engine.service.discovery, "boosts", boosts)
        errors = []
        await engine.refresh_discovery(2, errors)
        assert "discovery_temporarily_unavailable" not in errors
        assert "paid_exposure_feed_unavailable" in errors
        assert engine.service.discovery.status["boosts"]["state"] == "error"

    asyncio.run(run())


def test_cancelled_market_batch_leaves_no_detached_provider_requests(client_engine, monkeypatch):
    _, engine = client_engine
    c, _, _ = seed(engine)
    finished = set()

    async def run():
        started = {name: asyncio.Event() for name in ["pool", "gecko"]}

        async def source(name):
            started[name].set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.add(name)

        monkeypatch.setattr("app.opportunities.pool_markets", lambda *a: source("pool"))
        monkeypatch.setattr("app.opportunities.gecko_markets", lambda *a: source("gecko"))

        async def collect():
            return [row async for row in engine.market_candidates([c], [])]

        task = asyncio.create_task(collect())
        await asyncio.wait_for(asyncio.gather(*(e.wait() for e in started.values())), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert finished == {"pool", "gecko"}
