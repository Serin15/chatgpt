"""Synthetic pool references: never live article, token, or issuer evidence."""

import asyncio
import json
import time

import httpx
import pytest

from app.models import utcnow
from app.opportunity_rules import EngineConfig, features
from app.story_markets import resolve_references, validated_reference
from tests.conftest import market
from tests.test_opportunities import TOKEN
from tests.test_opportunities import client_engine as client_engine
from tests.test_story_evidence import save_document

POOL = "G2UuRbmVDzDFP4qyoBJrSKBXSi7d6V4bPP9tHPs36y4b"
SOL = "So11111111111111111111111111111111111111112"


def reference(**changes):
    return {
        "state": "resolved",
        "reference_url": "https://dexscreener.com/solana/" + POOL.lower(),
        "pool": POOL,
        "base_contract": TOKEN,
        "quote_contract": SOL,
        "base_name": "Explicit fixture",
        "quote_name": "Wrapped SOL",
        "negative_context": False,
        "response_sha256": "a" * 64,
        "observed_at": utcnow(),
        "price_usd": 1,
        "liquidity_usd": 50000,
        "pool_created_at_reported": int((time.time() - 1800) * 1000),
        "price_change_24h_reported_pct": 12,
    } | changes


@pytest.mark.parametrize(
    "changes",
    [
        {"price_usd": float("nan")},
        {"liquidity_usd": -1},
        {"price_change_24h_reported_pct": float("inf")},
        {"price_change_24h_reported_pct": -101},
        {"reference_url": "https://dexscreener.com/solana/" + POOL + "?cluster=devnet"},
        {"observed_at": "2026-10-16T00:00:00"},
        {"pool_created_at_reported": int((time.time() + 3600) * 1000)},
    ],
)
def test_reference_rejects_invalid_or_future_data(changes):
    with pytest.raises(ValueError):
        validated_reference(reference(**changes))


@pytest.mark.parametrize(
    "quote,negative,expected", [(SOL, False, True), (POOL, False, False), (SOL, True, False)]
)
def test_reference_does_not_infer_endorsement_or_arbitrary_quote(quote, negative, expected):
    p = validated_reference(
        reference(
            quote_contract=quote,
            negative_context=negative,
            qualifies_for_discovery=True,
            issuer_verified=True,
        )
    )
    assert p["qualifies_for_discovery"] is expected
    assert p["issuer_verified"] is False and p["contract_printed_in_document"] is False


def test_pool_link_resolution_failure_isolated_and_no_name_search():
    async def run():
        calls = []

        def reply(request):
            calls.append(str(request.url))
            return httpx.Response(
                200,
                json={
                    "pairs": [
                        {
                            "chainId": "solana",
                            "pairAddress": POOL,
                            "baseToken": {"address": TOKEN, "name": "Fixture", "symbol": "FX"},
                            "quoteToken": {"address": SOL, "name": "SOL"},
                            "priceUsd": "1",
                            "liquidity": {"usd": 50000},
                            "pairCreatedAt": int((time.time() - 1800) * 1000),
                            "priceChange": {"h24": 12},
                            "dexId": "fixture",
                        }
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            url = reference()["reference_url"]
            doc = {
                "links": ["https://evil.invalid/solana/" + POOL, url],
                "link_contexts": [{"url": url, "text": "Pool reference in explicit fixture"}],
            }
            refs = await resolve_references(doc, client)
        assert len(calls) == 1 and calls[0].startswith(
            "https://api.dexscreener.com/latest/dex/pairs/solana/"
        )
        assert refs[0]["qualifies_for_discovery"] and refs[0]["base_contract"] == TOKEN

    asyncio.run(run())


def test_reported_prior_surge_is_late_but_future_reference_is_not_used():
    ref = reference(price_change_24h_reported_pct=2900)
    m = market(TOKEN).model_dump()
    discovery = {"price_usd": m["price_usd"], "story_evidence": {"market_reference": ref}}
    p = features(m, [], discovery, utcnow(), EngineConfig())
    assert p["excessive_extension"] and p["price_change_since_first_capture_pct"] == 0
    assert p["story_reference_prior_24h_move_reported_pct"] == 2900
    ref["observed_at"] = "2099-01-01T00:00:00Z"
    p = features(m, [], discovery, utcnow(), EngineConfig())
    assert not p["excessive_extension"] and p["story_reference_prior_24h_move_reported_pct"] is None


@pytest.mark.parametrize(
    "failure", ["http", "timeout", "wrong_chain", "wrong_pool", "ambiguous", "nonfinite"]
)
def test_unvalidated_pool_response_never_guesses_a_mint(failure):
    async def run():
        def reply(request):
            if failure == "http":
                return httpx.Response(503)
            if failure == "timeout":
                raise httpx.ReadTimeout("Explicit fixture timeout")
            pair = {
                "chainId": "base" if failure == "wrong_chain" else "solana",
                "pairAddress": SOL if failure == "wrong_pool" else POOL,
            }
            if failure == "nonfinite":
                return httpx.Response(200, content=b'{"pairs":[],"bad":NaN}')
            return httpx.Response(
                200, json={"pairs": [pair, pair] if failure == "ambiguous" else [pair]}
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            refs = await resolve_references({"links": [reference()["reference_url"]]}, client)
        assert refs[0]["state"] == "unavailable" and not refs[0]["qualifies_for_discovery"]
        assert not refs[0].get("base_contract")

    asyncio.run(run())


def save_reference(engine, ref):
    news_id, doc_id = save_document(engine, candidates=[])
    with engine.store.connect() as db:
        value = json.loads(
            db.execute(
                "SELECT payload FROM announcement_documents WHERE id=?", (doc_id,)
            ).fetchone()[0]
        )
        value["market_pair_references"] = [ref]
        db.execute(
            "UPDATE announcement_documents SET payload=? WHERE id=?", (json.dumps(value), doc_id)
        )
    return news_id


@pytest.mark.parametrize("qualifies", [True, False])
def test_pool_reference_handoff_preserves_evidence_kind(client_engine, monkeypatch, qualifies):
    _, engine = client_engine

    async def quoted(address):
        return market(address, pair_address=POOL, pool_created_at=int((time.time() - 1800) * 1000))

    monkeypatch.setattr(engine.service.providers, "market", quoted)
    save_reference(engine, reference(quote_contract=SOL if qualifies else POOL))
    asyncio.run(engine.cycle(refresh_discovery=False))
    rows = engine.listing()["items"]
    if not qualifies:
        assert not rows and engine.story_discovery.summary()["tracked_contracts"] == 0
        return
    detail = engine.detail(rows[0]["id"])
    assert detail["contract"] == TOKEN and detail["contract"] != POOL
    assert detail["discovery"]["discovery_basis"] == "news_market_pair_reference_not_launch"
    narrative = detail["observations"][-1]["narrative"]
    assert narrative["market_references"] and not narrative["supported"]
    assert narrative["ranking_supported"] is False
    assert engine.service.portfolio("news")["orders"] == []
    save_document(engine, candidates=[])
    engine.narratives.stories.index_documents()
    assert not engine.narratives.evidence(TOKEN, utcnow())["market_references"]
