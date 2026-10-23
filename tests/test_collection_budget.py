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


@pytest.mark.parametrize("scope", ["enrichment", "cycle", "discovery_group"])
def test_expired_timer_cannot_reopen_allowance_when_accounting_clock_lags(scope):
    """A coarse clock need not advance as far as the event loop's timeout."""
    async def run():
        budget = CollectionBudget(0.04, reserve=0.03 if scope == "cycle" else 0, clock=lambda: 0)
        limits = {"enrichment": scope == "enrichment"}
        if scope == "discovery_group":
            limits["until"] = 0.01
        cancelled, started = [], []

        async def stalled():
            started.append(True)
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

        with pytest.raises(TimeoutError):
            await budget.call("first", stalled, 1, **limits)
        first = budget.report()["calls"]["first"]
        assert first["budget_timeouts"] == 1
        assert first["provider_timeouts"] == 0
        with pytest.raises(CollectionDeferred):
            await budget.call("second", stalled, 1, **limits)
        assert started == cancelled == [True]
        assert budget.report()["calls"]["second"]["started"] == 0

    asyncio.run(run())


def test_provider_timeout_does_not_exhaust_unused_collection_allowance():
    async def run():
        budget = CollectionBudget(60, clock=lambda: 0)

        async def provider_timeout():
            raise TimeoutError("Provider rejected its own request immediately")

        async def healthy():
            return "independent evidence"

        with pytest.raises(TimeoutError):
            await budget.call("provider", provider_timeout, 30, enrichment=True)
        assert await budget.call("healthy", healthy, 30, enrichment=True) == "independent evidence"
        assert budget.remaining == 55
        report = budget.report()
        assert report["calls"]["provider"]["provider_timeouts"] == 1
        assert report["calls"]["provider"]["budget_timeouts"] == 0
        assert report["enrichment_accounted_seconds"] == 0
        assert report["enrichment_reserved_seconds"] == 0

    asyncio.run(run())


def test_concurrent_optional_requests_reserve_one_shared_allowance_and_release_on_cancel():
    async def run():
        budget = CollectionBudget(60, clock=lambda: 0)
        entered, finished = asyncio.Event(), asyncio.Event()
        unexpected = []

        async def stalled():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

        async def healthy():
            unexpected.append(True)
            return "evidence"

        task = asyncio.create_task(budget.call("first", stalled, 30, enrichment=True))
        await entered.wait()
        assert budget.report()["enrichment_reserved_seconds"] == 15
        with pytest.raises(CollectionDeferred):
            await budget.call("second", healthy, 30, enrichment=True)
        assert not unexpected
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
        assert budget.report()["enrichment_reserved_seconds"] == 0
        assert budget.report()["calls"]["first"]["timeouts"] == 0
        assert await budget.call("third", healthy, 30, enrichment=True) == "evidence"

    asyncio.run(run())


def test_per_request_timeout_does_not_spend_the_whole_optional_budget():
    async def run():
        budget = CollectionBudget(60, clock=lambda: 0)

        async def stalled():
            await asyncio.Event().wait()

        async def healthy():
            return True

        with pytest.raises(TimeoutError):
            await budget.call("short_request", stalled, 0.01, enrichment=True)
        assert budget.report()["enrichment_accounted_seconds"] == 0.01
        assert budget.report()["enrichment_wait_seconds"] == 0
        assert await budget.call("next", healthy, 30, enrichment=True)
        assert budget.remaining == 55

    asyncio.run(run())
