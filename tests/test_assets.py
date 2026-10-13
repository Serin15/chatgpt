import asyncio
import time
from datetime import UTC, datetime
from decimal import Decimal as D

import httpx
import pytest
from fastapi.testclient import TestClient

from app.assets import Assets, parse_asset, research_case
from app.main import create_app
from app.paper import Rejected, fill
from tests.test_news import FixtureNews, NewsFixtureProviders


def cg_asset(price=100):
    return {
        "id": "bitcoin",
        "name": "Bitcoin",
        "symbol": "btc",
        "current_price": price,
        "market_cap": 1000000,
        "total_volume": 100000,
        "price_change_percentage_24h": 1,
        "market_cap_rank": 1,
        "last_updated": datetime.now(UTC).isoformat(),
    }


class FixtureAssets(Assets):
    async def refresh(self):
        self.save(parse_asset(cg_asset()))
        self.status = {"state": "ok", "at": datetime.now(UTC).isoformat(), "error": None}
        return self.status

    async def quote(self, asset_id):
        if asset_id != "bitcoin":
            raise ValueError("Fixture asset not configured")
        asset = parse_asset(cg_asset())
        asset["book"] = {
            "bid": "99",
            "ask": "100",
            "bid_size": "100",
            "ask_size": "100",
            "observed_at": asset["observed_at"],
            "source": "explicit fixture order book",
        }
        self.save(asset)
        return asset

    async def venues(self, asset_id):
        return [
            {
                "name": "Fixture Exchange",
                "pair": "BTC/USD",
                "url": "https://example.org/fixture",
                "observed_at": datetime.now(UTC).isoformat(),
                "execution_verified": False,
            }
        ]

    async def profile(self, asset_id):
        return {
            "asset_id": asset_id,
            "documents": [
                {
                    "label": "Fixture website",
                    "url": "https://example.org/fixture",
                    "status": "provider_reported_not_independently_verified",
                }
            ],
            "contracts": {},
            "fundamentals_verified": False,
        }


def test_market_reference_is_not_fundamental_evidence():
    asset = parse_asset(cg_asset())
    assert asset["kind"] == "market_asset"
    assert asset["address"] == "asset:bitcoin"
    assert not research_case(asset)["fundamentals_verified"]
    assert all(c["status"] == "unknown" for c in research_case(asset)["checks"])


@pytest.mark.parametrize("price", [0, -1, float("nan"), float("inf")])
def test_invalid_market_price_rejected(price):
    with pytest.raises(ValueError):
        parse_asset(cg_asset(price))


def test_orderbook_spread_fees_and_depth(settings):
    asset = parse_asset(cg_asset())
    asset["book"] = {"bid": "99", "ask": "100", "bid_size": "100", "ask_size": "100"}
    entry = fill("buy", "50", asset, settings)
    assert entry["cash_change"] == "-50"
    assert D(entry["quantity"]) == D("0.497")
    exit_order = fill("sell", entry["quantity"], asset, settings)
    assert D(exit_order["cash_change"]) < D("49")
    assert entry["model"] == "observed_level1_book_assumed_fee"
    assert not entry["execution_verified"]
    asset["book"]["ask_size"] = "0.1"
    with pytest.raises(Rejected, match="cantitatea ask"):
        fill("buy", "50", asset, settings)


def test_missing_book_is_explicit_scenario(settings):
    asset = parse_asset(cg_asset())
    entry = fill("buy", "50", asset, settings)
    assert entry["model"] == "market_reference_assumed_slippage_and_fee"
    assert entry["book"] is None
    assert not entry["execution_verified"]
    assert D(fill("sell", entry["quantity"], asset, settings)["cash_change"]) < D(50)


def test_inverted_orderbook_rejected(settings):
    asset = parse_asset(cg_asset())
    asset["book"] = {"bid": "101", "ask": "100", "bid_size": "100", "ask_size": "100"}
    with pytest.raises(Rejected, match="inversat"):
        fill("buy", "50", asset, settings)


def test_live_payload_parsers_with_mock_transport(settings, store):
    async def run():
        def handler(request):
            if "coinbase" in request.url.host:
                return httpx.Response(
                    200,
                    json={
                        "bids": [["99", "100", 1]],
                        "asks": [["100", "100", 1]],
                        "time": datetime.now(UTC).isoformat(),
                    },
                )
            return httpx.Response(200, json=[cg_asset()])

        assets = Assets(store, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            assert (await assets.refresh())["state"] == "ok"
            quote = await assets.quote("bitcoin")
            assert quote["book"]["bid"] == "99"
            assert len(assets.history("bitcoin")) == 2
        finally:
            await assets.close()

    asyncio.run(run())


def test_stale_and_anomalous_venues_filtered(settings, store):
    async def run():
        tickers = [
            {
                "coin_id": "bitcoin",
                "market": {"name": "Good"},
                "base": "BTC",
                "target": "USD",
                "trade_url": "https://example.org/trade",
            },
            {"coin_id": "bitcoin", "trade_url": "https://example.org/stale", "is_stale": True},
            {"coin_id": "different-coin", "trade_url": "https://example.org/wrong"},
            {"coin_id": "bitcoin", "trade_url": "https://username:password@example.org/private"},
        ]
        assets = Assets(
            store,
            httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(200, json={"tickers": tickers})
                )
            ),
        )
        try:
            result = await assets.venues("bitcoin")
            assert len(result) == 1
            assert result[0]["name"] == "Good"
            assert not result[0]["execution_verified"]
        finally:
            await assets.close()

    asyncio.run(run())


