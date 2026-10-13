"""General crypto market references and optional public level-one exchange books."""

import asyncio
import json
import math
import re
import time
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from app.models import number, utcnow
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
    return Asset(
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


class Assets:
    def __init__(self, store, client=None):
        self.store = store
        self.client = client or httpx.AsyncClient(
            timeout=20, follow_redirects=False, headers={"User-Agent": "CryptoResearch/0.2"}
        )
        self.status = {"state": "unverified", "at": None, "error": None}
        self.lock = asyncio.Lock()
        self.request_lock = asyncio.Lock()
        self.last_request = 0
        self.cached_venues = {}
        self.cached_profiles = {}
        self.held_assets = None
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS assets(asset_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS asset_observations(id INTEGER PRIMARY KEY,asset_id TEXT NOT NULL,at TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS asset_history ON asset_observations(asset_id,id DESC);
            """)

    async def close(self):
        await self.client.aclose()

    async def request(self, url, params=None):
        async with self.request_lock:
            delay = 2.1 - (time.monotonic() - self.last_request)
            if delay > 0:
                await asyncio.sleep(delay)
            self.last_request = time.monotonic()
            try:
                response = await self.client.get(url, params=params)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                reason = (
                    f"HTTP {exc.response.status_code}"
                    if isinstance(exc, httpx.HTTPStatusError)
                    else type(exc).__name__
                )
                raise ProviderError("Piață crypto: " + reason) from None

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

    def listing(self):
        with self.store.connect() as db:
            assets = [json.loads(r[0]) for r in db.execute("SELECT payload FROM assets")]
        return sorted(assets, key=lambda a: a.get("rank") or 100000)

    def get(self, asset_id):
        with self.store.connect() as db:
            row = db.execute("SELECT payload FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def history(self, asset_id):
        with self.store.connect() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM asset_observations WHERE asset_id=? ORDER BY id DESC LIMIT 48",
                    (asset_id,),
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
                parsed = [parse_asset(a) for a in data if number(a.get("current_price")) > 0]
                if not parsed:
                    raise ValueError
                for asset in parsed:
                    self.save(asset)
                self.status = {"state": "ok", "at": utcnow(), "error": None, "assets": len(parsed)}
            except (ProviderError, ValueError, KeyError, TypeError, AttributeError) as exc:
                self.status = {
                    "state": "error",
                    "at": utcnow(),
                    "error": str(exc)
                    if isinstance(exc, ProviderError)
                    else "Schema de piață incompatibilă",
                }
        return self.status

    async def quote(self, asset_id):
        if not re.fullmatch(r"[a-z0-9-]{1,80}", asset_id):
            raise ProviderError("ID crypto invalid")
        try:
            data = await self.request(
                "https://api.coingecko.com/api/v3/coins/markets",
                {"vs_currency": "usd", "ids": asset_id, "sparkline": "false"},
            )
            if not isinstance(data, list) or len(data) != 1 or data[0].get("id") != asset_id:
                raise ProviderError("Activ fără preț disponibil")
            asset = parse_asset(data[0])
            asset["market_source_updated_at"] = asset["source_updated_at"]
            if asset_id in PRODUCTS:
                try:
                    book = await self.request(
                        f"https://api.exchange.coinbase.com/products/{PRODUCTS[asset_id]}/book",
                        {"level": 1},
                    )
                    bid, ask = book["bids"][0], book["asks"][0]
                    if not (
                        all(math.isfinite(float(v)) for v in [bid[0], bid[1], ask[0], ask[1]])
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
                        "sequence": book.get("sequence"),
                        "observed_at": utcnow(),
                        "source": "Coinbase Exchange public order book",
                    }
                    asset["price_usd"] = (float(bid[0]) + float(ask[0])) / 2
                    asset["source_updated_at"] = book.get("time") or asset["book"]["observed_at"]
                except (ProviderError, ValueError, KeyError, TypeError, IndexError, AttributeError):
                    asset["book_error"] = (
                        "Order book indisponibil; rămâne preț de referință CoinGecko."
                    )
            asset["observed_at"] = utcnow()
            self.save(asset)
            return asset
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ProviderError("Schema prețului crypto nu poate fi interpretată") from exc

    async def venues(self, asset_id):
        cached = self.cached_venues.get(asset_id)
        if cached and time.time() - cached[0] < 300:
            return cached[1]
        data = await self.request(
            f"https://api.coingecko.com/api/v3/coins/{asset_id}/tickers", {"page": 1}
        )
        result = []
        for ticker in data.get("tickers", []):
            if ticker.get("is_anomaly") or ticker.get("is_stale"):
                continue
            if ticker.get("coin_id") and ticker["coin_id"] != asset_id:
                continue
            url = ticker.get("trade_url")
            parsed = urlsplit(url or "")
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                continue
            result.append(
                {
                    "name": ticker.get("market", {}).get("name", "Unknown"),
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

    async def run(self):
        while True:
            await self.refresh()
            if self.held_assets:
                for asset_id in self.held_assets()[:5]:
                    try:
                        await self.quote(asset_id)
                    except ProviderError:
                        continue
            await asyncio.sleep(120)

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
        documents = []
        for kind, urls in [
            ("Site declarat", links.get("homepage") or []),
            ("Whitepaper", [links.get("whitepaper")]),
            ("Repository declarat", (links.get("repos_url") or {}).get("github") or []),
        ]:
            for url in urls[:4]:
                parsed = urlsplit(url or "")
                if (
                    parsed.scheme == "https"
                    and parsed.hostname
                    and not parsed.username
                    and not parsed.password
                ):
                    documents.append(
                        {
                            "label": kind,
                            "url": url,
                            "status": "provider_reported_not_independently_verified",
                        }
                    )
        result = {
            "asset_id": asset_id,
            "documents": documents,
            "contracts": data.get("platforms") or {},
            "genesis_date_reported": data.get("genesis_date"),
            "categories": data.get("categories") or [],
            "source": "CoinGecko project metadata",
            "observed_at": utcnow(),
            "fundamentals_verified": False,
        }
        self.cached_profiles[asset_id] = (time.time(), result)
        return result


def research_case(asset):
    fields = [
        "Produs funcțional",
        "Echipă și emitent",
        "Tokenomics / vesting",
        "Audit și permisiuni",
        "Afiliere oficială / susținere",
    ]
    return {
        "verdict": "research_only",
        "fundamentals_verified": False,
        "checks": [{"label": label, "status": "unknown"} for label in fields],
        "notes": [
            "Prețul, volumul și capitalizarea nu demonstrează că un proiect este solid.",
            "Un nume sau o știre despre o persoană nu confirmă susținerea tokenului.",
        ],
    }
