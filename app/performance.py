"""Forward paper measurements, including missing valuations and explicit BTC scenarios."""

import asyncio
import json
from decimal import Decimal as D

from app.models import freshness, utcnow


class Performance:
    def __init__(self, service):
        self.service = service
        self.status = {"state": "unverified", "at": None, "error": None}
        self.account_status = {}
        for store in (service.store, service.news_paper):
            with store.connect() as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS equity_observations(id INTEGER PRIMARY KEY,at TEXT NOT NULL,equity TEXT,cash TEXT NOT NULL,btc_price TEXT,context TEXT NOT NULL)"
                )

    def safe_observe(self, account):
        try:
            self.observe(account)
            self.account_status[account] = {"state": "ok", "at": utcnow(), "error": None}
        except Exception as exc:
            self.account_status[account] = {
                "state": "error",
                "at": utcnow(),
                "error": type(exc).__name__,
            }
        failures = {k: v["error"] for k, v in self.account_status.items() if v["state"] == "error"}
        self.status = {
            "state": "error" if failures else "ok",
            "at": utcnow(),
            "error": failures or None,
            "accounts": dict(self.account_status),
        }

    async def run(self):
        while True:
            for account in ("scanner", "news"):
                self.safe_observe(account)
            await asyncio.sleep(60)

    def observe(self, account):
        store = self.service.paper_store(account)
        portfolio = self.service.portfolio(account)
        btc = None
        if self.service.assets:
            for point in reversed(self.service.assets.history("bitcoin")):
                if (
                    not point.get("book")
                    and freshness(
                        point.get("observed_at"),
                        point.get("source_updated_at"),
                        self.service.settings.max_snapshot_age,
                    )["fresh"]
                ):
                    btc = str(point["price_usd"])
                    break
        context = {
            "open_positions": sum(not p["closed_at"] for p in portfolio["positions"]),
            "valuation_complete": portfolio["estimated_equity_usd"] is not None,
            "fee": str(self.service.settings.reference_fee),
            "slippage": str(self.service.settings.reference_slippage),
            "benchmark_source": "CoinGecko reference scenario",
        }
        with store.connect() as db:
            db.execute(
                "INSERT INTO equity_observations(at,equity,cash,btc_price,context) VALUES(?,?,?,?,?)",
                (
                    utcnow(),
                    portfolio["estimated_equity_usd"],
                    portfolio["cash"],
                    btc,
                    json.dumps(context),
                ),
            )

    def report(self, account):
        store = self.service.paper_store(account)
        p = self.service.portfolio(account)
        with store.connect() as db:
            points = [
                dict(r) | {"context": json.loads(r["context"])}
                for r in db.execute("SELECT * FROM equity_observations ORDER BY id DESC LIMIT 5000")
            ][::-1]
            total_points = db.execute("SELECT COUNT(*) FROM equity_observations").fetchone()[0]
            signals = db.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
            used = db.execute("SELECT COUNT(DISTINCT signal_id) FROM positions").fetchone()[0]
            failures = db.execute("SELECT COUNT(*) FROM orders WHERE status='failed'").fetchone()[0]
        closed = [x for x in p["positions"] if x["closed_at"]]
        wins = sum(D(x["pnl"]) > 0 for x in closed)
        peak, drawdown = D(0), D(0)
        for point in points:
            if point["equity"] is not None:
                value = D(point["equity"])
                peak = max(peak, value)
                if peak > 0:
                    drawdown = max(drawdown, (peak - value) / peak * 100)
        aligned = [x for x in points if x["equity"] is not None and x["btc_price"] is not None]
        comparison = None
        if (
            len(aligned) >= 2
            and points[-1]["equity"] is not None
            and points[-1]["btc_price"] is not None
        ):
            first, last = aligned[0], aligned[-1]
            if D(first["equity"]) > 0:
                costs = first["context"]
                factor = (
                    (1 - D(costs["fee"]))
                    * (1 - D(last["context"]["fee"]))
                    * (1 - D(last["context"]["slippage"]))
                    / (1 + D(costs["slippage"]))
                )
                comparison = {
                    "from": first["at"],
                    "to": last["at"],
                    "portfolio_return_pct": str((D(last["equity"]) / D(first["equity"]) - 1) * 100),
                    "btc_scenario_return_pct": str(
                        (D(last["btc_price"]) / D(first["btc_price"]) * factor - 1) * 100
                    ),
                    "model": "BTC reference, assumed fees/slippage; not an executable quote",
                    "aligned_observations": len(aligned),
                }
        equity = p["estimated_equity_usd"]
        return {
            "account": account,
            "initial_balance": p["initial_balance"],
            "cash": p["cash"],
            "estimated_equity_usd": equity,
            "realized_pnl_usd": p["realized_pnl_usd"],
            "estimated_total_return_pct": str((D(equity) / D(p["initial_balance"]) - 1) * 100)
            if equity is not None
            else None,
            "closed_trades": len(closed),
            "open_trades": len(p["positions"]) - len(closed),
            "wins": wins,
            "win_rate_closed_only_pct": str(D(wins) / len(closed) * 100) if closed else None,
            "failed_attempts": failures,
            "signals_total": signals,
            "signals_without_trade": signals - used,
            "max_observed_drawdown_pct": str(drawdown)
            if len([x for x in points if x["equity"] is not None]) >= 2
            else None,
            "observations_total": total_points,
            "observations_in_report": len(points),
            "missing_valuations": sum(x["equity"] is None for x in points),
            "history_truncated": total_points > len(points),
            "comparison": comparison,
            "recent_points": points[-240:],
            "note": "Drawdown din observațiile disponibile; intervalele fără evaluare și perioada netestată nu sunt acoperite. Win rate include doar pozițiile închise. Nu demonstrează un avantaj financiar.",
        }
