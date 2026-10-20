"""Jupiter ExactIn quotes for paper only. No swap construction, signing or submission."""

import os
from decimal import ROUND_DOWN, Decimal

import httpx

from app.credentials import secret
from app.errors import ProviderError
from app.http_client import read_json
from app.models import epoch, solana_address, utcnow
from app.paper import Rejected, amount

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
D = Decimal


def raw_integer(value):
    """Accept exact integer units, never bools or rounded JSON floats."""
    if type(value) is int:
        return value
    if isinstance(value, str) and len(value) <= 20 and value.isascii() and value.isdecimal():
        return int(value)
    raise ValueError("Invalid raw integer units")


class Jupiter:
    def __init__(self, settings, onchain, client=None):
        self.settings, self.onchain = settings, onchain
        self.client = client or httpx.AsyncClient(timeout=20, follow_redirects=False)
        self.status = {"state": "unverified", "at": None}

    @property
    def enabled(self):
        return os.getenv("PAPER_SOLANA_EXECUTION", "pool") == "jupiter"

    async def close(self):
        await self.client.aclose()

    def config(self):
        return {
            "mode": "jupiter" if self.enabled else "estimated_pool",
            "api_key_present": bool(secret("JUPITER_API_KEY")),
            "status": self.status,
            "live_execution": False,
            "note": "Cotații neexecutate. Accesul fără cheie depinde de furnizor; 401/403 cer acces valid. Rețeaua și conversia au costuri presupuse. Lipsa unei rute nu produce un fill de pool.",
        }

    async def quote(self, input_mint, output_mint, raw_amount, slippage_bps=50):
        solana_address(input_mint)
        solana_address(output_mint)
        if (
            type(raw_amount) is not int
            or not 0 < raw_amount < 2**64
            or type(slippage_bps) is not int
            or not 0 <= slippage_bps <= 200
        ):
            raise Rejected("Cantitate sau slippage invalid pentru quote.")
        key = secret("JUPITER_API_KEY")
        try:
            requested_at = utcnow()
            response = await read_json(
                self.client,
                "GET",
                "https://api.jup.ag/swap/v1/quote",
                headers={"Cache-Control": "no-cache"} | ({"x-api-key": key} if key else {}),
                params={
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "amount": str(raw_amount),
                    "slippageBps": slippage_bps,
                    "swapMode": "ExactIn",
                    "restrictIntermediateTokens": "true",
                },
            )
            if (
                not isinstance(response, dict)
                or response.get("inputMint") != input_mint
                or response.get("outputMint") != output_mint
                or raw_integer(response.get("inAmount")) != raw_amount
                or response.get("swapMode") != "ExactIn"
                or type(response.get("slippageBps")) is not int
                or response.get("slippageBps") != slippage_bps
            ):
                raise ProviderError("Quote-ul nu corespunde cererii exacte.")
            out, minimum = (
                raw_integer(response["outAmount"]),
                raw_integer(response["otherAmountThreshold"]),
            )
            impact = D(str(response["priceImpactPct"]))
            if (
                not 0 < minimum <= out < 2**64
                or not impact.is_finite()
                or not 0 <= impact <= self.settings.max_price_impact
            ):
                raise Rejected("Quote cu ieșire/impact neacceptabil.")
            if minimum < int(
                (D(out) * (1 - D(slippage_bps) / 10000)).to_integral_value(rounding=ROUND_DOWN)
            ):
                raise Rejected("Pragul de ieșire nu respectă slippage-ul solicitat.")
            if (
                not isinstance(response.get("routePlan"), list)
                or not response["routePlan"]
                or type(response.get("contextSlot")) is not int
                or response["contextSlot"] <= 0
                or len(response["routePlan"]) > 100
                or any(
                    not isinstance(leg, dict) or not isinstance(leg.get("swapInfo"), dict)
                    for leg in response["routePlan"]
                )
            ):
                raise ProviderError("Ruta sau slotul quote-ului lipsesc.")
            response["observed_at"] = utcnow()
            response["request_started_at"] = requested_at
            self.status = {"state": "ok", "at": utcnow(), "error": None}
            return response
        except (ProviderError, Rejected) as exc:
            if isinstance(exc, ProviderError) and any(
                s in str(exc) for s in ["HTTP 401", "HTTP 403"]
            ):
                exc = ProviderError(
                    "Jupiter HTTP 401/403: configurează JUPITER_API_KEY cu acces valid."
                )
            self.status = {"state": "error", "at": utcnow(), "error": str(exc)}
            raise exc
        except (KeyError, ValueError, TypeError, ArithmeticError):
            self.status = {"state": "error", "at": utcnow(), "error": "Quote incompatibil."}
            raise ProviderError("Quote Jupiter incompatibil cu schema așteptată.") from None

    async def stable_book(self):
        try:
            return await self.kraken_book()
        except ProviderError as kraken_error:
            try:
                return await self.coinbase_book()
            except ProviderError as coinbase_error:
                raise ProviderError(
                    f"USDC/USD book indisponibil: Kraken ({kraken_error}); Coinbase ({coinbase_error}). Fără paritate presupusă."
                ) from None

    async def kraken_book(self):
        data = await read_json(
            self.client,
            "GET",
            "https://api.kraken.com/0/public/Depth",
            params={"pair": "USDCUSD", "count": 1},
        )
        try:
            if not isinstance(data, dict) or data.get("error") or len(data["result"]) != 1:
                raise ValueError
            pair = next(iter(data["result"]))
            if pair not in {"USDCUSD", "USDCZUSD"}:
                raise ValueError
            book = data["result"][pair]
            bid, ask = amount(book["bids"][0][0]), amount(book["asks"][0][0])
            bid_size, ask_size = amount(book["bids"][0][1]), amount(book["asks"][0][1])
            if bid > ask or 1 - bid / ask > self.settings.max_price_impact:
                raise ValueError
            return {
                "bid": bid,
                "ask": ask,
                "bid_size": bid_size,
                "ask_size": ask_size,
                "observed_at": utcnow(),
                "source": "Kraken public USDC/USD L1",
            }
        except (ValueError, TypeError, KeyError, IndexError, Rejected):
            raise ProviderError("Order book Kraken USDC/USD invalid sau indisponibil.") from None

    async def coinbase_book(self):
        data = await read_json(
            self.client,
            "GET",
            "https://api.exchange.coinbase.com/products/USDC-USD/book",
            params={"level": 1},
        )
        try:
            bid, ask = amount(data["bids"][0][0]), amount(data["asks"][0][0])
            bid_size, ask_size = amount(data["bids"][0][1]), amount(data["asks"][0][1])
            if bid > ask or 1 - bid / ask > self.settings.max_price_impact:
                raise ValueError
            return {
                "bid": bid,
                "ask": ask,
                "bid_size": bid_size,
                "ask_size": ask_size,
                "observed_at": utcnow(),
                "source": "Coinbase public USDC-USD L1",
            }
        except (ValueError, TypeError, KeyError, IndexError, Rejected):
            raise ProviderError(
                "USDC/USD book indisponibil sau invalid; nu presupunem paritate USD."
            ) from None

    async def fill(self, side, size, address, slippage_bps=50):
        solana_address(address)
        info = await self.onchain.token("solana", address, include_distribution=False)
        decimals = info["decimals"]
        if not 0 <= decimals <= 18:
            raise Rejected("Precizie de token neacceptată pentru paper.")
        book = await self.stable_book()
        size = amount(size)
        network = self.settings.network_fee_usd
        conversion_rate = self.settings.reference_fee
        if side == "buy":
            raw = int(
                (size * (1 - conversion_rate) / book["ask"] * 10**6).to_integral_value(
                    rounding=ROUND_DOWN
                )
            )
            stable = D(raw) / 10**6
            if stable > book["ask_size"]:
                raise Rejected("Bugetul depășește USDC ask size observat.")
            quoted = await self.quote(USDC, address, raw, slippage_bps)
            quantity = D(quoted["otherAmountThreshold"]) / 10**decimals
            conversion_fee = stable * book["ask"] * conversion_rate / (1 - conversion_rate)
            cash = -(stable * book["ask"] + conversion_fee + network)
        elif side == "sell":
            raw = int((size * 10**decimals).to_integral_value(rounding=ROUND_DOWN))
            if D(raw) / 10**decimals != size:
                raise Rejected("Cantitatea de ieșire depășește precizia mintului.")
            quoted = await self.quote(address, USDC, raw, slippage_bps)
            stable = D(quoted["otherAmountThreshold"]) / 10**6
            if stable > book["bid_size"]:
                raise Rejected("Ieșirea depășește USDC bid size observat.")
            quantity = size
            conversion_fee = stable * book["bid"] * conversion_rate
            cash = stable * book["bid"] - conversion_fee - network
            if cash <= 0:
                raise Rejected("Costurile depășesc ieșirea quote-ului.")
        else:
            raise Rejected("Sens necunoscut.")
        if not 0 <= epoch(utcnow()) - epoch(book["observed_at"]) <= 15:
            raise Rejected("Book-ul USDC/USD a expirat în timpul cererii.")
        return {
            "address": address,
            "side": side,
            "requested_size": str(size),
            "token_decimals": decimals,
            "quantity": str(quantity),
            "cash_change": str(cash),
            "quote_observed_at": quoted["observed_at"],
            "jupiter_quote": quoted,
            "usdc_usd_book": {k: str(v) if isinstance(v, D) else v for k, v in book.items()},
            "network_fee_usd": str(network),
            "network_fee_origin": "configured_assumption",
            "conversion_fee_usd": str(conversion_fee),
            "conversion_fee_origin": "configured_assumption",
            "swap_fee_usd": None,
            "swap_fee_origin": "included_in_route_outAmount; fees retained per feeMint in routePlan, not counted again",
            "price_impact": str(quoted["priceImpactPct"]),
            "slippage_bps": quoted.get("slippageBps", 50),
            "fill_assumption": "conservative_otherAmountThreshold",
            "model": "jupiter_quote_conservative_min_out",
            "execution_verified": False,
        }
