"""Isolated document fixtures, never evidence of real publisher/token relationships."""

import asyncio
import json
import time

import pytest

from app.models import utcnow
from tests.test_news import article
from tests.test_opportunities import TOKEN, payload, seed, stamp
from tests.test_opportunities import client_engine as client_engine


def save_document(engine, *, candidates=None, state="read", title="Original research fixture"):
    news_id = engine.service.news.save(
        article(topic="crypto", title=title)
        | {"url": "https://solana.com/fixture/" + title.replace(" ", "-")}
    )
    value = {
        "state": state,
        "url": "https://solana.com/fixture/" + title.replace(" ", "-"),
        "sha256": "a" * 64,
        "contract_candidates": candidates
        if candidates is not None
        else [{"contract": TOKEN, "networks_reported": ["solana"], "negative_context": False}],
    }
    with engine.store.connect() as db:
        document_id = db.execute(
            "INSERT INTO announcement_documents(news_id,at,payload) VALUES(?,?,?)",
            (news_id, utcnow(), json.dumps(value)),
        ).lastrowid
    return news_id, document_id


def test_document_contract_reaches_discovery_without_dex_name_match(client_engine):
    _, engine = client_engine
    candidate, _, _ = seed(engine)
    news_id, _ = save_document(engine)
    with engine.store.connect() as db:
        assert db.execute("SELECT count(*) FROM news_matches").fetchone()[0] == 0
    asyncio.run(engine.cycle(refresh_discovery=False))
    narrative = engine.detail(candidate["id"])["observations"][-1]["narrative"]
    assert [item["news_id"] for item in narrative["supported"]] == [news_id]
    assert narrative["supported"][0]["endorsement_verified"] is False
    assert engine.service.portfolio("news")["orders"] == []


@pytest.mark.parametrize(
    "networks,negative,group",
    [
        (["solana"], True, "contradictory"),
        (["base"], False, "uncertain"),
        (["solana", "ethereum"], False, "uncertain"),
        ([], False, "uncertain"),
    ],
)
def test_exact_address_requires_unambiguous_chain_and_context(
    client_engine, networks, negative, group
):
    _, engine = client_engine
    seed(engine)
    save_document(
        engine,
        candidates=[
            {"contract": TOKEN, "networks_reported": networks, "negative_context": negative}
        ],
    )
    engine.narratives.stories.index_documents()
    result = engine.narratives.evidence(TOKEN, utcnow())
    assert result[group] and not result["supported"] and result["score"] is None
    assert result["ranking_supported"] is False


def test_indexing_does_not_backdate_evidence_or_duplicate_links(client_engine, monkeypatch):
    _, engine = client_engine
    seed(engine)
    save_document(engine)
    before_index = utcnow()
    after_index = stamp(time.time() + 1)
    monkeypatch.setattr("app.story_evidence.utcnow", lambda: after_index)
    assert engine.narratives.stories.index_documents() == 1
    assert engine.narratives.stories.index_documents() == 0
    assert not engine.narratives.evidence(TOKEN, before_index)["supported"]
    assert len(engine.narratives.evidence(TOKEN, after_index)["supported"]) == 1


@pytest.mark.parametrize(
    "new_state,new_candidates",
    [
        ("unavailable", []),
        ("read", []),
        ("read", [{"contract": TOKEN, "networks_reported": ["solana"], "negative_context": True}]),
    ],
)
def test_newer_document_removal_or_denial_does_not_fall_back_to_old_positive(
    client_engine, new_state, new_candidates
):
    _, engine = client_engine
    seed(engine)
    save_document(engine)
    engine.narratives.stories.index_documents()
    assert engine.narratives.evidence(TOKEN, utcnow())["supported"]
    save_document(engine, state=new_state, candidates=new_candidates)
    engine.narratives.stories.index_documents()
    assert not engine.narratives.evidence(TOKEN, utcnow())["supported"]


def test_document_invalid_json_does_not_block_other_candidates(client_engine):
    _, engine = client_engine
    c, _, _ = seed(engine)
    news_id, _ = save_document(engine)
    with engine.store.connect() as db:
        db.execute(
            "INSERT INTO announcement_documents(news_id,at,payload) VALUES(?,?,?)",
            (news_id, utcnow(), "[]"),
        )
    asyncio.run(engine.cycle(refresh_discovery=False))
    assert engine.detail(c["id"])["observations"][-1]["market"] is not None
    assert engine.narratives.stories.listing()["items"][0]["document_state"] == "invalid"


def test_current_story_does_not_rewrite_an_earlier_signal(client_engine):
    client, engine = client_engine
    c, policy, cfg = seed(engine)
    engine.save_observation(c, payload(engine, c, time.time()), policy, cfg)
    before = engine.detail(c["id"])["signals"]
    save_document(engine)
    engine.narratives.stories.index_documents()
    detail = client.get(f"/api/opportunities/{c['id']}").json()
    assert detail["current_narrative"]["supported"]
    assert detail["signals"] == before


def test_stories_are_visible_without_ai_and_reads_do_not_index(client_engine):
    client, engine = client_engine
    seed(engine)
    save_document(engine)
    p = client.get("/api/opportunities/narratives").json()
    assert p["enabled"] is False
    assert p["stories"]["pending_index"] == 1
    engine.narratives.stories.index_documents()
    p = client.get("/api/opportunities/narratives").json()
    mention = p["stories"]["items"][0]["contracts"][0]
    assert mention["contract"] == TOKEN and mention["candidate_id"] is not None
    assert p["stories"]["items"][0]["endorsement_verified"] is False


def test_memecoin_headlines_are_visible_before_unrelated_catalog_news(client_engine):
    _, engine = client_engine
    for i in range(8):
        save_document(engine, candidates=[], title=f"Unrelated general fixture story {i}")
    news_id = engine.service.news.save(article(topic="memecoins", title="Memecoin community announces launch fixture"))
    result = engine.narratives.stories.listing()["items"]
    assert result[0]["news_id"] == news_id
    assert result[0]["memecoin_headline"] is True
    assert result[0]["document_state"] == "headline_only_unpermitted_document"
    assert result[0]["contracts"] == [] and result[0]["claim_verified"] is False
