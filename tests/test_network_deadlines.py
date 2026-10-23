"""Controlled network faults, real collector/SQLite; no real trades or API calls."""

import asyncio
import time

from tests.test_observation_sampling import candidate
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import seed
from tests.test_opportunity_routes import routed as routed


def small_budget(*args, **kwargs):
    from app.collection_budget import CollectionBudget

    return CollectionBudget(1.6, reserve=0.1)


def test_security_outage_cannot_block_every_later_candidate(client_engine, monkeypatch):
    _, engine = client_engine
    first, _, cfg = seed(engine)
    second = candidate(engine, 22001, time.time())
    engine.configure(cfg.model_copy(update={"routed_quotes_enabled": False}))
    monkeypatch.setattr(engine, "due", lambda _: [first, second])
    monkeypatch.setattr("app.opportunities.CollectionBudget", small_budget, raising=False)
    calls, cancelled = [], []

    async def stalled(address):
        calls.append(address)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(address)

    monkeypatch.setattr(engine.service.providers, "security", stalled)

    async def run():
        return await asyncio.wait_for(engine.cycle(False), 5)

    result = asyncio.run(run())
    assert result["observed"] == 2
    assert len(calls) == len(cancelled) == 1
    assert result["security_allocation"]["used"] == 1
    for c in [first, second]:
        last = engine.history(c["id"])[-1]
        assert last["security"]["rpc"] is None
        assert last["decision"]["screening"]["paper_allowed"] is False


def test_stalled_discovery_does_not_block_already_due_observations(client_engine, monkeypatch):
    _, engine = client_engine
    c, _, cfg = seed(engine)
    engine.configure(cfg.model_copy(update={"routed_quotes_enabled": False}))
    monkeypatch.setattr("app.opportunities.CollectionBudget", small_budget, raising=False)
    cancelled = []

    async def stalled(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    async def boosts():
        return None

    monkeypatch.setattr(engine.service.discovery, "refresh", stalled)
    monkeypatch.setattr(engine.service.discovery, "boosts", boosts)

    async def run():
        return await asyncio.wait_for(engine.cycle(), 5)

    result = asyncio.run(run())
    assert cancelled == [True]
    assert result["observed"] == 1
    assert engine.history(c["id"])[-1]["market"]
    assert "discovery_temporarily_unavailable" in result["errors"]


def test_no_time_for_a_full_quote_defers_without_claiming_a_failed_trade(routed):
    from types import SimpleNamespace

    r = routed
    before = r.engine.routes.detail(r.candidate["id"])
    session = {
        "limit": 4,
        "attempted": 0,
        "errors": [],
        "started_at": "fixture",
        "clock": SimpleNamespace(remaining=0),
    }
    asyncio.run(r.engine.dispatch_routes(session))
    after = r.engine.routes.detail(r.candidate["id"])
    assert after["attempts"] == before["attempts"] == []
    assert after["entries"][0]["entry_state"] == "entry_pending"
    assert session["attempted"] == 0
    assert r.calls == []


def test_unstarted_second_batch_keeps_jobs_pending_without_a_provider_failure(
    client_engine, monkeypatch
):
    from app.collection_budget import CollectionBudget
    from tests.test_observation_sampling import scheduled

    _, engine = client_engine
    now = time.time()
    queue = [scheduled(engine, 23000 + i, now - 10, selected=True)[0] for i in range(31)]
    engine.configure(engine.config().model_copy(update={"routed_quotes_enabled": False}))
    monkeypatch.setattr(engine, "due", lambda _: queue)
    clock = [0.0]
    budget = CollectionBudget(60, clock=lambda: clock[0])
    monkeypatch.setattr("app.opportunities.CollectionBudget", lambda *a, **k: budget)
    original = engine._persist_candidate

    def persist(*args):
        original(*args)
        clock[0] = 56

    monkeypatch.setattr(engine, "_persist_candidate", persist)
    result = asyncio.run(engine.cycle(False))
    assert result["collection_plan"]["started"] == 30
    assert result["collection_plan"]["deferred_before_market_read"] == 1
    with engine.store.connect() as db:
        jobs = db.execute(
            "SELECT status,last_dispatch_at FROM observation_jobs WHERE candidate_id=?",
            (queue[-1]["id"],),
        ).fetchall()
        assert all(r["status"] == "pending" and r["last_dispatch_at"] is None for r in jobs)
        assert (
            db.execute(
                "SELECT last_attempt_at FROM opportunity_candidates WHERE id=?", (queue[-1]["id"],)
            ).fetchone()[0]
            is None
        )
    assert engine.history(queue[-1]["id"]) == []


def test_quote_dispatch_admits_one_at_a_time_and_preserves_total_budget(routed, monkeypatch):
    from types import SimpleNamespace

    r = routed
    calls = []

    async def routes(*, budget):
        calls.append(budget)
        return {"attempted": 1, "errors": [], "state": "ok"}

    monkeypatch.setattr(r.engine.routes, "cycle", routes)
    session = {
        "limit": 4,
        "attempted": 0,
        "errors": [],
        "started_at": "fixture",
        "clock": SimpleNamespace(remaining=100),
    }
    asyncio.run(r.engine.dispatch_routes(session))
    assert calls == [1]
    asyncio.run(r.engine.dispatch_routes(session, drain=True))
    assert calls == [1, 1, 1, 1]
    assert session["attempted"] == 4


def test_empty_routed_queue_is_not_reported_as_a_deferred_trade(client_engine):
    from types import SimpleNamespace

    _, engine = client_engine
    engine.configure(engine.config().model_copy(update={"routed_quotes_enabled": True}))
    session = {
        "limit": 4,
        "attempted": 0,
        "errors": [],
        "started_at": "fixture",
        "clock": SimpleNamespace(remaining=0),
    }
    asyncio.run(engine.dispatch_routes(session, drain=True))
    assert session["deferred_for_time"] is False
    assert engine.routes.status["state"] == "ok"
    assert engine.routes.status["collector_dispatch_state"] == "idle"