def test_project_links_are_reported_not_verified(store):
    async def run():
        payload = {
            "id": "bitcoin",
            "links": {
                "homepage": ["https://example.org/project", "javascript:bad"],
                "whitepaper": "https://example.org/paper.pdf",
                "repos_url": {"github": ["https://github.com/example/project"]},
            },
            "platforms": {},
            "genesis_date": "2009-01-03",
            "categories": ["Cryptocurrency"],
        }
        assets = Assets(
            store,
            httpx.AsyncClient(
                transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
            ),
        )
        try:
            profile = await assets.profile("bitcoin")
            assert not profile["fundamentals_verified"]
            assert len(profile["documents"]) == 3
            assert all(
                d["status"] == "provider_reported_not_independently_verified"
                for d in profile["documents"]
            )
        finally:
            await assets.close()

    asyncio.run(run())


def test_general_crypto_paper_flow_preserves_prior_account(settings):
    app = create_app(settings, NewsFixtureProviders(), False, FixtureNews, FixtureAssets)
    with TestClient(app) as c:
        assert c.post("/api/assets/refresh").status_code == 200
        assert c.get("/api/assets").json()[0]["asset_id"] == "bitcoin"
        assert c.get("/api/assets/bitcoin/venues").json()["prelisting_access"] == "not_established"
        response = c.post(
            "/api/assets/bitcoin/signal", json={"thesis": "Check this claim against the source"}
        )
        assert response.status_code == 200, response.text
        signal = response.json()["id"]
        with app.state.service.news_paper.connect() as db:
            db.execute(
                "UPDATE signals SET at=? WHERE id=?",
                (datetime.fromtimestamp(time.time() - 4, UTC).isoformat(), signal),
            )
        response = c.post(
            "/api/paper/assets/buy",
            json={"asset_id": "bitcoin", "amount_usd": "50", "signal_id": signal},
        )
        assert response.status_code == 200, response.text
        assert response.json()["entry_context"]["thesis"] == "Check this claim against the source"
        p = c.get("/api/portfolio?account=news").json()
        assert p["cash"] == "450"
        assert D(p["estimated_equity_usd"]) < D(500)
        assert c.get("/api/portfolio?account=scanner").json()["cash"] == "100"
        pos = p["positions"][0]
        assert pos["kind"] == "market_asset"
        assert c.post(f"/api/paper/positions/{pos['id']}/sell?account=news").status_code == 200
        assert D(c.get("/api/portfolio?account=news").json()["realized_pnl_usd"]) < 0


@pytest.mark.parametrize("timestamp", ["2020-01-01T00:00:00+00:00", None, "invalid-date"])
def test_crypto_source_freshness_gates_ledger(settings, timestamp):
    class StaleAssets(FixtureAssets):
        async def quote(self, asset_id):
            asset = await super().quote(asset_id)
            asset["source_updated_at"] = timestamp
            self.save(asset)
            return asset

    app = create_app(settings, NewsFixtureProviders(), False, FixtureNews, StaleAssets)
    with TestClient(app) as c:
        signal = c.post("/api/assets/bitcoin/signal", json={}).json()["id"]
        response = c.post(
            "/api/paper/assets/buy",
            json={"asset_id": "bitcoin", "amount_usd": "50", "signal_id": signal},
        )
        assert response.status_code == 409
        p = c.get("/api/portfolio?account=news").json()
        assert p["cash"] == "500"
        assert p["orders"][0]["status"] == "failed"


def test_book_entry_cannot_exit_with_unobserved_liquidity(settings):
    class MissingBook(FixtureAssets):
        missing = False

        async def quote(self, asset_id):
            asset = await super().quote(asset_id)
            if self.missing:
                asset["book"] = None
                self.save(asset)
            return asset

    app = create_app(settings, NewsFixtureProviders(), False, FixtureNews, MissingBook)
    with TestClient(app) as c:
        signal = c.post("/api/assets/bitcoin/signal", json={}).json()["id"]
        with app.state.service.news_paper.connect() as db:
            db.execute(
                "UPDATE signals SET at=? WHERE id=?",
                (datetime.fromtimestamp(time.time() - 4, UTC).isoformat(), signal),
            )
        order = c.post(
            "/api/paper/assets/buy",
            json={"asset_id": "bitcoin", "amount_usd": "50", "signal_id": signal},
        ).json()
        app.state.service.assets.missing = True
        assert (
            c.post(f"/api/paper/positions/{order['position_id']}/sell?account=news").status_code
            == 409
        )
        p = c.get("/api/portfolio?account=news").json()
        assert p["cash"] == "450"
        assert p["positions"][0]["closed_at"] is None
        assert p["estimated_equity_usd"] is None
