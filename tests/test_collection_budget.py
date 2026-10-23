"""Real event-loop cancellation plus deterministic admission-clock checks."""

import asyncio

import pytest

from app.collection_budget import CollectionBudget, CollectionDeferred


def test_expired_budget_does_not_create_a_coroutine_or_start_a_request():
    clock = [0.0]
    budget = CollectionBudget(60, clock=lambda: clock[0])
    clock[0] = 56
    called = []

    def request():
        called.append(True)
        raise AssertionError("Must not create the request")

    with pytest.raises(CollectionDeferred):
        asyncio.run(budget.call("fixture", request, 20))
    assert called == []
    assert budget.report()["calls"]["fixture"]["started"] == 0


def test_optional_timeouts_share_one_allowance_and_cancel_the_underlying_request():
    async def run():
        budget = CollectionBudget(0.2, reserve=0)
        cancelled = []

        async def stalled():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

        with pytest.raises(TimeoutError):
            await budget.call("security", stalled, 30, enrichment=True)
        with pytest.raises(CollectionDeferred):
            await budget.call("fallback", stalled, 15, enrichment=True)
        assert cancelled == [True]
        assert budget.report()["calls"]["security"]["timeouts"] == 1
        assert budget.report()["calls"]["fallback"]["started"] == 0

    asyncio.run(run())


def test_parent_cancellation_is_not_swallowed_or_left_running():
    async def run():
        budget = CollectionBudget(60)
        entered, finished = asyncio.Event(), asyncio.Event()

        async def request():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

        task = asyncio.create_task(budget.call("fixture", request, 20))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()

    asyncio.run(run())
