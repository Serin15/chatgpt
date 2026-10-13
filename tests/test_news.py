import time
from datetime import UTC, datetime
from email.utils import format_datetime

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.news import News, matches_name, mentioned_assets, parse_rss
from tests.conftest import ADDRESS, OTHER, market
from tests.test_api import FixtureProviders


def article(topic="claude", title="Claude test headline — explicit fixture"):
    return {
        "topic": topic,
        "title": title,
        "url": f"https://example.org/test/{topic}",
        "publisher": "Test fixture publication",
        "published_at": datetime.now(UTC).isoformat(),
        "fingerprint": topic + title,
        "article_verified": False,
        "origin": "fixture",
    }


class FixtureNews(News):
    async def feed(self, topic):
        return [article(topic)] if topic == "claude" else []


class NewsFixtureProviders(FixtureProviders):
    async def search(self, query):
        return [
            {
                "address": ADDRESS,
                "symbol": "CLAUDE",
                "name": "Claude test token",
                "pool_created_at": int((time.time() - 3600) * 1000),
                "liquidity_usd": 50000,
                "pair_address": OTHER,
                "price_usd": 1,
                "observed_at": datetime.now(UTC).isoformat(),
            }
        ]

    async def market(self, address):
        return market(address, symbol="CLAUDE", name="Explicit test token")


def rss(title, url="https://example.org/article", offset=0):
    published = format_datetime(datetime.fromtimestamp(time.time() + offset, UTC))
    return f"<rss><channel><item><title>{title}</title><link>{url}</link><pubDate>{published}</pubDate><source>Example newspaper</source></item></channel></rss>".encode()


def test_rss_claim_not_upgraded_to_fact():
    result = parse_rss(rss("Claude allegedly discovered a planet"), "claude")
    assert result[0]["article_verified"] is False
    assert result[0]["title"] == "Claude allegedly discovered a planet"
    assert result[0]["publisher"] == "Example newspaper"
    assert "probability" not in result[0]


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "http://example.org", "https://user:pass@example.org"]
)
def test_rss_dangerous_links_ignored(url):
    assert parse_rss(rss("Claude", url), "claude") == []


@pytest.mark.parametrize(
    "title", ["Claude coin will do 100x", "Claude price prediction", "Claude price today"]
)
def test_hype_ignored(title):
    assert parse_rss(rss(title), "claude") == []


@pytest.mark.parametrize("offset", [-86400 * 3, 3600])
def test_future_and_stale_rss_ignored(offset):
    assert parse_rss(rss("Claude", offset=offset), "claude") == []


def test_entities_blocked_and_word_boundaries():
    with pytest.raises(ValueError):
        parse_rss(b'<!DOCTYPE rss [<!ENTITY x "fake">]><rss/>', "claude")
    assert matches_name("Claude AI", ["claude"])
    assert not matches_name("claudette", ["claude"])
    assert not matches_name("trumpet", ["trump"])


def test_news_dedup_and_chronology(settings, store):
    news = News(store, None)
    first = news.save(article())
    assert news.save(article()) == first
    news.save_matches(
        first,
        [
            {
                "address": ADDRESS,
                "name": "Claude",
                "symbol": "CLAUDE",
                "pool_created_at": int((time.time() - 86400) * 1000),
            }
        ],
    )
    saved = news.listing()[0]
    assert saved["article_verified"] is False
    assert saved["association"] == "lexical_hypothesis"
    assert saved["matches"][0]["chronology"] == "pool_before_article"
    assert saved["matches"][0]["token_created_at"] is None
    assert saved["matches"][0]["official_affiliation"] == "unverified"


