"""Headline ingestion and lexical token associations. No claim verification or causal inference."""

import asyncio
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

from app.models import epoch, utcnow
from app.providers import ProviderError

TOPICS = {
    "claude": {
        "label": "Claude / Anthropic",
        "query": "Claude Anthropic",
        "aliases": ["claude", "anthropic"],
    },
    "trump": {"label": "Trump", "query": "Donald Trump announcement", "aliases": ["trump"]},
}

HYPE = re.compile(
    r"\b(?:\d{2,}x|price prediction|price forecast|price today|buy now|next millionaire|to the moon)\b",
    re.I,
)


def event_headline(title):
    return not HYPE.search(title)


def matches_name(value, aliases):
    words = set(re.findall(r"[a-z0-9]+", value.lower()))
    return bool(words.intersection(aliases))


def safe_link(value):
    url = urlsplit(value)
    return url.scheme == "https" and bool(url.hostname) and not url.username and not url.password


def parse_rss(content, topic, now=None):
    if (
        len(content) > 2_000_000
        or b"<!DOCTYPE" in content.upper()
        or b"<!ENTITY" in content.upper()
    ):
        raise ValueError("XML RSS nesuportat")
    root = ET.fromstring(content)
    now = time.time() if now is None else now
    output = []
    for item in root.findall("./channel/item")[:100]:
        title, link = (item.findtext("title") or "").strip(), (item.findtext("link") or "").strip()
        if (
            not title
            or not safe_link(link)
            or not event_headline(title)
            or not matches_name(title, TOPICS[topic]["aliases"])
        ):
            continue
        raw_date = item.findtext("pubDate")
        published = None
        if raw_date:
            try:
                date = parsedate_to_datetime(raw_date)
                if not date.tzinfo:
                    continue
                age = now - date.timestamp()
                if age < -300 or age > 86400 * 2:
                    continue
                published = date.astimezone(UTC).isoformat()
            except (TypeError, ValueError, OverflowError):
                pass
        source = item.find("source")
        publisher = source.text if source is not None and source.text else "Google News RSS"
        output.append(
            {
                "topic": topic,
                "title": title[:500],
                "url": link,
                "publisher": publisher[:100],
                "published_at": published,
                "article_verified": False,
                "origin": "google_news_rss",
                "fingerprint": hashlib.sha256((topic + link).encode()).hexdigest(),
            }
        )
    return output[:10]


class News:
    def __init__(self, store, providers, client=None):
        self.store, self.providers = store, providers
        self.client = client or httpx.AsyncClient(
            timeout=20, follow_redirects=False, headers={"User-Agent": "MemecoinResearch/0.1"}
        )
        self.lock = asyncio.Lock()
        self.status = {
            "running": False,
            "last_completed_at": None,
            "topics": {},
            "interval_seconds": 300,
        }
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS news (
                    id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
                    topic TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL,
                    publisher TEXT NOT NULL, published_at TEXT, first_seen_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS news_matches (
                    news_id INTEGER NOT NULL, address TEXT NOT NULL, market TEXT NOT NULL,
                    first_matched_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(news_id,address));
            """)

    async def close(self):
        await self.client.aclose()

    async def feed(self, topic):
        try:
            response = await self.client.get(
                "https://news.google.com/rss/search",
                params={
                    "q": TOPICS[topic]["query"] + " when:1d",
                    "hl": "en-US",
                    "gl": "US",
                    "ceid": "US:en",
                },
            )
            response.raise_for_status()
            return parse_rss(response.content, topic)
        except (httpx.HTTPError, ValueError, ET.ParseError) as exc:
            reason = (
                f"HTTP {exc.response.status_code}"
                if isinstance(exc, httpx.HTTPStatusError)
                else type(exc).__name__
            )
            raise ProviderError(f"Știri {topic}: {reason}") from None

    def save(self, item):
        with self.store.connect() as db:
            db.execute(
                """INSERT OR IGNORE INTO news
                (fingerprint,topic,title,url,publisher,published_at,first_seen_at) VALUES(?,?,?,?,?,?,?)""",
                (
                    item["fingerprint"],
                    item["topic"],
                    item["title"],
                    item["url"],
                    item["publisher"],
                    item["published_at"],
                    utcnow(),
                ),
            )
            return db.execute(
                "SELECT id FROM news WHERE fingerprint=?", (item["fingerprint"],)
            ).fetchone()[0]

    def save_matches(self, news_id, candidates):
        with self.store.connect() as db:
            for candidate in candidates:
                db.execute(
                    """INSERT INTO news_matches VALUES(?,?,?,?,?)
                    ON CONFLICT(news_id,address) DO UPDATE SET market=excluded.market, updated_at=excluded.updated_at""",
                    (news_id, candidate["address"], json.dumps(candidate), utcnow(), utcnow()),
                )

    async def refresh(self):
        if self.lock.locked():
            return self.status
        async with self.lock:
            self.status["running"] = True
            try:
                for topic, definition in TOPICS.items():
                    try:
                        items = await self.feed(topic)
                        ids = [self.save(item) for item in items]
                        candidates = (
                            await self.providers.search(definition["aliases"][0]) if ids else []
                        )
                        candidates = [
                            c
                            for c in candidates
                            if matches_name(c["name"] + " " + c["symbol"], definition["aliases"])
                        ]
                        for news_id in ids:
                            self.save_matches(news_id, candidates[:6])
                        self.status["topics"][topic] = {
                            "state": "ok",
                            "at": utcnow(),
                            "headlines": len(items),
                            "candidates": len(candidates[:6]),
                            "error": None,
                        }
                    except ProviderError as exc:
                        self.status["topics"][topic] = {
                            "state": "error",
                            "at": utcnow(),
                            "error": str(exc),
                        }
                self.status["last_completed_at"] = utcnow()
            finally:
                self.status["running"] = False
        return self.status

    async def run(self):
        while True:
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except (ValueError, KeyError, TypeError):
                self.status["error"] = "Date de știri incompatibile; verifică furnizorul."
            await asyncio.sleep(300)

    def listing(self):
        with self.store.connect() as db:
            result = []
            for row in db.execute(
                "SELECT * FROM news ORDER BY COALESCE(published_at,first_seen_at) DESC LIMIT 40"
            ):
                if not event_headline(row["title"]):
                    continue
                article = dict(row)
                article |= {
                    "article_verified": False,
                    "association": "lexical_hypothesis",
                    "topic_label": TOPICS[article["topic"]]["label"],
                    "matches": [],
                }
                for match in db.execute("SELECT * FROM news_matches WHERE news_id=?", (row["id"],)):
                    market = json.loads(match["market"])
                    created, published = market.get("pool_created_at"), article["published_at"]
                    chronology = "unknown"
                    if created and published:
                        chronology = (
                            "pool_before_article"
                            if created / 1000 < epoch(published)
                            else "pool_after_article"
                        )
                    article["matches"].append(
                        {
                            "market": market,
                            "chronology": chronology,
                            "token_created_at": None,
                            "official_affiliation": "unverified",
                            "first_matched_at": match["first_matched_at"],
                            "updated_at": match["updated_at"],
                        }
                    )
                result.append(article)
        return result

    def context(self, news_id, address):
        article = next((n for n in self.listing() if n["id"] == news_id), None)
        if not article:
            raise ValueError("Știre inexistentă în lista curentă.")
        matched = next((m for m in article["matches"] if m["market"]["address"] == address), None)
        if not matched:
            raise ValueError("Tokenul nu are o asociere înregistrată pentru această știre.")
        return {k: v for k, v in article.items() if k != "matches"} | {"match": matched}
