"""Public market references, explicit provenance and bounded personal watchlists."""

import asyncio
import json
import math
import re
import time
from functools import wraps
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from app.models import freshness, utcnow
from app.providers import ProviderError

PRODUCTS = {
    "bitcoin": "BTC-USD",
    "ethereum": "ETH-USD",
    "solana": "SOL-USD",
    "ripple": "XRP-USD",
    "dogecoin": "DOGE-USD",
    "cardano": "ADA-USD",
    "avalanche-2": "AVAX-USD",
    "chainlink": "LINK-USD",
    "litecoin": "LTC-USD",
}


def safe_link(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
        )
    except ValueError:
        return False


def schema_checked(fn):
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except (ValueError, TypeError, KeyError, AttributeError, IndexError):
            raise ProviderError("Răspuns de piață incompatibil cu schema așteptată.") from None

    return wrapped


class Asset(BaseModel):
    asset_id: str = Field(pattern=r"^[a-z0-9-]{1,80}$")
    kind: str = "market_asset"
    address: str
    name: str
    symbol: str
    price_usd: float = Field(gt=0, allow_inf_nan=False)
    market_cap: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    volume_24h: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    change_24h: float | None = Field(default=None, allow_inf_nan=False)
    rank: int | None = None
    observed_at: str
    source_updated_at: str | None = None
    source: str = "CoinGecko"
    book: dict | None = None


def parse_asset(item):
    asset = Asset(
        asset_id=item["id"],
        address="asset:" + item["id"],
        name=item["name"],
        symbol=item["symbol"].upper(),
        price_usd=item["current_price"],
        market_cap=item.get("market_cap"),
        volume_24h=item.get("total_volume"),
        change_24h=item.get("price_change_percentage_24h"),
        rank=item.get("market_cap_rank"),
        observed_at=utcnow(),
        source_updated_at=item.get("last_updated"),
    ).model_dump()
    return asset | {
        "price_source": "CoinGecko",
        "volume_source": "CoinGecko",
        "market_source_updated_at": asset["source_updated_at"],
        "reference_price_usd": asset["price_usd"],
    }


