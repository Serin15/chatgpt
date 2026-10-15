"""Audit regressions. All provider responses here are isolated fixtures."""

import asyncio
import io
import json
import sqlite3
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from http.cookies import SimpleCookie
from threading import Barrier
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import COOKIE, Auth, LoginInput
from app.errors import ProviderError
from app.http_client import read_json
from app.jupiter import USDC, Jupiter
from app.main import create_app
from app.onchain import Onchain
from app.paper import Rejected
from app.providers import Providers
from tests.conftest import ADDRESS
from tests.test_assets import FixtureAssets
from tests.test_news import FixtureNews, NewsFixtureProviders
from tests.test_observation_sampling import candidate
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, stamp


def test_rpc_application_error_is_visible_in_provider_health(settings):
    async def run():
        p = Providers(
            settings,
            httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, json={"error": {"code": -32602}})
                )
            ),
        )
        try:
            with pytest.raises(ProviderError):
                await p.mint_info(ADDRESS)
            assert p.status["rpc"]["state"] == "error"
        finally:
            await p.close()

    asyncio.run(run())


def test_invalid_token_is_visible_in_onchain_health(settings):
    async def run():
        rpc = Onchain(
            settings,
            httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, json={"result": {"value": None}})
                )
            ),
        )
        try:
            with pytest.raises(ProviderError):
                await rpc.token("solana", ADDRESS)
            assert rpc.status["solana"]["state"] == "error"
        finally:
            await rpc.close()

    asyncio.run(run())


@pytest.mark.parametrize("value", ["1e999", "-1e999", "NaN", "Infinity"])
def test_nonfinite_provider_numbers_are_rejected(value):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, content='{"price":' + value + "}")
            )
        ) as client:
            with pytest.raises(ProviderError, match="JSON invalid"):
                await read_json(client, "GET", "https://example.com/data")

    asyncio.run(run())


@pytest.mark.parametrize("body", ['{"price":1e999}', '{"price":NaN}'], ids=["overflow", "nan"])
def test_legacy_provider_rejects_nonfinite_json(settings, body):
    async def run():
        provider = Providers(
            settings,
            httpx.AsyncClient(
                transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
            ),
        )
        try:
            with pytest.raises(ProviderError, match="JSON invalid"):
                await provider.request("dex", "GET", "https://example.com/data")
            assert provider.status["dex"]["state"] == "error"
        finally:
            await provider.close()

    asyncio.run(run())


def test_jupiter_impact_rejection_keeps_the_risk_reason(settings):
    async def run():
        response = {
            "inputMint": USDC,
            "outputMint": ADDRESS,
            "inAmount": "1000",
            "outAmount": "1000",
            "otherAmountThreshold": "995",
            "swapMode": "ExactIn",
            "slippageBps": 50,
            "priceImpactPct": "1",
            "contextSlot": 42,
            "routePlan": [{"swapInfo": {}}],
        }
        j = Jupiter(
            settings,
            None,
            httpx.AsyncClient(
                transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))
            ),
        )
        try:
            with pytest.raises(Rejected, match="impact"):
                await j.quote(USDC, ADDRESS, 1000)
            assert "impact" in j.status["error"]
        finally:
            await j.close()

    asyncio.run(run())


def test_password_rotation_invalidates_existing_sessions(store, monkeypatch):
    monkeypatch.setenv("PULSE_AUTH_PASSWORD", "first-fixture-password-123")
    auth = Auth(store)
    request = SimpleNamespace(cookies={}, client=SimpleNamespace(host="127.0.0.1"))
    response = auth.login(request, LoginInput(password="first-fixture-password-123"))
    cookie = SimpleCookie(response.headers["set-cookie"])[COOKIE].value
    request.cookies[COOKIE] = cookie
    assert auth.session(request)["authenticated"]
    monkeypatch.setenv("PULSE_AUTH_PASSWORD", "rotated-fixture-password-456")
    restarted = Auth(store)
    assert not restarted.session(request)["authenticated"]
    assert auth.session(request)["authenticated"]  # existing owner process is unchanged


def test_backup_supports_hash_percent_and_non_ascii_paths(settings):
    config = replace(settings, data_dir=settings.data_dir / "Date #1 % & România")
    with TestClient(
        create_app(config, NewsFixtureProviders(), False, FixtureNews, FixtureAssets)
    ) as client:
        response = client.post("/api/backup")
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for name, initial in [
                ("research.sqlite3", "100"),
                ("news_paper/research.sqlite3", "500"),
            ]:
                restored = settings.data_dir / "restored.sqlite3"
                restored.write_bytes(archive.read(name))
                with sqlite3.connect(restored) as db:
                    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                    assert db.execute("SELECT balance FROM account").fetchone()[0] == initial


