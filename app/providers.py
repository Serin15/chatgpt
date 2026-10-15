"""Read-only providers. A profile/boost feed is a biased discovery sample, not all launches."""

import asyncio
import time
from functools import wraps
from urllib.parse import urlsplit

import httpx

from app.errors import ProviderError
from app.http_client import decode_json
from app.models import Market, number, solana_address, utcnow


def schema_checked(source):
    def decorate(fn):
        @wraps(fn)
        async def wrapped(self, *args, **kwargs):
            try:
                return await fn(self, *args, **kwargs)
            except ProviderError as exc:
                self.status[source] = {"state": "error", "at": utcnow(), "error": str(exc)}
                raise
            except (ValueError, TypeError, KeyError, AttributeError):
                self.status[source] = {"state": "error", "at": utcnow(), "error": "SchemaError"}
                raise ProviderError(f"{source}: răspuns incompatibil cu schema așteptată") from None

        return wrapped

    return decorate


class Providers:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client or httpx.AsyncClient(
            timeout=20, follow_redirects=False, headers={"User-Agent": "MemecoinResearch/0.1"}
        )
        self.status = {}
        self.locks = {name: asyncio.Lock() for name in ("dex", "goplus", "rpc")}
        self.last_request = {}

    async def close(self):
        await self.client.aclose()

    def records(self, data, source):
        if not isinstance(data, list):
            raise ValueError("Expected record list")
        records = [item for item in data if isinstance(item, dict)]
        rejected = len(data) - len(records)
        if rejected and not records:
            raise ValueError("No structurally valid records")
        if rejected:
            self.status.setdefault(source, {})["rejected_records"] = rejected
        return records

    async def request(self, source, method, url, **kwargs):
        # Per-provider pacing remains below the anticipated free-tier limits.
        async with self.locks[source]:
            interval = 1.1 if source == "dex" else 2.1
            for attempt in range(3):
                delay = interval - (time.monotonic() - self.last_request.get(source, 0))
                if delay > 0:
                    await asyncio.sleep(delay)
                self.last_request[source] = time.monotonic()
                try:
                    response = await self.client.request(method, url, **kwargs)
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt < 2:
                            try:
                                retry = float(response.headers.get("Retry-After", 2**attempt))
                            except ValueError:
                                retry = 2**attempt
                            await asyncio.sleep(min(max(retry, 0), 30))
                            continue
                    response.raise_for_status()
                    data = decode_json(response.content)
                    self.status[source] = {"state": "ok", "at": utcnow(), "error": None}
                    return data
                except ProviderError as exc:
                    self.status[source] = {"state": "error", "at": utcnow(), "error": str(exc)}
                    raise
                except (httpx.HTTPError, ValueError) as exc:
                    if isinstance(exc, httpx.HTTPStatusError):
                        reason = f"HTTP {exc.response.status_code}"
                    else:
                        # URLs, proxy details and credentials must never reach UI/logs.
                        reason = type(exc).__name__
                    self.status[source] = {"state": "error", "at": utcnow(), "error": reason}
                    if isinstance(exc, httpx.TransportError) and attempt < 2:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise ProviderError(f"{source}: {reason}") from None

    @schema_checked("dex")
    async def discover(self):
        data = await self.request(
            "dex", "GET", "https://api.dexscreener.com/token-profiles/latest/v1"
        )
        if not isinstance(data, list):
            raise ProviderError("dex: format de discovery necunoscut")
        addresses = []
        for item in self.records(data, "dex"):
            if item.get("chainId") == "solana":
                try:
                    address = solana_address(item.get("tokenAddress", ""))
                except ValueError:
                    continue
                if address not in addresses:
                    addresses.append(address)
        return addresses[:12]

    @schema_checked("dex")
    async def market(self, address):
        data = await self.request(
            "dex", "GET", f"https://api.dexscreener.com/token-pairs/v1/solana/{address}"
        )
        if not isinstance(data, list):
            raise ProviderError("dex: format de perechi necunoscut")
        # Pricing a quote token with the base token's price would be incorrect.
        pairs = [
            p
            for p in self.records(data, "dex")
            if p.get("chainId") == "solana"
            and isinstance(p.get("baseToken"), dict)
            and isinstance(p.get("liquidity"), dict)
            and p.get("baseToken", {}).get("address") == address
            and number(p.get("priceUsd")) > 0
            and number((p.get("liquidity") or {}).get("usd")) > 0
        ]
        if not pairs:
            raise ProviderError("dex: nicio pereche cu preț și lichiditate pentru tokenul de bază")
        for pair in sorted(
            pairs, key=lambda p: number(p.get("liquidity", {}).get("usd")), reverse=True
        ):
            try:
                return self.parse_market(pair, address)
            except (ValueError, TypeError, KeyError, AttributeError):
                self.status.setdefault("dex", {})["rejected_records"] = (
                    self.status.get("dex", {}).get("rejected_records", 0) + 1
                )
        raise ProviderError("dex: nicio pereche cu schemă de piață validă")

    @staticmethod
    def parse_market(pair, address):
        token = pair["baseToken"]
        tx = (pair.get("txns") or {}).get("m5") or {}
        return Market(
            address=address,
            symbol=token.get("symbol", "?"),
            name=token.get("name", "?"),
            pair_address=pair["pairAddress"],
            dex=pair.get("dexId", "unknown"),
            price_usd=number(pair["priceUsd"]),
            liquidity_usd=number(pair["liquidity"]["usd"]),
            volume_5m=number((pair.get("volume") or {}).get("m5"), None),
            volume_1h=number((pair.get("volume") or {}).get("h1"), None),
            change_5m=number((pair.get("priceChange") or {}).get("m5"), None),
            buys_5m=int(tx["buys"]) if tx.get("buys") is not None else None,
            sells_5m=int(tx["sells"]) if tx.get("sells") is not None else None,
            market_cap=pair.get("marketCap"),
            fdv=pair.get("fdv"),
            pool_created_at=pair.get("pairCreatedAt"),
        )

    @schema_checked("dex")
    async def search(self, query):
        data = await self.request(
            "dex", "GET", "https://api.dexscreener.com/latest/dex/search", params={"q": query}
        )
        pairs = data.get("pairs") or []
        candidates = {}
        for pair in self.records(pairs, "dex"):
            if pair.get("chainId") != "solana":
                continue
            token = pair.get("baseToken") or {}
            address = token.get("address", "")
            try:
                solana_address(address)
            except ValueError:
                continue
            liquidity = number((pair.get("liquidity") or {}).get("usd"), None)
            item = {
                "address": address,
                "symbol": token.get("symbol", "?"),
                "name": token.get("name", "?"),
                "pair_address": pair.get("pairAddress"),
                "pool_created_at": number(pair.get("pairCreatedAt"), None),
                "price_usd": number(pair.get("priceUsd"), None),
                "liquidity_usd": liquidity,
                "observed_at": utcnow(),
                "source": "DEX Screener search",
            }
            if address not in candidates or (liquidity or 0) > (
                candidates[address]["liquidity_usd"] or 0
            ):
                candidates[address] = item
        return sorted(candidates.values(), key=lambda c: c["liquidity_usd"] or 0, reverse=True)[:12]

    async def security(self, address):
        evidence = {"observed_at": utcnow(), "rpc": None, "goplus": None, "errors": []}
        for source, fn in (("rpc", self.mint_info), ("goplus", self.goplus)):
            try:
                evidence[source] = await fn(address)
            except ProviderError as exc:
                evidence["errors"].append(str(exc))
        return evidence

    @schema_checked("rpc")
    async def mint_info(self, address):
        if urlsplit(self.settings.rpc_url).scheme != "https":
            raise ProviderError("rpc: HTTPS obligatoriu")
        data = await self.request(
            "rpc",
            "POST",
            self.settings.rpc_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [address, {"encoding": "jsonParsed", "commitment": "confirmed"}],
            },
        )
        if "error" in data:
            raise ProviderError("rpc: eroare JSON-RPC")
        account = (data.get("result") or {}).get("value")
        if not account or not isinstance(account.get("data"), dict):
            raise ProviderError("rpc: mint inexistent sau date neinterpretate")
        parsed = account["data"].get("parsed", {})
        if parsed.get("type") != "mint":
            raise ProviderError("rpc: adresa nu este un mint")
        info = parsed.get("info", {})
        return {
            "program": account.get("owner"),
            "mint_authority": info.get("mintAuthority", "unknown"),
            "freeze_authority": info.get("freezeAuthority", "unknown"),
            "extensions": info.get("extensions"),
            "slot": data.get("result", {}).get("context", {}).get("slot"),
        }

    @schema_checked("goplus")
    async def goplus(self, address):
        headers = {}
        if self.settings.goplus_token:
            headers["Authorization"] = f"Bearer {self.settings.goplus_token}"
        data = await self.request(
            "goplus",
            "GET",
            "https://api.gopluslabs.io/api/v1/solana/token_security",
            params={"contract_addresses": address},
            headers=headers,
        )
        if str(data.get("code")) != "1":
            raise ProviderError("goplus: răspuns fără succes")
        result = (data.get("result") or {}).get(address)
        if not isinstance(result, dict) or not result:
            raise ProviderError("goplus: raport indisponibil")
        return result
