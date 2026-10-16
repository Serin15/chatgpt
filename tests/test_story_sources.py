"""Publisher responses below are synthetic; live access is reported separately."""

import asyncio
import json
import time

import httpx
import pytest

from app.announcements import Announcements
from app.models import utcnow
from app.news import TOPICS, News, parse_rss
from tests.test_news import article, rss
from tests.test_opportunities import TOKEN, stamp


@pytest.mark.parametrize("topic", ["solana_official", "decrypt", "cointelegraph"])
def test_direct_publisher_feed_and_document_are_scoped_to_catalog(store, topic):
    async def run():
        definition = TOPICS[topic]
        url = "https://" + definition["source_host"] + "/fixture/new-meme"
        calls = []

        def response(request):
            calls.append(str(request.url))
            if str(request.url) == definition["feed"]:
                return httpx.Response(200, content=rss("New memecoin community launch", url))
            assert str(request.url) == url
            return httpx.Response(
                200,
                text=f"<article><p>Solana contract {TOKEN}</p></article>",
                headers={"content-type": "text/html"},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(response))
        news, documents = News(store, None, client), Announcements(store, client)
        try:
            items = await news.feed(topic)
            assert len(items) == 1 and items[0]["publisher"] == definition["publisher"]
            news_id = news.save(items[0])
            await documents.enrich_news(news, None)
            document = documents.news_document(news_id)
            assert document["state"] == "read"
            assert document["contract_candidates"][0]["contract"] == TOKEN
            assert document["claim_verified"] is False
            assert calls == [definition["feed"], url]
        finally:
            await news.close()

    asyncio.run(run())


@pytest.mark.parametrize("topic", ["solana_official", "decrypt", "cointelegraph"])
def test_publisher_feed_cannot_delegate_to_arbitrary_article_hosts(topic):
    assert parse_rss(rss("New memecoin launch", "https://evil.example/fixture"), topic) == []


def test_memecoin_query_remains_a_headline_hypothesis_without_name_search():
    assert TOPICS["memecoins"]["search"] is None
    assert parse_rss(rss("Unrelated industrial production announcement"), "memecoins") == []
    item = parse_rss(rss("New memecoin launches after reported viral event"), "memecoins")[0]
    assert item["article_verified"] is False
    assert parse_rss(rss("New memecoin will do 100x"), "memecoins") == []


def test_new_document_precedes_hourly_reread_in_same_budget(store):
    async def run():
        calls = []

        def response(request):
            calls.append(str(request.url))
            return httpx.Response(
                200,
                text="<article><p>Reported story, no contract.</p></article>",
                headers={"content-type": "text/html"},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(response))
        news, documents = News(store, None), Announcements(store, client)
        try:
            old_url, new_url = (
                "https://solana.com/fixture/old",
                "https://www.coindesk.com/fixture/new",
            )
            old_id = news.save(article(title="Latest primary fixture story") | {"url": old_url})
            news.save(
                article(title="Memecoin launch fixture")
                | {"url": new_url, "published_at": stamp(time.time() - 600)}
            )
            with store.connect() as db:
                db.execute(
                    "INSERT INTO announcement_documents(news_id,at,payload) VALUES(?,?,?)",
                    (
                        old_id,
                        stamp(time.time() - 7200),
                        json.dumps({"state": "read", "url": old_url}),
                    ),
                )
            await documents.enrich_news(news, None, limit=1)
            assert calls == [new_url]
        finally:
            await news.close()
            await client.aclose()

    asyncio.run(run())


def test_timeout_is_an_error_and_other_feed_still_saves_news(store, monkeypatch):
    class SlowNews(News):
        async def feed(self, topic):
            if topic == "memecoins":
                raise TimeoutError
            return (
                [article(topic="crypto", title="Explicit accessible feed fixture")]
                if topic == "crypto"
                else []
            )

    async def run():
        news = SlowNews(store, None)
        try:
            result = await news.refresh()
            assert result["topics"]["memecoins"]["state"] == "error"
            assert result["topics"]["memecoins"]["error"]
            assert result["topics"]["crypto"]["state"] == "ok"
            assert len(news.listing()) == 1
            assert result["running"] is False and result["last_completed_at"] <= utcnow()
        finally:
            await news.close()

    asyncio.run(run())
