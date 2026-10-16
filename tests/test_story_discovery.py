"""Synthetic document/market fixtures; these tests do not verify live endorsements."""

import asyncio
import time

import pytest

from app.announcements import DocumentReader, contract_candidates
from app.errors import ProviderError
from app.models import utcnow
from tests.conftest import market
from tests.test_opportunities import TOKEN
from tests.test_opportunities import client_engine as client_engine
from tests.test_story_evidence import save_document


def test_news_contract_enters_engine_without_pool_feed_or_name_search(client_engine, monkeypatch):
    client, engine = client_engine

    async def quoted(address):
        return market(address, pool_created_at=int((time.time() - 1800) * 1000))

    monkeypatch.setattr(engine.service.providers, "market", quoted)
    save_document(engine)
    assert engine.listing()["items"] == []
    asyncio.run(engine.cycle(refresh_discovery=False))
    candidates = client.get("/api/opportunities").json()["items"]
    assert len(candidates) == 1
    detail = engine.detail(candidates[0]["id"])
    assert detail["contract"] == TOKEN
    assert detail["discovery"]["discovery_basis"] == "exact_contract_news_mention_not_launch"
    assert detail["observations"][-1]["narrative"]["supported"]
    assert engine.alerts()
    assert client.get("/api/portfolio?account=news").json()["orders"] == []


@pytest.mark.parametrize("bad", ["identity", "pool", "stale", "future", "liquidity", "provider", "nan"])
def test_invalid_or_failed_pool_lookup_remains_unknown_and_backed_off(
    client_engine, monkeypatch, bad
):
    _, engine = client_engine
    calls = []

    async def quoted(address):
        calls.append(address)
        if bad == "provider":
            raise ProviderError("Explicit fixture HTTP failure")
        overrides = {
            "identity": {"address": "So11111111111111111111111111111111111111112"},
            "pool": {"pair_address": "invalid"},
            "stale": {"observed_at": "2000-01-01T00:00:00Z"},
            "future": {"observed_at": "2099-01-01T00:00:00Z"},
            "liquidity": {"liquidity_usd": 0},
            "nan": {"price_usd": float("nan")},
        }[bad]
        return market(address).model_copy(update=overrides)

    monkeypatch.setattr(engine.service.providers, "market", quoted)
    save_document(engine)
    asyncio.run(engine.cycle(refresh_discovery=False))
    assert not engine.listing()["items"]
    assert engine.story_discovery.summary()["states"] == {"market_unavailable": 1}
    from app.story_discovery import StoryDiscovery

    restarted = StoryDiscovery(engine.service, engine.narratives.stories)
    asyncio.run(restarted.cycle())
    assert calls == [TOKEN]
    with engine.store.connect() as db:
        row = db.execute("SELECT * FROM story_pool_lookups").fetchone()
        assert row["attempts"] == 1 and row["next_due"] > time.time() + 200
        assert db.execute("SELECT count(*) FROM opportunity_outcomes").fetchone()[0] == 0


@pytest.mark.parametrize("networks,negative", [(["base"], False), ([], False), (["solana"], True)])
def test_uncertain_or_negative_document_never_enqueues_a_market_lookup(
    client_engine, networks, negative
):
    _, engine = client_engine
    save_document(
        engine,
        candidates=[
            {"contract": TOKEN, "networks_reported": networks, "negative_context": negative}
        ],
    )
    asyncio.run(engine.cycle(refresh_discovery=False))
    assert engine.story_discovery.summary()["tracked_contracts"] == 0
    assert not engine.listing()["items"]


def test_discovery_retry_survives_restart_and_deduplicates(client_engine, monkeypatch):
    _, engine = client_engine
    calls = []

    async def quoted(address):
        calls.append(address)
        if len(calls) == 1:
            raise ProviderError("Explicit temporary fixture failure")
        return market(address)

    monkeypatch.setattr(engine.service.providers, "market", quoted)
    save_document(engine)
    asyncio.run(engine.cycle(refresh_discovery=False))
    with engine.store.connect() as db:
        db.execute("UPDATE story_pool_lookups SET next_due=0")
    asyncio.run(engine.cycle(refresh_discovery=False))
    before = engine.detail(engine.listing()["items"][0]["id"])["discovery"]
    asyncio.run(engine.cycle(refresh_discovery=False))
    assert calls == [TOKEN, TOKEN]
    assert len(engine.listing()["items"]) == 1
    assert before == engine.detail(engine.listing()["items"][0]["id"])["discovery"]
    assert engine.story_discovery.summary()["states"] == {"resolved_pool": 1}


def test_removal_during_lookup_prevents_a_stale_association(client_engine, monkeypatch):
    _, engine = client_engine

    async def quoted(address):
        save_document(engine, candidates=[])
        engine.narratives.stories.index_documents()
        return market(address)

    monkeypatch.setattr(engine.service.providers, "market", quoted)
    save_document(engine)
    asyncio.run(engine.cycle(refresh_discovery=False))
    assert not engine.listing()["items"]
    assert engine.story_discovery.summary()["states"] == {"market_unavailable": 1}


