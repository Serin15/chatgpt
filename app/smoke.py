"""Read-only integration check. Wrapped SOL is an infrastructure fixture, not a recommendation."""

import asyncio
import time

from app.analysis import analyze
from app.config import Settings
from app.providers import ProviderError, Providers


async def main():
    settings = Settings.from_environment()
    providers = Providers(settings)
    try:
        discovered = await providers.discover()
        print(f"Live discovery: {len(discovered)} valid Solana profile addresses")
        market = await providers.market("So11111111111111111111111111111111111111112")
        security = await providers.security(market.address)
        result = analyze(market, security, settings, time.time())
        print(
            f"Wrapped SOL infrastructure check: price={market.price_usd}, liquidity={market.liquidity_usd}"
        )
        print(
            f"RPC available: {security['rpc'] is not None}; GoPlus available: {security['goplus'] is not None}"
        )
        if not result["paper_allowed"]:
            print("FAILED: basic evidence is incomplete or a veto is present.")
            for error in security["errors"]:
                print(error)
            return 1
        print(
            "PASS: market ingestion and basic security interpretation. No trading/quotes executed."
        )
        return 0
    except ProviderError as exc:
        print(f"FAILED: {exc}")
        return 1
    finally:
        await providers.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
