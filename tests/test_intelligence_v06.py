"""Isolated integration tests. Every external provider here is an explicit HTTP/RPC fixture."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.discovery import Discovery
from app.errors import ProviderError
from app.jupiter import USDC, Jupiter
from app.main import create_app
from app.notifications import Notifications
from app.onchain import Onchain
from app.paper import Rejected
from app.wallets import JUPITER_PROGRAM, WalletInput, Wallets, solana_activity
from tests.conftest import ADDRESS, OTHER
from tests.test_assets import FixtureAssets
from tests.test_news import FixtureNews, NewsFixtureProviders

EVM = "0x" + "a" * 40
POOL = "0x" + "b" * 40


@pytest.fixture(autouse=True)
def no_external_credentials(monkeypatch):
    for key in (
        "PULSE_AUTH_PASSWORD",
        "PULSE_PUBLIC_ORIGIN",
        "PULSE_HOSTED",
        "PAPER_SOLANA_EXECUTION",
        "JUPITER_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ):
        monkeypatch.delenv(key, raising=False)


def test_discovery_preserves_first_seen_and_distinguishes_pool_from_launch(store):
    async def run():
        def handler(request):
            if "new_pools" in request.url.path:
                row = {
                    "attributes": {
                        "address": POOL,
                        "name": "Example / USDC",
                        "pool_created_at": "2026-01-01T00:00:00Z",
                        "base_token_price_usd": "1",
                        "reserve_in_usd": "50000",
                    },
                    "relationships": {"base_token": {"data": {"id": "base_" + EVM}}},
                }
                return httpx.Response(200, json={"data": [None, row]})
            return httpx.Response(200, json=[])

        discovery = Discovery(store, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            result = await discovery.refresh("base")
            assert len(result["items"]) == 1 and result["sources"]["base"]["rejected"] == 1
            first = result["items"][0]["first_seen_at"]
            await discovery.refresh("base")
            item = discovery.listing()["items"][0]
            assert item["first_seen_at"] == first and item["payload"]["token_launched_at"] is None
            assert (
                item["payload"]["pool_created_at_reported"]
                and item["payload"]["indexed_at"] is None
            )
        finally:
            await discovery.close()

    asyncio.run(run())


def test_discovery_cursor_has_no_missing_or_repeated_rows(store):
    async def run():
        discovery = Discovery(store)
        try:
            for i in range(5):
                discovery.save(
                    {
                        "chain": "base",
                        "pool": "0x" + f"{i:040x}",
                        "contract": EVM,
                        "token_launched_at": None,
                    }
                )
            one = discovery.listing(limit=2)
            two = discovery.listing(before=one["next_cursor"], limit=2)
            three = discovery.listing(before=two["next_cursor"], limit=2)
            assert len({r["pool"] for r in one["items"] + two["items"] + three["items"]}) == 5
            assert three["next_cursor"] is None
        finally:
            await discovery.close()

    asyncio.run(run())


def test_base_rpc_refuses_another_network_and_all_write_methods(settings):
    async def run():
        calls = []

        def handler(request):
            method = json.loads(request.content)["method"]
            calls.append(method)
            return httpx.Response(200, json={"result": "0x1"})

        rpc = Onchain(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            with pytest.raises(ProviderError, match="Base mainnet"):
                await rpc.token("base", EVM)
            with pytest.raises(ProviderError, match="exclusiv citire"):
                await rpc.rpc("base", "eth_sendRawTransaction", ["never"])
            assert calls == ["eth_chainId"]
        finally:
            await rpc.close()

    asyncio.run(run())


def test_base_contract_observation_is_not_an_audit(settings):
    async def run():
        def handler(request):
            body = json.loads(request.content)
            value = {"eth_chainId": "0x2105", "eth_getCode": "0x1234"}.get(body["method"])
            if body["method"] == "eth_call":
                value = "0x6" if body["params"][0]["data"] == "0x313ce567" else "0xf4240"
            return httpx.Response(200, json={"result": value})

        rpc = Onchain(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            result = await rpc.token("base", EVM)
            assert result["chain_id"] == 8453 and result["decimals"] == 6
            assert (
                result["raw_supply"] == "1000000"
                and not result["audit_verified"]
                and not result["sellability_verified"]
            )
        finally:
            await rpc.close()

    asyncio.run(run())


def transaction(address=ADDRESS, failed=False):
    return {
        "slot": 12,
        "blockTime": 1700000000,
        "transaction": {"message": {"instructions": [{"programId": JUPITER_PROGRAM}]}},
        "meta": {
            "err": {"InstructionError": 1} if failed else None,
            "fee": 5000,
            "preTokenBalances": [
                {
                    "owner": address,
                    "mint": USDC,
                    "uiTokenAmount": {"amount": "10000000", "decimals": 6},
                }
            ],
            "postTokenBalances": [
                {
                    "owner": address,
                    "mint": USDC,
                    "uiTokenAmount": {"amount": "5000000", "decimals": 6},
                },
                {
                    "owner": address,
                    "mint": OTHER,
                    "uiTokenAmount": {"amount": "1000000000", "decimals": 9},
                },
            ],
        },
    }


def test_wallet_changes_are_not_invented_pnl_or_verified_swaps():
    activity = solana_activity(transaction(), ADDRESS)
    assert activity["kind"] == "swap_candidate" and activity["token_deltas"][USDC] == "-5"
    assert activity["pnl_usd"] is None and not activity["swap_verified"]
    assert solana_activity(transaction(failed=True), ADDRESS)["kind"] == "failed_transaction"
    other = transaction()
    other["transaction"]["message"]["instructions"] = []
    assert solana_activity(other, ADDRESS)["kind"] == "token_balance_change"


def test_wallet_pagination_and_event_deduplication(store):
    class RPC:
        async def rpc(self, chain, method, params):
            if method == "getSignaturesForAddress":
                return [{"signature": "s" * 88}]
            return transaction()

    async def run():
        wallets = Wallets(store, RPC())
        wallets.add(WalletInput(chain="solana", address=ADDRESS, label="Explicit fixture"))
        wallet_id = wallets.listing()[0]["id"]
        await wallets.refresh(wallet_id)
        result = await wallets.refresh(wallet_id)
        assert (
            result["events_total"] == 1 and result["pnl_usd"] is None and not result["full_history"]
        )

    asyncio.run(run())


def test_telegram_getme_does_not_send_and_ambiguous_delivery_is_not_retried(settings, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "explicit-fake-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "explicit-fake-chat")
    app = create_app(
        settings,
        NewsFixtureProviders(),
        run_scanner=False,
        news_factory=FixtureNews,
        assets_factory=FixtureAssets,
    )
    with TestClient(app) as client:
        service = app.state.service
        client.post("/api/news/refresh")
        client.post("/api/alerts/collect")
        assert len(client.get("/api/alerts").json()["items"]) == 1
        calls = []

        def handler(request):
            calls.append(request.url.path.rsplit("/", 1)[-1])
            if calls[-1] == "getMe":
                return httpx.Response(
                    200, json={"ok": True, "result": {"is_bot": True, "username": "fixture_bot"}}
                )
            raise httpx.ReadTimeout("explicit-fake-token must not leak")

        old = service.notifications
        service.notifications = Notifications(
            service, httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        try:
            assert (
                client.post("/api/integrations/telegram/check").json()["status"]["message_sent"]
                is False
            )
            alert = client.get("/api/alerts").json()["items"][0]
            assert client.post(f"/api/alerts/{alert['id']}/telegram").status_code == 422
            result = client.post(f"/api/alerts/{alert['id']}/telegram?confirm_send=true").json()
            assert result[
                "delivery_state"
            ] == "delivery_unknown" and "explicit-fake-token" not in json.dumps(result)
            assert (
                client.post(f"/api/alerts/{alert['id']}/telegram?confirm_send=true").status_code
                == 503
            )
            assert calls == ["getMe", "sendMessage"]
        finally:
            asyncio.run(old.close())


def test_authentication_csrf_cookie_logout_and_no_password_leak(settings, monkeypatch):
    secret = "fixture-password-at-least-16-characters"
    monkeypatch.setenv("PULSE_AUTH_PASSWORD", secret)
    app = create_app(
        settings,
        NewsFixtureProviders(),
        run_scanner=False,
        news_factory=FixtureNews,
        assets_factory=FixtureAssets,
    )
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/status").status_code == 401
        assert client.get("/api/auth/session").json()["required"]
        assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
        response = client.post("/api/auth/login", json={"password": secret})
        assert response.status_code == 200 and secret not in response.text
        assert (
            "HttpOnly" in response.headers["set-cookie"]
            and "SameSite=strict" in response.headers["set-cookie"]
        )
        csrf = response.json()["csrf"]
        assert client.get("/api/status").status_code == 200
        assert client.post("/api/ai/config", json={"provider": "disabled"}).status_code == 403
        assert (
            client.post(
                "/api/ai/config", json={"provider": "disabled"}, headers={"X-Pulse-CSRF": csrf}
            ).status_code
            == 200
        )
        assert secret not in client.get("/api/status").text
        assert client.post("/api/auth/logout", headers={"X-Pulse-CSRF": csrf}).status_code == 200
        assert client.get("/api/portfolio").status_code == 401


def test_hosted_mode_requires_auth_and_https(settings, monkeypatch):
    monkeypatch.setenv("PULSE_HOSTED", "1")
    app = create_app(settings, NewsFixtureProviders(), run_scanner=False)
    with pytest.raises(RuntimeError, match="Găzduirea necesită"):
        with TestClient(app):
            pass


def test_auth_rate_limits_failed_passwords(settings, monkeypatch):
    monkeypatch.setenv("PULSE_AUTH_PASSWORD", "this-is-a-fixture-password-only")
    app = create_app(
        settings,
        NewsFixtureProviders(),
        run_scanner=False,
        news_factory=FixtureNews,
        assets_factory=FixtureAssets,
    )
    with TestClient(app) as client:
        for _ in range(5):
            assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
        assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 429


def test_jupiter_missing_key_and_exact_route_validation(settings, monkeypatch):
    async def run():
        def handler(request):
            if not request.headers.get("x-api-key"):
                return httpx.Response(
                    401, json={"error": "explicit fixture requires authentication"}
                )
            return httpx.Response(
                200,
                json={
                    "inputMint": USDC,
                    "outputMint": ADDRESS,
                    "inAmount": "50000000",
                    "outAmount": "1000000000",
                    "otherAmountThreshold": "995000000",
                    "swapMode": "ExactIn",
                    "slippageBps": 50,
                    "priceImpactPct": "0.001",
                    "contextSlot": 12,
                    "routePlan": [{"swapInfo": {"feeAmount": "100", "feeMint": USDC}}],
                },
            )

        source = Jupiter(settings, None, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            with pytest.raises(ProviderError, match="JUPITER_API_KEY"):
                await source.quote(USDC, ADDRESS, 50_000_000)
            monkeypatch.setenv("JUPITER_API_KEY", "explicit-fake-api-key")
            result = await source.quote(USDC, ADDRESS, 50_000_000)
            assert result["otherAmountThreshold"] == "995000000"
            with pytest.raises(ProviderError, match="cererii exacte"):
                await source.quote(USDC, OTHER, 50_000_000)
        finally:
            await source.close()

    asyncio.run(run())


def test_jupiter_stale_quote_cannot_mutate_cash(store, settings):
    from app.paper import buy
    from tests.conftest import snapshot

    snapshot_data = snapshot(settings)
    cash = store.portfolio()["cash"]
    with pytest.raises(Rejected, match="expirat"):
        buy(
            store,
            snapshot_data,
            1,
            "10",
            settings,
            execution={
                "model": "jupiter_quote_conservative_min_out",
                "address": ADDRESS,
                "side": "buy",
                "requested_size": "10",
                "quantity": "1",
                "cash_change": "-10.01",
                "quote_observed_at": "2020-01-01T00:00:00+00:00",
            },
        )
    assert store.portfolio()["cash"] == cash and store.portfolio()["orders"] == []


def test_fundamentals_separate_manual_ai_and_observations(settings):
    app = create_app(
        settings,
        NewsFixtureProviders(),
        run_scanner=False,
        news_factory=FixtureNews,
        assets_factory=FixtureAssets,
    )
    with TestClient(app) as client:
        client.post("/api/assets/refresh")
        report = client.post("/api/research/asset:bitcoin/fundamentals/refresh").json()
        assert not report["fundamentals_verified"]
        assert {c["key"] for c in report["categories"]} >= {
            "distribution",
            "unlocks",
            "contract_risk",
        }
        assert all(f["origin"] != "ai" for f in report["observations"]["facts"])
        assert report["ai_interpretations"] == [] and "team" in report["missing"]


def test_unlabeled_forward_report_does_not_claim_test_performance(settings):
    app = create_app(
        settings,
        NewsFixtureProviders(),
        run_scanner=False,
        news_factory=FixtureNews,
        assets_factory=FixtureAssets,
    )
    with TestClient(app) as client:
        result = client.get("/api/evaluation/forward").json()
        assert result["cohorts"]["test"]["signals"] == 0
        assert result["cohorts"]["test"]["loss_signal_rate"] is None
        assert client.get("/api/evaluation/forward?split_at=2020-01-01").status_code == 422
        assert client.get("/api/evaluation/forward?horizon_seconds=1").status_code == 422


def test_malformed_wallet_signature_isolated_from_valid_activity(store):
    class RPC:
        async def rpc(self, chain, method, params):
            if method == "getSignaturesForAddress":
                return [None, {"signature": "s" * 88}]
            return transaction()

    async def run():
        wallets = Wallets(store, RPC())
        wallets.add(WalletInput(chain="solana", address=ADDRESS))
        result = await wallets.refresh(wallets.listing()[0]["id"])
        assert result["events_total"] == 1
        assert result["status"]["state"] == "partial"
        assert result["status"]["rejected"] == 1

    asyncio.run(run())


def test_jupiter_fill_counts_usdc_conversion_fee(settings):
    from decimal import Decimal as D

    from app.models import utcnow

    class RPC:
        async def token(self, chain, address, **kwargs):
            return {"decimals": 6}

    async def run():
        source = Jupiter(settings, RPC())

        async def book():
            return {
                "bid": D("1"),
                "ask": D("1"),
                "bid_size": D("1000"),
                "ask_size": D("1000"),
                "observed_at": utcnow(),
            }

        async def quote(input_mint, output_mint, raw_amount, slippage_bps=50):
            return {
                "otherAmountThreshold": str(raw_amount),
                "priceImpactPct": "0",
                "observed_at": utcnow(),
            }

        source.stable_book = book
        source.quote = quote
        try:
            buy = await source.fill("buy", "50", ADDRESS)
            sell = await source.fill("sell", buy["quantity"], ADDRESS)
            assert D(buy["quantity"]) == D("49.7")
            assert D(buy["cash_change"]) == D("-50.01")
            assert D(sell["cash_change"]) == D("49.3918")
            assert buy["conversion_fee_origin"] == "configured_assumption"
        finally:
            await source.close()

    asyncio.run(run())


def test_base_wallet_skips_invalid_and_unrelated_logs(store):
    from app.wallets import TRANSFER

    owner = "0x" + "0" * 24 + "a" * 40
    valid = {
        "address": POOL,
        "topics": [TRANSFER, owner, "0x" + "0" * 64],
        "data": "0x1",
        "blockNumber": "0x64",
        "transactionHash": "0x" + "b" * 64,
        "logIndex": "0x1",
    }
    unrelated = valid | {"topics": [TRANSFER, "0x" + "1" * 64, "0x" + "2" * 64]}

    class RPC:
        async def rpc(self, chain, method, params):
            return "0x64" if method == "eth_blockNumber" else [None, unrelated, valid]

    async def run():
        wallets = Wallets(store, RPC())
        wallets.add(WalletInput(chain="base", address=EVM))
        result = await wallets.refresh(wallets.listing()[0]["id"])
        assert result["events_total"] == 1
        assert result["status"]["state"] == "partial"
        assert result["activity"][0]["payload"]["raw_amount"] == "1"

    asyncio.run(run())


def test_secret_files_and_tracebacks_are_redacted(tmp_path, monkeypatch):
    import io
    import logging

    from app.credentials import secret
    from app.logging_config import RedactSecrets, SafeFormatter

    path = tmp_path / "key"
    path.write_text("fixture-file-secret-123456\n")
    monkeypatch.setenv("PULSE_AI_API_KEY_FILE", str(path))
    assert secret("PULSE_AI_API_KEY") == "fixture-file-secret-123456"
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.addFilter(RedactSecrets())
    handler.setFormatter(SafeFormatter(logging.Formatter()))
    logger = logging.getLogger("pulse.isolated.redaction")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        try:
            raise ValueError("fixture-file-secret-123456")
        except ValueError:
            logger.exception("request /botabc123/sendMessage?api_key=secret-other")
        logged = output.getvalue()
        assert "fixture-file-secret-123456" not in logged and "abc123" not in logged
        assert "secret-other" not in logged and "ValueError" in logged
    finally:
        logger.handlers = []


def test_base_uniswap_v4_pool_id_is_not_a_token_contract(store):
    pool_id = "0xa1943e4bf3832848f62f7610abacb4f69c2bf6c4a9de79ef0eb91abad84f5c00"

    async def run():
        def handler(request):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "attributes": {"address": pool_id, "name": "observed-format fixture"},
                            "relationships": {"base_token": {"data": {"id": "base_" + EVM}}},
                        }
                    ]
                },
            )

        source = Discovery(store, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            result = await source.new_pools("base", 1)
            assert result["count"] == 1 and result["rejected"] == 0
            item = source.listing()["items"][0]
            assert item["pool"] == pool_id and item["contract"] == EVM
            assert item["payload"]["pool_identifier_type"] == "pool_id_32_bytes"
        finally:
            await source.close()

    asyncio.run(run())


def test_malformed_solana_mint_is_a_controlled_provider_failure(settings):
    async def run():
        def handler(request):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "value": {
                            "data": {
                                "parsed": {
                                    "type": "mint",
                                    "info": {"supply": "broken", "decimals": 6},
                                }
                            },
                            "owner": "invalid",
                        }
                    }
                },
            )

        source = Onchain(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            with pytest.raises(ProviderError, match="incompatibil"):
                await source.token("solana", ADDRESS, include_distribution=False)
        finally:
            await source.close()

    asyncio.run(run())


def test_distribution_outage_preserves_valid_mint_observation(settings):
    async def run():
        def handler(request):
            method = json.loads(request.content)["method"]
            if method == "getTokenLargestAccounts":
                return httpx.Response(429)
            return httpx.Response(
                200,
                json={
                    "result": {
                        "context": {"slot": 12},
                        "value": {
                            "owner": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                            "data": {
                                "parsed": {
                                    "type": "mint",
                                    "info": {
                                        "supply": "1000000",
                                        "decimals": 6,
                                        "mintAuthority": None,
                                        "freezeAuthority": None,
                                    },
                                }
                            },
                        },
                    }
                },
            )

        source = Onchain(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            value = await source.token("solana", ADDRESS)
            assert value["decimals"] == 6 and value["top10_token_accounts_pct"] is None
            assert value["distribution_error"] and not value["audit_verified"]
        finally:
            await source.close()

    asyncio.run(run())


def test_redaction_preserves_uvicorn_access_log_arguments(monkeypatch):
    import logging

    from uvicorn.logging import AccessFormatter

    from app.logging_config import RedactSecrets, SafeFormatter

    monkeypatch.setenv("PULSE_AI_API_KEY", "fixture-log-secret")
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", "/test?api_key=fixture-log-secret", "1.1", 200),
        None,
    )
    RedactSecrets().filter(record)
    formatter = SafeFormatter(
        AccessFormatter("%(client_addr)s %(request_line)s %(status_code)s", use_colors=False)
    )
    value = formatter.format(record)
    assert "200" in value and "fixture-log-secret" not in value and "[REDACTED]" in value
