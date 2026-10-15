"""Read-only Solana/Base RPC. Chain identity is checked before Base observations."""

import asyncio
import os
import re
import time
from urllib.parse import urlsplit

import httpx

from app.errors import ProviderError
from app.http_client import read_json
from app.models import solana_address, utcnow

READ_METHODS = {
    "solana": {
        "getAccountInfo",
        "getTokenSupply",
        "getTokenLargestAccounts",
        "getSignaturesForAddress",
        "getTransaction",
        "getRecentPrioritizationFees",
    },
    "base": {
        "eth_chainId",
        "eth_blockNumber",
        "eth_getCode",
        "eth_call",
        "eth_getLogs",
        "eth_getTransactionByHash",
        "eth_getTransactionReceipt",
        "eth_getBalance",
    },
}


def chain_address(chain, address):
    if chain == "solana":
        return solana_address(address)
    if chain == "base" and re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
        return address.lower()
    raise ValueError("Chain sau adresă invalidă; sunt acceptate Solana și Base.")


class Onchain:
    def __init__(self, settings, client=None):
        self.client = client or httpx.AsyncClient(timeout=20, follow_redirects=False)
        self.urls = {
            "solana": settings.rpc_url,
            "base": os.getenv("BASE_RPC_URL", "https://mainnet.base.org"),
        }
        self.locks = {chain: asyncio.Lock() for chain in self.urls}
        self.last = {}
        self.status = {}
        self.base_checked = False

    async def close(self):
        await self.client.aclose()

    async def rpc(self, chain, method, params):
        if method not in READ_METHODS.get(chain, set()):
            raise ProviderError("Metodă RPC nepermisă; adaptorul permite exclusiv citire.")
        if urlsplit(self.urls[chain]).scheme != "https":
            raise ProviderError("RPC necesită HTTPS.")
        if chain == "base" and method != "eth_chainId" and not self.base_checked:
            identity = await self.rpc("base", "eth_chainId", [])
            if identity != "0x2105":
                self.status[chain] = {
                    "state": "error",
                    "at": utcnow(),
                    "error": "RPC-ul nu este Base mainnet (8453).",
                }
                raise ProviderError("RPC-ul configurat nu este Base mainnet (8453).")
            self.base_checked = True
        async with self.locks[chain]:
            delay = 0.35 - (time.monotonic() - self.last.get(chain, 0))
            if delay > 0:
                await asyncio.sleep(delay)
            self.last[chain] = time.monotonic()
            try:
                data = await read_json(
                    self.client,
                    "POST",
                    self.urls[chain],
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                )
                if not isinstance(data, dict) or data.get("error") or "result" not in data:
                    raise ProviderError(
                        "RPC nu a returnat un rezultat utilizabil; acoperirea rămâne incompletă."
                    )
                self.status[chain] = {"state": "ok", "at": utcnow(), "error": None}
                return data["result"]
            except ProviderError as exc:
                self.status[chain] = {"state": "error", "at": utcnow(), "error": str(exc)}
                raise

    async def token(self, chain, address, include_distribution=True):
        address = chain_address(chain, address)
        try:
            return await self._token(chain, address, include_distribution)
        except ProviderError as exc:
            self.status[chain] = {"state": "error", "at": utcnow(), "error": str(exc)}
            raise
        except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError):
            self.status[chain] = {
                "state": "error", "at": utcnow(),
                "error": "Răspuns RPC incompatibil cu schema unui token.",
            }
            raise ProviderError("Răspuns RPC incompatibil cu schema unui token.") from None

    async def _token(self, chain, address, include_distribution):
        if chain == "solana":
            result = await self.rpc(
                chain,
                "getAccountInfo",
                [address, {"encoding": "jsonParsed", "commitment": "confirmed"}],
            )
            account = result.get("value") if isinstance(result, dict) else None
            parsed = (account or {}).get("data", {})
            parsed = parsed.get("parsed", {}) if isinstance(parsed, dict) else {}
            if parsed.get("type") != "mint":
                raise ProviderError("Adresa nu este un mint Solana interpretabil.")
            info = parsed["info"]
            supply = int(info["supply"])
            if (
                supply < 0
                or not 0 <= int(info["decimals"]) <= 255
                or account["owner"]
                not in {
                    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
                }
            ):
                raise ValueError("Invalid mint fields")
            distribution_error, balances = None, []
            if include_distribution:
                try:
                    largest = await self.rpc(
                        chain, "getTokenLargestAccounts", [address, {"commitment": "confirmed"}]
                    )
                    balances = [int(row["amount"]) for row in largest["value"]]
                    if len(balances) > 20 or any(b < 0 for b in balances):
                        raise ValueError("Invalid largest accounts")
                except ProviderError as exc:
                    distribution_error = str(exc)
                except (ValueError, TypeError, KeyError, AttributeError):
                    distribution_error = "Distribuție RPC incompatibilă; procent necunoscut."
            total_top = sum(sorted(balances, reverse=True)[:10])
            valid_supply = (
                include_distribution
                and not distribution_error
                and supply > 0
                and total_top <= supply
            )
            return {
                "chain": chain,
                "contract": address,
                "observed_at": utcnow(),
                "origin": "rpc_observation",
                "slot": result.get("context", {}).get("slot"),
                "decimals": int(info["decimals"]),
                "raw_supply": str(supply),
                "program": account["owner"],
                "mint_authority": info.get("mintAuthority", "unknown"),
                "freeze_authority": info.get("freezeAuthority", "unknown"),
                "top10_token_accounts_pct": 100 * total_top / supply if valid_supply else None,
                "distribution_error": distribution_error,
                "distribution_note": "Conturi de token, nu proprietari unici. LP/custodie nu sunt excluse; acoperire maximum 20 conturi. Supply nativ/inconsistent nu produce procent.",
                "audit_verified": False,
                "sellability_verified": False,
            }
        code = await self.rpc(chain, "eth_getCode", [address, "latest"])
        if not isinstance(code, str) or code in {"0x", "0x0"}:
            raise ProviderError("La această adresă nu există bytecode pe Base mainnet.")
        decimals = await self.rpc(
            chain, "eth_call", [{"to": address, "data": "0x313ce567"}, "latest"]
        )
        supply = await self.rpc(
            chain, "eth_call", [{"to": address, "data": "0x18160ddd"}, "latest"]
        )
        decimals, supply = int(decimals, 16), int(supply, 16)
        if not 0 <= decimals <= 255:
            raise ProviderError("Decimale ERC-20 invalide.")
        return {
            "chain": chain,
            "contract": address,
            "observed_at": utcnow(),
            "origin": "rpc_observation",
            "chain_id": 8453,
            "bytecode_present": True,
            "decimals": decimals,
            "raw_supply": str(supply),
            "distribution": None,
            "upgradeability": "unknown",
            "audit_verified": False,
            "sellability_verified": False,
        }
