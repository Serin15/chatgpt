"""Headline ingestion and lexical token associations. No claim verification or causal inference."""

import asyncio
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.assets import safe_link
from app.models import epoch, number, utcnow
from app.providers import ProviderError

TOPICS = {
    "claude": {
        "label": "Claude / Anthropic",
        "query": "Claude Anthropic",
        "aliases": ["claude", "anthropic"],
    },
    "trump": {
        "label": "Trump",
        "query": '"Donald Trump" (crypto OR bitcoin OR token OR cryptocurrency)',
        "aliases": ["trump"],
    },
    "crypto": {
        "label": "Piață crypto",
        "query": "(cryptocurrency OR blockchain OR crypto) (launch OR funding OR exchange OR regulation OR mainnet)",
        "aliases": ["crypto", "cryptocurrency", "blockchain", "bitcoin", "ethereum", "token"],
        "search": None,
    },
    "launches": {
        "label": "Lansări și proiecte",
        "query": "crypto token mainnet launch funding",
        "aliases": ["crypto", "token", "mainnet", "blockchain", "launch", "funding"],
        "search": None,
    },
    "elon": {
        "label": "Elon Musk",
        "query": '"Elon Musk" (crypto OR bitcoin OR dogecoin)',
        "aliases": ["elon", "musk"],
        "search": "musk",
    },
    "zelensky": {
        "label": "Zelenski",
        "query": "(Zelensky OR Zelenskyy OR Zelenski) (crypto OR cryptocurrency OR blockchain)",
        "aliases": ["zelensky", "zelenskyy", "zelenski"],
        "search": None,
    },
    "ethereum_official": {
        "label": "Ethereum · sursă primară",
        "aliases": [],
        "feed": "https://blog.ethereum.org/en/feed.xml",
        "publisher": "Ethereum Foundation",
        "source_kind": "primary",
        "source_host": "blog.ethereum.org",
        "asset": "ethereum",
    },
    "kraken_official": {
        "label": "Kraken · sursă primară",
        "aliases": [],
        "feed": "https://blog.kraken.com/feed",
        "publisher": "Kraken Blog",
        "source_kind": "primary",
        "source_host": "blog.kraken.com",
    },
    "coindesk": {
        "label": "CoinDesk",
        "aliases": [],
        "feed": "https://www.coindesk.com/arc/outboundfeeds/rss",
        "publisher": "CoinDesk",
        "source_kind": "publisher",
        "source_host": "www.coindesk.com",
    },
}

HYPE = re.compile(
    r"\b(?:\d{2,}x|price prediction|price forecast|price today|buy now|next millionaire|to the moon)\b",
    re.I,
)
KNOWN_PUBLISHERS = {
    "reuters",
    "coindesk",
    "the block",
    "decrypt",
    "associated press",
    "ap news",
    "bloomberg",
    "financial times",
    "cnbc",
    "bbc",
    "bbc news",
    "the guardian",
    "the verge",
    "techcrunch",
    "the decoder",
}


def event_headline(title):
    return not HYPE.search(title)


def relevant_headline(title, topic):
    if topic in {"trump", "elon", "zelensky"}:
        return bool(
            re.search(
                r"\b(?:crypto\w*|bitcoin|ethereum|blockchain|tokens?|coins?|dogecoin|xrp|nft|stablecoins?|digital assets?)\b",
                title,
                re.I,
            )
        )
    return True


def matches_name(value, aliases):
    words = set(re.findall(r"[a-z0-9]+", value.lower()))
    return bool(words.intersection(aliases))


def mentioned_assets(title, definition, assets):
    remaining = title
    result = []
    for asset in sorted(assets, key=lambda a: len(a["name"]), reverse=True):
        pattern = r"\b" + re.escape(asset["name"]) + r"\b"
        by_name = bool(re.search(pattern, remaining, re.I))
        by_ticker = bool(re.search(r"\$" + re.escape(asset["symbol"]) + r"\b", title))
        ecosystem = definition.get("asset") == asset["asset_id"]
        if by_name or by_ticker or ecosystem:
            result.append(
                asset
                | {
                    "news_relation": "headline_mention"
                    if by_name or by_ticker
                    else "publisher_ecosystem"
                }
            )
            if by_name:
                remaining = re.sub(pattern, " ", remaining, flags=re.I)
    return result[:4]


