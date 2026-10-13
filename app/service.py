import asyncio
import logging
import time
from dataclasses import replace
from decimal import Decimal

from app import paper
from app.analysis import analyze
from app.models import Market, epoch, utcnow
from app.providers import ProviderError
from app.store import Store

log = logging.getLogger(__name__)


class Service:
    def __init__(self, settings, store, providers):
        self.settings, self.store, self.providers = settings, store, providers
        self.scan_lock = asyncio.Lock()
        self.refresh_locks = {}
        self.scan_status = {"running": False, "last_completed_at": None, "error": None}
        self.news_paper = Store(
            replace(
                settings, data_dir=settings.data_dir / "news_paper", initial_balance=Decimal(500)
            )
        )
        self.news = None

    def paper_store(self, account):
        return self.news_paper if account == "news" else self.store

    def copy_for_paper(self, snapshot, account):
        if account == "scanner":
            return snapshot
        market = Market(**snapshot["market"])
        self.news_paper.save_snapshot(market, snapshot["security"], snapshot["analysis"])
        return self.news_paper.latest(market.address)

    def signal(self, address, account, news_id=None):
        snapshot = self.store.latest(address)
        if not snapshot:
            raise paper.Rejected("Token fără observații de piață.")
        context = {"paper_account": account}
        if news_id:
            try:
                context["news_context"] = self.news.context(news_id, address)
            except ValueError as exc:
                raise paper.Rejected(str(exc)) from None
        return self.paper_store(account).signal(self.copy_for_paper(snapshot, account), context)

    def portfolio(self, account):
        portfolio = self.paper_store(account).portfolio() | {"account": account}
        for position in portfolio["positions"]:
            position["valuation"] = None
            if position["closed_at"]:
                continue
            snapshot = self.store.latest(position["address"])
            if not snapshot:
                continue
            market = Market(**snapshot["market"])
            current = analyze(market, snapshot["security"], self.settings, time.time())
            valuation = {
                "observed_at": snapshot["at"],
                "indicative_value_usd": str(
                    Decimal(position["quantity"]) * Decimal(str(market.price_usd))
                ),
                "estimated_exit_proceeds_usd": None,
                "estimated_unrealized_pnl_usd": None,
                "exit_simulation_available": False,
            }
            if current["paper_allowed"]:
                try:
                    quote = paper.fill(
                        "sell", position["quantity"], snapshot["market"], self.settings
                    )
                    valuation |= {
                        "exit_simulation_available": True,
                        "estimated_exit_proceeds_usd": quote["cash_change"],
                        "estimated_unrealized_pnl_usd": str(
                            Decimal(quote["cash_change"]) - Decimal(position["entry_cost"])
                        ),
                    }
                except paper.Rejected:
                    pass
            position["valuation"] = valuation
        return portfolio

    async def refresh(self, address):
        lock = self.refresh_locks.setdefault(address, asyncio.Lock())
        async with lock:
            try:
                market = await self.providers.market(address)
                security = await self.providers.security(address)
                analysis = analyze(market, security, self.settings, time.time())
                self.store.save_snapshot(market, security, analysis)
                return self.store.latest(address)
            except ProviderError as exc:
                self.store.set_error(address, str(exc))
                raise

    async def scan(self):
        if self.scan_lock.locked():
            return self.scan_status
        async with self.scan_lock:
            self.scan_status |= {"running": True, "error": None}
            try:
                try:
                    for address in await self.providers.discover():
                        self.store.add_token(address, "latest_profile")
                except ProviderError as exc:
                    self.scan_status["error"] = str(exc)
                # Preserve holdings/watchlist monitoring; then refresh recent profile candidates.
                held = [
                    p["address"] for p in self.store.portfolio()["positions"] if not p["closed_at"]
                ]
                held += [
                    p["address"]
                    for p in self.news_paper.portfolio()["positions"]
                    if not p["closed_at"]
                ]
                addresses = list(dict.fromkeys(held + [t["address"] for t in self.store.tokens()]))[
                    :30
                ]
                for address in addresses:
                    try:
                        await self.refresh(address)
                    except ProviderError:
                        continue
                self.scan_status["last_completed_at"] = utcnow()
            finally:
                self.scan_status["running"] = False
        return self.scan_status

    async def run(self):
        while True:
            try:
                await self.scan()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Exclude exception messages which could include authenticated provider URLs.
                log.error("Scanner failure: %s", type(exc).__name__)
                self.scan_status["error"] = "Eroare internă scanner; verifică logurile."
            await asyncio.sleep(self.settings.scan_interval_seconds)

    def listing(self):
        now = time.time()
        output = []
        for token in self.store.tokens()[:100]:
            snapshot = self.store.latest(token["address"])
            if snapshot:
                snapshot["analysis"] = analyze(
                    Market(**snapshot["market"]), snapshot["security"], self.settings, now
                )
            output.append(
                token
                | {
                    "snapshot": snapshot,
                    "age_seconds": round(now - epoch(snapshot["at"])) if snapshot else None,
                }
            )
        return sorted(
            output,
            key=lambda t: (
                t["snapshot"]["analysis"]["scores"]["research_priority"] if t["snapshot"] else -1
            ),
            reverse=True,
        )

    async def paper_buy(self, request):
        store = self.paper_store(request.account)
        try:
            current = await self.refresh(request.address)
            return paper.buy(
                store,
                self.copy_for_paper(current, request.account),
                request.signal_id,
                request.amount_usd,
                self.settings,
            )
        except (ProviderError, paper.Rejected) as exc:
            store.failed_order(request.address, "buy", str(exc))
            raise

    async def paper_sell(self, position_id, account="scanner"):
        store = self.paper_store(account)
        position = next(
            (
                p
                for p in store.portfolio()["positions"]
                if p["id"] == position_id and not p["closed_at"]
            ),
            None,
        )
        if not position:
            raise paper.Rejected("Poziție deschisă inexistentă.")
        try:
            current = await self.refresh(position["address"])
            return paper.sell(
                store, position_id, self.copy_for_paper(current, account), self.settings
            )
        except (ProviderError, paper.Rejected) as exc:
            store.failed_order(position["address"], "sell", str(exc))
            raise
