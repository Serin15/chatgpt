"""Read-only integration check. Wrapped SOL is an infrastructure fixture, not a recommendation."""

import asyncio
import time

from app.analysis import analyze
from app.assets import Assets
from app.config import Settings
from app.news import News
from app.providers import ProviderError, Providers
from app.store import Store


async def main():
    settings = Settings.from_environment()
    providers = Providers(settings)
    assets = Assets(Store(settings))
    news = News(assets.store, providers)
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
        status = await assets.refresh()
        if status["state"] != "ok":
            print("FAILED: general crypto market unavailable.")
            return 1
        quote = await assets.quote("bitcoin")
        print(
            f"General crypto: {len(assets.listing())} cached assets; BTC public book available: {quote['book'] is not None}"
        )
        items = await news.feed("coindesk")
        print(
            f"Publisher RSS: {len(items)} recent CoinDesk headlines; article contents remain unverified."
        )
        print(
            "PASS: market references, news metadata and basic Solana security. No orders or transactions executed."
        )
        return 0
    except ProviderError as exc:
        print(f"FAILED: {exc}")
        return 1
    finally:
        await providers.close()
        await assets.close()
        await news.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
