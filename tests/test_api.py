import time

from fastapi.testclient import TestClient

from app.main import create_app
from app.providers import ProviderError
from tests.conftest import ADDRESS, market, old_signal, security


class FixtureProviders:
    """Explicit mocked providers, used only with isolated temporary test databases."""

    status = {}
    failing = False

    async def close(self):
        pass

    async def discover(self):
        return [ADDRESS]

    async def market(self, address):
        if self.failing:
            raise ProviderError("dex: fixture network failure")
        return market(address)

    async def security(self, address):
        return security()


def test_scanner_signal_paper_roundtrip_and_history(settings):
    app = create_app(settings, FixtureProviders(), run_scanner=False)
    with TestClient(app) as client:
        assert client.get("/api/tokens").json() == []
        assert client.post("/api/scan").status_code == 200
        listing = client.get("/api/tokens").json()
        assert listing[0]["snapshot"]["analysis"]["paper_allowed"]
        stored = app.state.service.store.latest(ADDRESS)
        signal_id = old_signal(app.state.service.store, stored)
        response = client.post(
            "/api/paper/buy", json={"address": ADDRESS, "amount_usd": "5", "signal_id": signal_id}
        )
        assert response.status_code == 200, response.text
        position = response.json()["position_id"]
        assert client.post(f"/api/paper/positions/{position}/sell").status_code == 200
        portfolio = client.get("/api/portfolio").json()
        assert float(portfolio["cash"]) < 100
        assert len(client.get(f"/api/tokens/{ADDRESS}").json()["history"]) == 3
        assert client.get("/api/status").json()["live_execution"] is False
        assert client.post("/api/live/buy", json={}).status_code == 404


def test_failed_refresh_does_not_fill_using_cache(settings):
    providers = FixtureProviders()
    app = create_app(settings, providers, run_scanner=False)
    with TestClient(app) as client:
        client.post("/api/scan")
        signal_id = old_signal(app.state.service.store, app.state.service.store.latest(ADDRESS))
        providers.failing = True
        response = client.post(
            "/api/paper/buy", json={"address": ADDRESS, "amount_usd": "5", "signal_id": signal_id}
        )
        assert response.status_code == 503
        portfolio = client.get("/api/portfolio").json()
        assert portfolio["cash"] == "100"
        assert portfolio["orders"][0]["status"] == "failed"
        assert not portfolio["positions"]


def test_cross_origin_mutations_blocked(settings):
    with TestClient(create_app(settings, FixtureProviders(), False)) as client:
        assert (
            client.post("/api/scan", headers={"origin": "https://untrusted.example"}).status_code
            == 403
        )


def test_reject_bad_address_and_render_assets(settings):
    with TestClient(create_app(settings, FixtureProviders(), False)) as client:
        assert (
            client.post("/api/tokens", json={"address": "<script>bad</script>"}).status_code == 422
        )
        page = client.get("/")
        assert page.status_code == 200
        assert "PAPER ONLY" in page.text
        assert client.get("/static/app.js").status_code == 200
        assert "script-src 'self'" in page.headers["content-security-policy"]


def test_listing_invalidates_expired_observations(settings):
    with TestClient(create_app(settings, FixtureProviders(), False)) as client:
        client.post("/api/scan")
        service = client.app.state.service
        snap = service.store.latest(ADDRESS)
        from datetime import UTC, datetime

        with service.store.connect() as db:
            old = datetime.fromtimestamp(time.time() - 121, UTC).isoformat()
            import json

            snap["market"]["observed_at"] = old
            db.execute(
                "UPDATE snapshots SET at=?,market=? WHERE id=?",
                (old, json.dumps(snap["market"]), snap["id"]),
            )
        assert client.get("/api/tokens").json()[0]["snapshot"]["analysis"]["paper_allowed"] is False


def test_watchlist_can_be_removed_without_deleting_history(settings):
    with TestClient(create_app(settings, FixtureProviders(), False)) as client:
        assert client.post("/api/tokens", json={"address": ADDRESS}).status_code == 201
        assert client.get(f"/api/tokens/{ADDRESS}").json()["watch"] == 1
        client.post(f"/api/tokens/{ADDRESS}/unwatch")
        details = client.get(f"/api/tokens/{ADDRESS}").json()
        assert details["watch"] == 0
        assert len(details["history"]) == 1
