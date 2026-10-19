import asyncio
import json
import logging
import time
from dataclasses import replace
from decimal import Decimal

from app import paper
from app.analysis import analyze
from app.auth import Auth
from app.discovery import Discovery
from app.forward import Forward
from app.fundamentals import Fundamentals
from app.jupiter import Jupiter
from app.listings import Listings
from app.models import Market, epoch, freshness, utcnow
from app.notifications import Notifications
from app.onchain import Onchain
from app.opportunities import Opportunities
from app.performance import Performance
from app.providers import ProviderError
from app.research import Research
from app.store import Store
from app.wallets import Wallets

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
        self.assets = None
        self.research = Research(store)
        self.performance = Performance(self)
        self.auth = Auth(store)
        self.onchain = Onchain(settings)
        self.discovery = Discovery(store)
        self.fundamentals = Fundamentals(self, self.onchain)
        self.wallets = Wallets(store, self.onchain)
        self.jupiter = Jupiter(settings, self.onchain)
        self.listings = Listings(self)
        self.notifications = Notifications(self)
        self.forward = Forward(self)
        self.opportunities = Opportunities(self)

    def frozen_rules(self):
        return {
            key: str(getattr(self.settings, key))
            for key in (
                "swap_fee",
                "network_fee_usd",
                "reference_fee",
                "reference_slippage",
                "max_price_impact",
                "min_liquidity",
            )
        }

    async def run_intelligence(self):
        await self.opportunities.run()

    async def close_intelligence(self):
        await self.opportunities.close()
        for source in (self.onchain, self.discovery, self.jupiter, self.notifications):
            await source.close()

    def reference_analysis(self, asset):
        fresh = freshness(
            asset.get("observed_at"), asset.get("source_updated_at"), self.settings.max_snapshot_age
        )["fresh"]
        return {
            "paper_allowed": fresh
            and (bool(asset.get("book")) or (asset.get("volume_24h") or 0) > 0),
            "scope": "reference_price_scenario_not_token_security",
            "fundamentals_verified": False,
            "critical": [],
            "unknown": [
                "Fundamentele proiectului nu au fost evaluate",
                "Prețul nu garantează execuția unui ordin",
            ],
            "warnings": [
                "Comisionul este o presupunere configurabilă",
                "Fără order book, slippage este estimat",
            ],
            "action": "investigate" if fresh else "monitor",
        }

    async def asset_snapshot(self, asset_id):
        asset = await self.assets.quote(asset_id)
        if not asset.get("book"):
            self.assets.invalidate_book(asset_id)
        return self.news_paper.save_reference(asset, self.reference_analysis(asset))

    async def asset_signal(self, asset_id, news_id=None, thesis=""):
        snapshot = await self.asset_snapshot(asset_id)
        context = {"paper_account": "news", "thesis": thesis, "asset_kind": "market_asset"}
        context["rules_at_signal"] = self.frozen_rules()
        context["paper_execution_mode"] = "reference"
        context["research_context"] = self.research.case(snapshot["address"])
        if news_id:
            try:
                context["news_context"] = self.news.context(news_id, snapshot["address"])
            except ValueError as exc:
                raise paper.Rejected(str(exc)) from None
        context["ai_context"] = self.research.ai.history(
            snapshot["address"], context.get("news_context", {}).get("id")
        )
        return self.news_paper.signal(snapshot, context) | {"snapshot": snapshot}

    async def asset_buy(self, body):
        address = "asset:" + body.asset_id
        try:
            snapshot = await self.asset_snapshot(body.asset_id)
            order = paper.buy(
                self.news_paper, snapshot, body.signal_id, body.amount_usd, self.settings
            )
            self.performance.safe_observe("news")
            return order
        except (ProviderError, paper.Rejected) as exc:
            self.news_paper.failed_order(address, "buy", str(exc))
            raise

    def paper_store(self, account):
        return self.news_paper if account == "news" else self.store

    def copy_for_paper(self, snapshot, account):
        if account == "scanner":
            return snapshot
        market = Market(**snapshot["market"])
        self.news_paper.save_snapshot(market, snapshot["security"], snapshot["analysis"])
        return self.news_paper.latest(market.address)

    def signal(self, address, account, news_id=None, thesis=""):
        snapshot = self.store.latest(address)
        if not snapshot:
            raise paper.Rejected("Token fără observații de piață.")
        context = {"paper_account": account, "thesis": thesis}
        context["rules_at_signal"] = self.frozen_rules()
        context["paper_execution_mode"] = "jupiter" if self.jupiter.enabled else "estimated_pool"
        context["research_context"] = self.research.case(address)
        if news_id:
            try:
                context["news_context"] = self.news.context(news_id, address)
            except ValueError as exc:
                raise paper.Rejected(str(exc)) from None
        context["ai_context"] = self.research.ai.history(
            address, context.get("news_context", {}).get("id")
        )
        saved_snapshot = self.copy_for_paper(snapshot, account)
        return self.paper_store(account).signal(saved_snapshot, context) | {
            "snapshot": saved_snapshot
        }

    def portfolio(self, account):
        portfolio = self.paper_store(account).portfolio() | {"account": account}
        for position in portfolio["positions"]:
            position["valuation"] = None
            position["kind"] = (
                "market_asset" if position["address"].startswith("asset:") else "dex_token"
            )
            if position["closed_at"]:
                continue
            if position["kind"] == "market_asset":
                asset = self.assets.get(position["address"][6:]) if self.assets else None
                snapshot = {"at": asset["observed_at"], "market": asset} if asset else None
                current = self.reference_analysis(asset) if asset else {"paper_allowed": False}
                with self.paper_store(account).connect() as db:
                    entry = db.execute(
                        "SELECT market FROM snapshots WHERE id=?", (position["entry_snapshot_id"],)
                    ).fetchone()
                if entry and json.loads(entry[0]).get("book") and asset and not asset.get("book"):
                    current["paper_allowed"] = False
            else:
                snapshot = self.store.latest(position["address"])
                current = (
                    analyze(
                        Market(**snapshot["market"]),
                        snapshot["security"],
                        self.settings,
                        time.time(),
                    )
                    if snapshot
                    else {"paper_allowed": False}
                )
            if not snapshot:
                continue
            market = snapshot["market"]
            position["symbol"] = market["symbol"]
            position["name"] = market["name"]
            valuation = {
                "observed_at": snapshot["at"],
                "indicative_value_usd": str(
                    Decimal(position["quantity"]) * Decimal(str(market["price_usd"]))
                ),
                "estimated_exit_proceeds_usd": None,
                "estimated_unrealized_pnl_usd": None,
                "exit_simulation_available": False,
            }
            with self.paper_store(account).connect() as db:
                entry_order = db.execute(
                    "SELECT details FROM orders WHERE side='buy' AND json_extract(details,'$.position_id')=?",
                    (position["id"],),
                ).fetchone()
            if (
                entry_order
                and json.loads(entry_order[0]).get("model") == "jupiter_quote_conservative_min_out"
            ):
                current["paper_allowed"] = False
                valuation["note"] = (
                    "Necesită un quote Jupiter nou; nu înlocuim ruta cu o estimare de pool."
                )
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
        portfolio["realized_pnl_usd"] = str(
            sum((Decimal(p["pnl"]) for p in portfolio["positions"] if p["closed_at"]), Decimal(0))
        )
        open_positions = [p for p in portfolio["positions"] if not p["closed_at"]]
        portfolio["estimated_equity_usd"] = (
            str(
                Decimal(portfolio["cash"])
                + sum(
                    (
                        Decimal(p["valuation"]["estimated_exit_proceeds_usd"])
                        for p in open_positions
                    ),
                    Decimal(0),
                )
            )
            if all(
                p["valuation"] and p["valuation"]["estimated_exit_proceeds_usd"] is not None
                for p in open_positions
            )
            else None
        )
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

    async def scan(self, discover=True):
        if self.scan_lock.locked():
            return self.scan_status
        async with self.scan_lock:
            self.scan_status |= {"running": True, "error": None}
            try:
                try:
                    if discover:
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
                held = [address for address in held if not address.startswith("asset:")]
                tracked = await asyncio.to_thread(self.store.tokens)
                addresses = list(
                    dict.fromkeys(held + [t["address"] for t in tracked if discover or t["watch"]])
                )[:30]
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
                await self.scan(discover=not self.opportunities.config().enabled)
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
        held = {
            p["address"]
            for store in (self.store, self.news_paper)
            for p in store.portfolio()["positions"]
            if not p["closed_at"]
        }
        tokens = self.store.tokens()
        chosen = [t for t in tokens if t["address"] in held or t["watch"]]
        chosen_ids = {t["address"] for t in chosen}
        chosen += [t for t in tokens if t["address"] not in chosen_ids][: max(0, 100 - len(chosen))]
        for token in chosen:
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
            execution = (
                await self.jupiter.fill("buy", request.amount_usd, request.address)
                if self.jupiter.enabled
                else None
            )
            order = paper.buy(
                store,
                self.copy_for_paper(current, request.account),
                request.signal_id,
                request.amount_usd,
                self.settings,
                execution=execution,
            )
            self.performance.safe_observe(request.account)
            return order
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
            if position["address"].startswith("asset:"):
                current = await self.asset_snapshot(position["address"][6:])
                order = paper.sell(store, position_id, current, self.settings)
                self.performance.safe_observe(account)
                return order
            current = await self.refresh(position["address"])
            execution = (
                await self.jupiter.fill("sell", position["quantity"], position["address"])
                if self.jupiter.enabled
                else None
            )
            order = paper.sell(
                store,
                position_id,
                self.copy_for_paper(current, account),
                self.settings,
                execution=execution,
            )
            self.performance.safe_observe(account)
            return order
        except (ProviderError, paper.Rejected) as exc:
            store.failed_order(position["address"], "sell", str(exc))
            raise