def test_candidate_search_and_verdict_apply_before_pagination(client_engine):
    client, engine = client_engine
    now = time.time()
    target = candidate(engine, 701, now)
    policy, cfg = engine.policy(engine.config()), engine.config()
    value = payload(engine, target, now)
    value["market"].update(name="Hidden audit candidate", symbol="HIDDEN")
    engine.save_observation(target, value, policy, cfg, stamp(now))
    for i in range(702, 757):
        candidate(engine, i, now)
    result = client.get("/api/opportunities", params={"q": "HIDDEN", "limit": 5}).json()
    assert [c["id"] for c in result["items"]] == [target["id"]]
    assert result["matching_total"] == 1
    pending = client.get("/api/opportunities", params={"verdict": "PENDING", "limit": 200}).json()
    assert len(pending["items"]) == 55
    assert client.get("/api/opportunities?verdict=INVALID").status_code == 422
    assert client.get("/api/opportunities?q=%25").json()["items"] == []  # literal %, no wildcard


def test_future_observation_cannot_displace_current_rank(client_engine):
    client, engine = client_engine
    now = time.time()
    policy, cfg = engine.policy(engine.config()), engine.config()
    current, future = candidate(engine, 800, now), candidate(engine, 801, now)
    for c, at, rank in [(current, now, 1), (future, now + 3600, 99)]:
        value = payload(engine, c, at)
        value["decision"]["rank_score"] = rank
        engine.save_observation(c, value, policy, cfg, stamp(at))
    result = client.get("/api/opportunities?sort=rank&limit=1").json()
    assert result["items"][0]["id"] == current["id"]


def test_forward_report_does_not_call_missing_results_zero_profit(client_engine):
    client, _ = client_engine
    report = client.get("/api/evaluation/forward").json()
    assert all(g["net_pnl_independent_experiments_usd"] is None for g in report["cohorts"].values())


def test_routed_live_verifier_preserves_partial_evidence_on_service_disconnect(monkeypatch):
    from app.routes_verify import verify

    original = httpx.Client

    def response(request):
        if request.url.path == "/api/status":
            return httpx.Response(
                200, json={"app_id": "pulse_crypto_research", "live_execution": False}
            )
        raise httpx.ConnectError("isolated service disconnected")

    monkeypatch.setattr(
        "app.routes_verify.httpx.Client",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(response)),
    )
    proof = verify("http://127.0.0.1:8767", 30)
    assert not proof["complete"] and proof["criteria"]["real_money_disabled"]
    assert proof["manual_orders"] is None and "ConnectError" in proof["errors"][0]


def test_password_unchanged_preserves_authenticated_session(store, monkeypatch):
    monkeypatch.setenv("PULSE_AUTH_PASSWORD", "unchanged-fixture-password-123")
    auth = Auth(store)
    request = SimpleNamespace(cookies={}, client=SimpleNamespace(host="127.0.0.1"))
    response = auth.login(request, LoginInput(password="unchanged-fixture-password-123"))
    request.cookies[COOKIE] = SimpleCookie(response.headers["set-cookie"])[COOKIE].value
    assert Auth(store).session(request)["authenticated"]


def test_concurrent_bad_logins_cannot_bypass_rate_limit(store, monkeypatch):
    monkeypatch.setenv("PULSE_AUTH_PASSWORD", "unchanged-fixture-password-123")
    auth = Auth(store)
    request = SimpleNamespace(cookies={}, client=SimpleNamespace(host="127.0.0.1"))
    gate = Barrier(8)
    import hmac

    original = hmac.compare_digest

    def slow_compare(a, b):
        time.sleep(0.01)  # reproduce overlapping requests before their failed-attempt update
        return original(a, b)

    monkeypatch.setattr("app.auth.hmac.compare_digest", slow_compare)

    def login(_):
        gate.wait(timeout=10)
        return auth.login(request, LoginInput(password="incorrect fixture password")).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(login, range(8)))
    assert codes.count(401) == 5 and codes.count(429) == 3, codes


@pytest.mark.parametrize(
    "result",
    [
        {"message_id": 123, "chat": {"id": 999}},
        {"message_id": True, "chat": {"id": 12345}},
        {"message_id": 0, "chat": {"id": 12345}},
        None,
    ],
)
def test_manual_telegram_requires_valid_acknowledgment_from_requested_chat(
    client_engine, monkeypatch, result
):
    _, engine = client_engine
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "isolated-fixture-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    with engine.store.connect() as db:
        row = db.execute(
            "INSERT INTO alerts(news_id,at,payload) VALUES(1,?,?)",
            (
                stamp(time.time()),
                json.dumps(
                    {"title": "Fixture", "publisher": "Fixture", "url": "https://example.com"}
                ),
            ),
        )
        aid = row.lastrowid
    calls = []

    async def send(method, body):
        calls.append(method)
        return result

    monkeypatch.setattr(engine.service.notifications, "telegram", send)
    response = asyncio.run(engine.service.notifications.deliver(aid))
    assert response["delivery_state"] == "delivery_unknown"
    with pytest.raises(ProviderError):
        asyncio.run(engine.service.notifications.deliver(aid))
    assert calls == ["sendMessage"]
