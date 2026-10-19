"""Regression fixtures for source coverage, repeated headlines and cohort accounting."""

import asyncio
import time
import xml.etree.ElementTree as ET

import httpx

from app.announcements import Announcements
from app.news import News, parse_rss
from tests.test_news import article, rss
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import stamp


def test_direct_feed_keeps_relevant_article_beyond_first_ten():
    root = ET.Element("rss")
    channel = ET.SubElement(root, "channel")
    for i in range(15):
        title = "New memecoin community announcement" if i == 12 else f"Generic crypto story {i}"
        channel.append(
            ET.fromstring(rss(title, f"https://decrypt.co/fixture/{i}")).find("./channel/item")
        )
    result = parse_rss(ET.tostring(root), "decrypt")
    assert any(x["url"].endswith("/12") for x in result)


def test_document_collection_does_not_depend_on_display_limit(store):
    async def run():
        calls = []
        target = "https://decrypt.co/fixture/meme"
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: (
                    calls.append(str(r.url))
                    or httpx.Response(
                        200,
                        text="<article><p>Explicit fixture with no contract.</p></article>",
                        headers={"content-type": "text/html"},
                    )
                )
            )
        )
        news, documents = News(store, None), Announcements(store, client)
        try:
            news.save(
                article(topic="crypto", title="Memecoin launch fixture")
                | {"url": target, "published_at": stamp(time.time() - 600)}
            )
            with store.connect() as db:
                db.executemany(
                    "INSERT INTO news(fingerprint,topic,title,url,publisher,published_at,first_seen_at,canonical_url) VALUES(?,?,?,?,?,?,?,?)",
                    [
                        (
                            str(i),
                            "crypto",
                            f"Generic fixture {i}",
                            f"https://solana.com/fixture/{i}",
                            "Explicit fixture",
                            stamp(time.time() - 60),
                            stamp(time.time() - 60),
                            f"https://solana.com/fixture/{i}",
                        )
                        for i in range(100)
                    ],
                )
            assert target not in [x["url"] for x in news.listing()]
            await documents.enrich_news(news, None, limit=1)
            assert calls == [target]
        finally:
            await news.close()
            await client.aclose()

    asyncio.run(run())


def test_repeated_headlines_share_one_display_group_but_preserve_raw_rows(client_engine):
    _, engine = client_engine
    for i, publisher in enumerate(["Decrypt", "Yahoo Finance"]):
        engine.service.news.save(
            article(topic="memecoins", title="New meme community launches - " + publisher)
            | {
                "url": ["https://decrypt.co/fixture", "https://finance.yahoo.com/fixture"][i],
                "publisher": publisher,
            }
        )
    result = engine.narratives.stories.listing()["items"]
    assert len(result) == 1
    assert len(result[0]["related_reports"]) == 2
    assert not result[0]["contracts"] and result[0]["claim_verified"] is False
    with engine.store.connect() as db:
        assert db.execute("SELECT count(*) FROM news").fetchone()[0] == 2


def test_same_headline_contract_evidence_is_never_grouped():
    from app.headline_groups import group_headlines

    a = {
        "title": "A new memecoin community starts trading",
        "published_at": stamp(time.time()),
        "contracts": [{"contract": "explicit fixture A"}],
    }
    b = a | {"contracts": [{"contract": "explicit fixture B"}]}
    assert len(group_headlines([a, b])) == 2
