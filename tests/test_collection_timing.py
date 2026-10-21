"""Synthetic time/providers, real collector, routing orchestration and database."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.jupiter import Jupiter
from tests.conftest import market, security
from tests.test_observation_sampling import candidate
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, stamp
from tests.test_opportunity_routes import execute
from tests.test_opportunity_routes import routed as routed


@pytest.mark.parametrize("security_age", [10, 118])
def test_exit_is_dispatched_before_unrelated_slow_candidate(routed, monkeypatch, security_age):
    r = routed
    execute(r)
    r.clock[0] += 301
    cached = payload(r.engine, r.candidate, r.clock[0] - 2)
    cached["security"]["observed_at"] = stamp(r.clock[0] - security_age)
    r.engine.save_observation(r.candidate, cached, r.policy, r.config, stamp(r.clock[0] - 2))
    second = candidate(r.engine, 9001, r.clock[0])
    queue = [r.candidate | {"collection_lane": "protected_followup"}, second]
    monkeypatch.setattr(r.engine, "due", lambda cfg: queue)
    monkeypatch.setattr("app.opportunities.utcnow", lambda: stamp(r.clock[0]))
    monkeypatch.setattr("app.opportunities.time", SimpleNamespace(time=lambda: r.clock[0]))
    trace = []

    async def quotes(providers, rows):
        return {
            (c["pool"], c["contract"]): market(c["contract"]).model_dump()
            | {"pair_address": c["pool"], "observed_at": stamp(r.clock[0])}
            for c in rows
        }

    async def checked(address):
        trace.append(("security", address))
        if address == second["contract"]:
            r.clock[0] += 25
        return security() | {"observed_at": stamp(r.clock[0])}

    original = Jupiter.fill

    async def fill(self, side, *args):
        trace.append((side, args[1]))
        return await original(self, side, *args)

    monkeypatch.setattr("app.opportunities.pool_markets", quotes)
    monkeypatch.setattr(r.engine.service.providers, "security", checked)
    monkeypatch.setattr(Jupiter, "fill", fill)

    async def run():
        await r.engine.cycle(False)
        if r.engine.route_task:
            await r.engine.route_task

    asyncio.run(run())
    out = next(
        o
        for o in r.engine.routes.detail(r.candidate["id"])["outcomes"]
        if o["signal_id"] == r.signal_id and o["horizon_seconds"] == 300
    )
    assert out["state"] == "evaluated", out["payload"]
    assert trace.index(("sell", r.candidate["contract"])) < trace.index(
        ("security", second["contract"])
    )
    if security_age == 118:
        assert ("security", r.candidate["contract"]) in trace
    assert r.engine.service.settings.max_snapshot_age == 120


def test_later_market_batch_is_fetched_after_first_batch_is_persisted(client_engine, monkeypatch):
    _, engine = client_engine
    engine.configure(engine.config().model_copy(update={"routed_quotes_enabled": False}))
    now = time.time()
    queue = [candidate(engine, 9100 + i, now) for i in range(31)]
    monkeypatch.setattr(engine, "due", lambda cfg: queue)
    events = []

    async def quotes(providers, rows):
        events.append(("fetch", rows[0]["id"]))
        return {
            (c["pool"], c["contract"]): market(c["contract"]).model_dump()
            | {"pair_address": c["pool"]}
            for c in rows
        }

    original = engine._persist_candidate

    def persist(c, *args):
        events.append(("persist", c["id"]))
        return original(c, *args)

    monkeypatch.setattr("app.opportunities.pool_markets", quotes)
    monkeypatch.setattr(engine, "_persist_candidate", persist)
    asyncio.run(engine.cycle(False))
    assert events.index(("persist", queue[29]["id"])) < events.index(("fetch", queue[30]["id"]))
    assert sum(e[0] == "fetch" for e in events) == 2


def test_collecting_many_candidates_keeps_one_total_route_budget(routed, monkeypatch):
    r = routed
    r.engine.configure(r.engine.config().model_copy(update={"routed_quote_budget": 2}))
    queue = [r.candidate]
    for i in range(4):
        c = candidate(r.engine, 9200 + i, r.clock[0] - 10)
        p = r.engine.policy(r.engine.config())
        r.engine.save_observation(
            c, payload(r.engine, c, r.clock[0] - 6), p, r.engine.config(), stamp(r.clock[0] - 6)
        )
        r.engine.save_observation(
            c, payload(r.engine, c, r.clock[0] - 1), p, r.engine.config(), stamp(r.clock[0] - 1)
        )
        queue.append(c)
    monkeypatch.setattr(r.engine, "due", lambda cfg: queue)

    async def run():
        await r.engine.cycle(False)
        if r.engine.route_task:
            await r.engine.route_task

    asyncio.run(run())
    with r.engine.store.connect() as db:
        assert db.execute("SELECT count(*) FROM routed_attempts").fetchone()[0] == 2


def test_zero_dispatch_budget_does_not_claim_an_attempt(routed):
    assert asyncio.run(routed.engine.routes.cycle(budget=0))["attempted"] == 0
    assert not routed.engine.routes.detail(routed.candidate["id"])["attempts"]
    assert not routed.calls


def test_later_empty_dispatch_cannot_hide_an_earlier_provider_failure(routed):
    r = routed
    r.failure[0] = 401
    asyncio.run(r.engine.cycle(False))
    status = r.engine.routes.status
    assert status["state"] == "partial"
    assert status["attempted"] == 1
    assert any("JUPITER_API_KEY" in error for error in status["errors"])
    assert (
        r.engine.routes.detail(r.candidate["id"])["entries"][0]["entry_state"]
        == "entry_unavailable"
    )
