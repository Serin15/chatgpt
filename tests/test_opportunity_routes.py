"""Synthetic RPC/HTTP providers, real routing orchestration and SQLite. No external requests."""

import asyncio
import time
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from app.jupiter import USDC, Jupiter
from app.opportunity_routes import Routes
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, seed, stamp


@pytest.fixture
def routed(client_engine, monkeypatch):
    client, engine = client_engine
    engine.configure(engine.config().model_copy(update={"routed_quotes_enabled": True}))
    clock = [float(int(time.time()))]
    monkeypatch.setattr("app.opportunity_routes.time", SimpleNamespace(time=lambda: clock[0]))
    monkeypatch.setattr("app.jupiter.time", SimpleNamespace(time=lambda: clock[0]))
    monkeypatch.setattr("app.opportunity_routes.utcnow", lambda: stamp(clock[0]))
    monkeypatch.setattr("app.jupiter.utcnow", lambda: stamp(clock[0]))
    calls = []
    failure = [None]

    class RPC:
        async def token(self, chain, address, **kwargs):
            return {"decimals": 6}

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        if request.url.host == "api.kraken.com":
            return httpx.Response(
                200,
                json={
                    "error": [],
                    "result": {
                        "USDCUSD": {"bids": [["1", "10000", 42]], "asks": [["1", "10000", 42]]}
                    },
                },
            )
        if request.url.host == "api.exchange.coinbase.com":
            return httpx.Response(
                200, json={"bids": [["1", "10000", 1]], "asks": [["1", "10000", 1]]}
            )
        assert request.url.path == "/swap/v1/quote"
        if failure[0]:
            return httpx.Response(failure[0], json={"error": "Explicit isolated failure"})
        p = request.url.params
        raw = int(p["amount"])
        out = raw * 2 if p["inputMint"] == USDC else raw // 2
        slip = int(p["slippageBps"])
        return httpx.Response(
            200,
            json={
                "inputMint": p["inputMint"],
                "outputMint": p["outputMint"],
                "inAmount": str(raw),
                "outAmount": str(out),
                "otherAmountThreshold": str(out * (10000 - slip) // 10000),
                "swapMode": "ExactIn",
                "slippageBps": slip,
                "priceImpactPct": "0.001",
                "contextSlot": 42,
                "routePlan": [
                    {
                        "swapInfo": {
                            "inputMint": p["inputMint"],
                            "outputMint": p["outputMint"],
                            "feeMint": USDC,
                            "feeAmount": "10",
                        }
                    }
                ],
            },
        )

    asyncio.run(engine.service.jupiter.client.aclose())
    engine.service.jupiter.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    engine.service.onchain.token = RPC().token
    c, p, cfg = seed(engine)
    _, signal_id = engine.save_observation(
        c, payload(engine, c, clock[0] - 6), p, cfg, stamp(clock[0] - 6)
    )
    engine.save_observation(c, payload(engine, c, clock[0] - 1), p, cfg, stamp(clock[0] - 1))
    return SimpleNamespace(
        client=client,
        engine=engine,
        clock=clock,
        candidate=c,
        policy=p,
        config=cfg,
        signal_id=signal_id,
        calls=calls,
        failure=failure,
    )


def execute(r):
    return asyncio.run(r.engine.routes.cycle())


def later(r, unsafe=False):
    r.clock[0] += 301
    r.engine.save_observation(
        r.candidate,
        payload(r.engine, r.candidate, r.clock[0], unsafe=unsafe),
        r.policy,
        r.config,
        stamp(r.clock[0]),
    )


def test_public_quote_without_key_is_not_rejected_locally(routed):
    r = routed
    assert execute(r)["state"] == "ok"
    entry = r.engine.routes.detail(r.candidate["id"])["entries"][0]
    assert entry["entry_state"] == "filled"
    requests = [q for q in r.calls if q.url.host == "api.jup.ag"]
    assert len(requests) == 1 and "x-api-key" not in requests[0].headers
    assert entry["entry_payload"]["execution_verified"] is False
    assert r.client.get("/api/portfolio?account=news").json()["orders"] == []
    assert r.client.get("/api/portfolio?account=scanner").json()["orders"] == []


def test_exact_bought_quantity_is_sold_at_future_horizon_after_costs(routed):
    r = routed
    execute(r)
    entry = r.engine.routes.detail(r.candidate["id"])["entries"][0]
    buy = entry["entry_payload"]
    with r.engine.store.connect() as db:
        job = db.execute(
            "SELECT * FROM observation_jobs WHERE signal_id=? AND phase='routed_exit' AND horizon_seconds=300",
            (r.signal_id,),
        ).fetchone()
    assert job["due_at"] == pytest.approx(r.clock[0] + 300)
    later(r)
    execute(r)
    detail = r.client.get(f"/api/opportunities/{r.candidate['id']}").json()["routed"]
    result = next(
        o
        for o in detail["outcomes"]
        if o["signal_id"] == r.signal_id and o["horizon_seconds"] == 300
    )
    assert result["state"] == "evaluated"
    p = result["payload"]
    sale = p["exit_quote"]
    assert sale["jupiter_quote"]["inAmount"] == str(int(Decimal(buy["quantity"]) * 10**6))
    assert Decimal(p["pnl_usd"]) == Decimal(buy["cash_change"]) + Decimal(sale["cash_change"]) < 0
    assert p["actual_hold_seconds"] == pytest.approx(301)
    report = r.client.get("/api/opportunities/routes").json()
    assert report["horizons"]["300"]["alerts"]["evaluated"] == 1
    assert report["horizons"]["300"]["alerts"]["profitability_demonstrated"] is False
    assert len(detail["attempts"]) == 2
    execute(r)
    assert len(r.engine.routes.detail(r.candidate["id"])["attempts"]) == 2


def test_auth_failure_stays_unavailable_without_pool_fallback_or_retry(routed):
    r = routed
    r.failure[0] = 401
    assert execute(r)["state"] == "partial"
    d = r.engine.routes.detail(r.candidate["id"])
    assert d["entries"][0]["entry_state"] == "entry_unavailable"
    assert "JUPITER_API_KEY" in d["entries"][0]["reason"]
    assert all(o["payload"]["pnl_usd"] is None for o in d["outcomes"])
    count = len(r.calls)
    r.failure[0] = None
    execute(r)
    assert len(r.calls) == count


def test_missing_sell_route_has_null_pnl_and_preserves_buy_quote(routed):
    r = routed
    execute(r)
    later(r)
    r.failure[0] = 400
    execute(r)
    d = r.engine.routes.detail(r.candidate["id"])
    result = next(o for o in d["outcomes"] if o["horizon_seconds"] == 300)
    assert result["state"] == "exit_unavailable" and result["payload"]["pnl_usd"] is None
    assert d["entries"][0]["entry_payload"]["jupiter_quote"]
    assert "HTTP 400" in result["payload"]["reason"]


def test_new_unsafe_observation_blocks_exit_without_requesting_swap_quote(routed):
    r = routed
    execute(r)
    count = len(r.calls)
    later(r, unsafe=True)
    execute(r)
    result = next(
        o
        for o in r.engine.routes.detail(r.candidate["id"])["outcomes"]
        if o["signal_id"] == r.signal_id and o["horizon_seconds"] == 300
    )
    assert result["state"] == "exit_unavailable" and len(r.calls) == count


def test_signal_time_costs_and_slippage_remain_frozen(routed):
    r = routed
    execute(r)
    r.engine.service.settings = replace(r.engine.service.settings, network_fee_usd=Decimal("0.1"))
    r.engine.configure(r.engine.config().model_copy(update={"routed_slippage_bps": 100}))
    later(r)
    execute(r)
    result = next(
        o
        for o in r.engine.routes.detail(r.candidate["id"])["outcomes"]
        if o["signal_id"] == r.signal_id and o["horizon_seconds"] == 300
    )
    assert result["state"] == "evaluated"
    assert result["payload"]["exit_quote"]["network_fee_usd"] == "0.01"
    assert result["payload"]["exit_quote"]["slippage_bps"] == 50


def test_no_backfill_or_synthetic_quote_on_restart(routed):
    r = routed
    with r.engine.store.connect() as db:
        db.execute("DELETE FROM routed_outcomes")
        db.execute("DELETE FROM routed_experiments")
    restarted = Routes(r.engine)
    assert restarted.report()["entry_states"] == {}
    assert restarted.report()["legacy_baselines_not_measured"] == 1


def test_deadline_miss_keeps_unknown_result(routed):
    r = routed
    r.clock[0] += 181
    execute(r)
    d = r.engine.routes.detail(r.candidate["id"])
    assert d["entries"][0]["entry_state"] == "entry_unavailable"
    assert "deadline" in d["entries"][0]["reason"]
    assert not d["attempts"] and not r.calls


def test_atomic_claim_prevents_duplicate_quotes(routed):
    r = routed
    job = r.engine.routes.ready()[0]
    assert r.engine.routes.claim(job)
    assert r.engine.routes.claim(job) is None


def test_interrupted_attempt_is_terminal_and_late_callback_cannot_overwrite_it(routed):
    r = routed
    job = r.engine.routes.ready()[0]
    a = r.engine.routes.claim(job)
    r.clock[0] += 31
    execute(r)
    assert r.engine.routes.detail(r.candidate["id"])["entries"][0]["reason"] == "worker_interrupted"
    r.engine.routes.finish(job, a, {"quote_observed_at": stamp(r.clock[0])})
    assert (
        r.engine.routes.detail(r.candidate["id"])["entries"][0]["entry_state"]
        == "entry_unavailable"
    )


def test_model_change_stops_recomputation(routed, monkeypatch):
    r = routed
    monkeypatch.setattr("app.opportunity_routes.SOURCE_SHA256", "explicit_changed_implementation")
    execute(r)
    assert (
        r.engine.routes.detail(r.candidate["id"])["entries"][0]["reason"]
        == "cost_model_unavailable"
    )
    assert not r.calls


def test_disabled_configuration_does_not_collect(routed):
    r = routed
    r.engine.configure(r.engine.config().model_copy(update={"routed_quotes_enabled": False}))
    assert execute(r)["state"] == "disabled" and not r.calls


def test_protected_quote_slots_and_overlap_are_bounded(routed):
    ready = [
        {
            "signal_id": i,
            "phase": "entry",
            "horizon_seconds": 0,
            "deadline": i,
            "selected": i < 50,
            "control_member": i >= 50,
        }
        for i in range(100)
    ]
    chosen = routed.engine.routes.choose(ready, 4)
    assert (
        len(chosen) == 4
        and any(r["selected"] for r in chosen)
        and any(r["control_member"] for r in chosen)
    )
    ready[0]["control_member"] = True
    assert len({r["signal_id"] for r in routed.engine.routes.choose(ready, 4)}) == 4


def test_boolean_amount_rejected(settings):
    source = Jupiter(settings, None)

    async def run():
        from app.paper import Rejected

        try:
            with pytest.raises(Rejected):
                await source.quote(USDC, "So11111111111111111111111111111111111111112", True)
        finally:
            await source.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value",
    [
        ("slippageBps", 51),
        ("contextSlot", True),
        ("otherAmountThreshold", "1"),
        ("outAmount", str(2**64)),
    ],
)
def test_malformed_real_quote_schema_is_rejected(settings, field, value):
    from app.errors import ProviderError
    from app.paper import Rejected

    response = {
        "inputMint": USDC,
        "outputMint": "So11111111111111111111111111111111111111112",
        "inAmount": "50000000",
        "outAmount": "1000000000",
        "otherAmountThreshold": "995000000",
        "swapMode": "ExactIn",
        "slippageBps": 50,
        "priceImpactPct": "0.001",
        "contextSlot": 42,
        "routePlan": [{"swapInfo": {}}],
    }
    response[field] = value

    async def run():
        source = Jupiter(
            settings,
            None,
            httpx.AsyncClient(
                transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))
            ),
        )
        try:
            with pytest.raises((ProviderError, Rejected)):
                await source.quote(USDC, response["outputMint"], 50000000)
        finally:
            await source.close()

    asyncio.run(run())


def test_invalid_forex_books_do_not_create_parity_or_a_fill(routed):
    r = routed
    asyncio.run(r.engine.service.jupiter.client.aclose())
    r.engine.service.jupiter.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    )
    assert execute(r)["state"] == "partial"
    d = r.engine.routes.detail(r.candidate["id"])
    assert d["entries"][0]["entry_state"] == "entry_unavailable"
    assert "USDC/USD" in d["entries"][0]["reason"]
    assert not d["entries"][0]["entry_payload"]