class Assets:
    def __init__(self, store, client=None):
        self.store = store
        self.client = client or httpx.AsyncClient(
            timeout=20, follow_redirects=False, headers={"User-Agent": "PulseResearch/0.3"}
        )
        self.status = {"state": "unverified", "at": None, "error": None}
        self.source_status = {}
        self.lock = asyncio.Lock()
        self.watch_lock = asyncio.Lock()
        self.request_locks = {}
        self.last_requests = {}
        self.cached_venues = {}
        self.cached_profiles = {}
        self.held_assets = None
        self.cursor = 0
        self.max_age = getattr(store, "max_snapshot_age", 120)
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS assets(asset_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS asset_observations(id INTEGER PRIMARY KEY,asset_id TEXT NOT NULL,at TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS asset_history ON asset_observations(asset_id,id DESC);
                CREATE TABLE IF NOT EXISTS asset_books(asset_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS asset_watch(asset_id TEXT PRIMARY KEY,added_at TEXT NOT NULL);
            """)

    async def close(self):
        await self.client.aclose()

    async def request(self, url, params=None):
        source = "coinbase" if "coinbase" in urlsplit(url).hostname else "coingecko"
        async with self.request_locks.setdefault(source, asyncio.Lock()):
            for attempt in range(3):
                delay = 2.1 - (time.monotonic() - self.last_requests.get(source, 0))
                if delay > 0:
                    await asyncio.sleep(delay)
                self.last_requests[source] = time.monotonic()
                try:
                    response = await self.client.get(url, params=params)
                    if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                        await asyncio.sleep(2**attempt)
                        continue
                    response.raise_for_status()
                    payload = response.json()
                    self.source_status[source] = {"state": "ok", "at": utcnow(), "error": None}
                    return payload
                except (httpx.HTTPError, ValueError) as exc:
                    reason = (
                        f"HTTP {exc.response.status_code}"
                        if isinstance(exc, httpx.HTTPStatusError)
                        else type(exc).__name__
                    )
                    self.source_status[source] = {"state": "error", "at": utcnow(), "error": reason}
                    if isinstance(exc, httpx.TransportError) and attempt < 2:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise ProviderError(f"{source}: {reason}") from None

    def save(self, asset):
        with self.store.connect() as db:
            payload = json.dumps(asset)
            db.execute(
                "INSERT INTO assets VALUES(?,?) ON CONFLICT(asset_id) DO UPDATE SET payload=excluded.payload",
                (asset["asset_id"], payload),
            )
            db.execute(
                "INSERT INTO asset_observations(asset_id,at,payload) VALUES(?,?,?)",
                (asset["asset_id"], asset["observed_at"], payload),
            )
            if asset.get("book"):
                db.execute(
                    "INSERT OR REPLACE INTO asset_books VALUES(?,?)", (asset["asset_id"], payload)
                )

    def decorate(self, asset, book=None, watch=False):
        asset = dict(asset)
        if (
            book
            and freshness(book.get("observed_at"), book.get("source_updated_at"), self.max_age)[
                "fresh"
            ]
        ):
            for key in (
                "price_usd",
                "source",
                "price_source",
                "source_updated_at",
                "book",
                "observed_at",
            ):
                asset[key] = book.get(key)
        return asset | {
            "freshness": freshness(
                asset.get("observed_at"), asset.get("source_updated_at"), self.max_age
            ),
            "watch": watch,
        }

    def listing(self):
        with self.store.connect() as db:
            rows = [json.loads(r[0]) for r in db.execute("SELECT payload FROM assets")]
            books = {r[0]: json.loads(r[1]) for r in db.execute("SELECT * FROM asset_books")}
            watched = {r[0] for r in db.execute("SELECT asset_id FROM asset_watch")}
        return sorted(
            (self.decorate(a, books.get(a["asset_id"]), a["asset_id"] in watched) for a in rows),
            key=lambda a: (not a["watch"], a.get("rank") or 100000),
        )

    def get(self, asset_id):
        with self.store.connect() as db:
            row = db.execute("SELECT payload FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
            book = db.execute(
                "SELECT payload FROM asset_books WHERE asset_id=?", (asset_id,)
            ).fetchone()
            watch = db.execute("SELECT 1 FROM asset_watch WHERE asset_id=?", (asset_id,)).fetchone()
        return (
            self.decorate(json.loads(row[0]), json.loads(book[0]) if book else None, bool(watch))
            if row
            else None
        )

    def history(self, asset_id, limit=48):
        with self.store.connect() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM asset_observations WHERE asset_id=? ORDER BY id DESC LIMIT ?",
                    (asset_id, limit),
                )
            ][::-1]

    async def refresh(self):
        if self.lock.locked():
            return self.status
        async with self.lock:
            try:
                data = await self.request(
                    "https://api.coingecko.com/api/v3/coins/markets",
                    {
                        "vs_currency": "usd",
                        "order": "market_cap_desc",
                        "per_page": 25,
                        "page": 1,
                        "sparkline": "false",
                    },
                )
                if not isinstance(data, list) or not data:
                    raise ValueError
                parsed, rejected = [], 0
                for item in data:
                    try:
                        parsed.append(parse_asset(item))
                    except (ValueError, TypeError, KeyError, AttributeError):
                        rejected += 1
                if not parsed:
                    raise ValueError
                for asset in parsed:
                    self.save(asset)
                self.status = {
                    "state": "ok",
                    "at": utcnow(),
                    "error": None,
                    "assets": len(parsed),
                    "rejected_records": rejected,
                }
            except (ProviderError, ValueError, KeyError, TypeError, AttributeError) as exc:
                self.status = {
                    "state": "error",
                    "at": utcnow(),
                    "error": str(exc)
                    if isinstance(exc, ProviderError)
                    else "Schema de piață incompatibilă",
                }
        return self.status

    @schema_checked
    async def quote(self, asset_id):
        if not re.fullmatch(r"[a-z0-9-]{1,80}", asset_id):
            raise ProviderError("ID crypto invalid")
        reference_error = None
        try:
            data = await self.request(
                "https://api.coingecko.com/api/v3/coins/markets",
                {"vs_currency": "usd", "ids": asset_id, "sparkline": "false"},
            )
            if not isinstance(data, list) or len(data) != 1 or data[0].get("id") != asset_id:
                raise ProviderError("Activ fără preț disponibil")
            asset = parse_asset(data[0])
            self.save(asset)
        except (ProviderError, ValueError, KeyError, TypeError, AttributeError) as exc:
            asset = self.get(asset_id)
            if not asset or asset_id not in PRODUCTS:
                raise
            asset = dict(asset)
            reference_error = (
                str(exc) if isinstance(exc, ProviderError) else "Metadata de piață incompatibile"
            )
        asset["book"] = None
        if asset_id in PRODUCTS:
            try:
                data = await self.request(
                    f"https://api.exchange.coinbase.com/products/{PRODUCTS[asset_id]}/book",
                    {"level": 1},
                )
                bid, ask = data["bids"][0], data["asks"][0]
                if not (
                    all(math.isfinite(float(v)) for v in (bid[0], bid[1], ask[0], ask[1]))
                    and 0 < float(bid[0]) <= float(ask[0])
                    and float(bid[1]) > 0
                    and float(ask[1]) > 0
                ):
                    raise ValueError
                asset["book"] = {
                    "bid": bid[0],
                    "bid_size": bid[1],
                    "ask": ask[0],
                    "ask_size": ask[1],
                    "product": PRODUCTS[asset_id],
                    "sequence": data.get("sequence"),
                    "observed_at": utcnow(),
                    "source": "Coinbase Exchange public order book",
                }
                asset["price_usd"] = float(bid[0]) / 2 + float(ask[0]) / 2
                asset["source_updated_at"] = data.get("time") or asset["book"]["observed_at"]
                asset["source"] = asset["price_source"] = "Coinbase Exchange public order book"
            except (ProviderError, ValueError, KeyError, TypeError, IndexError, AttributeError):
                with self.store.connect() as db:
                    db.execute("DELETE FROM asset_books WHERE asset_id=?", (asset_id,))
                if reference_error:
                    raise ProviderError(
                        "Nici prețul de referință, nici bookul nu pot fi actualizate."
                    ) from None
                asset["book_error"] = "Book indisponibil; doar scenariu de referință."
        asset["observed_at"] = utcnow()
        if reference_error:
            asset["metadata_error"] = reference_error
        self.save(asset)
        return self.decorate(asset)

    @schema_checked
    async def venues(self, asset_id):
        cached = self.cached_venues.get(asset_id)
        if cached and time.time() - cached[0] < 300:
            return cached[1]
        data = await self.request(
            f"https://api.coingecko.com/api/v3/coins/{asset_id}/tickers", {"page": 1}
        )
        if not isinstance(data, dict) or not isinstance(data.get("tickers"), list):
            raise ProviderError("Schema piețelor nu poate fi interpretată.")
        result = []
        for ticker in data["tickers"]:
            if not isinstance(ticker, dict) or ticker.get("is_anomaly") or ticker.get("is_stale"):
                continue
            if ticker.get("coin_id") and ticker["coin_id"] != asset_id:
                continue
            url = ticker.get("trade_url")
            market = ticker.get("market")
            if not safe_link(url) or not isinstance(market, dict):
                continue
            result.append(
                {
                    "name": market.get("name", "Unknown"),
                    "pair": f"{ticker.get('base', '?')}/{ticker.get('target', '?')}",
                    "url": url,
                    "trust_score": ticker.get("trust_score"),
                    "source": "CoinGecko tickers",
                    "observed_at": utcnow(),
                    "last_traded_at": ticker.get("last_traded_at"),
                    "execution_verified": False,
                }
            )
            if len(result) >= 8:
                break
        self.cached_venues[asset_id] = (time.time(), result)
        return result

    @schema_checked
    async def profile(self, asset_id):
        cached = self.cached_profiles.get(asset_id)
        if cached and time.time() - cached[0] < 3600:
            return cached[1]
        data = await self.request(
            f"https://api.coingecko.com/api/v3/coins/{asset_id}",
            {
                "localization": "false",
                "tickers": "false",
                "market_data": "false",
                "community_data": "false",
                "developer_data": "false",
                "sparkline": "false",
            },
        )
        if not isinstance(data, dict) or data.get("id") != asset_id:
            raise ProviderError("Metadata de identitate indisponibile")
        links = data.get("links") or {}
        repos = links.get("repos_url") or {}
        if not isinstance(links, dict) or not isinstance(repos, dict):
            raise ProviderError("Schema linkurilor nu poate fi interpretată.")
        documents = []
        for kind, urls in [
            ("Site declarat", links.get("homepage") or []),
            ("Whitepaper", [links.get("whitepaper")]),
            ("Repository declarat", repos.get("github") or []),
        ]:
            if not isinstance(urls, list):
                raise ProviderError("Schema documentelor nu poate fi interpretată.")
            documents.extend(
                {
                    "label": kind,
                    "url": url,
                    "status": "provider_reported_not_independently_verified",
                }
                for url in urls[:4]
                if safe_link(url)
            )
        contracts = data.get("platforms") or {}
        if not isinstance(contracts, dict):
            raise ProviderError("Schema contractelor nu poate fi interpretată.")
        result = {
            "asset_id": asset_id,
            "documents": documents,
            "contracts": {k: v for k, v in contracts.items() if isinstance(v, str)},
            "genesis_date_reported": data.get("genesis_date"),
            "categories": data.get("categories") or [],
            "source": "CoinGecko project metadata",
            "observed_at": utcnow(),
            "fundamentals_verified": False,
        }
        self.cached_profiles[asset_id] = (time.time(), result)
        return result

    @schema_checked
    async def search(self, query):
        data = await self.request("https://api.coingecko.com/api/v3/search", {"query": query})
        if not isinstance(data, dict) or not isinstance(data.get("coins"), list):
            raise ProviderError("Schema căutării este indisponibilă.")
        return [
            {
                "asset_id": c["id"],
                "name": c["name"],
                "symbol": c["symbol"],
                "rank": c.get("market_cap_rank"),
            }
            for c in data["coins"]
            if isinstance(c, dict)
            and isinstance(c.get("id"), str)
            and re.fullmatch(r"[a-z0-9-]{1,80}", c["id"])
            and isinstance(c.get("name"), str)
            and isinstance(c.get("symbol"), str)
        ][:10]

    async def watch(self, asset_id):
        async with self.watch_lock:
            return await self._watch(asset_id)

    async def _watch(self, asset_id):
        with self.store.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM asset_watch").fetchone()[0]
            exists = db.execute(
                "SELECT 1 FROM asset_watch WHERE asset_id=?", (asset_id,)
            ).fetchone()
        if total >= 20 and not exists:
            raise ProviderError("Watchlist crypto limitată la 20 de active.")
        asset = await self.quote(asset_id)
        with self.store.connect() as db:
            db.execute("INSERT OR IGNORE INTO asset_watch VALUES(?,?)", (asset_id, utcnow()))
        return asset

    def unwatch(self, asset_id):
        with self.store.connect() as db:
            db.execute("DELETE FROM asset_watch WHERE asset_id=?", (asset_id,))

    def invalidate_book(self, asset_id):
        with self.store.connect() as db:
            db.execute("DELETE FROM asset_books WHERE asset_id=?", (asset_id,))

    async def run(self):
        last_catalog = 0
        while True:
            if time.monotonic() - last_catalog >= 120:
                await self.refresh()
                last_catalog = time.monotonic()
            held = self.held_assets() if self.held_assets else []
            with self.store.connect() as db:
                watched = [
                    r[0] for r in db.execute("SELECT asset_id FROM asset_watch ORDER BY added_at")
                ]
            selected = list(dict.fromkeys(held + watched))
            if selected:
                selected = (selected[self.cursor :] + selected[: self.cursor])[:7]
                self.cursor = (self.cursor + 7) % len(set(held + watched))
            for asset_id in selected:
                try:
                    await self.quote(asset_id)
                except ProviderError:
                    continue
            await asyncio.sleep(60)


def research_case(asset):
    return {
        "verdict": "research_only",
        "fundamentals_verified": False,
        "checks": [
            {"label": label, "status": "unknown"}
            for label in (
                "Produs funcțional",
                "Echipă și emitent",
                "Tokenomics / vesting",
                "Audit și permisiuni",
                "Afiliere oficială / susținere",
            )
        ],
        "notes": [
            "Prețul și capitalizarea nu demonstrează că un proiect este solid.",
            "Numele nu confirmă susținerea oficială.",
        ],
    }
