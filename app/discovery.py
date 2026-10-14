"""Bounded discovery on Solana/Base with separate observation, indexing and pool dates."""

import asyncio
import json
import re
from datetime import UTC, datetime

import httpx

from app.errors import ProviderError
from app.http_client import read_json
from app.models import number, utcnow
from app.onchain import chain_address


def pool_identifier(chain, value):
    # EVM singleton pools (e.g. Uniswap v4) use bytes32 IDs, not ERC-20 addresses.
    if chain == "base" and isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{64}", value):
        return value.lower(), "pool_id_32_bytes"
    return chain_address(chain, value), "account_address"


class Discovery:
    def __init__(self, store, client=None):
        self.store = store
        self.client = client or httpx.AsyncClient(timeout=20, follow_redirects=False)
        self.lock = asyncio.Lock()
        self.status = {}
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS discovered_pools(chain TEXT NOT NULL,pool TEXT NOT NULL,contract TEXT NOT NULL,first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(chain,pool));
                CREATE TABLE IF NOT EXISTS discovery_runs(id INTEGER PRIMARY KEY,at TEXT NOT NULL,payload TEXT NOT NULL);
            """)
            if "first_payload" not in {
                r[1] for r in db.execute("PRAGMA table_info(discovered_pools)")
            }:
                db.execute("ALTER TABLE discovered_pools ADD COLUMN first_payload TEXT")

    async def close(self):
        await self.client.aclose()

    def save(self, item):
        now = utcnow()
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO discovered_pools(chain,pool,contract,first_seen_at,last_seen_at,payload,first_payload) VALUES(?,?,?,?,?,?,?) ON CONFLICT(chain,pool) DO UPDATE SET last_seen_at=excluded.last_seen_at,payload=excluded.payload",
                (
                    item["chain"],
                    item["pool"],
                    item["contract"],
                    now,
                    now,
                    json.dumps(item),
                    json.dumps(item),
                ),
            )

    async def new_pools(self, chain, page):
        data = await read_json(
            self.client,
            "GET",
            f"https://api.geckoterminal.com/api/v2/networks/{chain}/new_pools",
            params={"page": page},
            headers={"accept": "application/json;version=20230302"},
        )
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ProviderError("Schema new_pools invalidă.")
        rejected = 0
        for row in data["data"]:
            try:
                a, relations = row["attributes"], row["relationships"]
                token_id = relations["base_token"]["data"]["id"]
                contract = chain_address(chain, token_id.removeprefix(chain + "_"))
                pool, identifier_type = pool_identifier(chain, a["address"])
                reported = a.get("pool_created_at")
                if reported and (
                    not datetime.fromisoformat(reported.replace("Z", "+00:00")).tzinfo
                    or datetime.fromisoformat(reported.replace("Z", "+00:00")) > datetime.now(UTC)
                ):
                    reported = None
                self.save(
                    {
                        "chain": chain,
                        "pool": pool,
                        "pool_identifier_type": identifier_type,
                        "contract": contract,
                        "name": a.get("name", "?"),
                        "price_usd": number(a.get("base_token_price_usd"), None),
                        "liquidity_usd": number(a.get("reserve_in_usd"), None),
                        "pool_created_at_reported": reported,
                        "token_launched_at": None,
                        "indexed_at": None,
                        "discovery_basis": "provider_new_pool_feed",
                        "source": "GeckoTerminal",
                        "observed_at": utcnow(),
                        "official_affiliation": "unverified",
                    }
                )
            except (ValueError, TypeError, KeyError, AttributeError):
                rejected += 1
        return {
            "count": len(data["data"]) - rejected,
            "rejected": rejected,
            "next_page": page + 1 if len(data["data"]) >= 20 and page < 10 else None,
        }

    async def profiles(self):
        data = await read_json(
            self.client, "GET", "https://api.dexscreener.com/token-profiles/latest/v1"
        )
        if not isinstance(data, list):
            raise ProviderError("Schema profiles invalidă.")
        by_chain = {"solana": [], "base": []}
        for row in data:
            try:
                chain = row["chainId"]
                if chain in by_chain:
                    address = chain_address(chain, row["tokenAddress"])
                    if address not in by_chain[chain]:
                        by_chain[chain].append(address)
            except (ValueError, TypeError, KeyError):
                continue
        counts = {}
        for chain, addresses in by_chain.items():
            if not addresses:
                counts[chain] = 0
                continue
            pairs = await read_json(
                self.client,
                "GET",
                f"https://api.dexscreener.com/tokens/v1/{chain}/" + ",".join(addresses[:30]),
            )
            if not isinstance(pairs, list):
                continue
            counts[chain] = 0
            for pair in pairs:
                try:
                    if pair["chainId"] != chain:
                        continue
                    contract = chain_address(chain, pair["baseToken"]["address"])
                    if contract not in addresses:
                        continue
                    pool, identifier_type = pool_identifier(chain, pair["pairAddress"])
                    created = number(pair.get("pairCreatedAt"), None)
                    created_at = (
                        datetime.fromtimestamp(created / 1000, UTC).isoformat()
                        if created and 0 < created / 1000 <= datetime.now(UTC).timestamp()
                        else None
                    )
                    self.save(
                        {
                            "chain": chain,
                            "pool": pool,
                            "pool_identifier_type": identifier_type,
                            "contract": contract,
                            "name": pair["baseToken"].get("name", "?"),
                            "price_usd": number(pair.get("priceUsd"), None),
                            "liquidity_usd": number((pair.get("liquidity") or {}).get("usd"), None),
                            "pool_created_at_reported": created_at,
                            "token_launched_at": None,
                            "indexed_at": None,
                            "discovery_basis": "latest_promotional_profile_not_launch",
                            "source": "DEX Screener",
                            "observed_at": utcnow(),
                            "official_affiliation": "unverified",
                        }
                    )
                    counts[chain] += 1
                except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                    continue
        return counts

    async def refresh(self, chain="all", page=1):
        if chain not in {"all", "solana", "base"} or not 1 <= page <= 10:
            raise ValueError("Chain sau pagină invalidă.")
        if self.lock.locked():
            raise ProviderError("Discovery este deja în curs.")
        async with self.lock:
            chains = ["solana", "base"] if chain == "all" else [chain]
            for target in chains:
                try:
                    page_result = await self.new_pools(target, page)
                    self.status[target] = {
                        "state": "partial" if page_result["rejected"] else "ok",
                        "at": utcnow(),
                        "page": page,
                        **page_result,
                    }
                except ProviderError as exc:
                    self.status[target] = {
                        "state": "error",
                        "at": utcnow(),
                        "error": str(exc),
                        "page": page,
                    }
            try:
                self.status["profiles"] = {
                    "state": "ok",
                    "at": utcnow(),
                    "counts": await self.profiles(),
                }
            except ProviderError as exc:
                self.status["profiles"] = {"state": "error", "at": utcnow(), "error": str(exc)}
            with self.store.connect() as db:
                db.execute(
                    "INSERT INTO discovery_runs(at,payload) VALUES(?,?)",
                    (utcnow(), json.dumps(self.status)),
                )
        return self.listing()

    def listing(self, chain=None, before=None, limit=50):
        query = "SELECT * FROM discovered_pools WHERE 1=1"
        args = []
        if chain:
            query += " AND chain=?"
            args.append(chain)
        if before:
            query += " AND (first_seen_at || '|' || chain || '|' || pool) < ?"
            args.append(before)
        query += " ORDER BY first_seen_at DESC,chain DESC,pool DESC LIMIT ?"
        args.append(limit + 1)
        with self.store.connect() as db:
            rows = db.execute(query, args).fetchall()
        items = [dict(r) | {"payload": json.loads(r["payload"])} for r in rows[:limit]]
        cursor = (
            items[-1]["first_seen_at"] + "|" + items[-1]["chain"] + "|" + items[-1]["pool"]
            if len(rows) > limit
            else None
        )
        return {
            "items": items,
            "next_cursor": cursor,
            "sources": self.status,
            "coverage": {
                "solana": "new_pools + latest profiles, partial",
                "base": "new_pools + latest profiles, partial",
                "other_chains": "not_covered",
            },
            "note": "Prima observare/indexare și crearea unui pool nu stabilesc data lansării tokenului. Feedul este neexhaustiv; niciun ordin automat.",
        }

    async def boosts(self):
        """A separately labeled paid-exposure feed, never evidence of organic demand."""
        rows = await read_json(
            self.client, "GET", "https://api.dexscreener.com/token-boosts/latest/v1"
        )
        if not isinstance(rows, list):
            raise ProviderError("Boost feed schema invalid.")
        by_address = {}
        for row in rows:
            try:
                if row.get("chainId") != "solana":
                    continue
                address = chain_address("solana", row["tokenAddress"])
                by_address[address] = {
                    "amount_reported": number(row.get("amount"), None),
                    "total_amount_reported": number(row.get("totalAmount"), None),
                    "observed_at": utcnow(),
                    "source": "DEX Screener token boosts",
                    "organic_demand_verified": False,
                }
            except (ValueError, TypeError, KeyError, AttributeError):
                continue
        count = 0
        for start in range(0, len(by_address), 30):
            addresses = list(by_address)[start : start + 30]
            pairs = await read_json(
                self.client,
                "GET",
                "https://api.dexscreener.com/tokens/v1/solana/" + ",".join(addresses),
            )
            if not isinstance(pairs, list):
                raise ProviderError("Boost pool schema invalid.")
            for p in pairs:
                try:
                    address = chain_address("solana", p["baseToken"]["address"])
                    if p.get("chainId") != "solana" or address not in by_address:
                        continue
                    pool = chain_address("solana", p["pairAddress"])
                    created = number(p.get("pairCreatedAt"), None)
                    self.save(
                        {
                            "chain": "solana",
                            "pool": pool,
                            "contract": address,
                            "name": p["baseToken"].get("name", "?"),
                            "price_usd": number(p.get("priceUsd"), None),
                            "liquidity_usd": number((p.get("liquidity") or {}).get("usd"), None),
                            "pool_created_at_reported": datetime.fromtimestamp(
                                created / 1000, UTC
                            ).isoformat()
                            if created and 0 < created / 1000 <= datetime.now(UTC).timestamp()
                            else None,
                            "token_launched_at": None,
                            "indexed_at": None,
                            "source": "DEX Screener",
                            "discovery_basis": "paid_boost_exposure_not_launch",
                            "promotion": by_address[address],
                            "observed_at": utcnow(),
                            "official_affiliation": "unverified",
                        }
                    )
                    count += 1
                except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                    continue
        self.status["boosts"] = {
            "state": "ok",
            "at": utcnow(),
            "reported_tokens": len(by_address),
            "pools": count,
            "sampling_bias": "paid exposure",
        }
        return count