def canonical_url(value):
    if not safe_link(value):
        return value
    url = urlsplit(value)
    query = [
        (k, v)
        for k, v in parse_qsl(url.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
    ]
    return urlunsplit((url.scheme, url.netloc.lower(), url.path, urlencode(query), ""))


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
            or not relevant_headline(title, topic)
            or (TOPICS[topic]["aliases"] and not matches_name(title, TOPICS[topic]["aliases"]))
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
        definition = TOPICS[topic]
        if definition.get("source_host") and urlsplit(link).hostname != definition["source_host"]:
            continue
        publisher = definition.get("publisher", publisher)
        output.append(
            {
                "topic": topic,
                "title": title[:500],
                "url": link,
                "publisher": publisher[:100],
                "published_at": published,
                "article_verified": False,
                "origin": definition.get("source_kind", "google_news_rss"),
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
                CREATE TABLE IF NOT EXISTS news_read(news_id INTEGER PRIMARY KEY,at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS news_topics(news_id INTEGER NOT NULL,topic TEXT NOT NULL,PRIMARY KEY(news_id,topic));
            """)
            if "canonical_url" not in {r[1] for r in db.execute("PRAGMA table_info(news)")}:
                db.execute("ALTER TABLE news ADD COLUMN canonical_url TEXT")
            migrated = db.execute(
                "SELECT 1 FROM schema_migrations WHERE name='news-canonical-v1'"
            ).fetchone()
            if not migrated:
                groups = {}
                for row in db.execute("SELECT * FROM news ORDER BY id").fetchall():
                    key = canonical_url(row["url"])
                    canonical = groups.setdefault(key, row["id"])
                    db.execute("UPDATE news SET canonical_url=? WHERE id=?", (key, row["id"]))
                    db.execute(
                        "INSERT OR IGNORE INTO news_topics VALUES(?,?)", (canonical, row["topic"])
                    )
                    if canonical != row["id"]:
                        db.execute(
                            "INSERT OR IGNORE INTO news_read SELECT ?,at FROM news_read WHERE news_id=?",
                            (canonical, row["id"]),
                        )
                        db.execute(
                            "INSERT OR IGNORE INTO news_matches SELECT ?,address,market,first_matched_at,updated_at FROM news_matches WHERE news_id=?",
                            (canonical, row["id"]),
                        )
                db.execute(
                    "INSERT INTO schema_migrations VALUES(?,?)", ("news-canonical-v1", utcnow())
                )
            db.execute("CREATE INDEX IF NOT EXISTS news_canonical_url ON news(canonical_url)")

    async def close(self):
        await self.client.aclose()

    async def feed(self, topic):
        try:
            definition = TOPICS[topic]
            response = await self.client.get(
                definition.get("feed", "https://news.google.com/rss/search"),
                params=None
                if definition.get("feed")
                else {
                    "q": definition["query"] + " when:1d",
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
            key = canonical_url(item["url"])
            existing = db.execute(
                "SELECT MIN(id) FROM news WHERE canonical_url=?", (key,)
            ).fetchone()[0]
            if existing is not None:
                db.execute(
                    "INSERT OR IGNORE INTO news_topics VALUES(?,?)", (existing, item["topic"])
                )
                return existing
            db.execute(
                """INSERT OR IGNORE INTO news
                (fingerprint,topic,title,url,publisher,published_at,first_seen_at,canonical_url) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    item["fingerprint"],
                    item["topic"],
                    item["title"],
                    item["url"],
                    item["publisher"],
                    item["published_at"],
                    utcnow(),
                    key,
                ),
            )
            news_id = db.execute(
                "SELECT id FROM news WHERE fingerprint=?", (item["fingerprint"],)
            ).fetchone()[0]
            db.execute("INSERT OR IGNORE INTO news_topics VALUES(?,?)", (news_id, item["topic"]))
            return news_id

    def resolve_id(self, news_id):
        with self.store.connect() as db:
            row = db.execute("SELECT canonical_url FROM news WHERE id=?", (news_id,)).fetchone()
            return (
                db.execute("SELECT MIN(id) FROM news WHERE canonical_url=?", (row[0],)).fetchone()[
                    0
                ]
                if row
                else None
            )

    def save_matches(self, news_id, candidates):
        with self.store.connect() as db:
            for candidate in candidates:
                db.execute(
                    """INSERT INTO news_matches VALUES(?,?,?,?,?)
                    ON CONFLICT(news_id,address) DO UPDATE SET market=excluded.market, updated_at=excluded.updated_at""",
                    (news_id, candidate["address"], json.dumps(candidate), utcnow(), utcnow()),
                )

    def replace_matches(self, news_id, candidates, topic=None):
        """Replace current hypotheses atomically, retaining their first observation."""
        now = utcnow()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            first_seen = {
                row["address"]: row["first_matched_at"]
                for row in db.execute("SELECT * FROM news_matches WHERE news_id=?", (news_id,))
            }
            if topic:
                merged = {}
                for row in db.execute("SELECT * FROM news_matches WHERE news_id=?", (news_id,)):
                    previous = json.loads(row["market"])
                    origins = set(previous.get("origin_topics", [topic])) - {topic}
                    if origins:
                        merged[row["address"]] = previous | {"origin_topics": sorted(origins)}
                for candidate in candidates:
                    origins = set(merged.get(candidate["address"], {}).get("origin_topics", [])) | {
                        topic
                    }
                    merged[candidate["address"]] = candidate | {"origin_topics": sorted(origins)}
                candidates = list(merged.values())
            db.execute("DELETE FROM news_matches WHERE news_id=?", (news_id,))
            for candidate in candidates:
                db.execute(
                    "INSERT OR REPLACE INTO news_matches VALUES(?,?,?,?,?)",
                    (
                        news_id,
                        candidate["address"],
                        json.dumps(candidate),
                        first_seen.get(candidate["address"], now),
                        now,
                    ),
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
                        query = definition.get(
                            "search", definition["aliases"][0] if definition["aliases"] else None
                        )
                        candidates = await self.providers.search(query) if ids and query else []
                        candidates = [
                            c
                            for c in candidates
                            if matches_name(
                                str(c.get("name", "")) + " " + str(c.get("symbol", "")),
                                definition["aliases"],
                            )
                        ]
                        for news_id, item in zip(ids, items):
                            assets = getattr(self, "assets", None)
                            linked = []
                            if assets:
                                linked = mentioned_assets(
                                    item["title"], definition, assets.listing()
                                )
                            self.replace_matches(news_id, candidates[:4] + linked[:4], topic)
                        self.status["topics"][topic] = {
                            "state": "ok",
                            "at": utcnow(),
                            "headlines": len(items),
                            "candidates": len(candidates[:4]),
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

    def listing(self, archive=False, news_id=None):
        with self.store.connect() as db:
            result = []
            read_ids = {r[0] for r in db.execute("SELECT news_id FROM news_read")}
            query = (
                "SELECT * FROM news WHERE id IN (SELECT MIN(id) FROM news GROUP BY canonical_url)"
            )
            parameters = []
            if news_id is not None:
                query += " AND id=?"
                parameters.append(self.resolve_id(news_id))
            if not archive:
                from datetime import datetime

                query += " AND COALESCE(published_at,first_seen_at)>=?"
                parameters.append(datetime.fromtimestamp(time.time() - 86400 * 2, UTC).isoformat())
            query += " ORDER BY COALESCE(published_at,first_seen_at) DESC LIMIT 100"
            for row in db.execute(query, parameters):
                if not event_headline(row["title"]):
                    continue
                if not relevant_headline(row["title"], row["topic"]):
                    continue
                article = dict(row)
                topics = [
                    r[0]
                    for r in db.execute(
                        "SELECT topic FROM news_topics WHERE news_id=?", (row["id"],)
                    )
                ]
                article |= {
                    "article_verified": False,
                    "association": "lexical_hypothesis",
                    "topic_label": TOPICS.get(article["topic"], {}).get("label", article["topic"]),
                    "matches": [],
                    "topics": topics,
                    "is_recent": 0
                    <= time.time() - epoch(article["published_at"] or article["first_seen_at"])
                    <= 86400 * 2,
                }
                definition = next(
                    (
                        TOPICS[t]
                        for t in topics
                        if TOPICS.get(t, {}).get("source_kind") == "primary"
                        and TOPICS[t].get("source_host") == urlsplit(article["url"]).hostname
                    ),
                    TOPICS.get(article["topic"], {}),
                )
                title = article["title"].lower()
                category = (
                    "listings"
                    if re.search(r"\blist(?:ing|ings|ed|s)\b", title)
                    else "launches"
                    if re.search(
                        r"\b(?:launch(?:es|ed|ing)?|mainnet|funding|raises|token sale)\b", title
                    )
                    else "public_figures"
                    if set(topics) & {"trump", "elon", "zelensky"}
                    else "ecosystem"
                )
                briefs = {
                    "listings": "Poate schimba accesul la tranzacționare. Verifică data începerii și perechea exactă.",
                    "launches": "Verifică emitentul, produsul, distribuția tokenului și existența unei piețe reale.",
                    "public_figures": "Relatarea despre o persoană nu confirmă susținerea unui token. Este necesar anunțul original.",
                    "ecosystem": "Context de cercetare. O actualizare de produs sau rețea nu dovedește creșterea prețului.",
                }
                article |= {
                    "category": category,
                    "brief": briefs[category],
                    "source_kind": definition.get("source_kind", "aggregator"),
                    "endorsement_verified": False,
                    "fundamentals_verified": False,
                    "published_source_url": definition.get("feed"),
                    "seen": article["id"] in read_ids,
                    "source_priority": (
                        "primary"
                        if definition.get("source_kind") == "primary"
                        else "editorial"
                        if article["publisher"].casefold() in KNOWN_PUBLISHERS
                        else "review_needed"
                    ),
                }
                for match in db.execute("SELECT * FROM news_matches WHERE news_id=?", (row["id"],)):
                    market = json.loads(match["market"])
                    created, published = (
                        number(market.get("pool_created_at"), None),
                        article["published_at"],
                    )
                    chronology = "unknown"
                    if created and created > 0 and published:
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
        return sorted(
            result,
            key=lambda a: (
                {"primary": 2, "editorial": 1, "review_needed": 0}[a["source_priority"]],
                a["published_at"] or a["first_seen_at"],
            ),
            reverse=True,
        )

    def context(self, news_id, address):
        article = next(iter(self.listing(archive=True, news_id=news_id)), None)
        if not article:
            raise ValueError("Știre inexistentă în lista curentă.")
        matched = next((m for m in article["matches"] if m["market"]["address"] == address), None)
        if not matched:
            raise ValueError("Tokenul nu are o asociere înregistrată pentru această știre.")
        return {k: v for k, v in article.items() if k != "matches"} | {"match": matched}

    def is_seen(self, news_id):
        with self.store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS news_read(news_id INTEGER PRIMARY KEY,at TEXT NOT NULL)"
            )
            return bool(
                db.execute("SELECT 1 FROM news_read WHERE news_id=?", (news_id,)).fetchone()
            )

    def mark_seen(self, news_id):
        news_id = self.resolve_id(news_id)
        if news_id is None:
            return False
        with self.store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS news_read(news_id INTEGER PRIMARY KEY,at TEXT NOT NULL)"
            )
            db.execute("INSERT OR IGNORE INTO news_read VALUES(?,?)", (news_id, utcnow()))
        return True