def test_news_50_order_preserves_existing_account_and_context(settings):
    app = create_app(settings, NewsFixtureProviders(), False, news_factory=FixtureNews)
    with TestClient(app) as c:
        assert c.post("/api/news/refresh").status_code == 200
        story = c.get("/api/news").json()[0]
        assert len(story["matches"]) == 1
        assert c.get("/api/portfolio?account=news").json()["cash"] == "500"
        c.post("/api/tokens", json={"address": ADDRESS})
        sig = c.post(
            f"/api/tokens/{ADDRESS}/signal", json={"account": "news", "news_id": story["id"]}
        )
        assert sig.status_code == 200, sig.text
        with app.state.service.news_paper.connect() as db:
            db.execute(
                "UPDATE signals SET at=? WHERE id=?",
                (datetime.fromtimestamp(time.time() - 4, UTC).isoformat(), sig.json()["id"]),
            )
        order = c.post(
            "/api/paper/buy",
            json={
                "address": ADDRESS,
                "amount_usd": "50",
                "signal_id": sig.json()["id"],
                "account": "news",
            },
        )
        assert order.status_code == 200, order.text
        assert order.json()["entry_context"]["news_context"]["title"] == story["title"]
        assert order.json()["entry_context"]["news_context"]["article_verified"] is False
        assert c.get("/api/portfolio?account=news").json()["cash"] == "449.99"
        assert c.get("/api/portfolio").json()["cash"] == "100"
        position = c.get("/api/portfolio?account=news").json()["positions"][0]
        assert float(position["valuation"]["estimated_unrealized_pnl_usd"]) < 0
        with app.state.service.store.connect() as db:
            db.execute("UPDATE news SET title=? WHERE id=?", ("Changed later", story["id"]))
        journal = c.get("/api/portfolio?account=news").json()["orders"][0]
        assert journal["details"]["entry_context"]["news_context"]["title"] == story["title"]
        assert c.post(f"/api/paper/positions/{position['id']}/sell?account=news").status_code == 200
        assert float(c.get("/api/portfolio?account=news").json()["positions"][0]["pnl"]) < 0


def test_unrelated_news_context_rejected(settings):
    with TestClient(
        create_app(settings, NewsFixtureProviders(), False, news_factory=FixtureNews)
    ) as c:
        c.post("/api/news/refresh")
        c.post("/api/tokens", json={"address": OTHER})
        news_id = c.get("/api/news").json()[0]["id"]
        assert (
            c.post(
                f"/api/tokens/{OTHER}/signal", json={"account": "news", "news_id": news_id}
            ).status_code
            == 409
        )


def test_public_figure_politics_without_crypto_not_an_opportunity():
    assert parse_rss(rss("Trump opens a golf course"), "trump") == []
    result = parse_rss(rss("Trump discusses a bitcoin announcement"), "trump")
    assert len(result) == 1
    assert not result[0]["article_verified"]


def test_source_priority_does_not_verify_endorsement(store):
    news = News(store, None)
    publisher = article(title="Claude news from a publisher")
    publisher["publisher"] = "Reuters"
    news.save(publisher)
    primary = article("kraken_official", title="Kraken announces a token listing")
    primary["publisher"] = "Kraken Blog"
    news.save(primary)
    rows = news.listing()
    assert rows[0]["source_priority"] == "primary"
    assert all(not r["endorsement_verified"] and not r["fundamentals_verified"] for r in rows)


def test_bitcoin_cash_not_silently_mapped_to_bitcoin():
    assets = [
        {"asset_id": "bitcoin", "name": "Bitcoin", "symbol": "BTC"},
        {"asset_id": "bitcoin-cash", "name": "Bitcoin Cash", "symbol": "BCH"},
    ]
    assert [
        a["asset_id"] for a in mentioned_assets("Bitcoin Cash announces an update", {}, assets)
    ] == ["bitcoin-cash"]
    assert {
        a["asset_id"] for a in mentioned_assets("Bitcoin and Bitcoin Cash update", {}, assets)
    } == {"bitcoin", "bitcoin-cash"}


def test_replacing_matches_preserves_first_seen_and_removes_obsolete(store):
    news = News(store, None)
    news_id = news.save(article())
    news.save_matches(news_id, [{"address": "asset:bitcoin"}, {"address": "asset:ethereum"}])
    with store.connect() as db:
        db.execute(
            "UPDATE news_matches SET first_matched_at=? WHERE address=?",
            ("2026-01-01T00:00:00+00:00", "asset:bitcoin"),
        )
    news.replace_matches(news_id, [{"address": "asset:bitcoin", "price_usd": 100}])
    matches = news.listing()[0]["matches"]
    assert len(matches) == 1
    assert matches[0]["first_matched_at"] == "2026-01-01T00:00:00+00:00"
    assert matches[0]["market"]["price_usd"] == 100
