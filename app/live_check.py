"""Real read-only source checks in temporary databases. Never places paper or real orders."""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from app.assets import Assets
from app.config import Settings
from app.models import utcnow
from app.news import News
from app.providers import Providers
from app.service import Service
from app.store import Store


async def collect():
    with tempfile.TemporaryDirectory(prefix="pulse-live-advanced-") as folder:
        settings = Settings(data_dir=Path(folder))
        providers = Providers(settings)
        service = Service(settings, Store(settings), providers)
        service.assets = Assets(service.store)
        service.news = News(service.store, providers)
        report = {"at": utcnow(), "real_requests": True, "orders_executed": 0}

        async def run(name, call):
            try:
                value = await call()
                partial = bool(value.get("distribution_error")) or any(
                    s.get("state") != "ok" for s in value.get("sources", {}).values()
                )
                report[name] = {
                    "state": "partial" if partial else "ok",
                    "result": value,
                }
            except Exception as e:
                from app.errors import ProviderError

                report[name] = {
                    "state": "blocked" if isinstance(e, ProviderError) else "error",
                    "error": str(e)[:300] if isinstance(e, ProviderError) else type(e).__name__,
                }

        try:
            await asyncio.gather(
                run("discovery", lambda: service.discovery.refresh()),
                run(
                    "circle_base",
                    lambda: service.fundamentals.circle_usdc(
                        "base", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
                    ),
                ),
                run(
                    "circle_solana",
                    lambda: service.fundamentals.circle_usdc(
                        "solana", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
                    ),
                ),
                run(
                    "solana_rpc",
                    lambda: service.onchain.token(
                        "solana", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
                    ),
                ),
                run(
                    "base_rpc",
                    lambda: service.onchain.token(
                        "base", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
                    ),
                ),
                run(
                    "venues_solana",
                    lambda: service.listings.venues("So11111111111111111111111111111111111111112"),
                ),
                run(
                    "venues_base",
                    lambda: service.listings.venues(
                        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "base"
                    ),
                ),
            )
            return report
        finally:
            await providers.close()
            await service.assets.close()
            await service.news.close()
            await service.research.close()
            await service.close_intelligence()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(collect())
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    if any(isinstance(v, dict) and v.get("state") != "ok" for v in report.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