def test_existing_candidate_needs_no_extra_quote_and_read_api_does_not_mutate(
    client_engine, monkeypatch
):
    from tests.test_opportunities import seed

    client, engine = client_engine
    seed(engine)
    save_document(engine)

    async def forbidden(address):
        pytest.fail("Existing candidate does not require another market request")

    monkeypatch.setattr(engine.service.providers, "market", forbidden)
    asyncio.run(engine.cycle(refresh_discovery=False))
    with engine.store.connect() as db:
        before = [tuple(r) for r in db.execute("SELECT * FROM story_pool_lookups")]
    response = client.get("/api/opportunities/narratives").json()
    assert response["story_discovery"]["states"] == {"existing_candidate": 1}
    with engine.store.connect() as db:
        assert before == [tuple(r) for r in db.execute("SELECT * FROM story_pool_lookups")]


def test_failed_lookup_does_not_block_another_address(client_engine, monkeypatch):
    _, engine = client_engine
    other = "acajNA5meGJMkLq4E8cVepGkm88RqTSxWyqFBvUpump"

    async def quoted(address):
        if address == TOKEN:
            raise ProviderError("Explicit fixture failure")
        return market(address)

    monkeypatch.setattr(engine.service.providers, "market", quoted)
    save_document(
        engine,
        candidates=[
            {"contract": c, "networks_reported": ["solana"], "negative_context": False}
            for c in [TOKEN, other]
        ],
    )
    asyncio.run(engine.cycle(refresh_discovery=False))
    assert [c["contract"] for c in engine.listing()["items"]] == [other]
    assert engine.story_discovery.status["state"] == "partial"
    assert engine.story_discovery.summary()["states"] == {
        "market_unavailable": 1,
        "resolved_pool": 1,
    }


def test_expired_evidence_is_retained_and_new_story_reopens_it(client_engine, monkeypatch):
    _, engine = client_engine
    save_document(engine)
    engine.narratives.stories.index_documents()
    jobs = engine.story_discovery
    jobs.enqueue(utcnow())
    with engine.store.connect() as db:
        first = db.execute("SELECT payload FROM story_pool_lookups").fetchone()[0]
        db.execute("UPDATE story_pool_lookups SET first_seen_at='2000-01-01T00:00:00Z'")
    save_document(engine, candidates=[])
    engine.narratives.stories.index_documents()
    asyncio.run(jobs.cycle())
    assert jobs.summary()["states"] == {"evidence_expired": 1}
    save_document(engine, title="Another independent fixture story")
    engine.narratives.stories.index_documents()
    asyncio.run(jobs.cycle())
    assert jobs.summary()["states"] == {"resolved_pool": 1}
    import json

    assert jobs.recent()[0]["payload"]["first_evidence"] == json.loads(first)["first_evidence"]


def test_same_document_reread_preserves_backoff(client_engine, monkeypatch):
    _, engine = client_engine

    async def quoted(address):
        raise ProviderError("Explicit temporary fixture failure")

    monkeypatch.setattr(engine.service.providers, "market", quoted)
    save_document(engine)
    asyncio.run(engine.cycle(refresh_discovery=False))
    before = engine.story_discovery.recent()[0]
    save_document(engine)
    asyncio.run(engine.cycle(refresh_discovery=False))
    after = engine.story_discovery.recent()[0]
    assert after["attempts"] == 1 and after["next_due"] == before["next_due"]
    assert (
        after["payload"]["last_enqueued_document_id"]
        > before["payload"]["last_enqueued_document_id"]
    )


def test_explicit_pump_mint_link_is_a_reference_not_an_endorsement():
    reader = DocumentReader("https://solana.com/fixture")
    reader.feed(
        f'<article><p>A reported meme: <a href="https://pump.fun/coin/{TOKEN}">token</a></p></article>'
    )
    document = reader.document() | {"url": reader.url}
    result = contract_candidates(document)
    assert len(result) == 1
    assert result[0]["contract"] == TOKEN
    assert result[0]["networks_reported"] == ["solana"]
    assert result[0]["token_identity_verified"] is False


@pytest.mark.parametrize(
    "url",
    [
        "https://pump.fun.evil.org/coin/" + TOKEN,
        "https://pump.fun/" + TOKEN,
        "https://dexscreener.com/solana/" + TOKEN,
        "https://pump.fun/coin/" + TOKEN + "?cluster=devnet",
        "https://solscan.io/token/" + TOKEN + "?cluster=devnet",
    ],
)
def test_unsupported_or_non_mainnet_links_are_not_mint_evidence(url):
    reader = DocumentReader("https://solana.com/fixture")
    reader.feed(f'<article><p>A reported meme: <a href="{url}">token</a></p></article>')
    assert contract_candidates(reader.document() | {"url": reader.url}) == []
