"""Monotonic limits for provider waits, without interrupting durable writes."""

import asyncio
from time import monotonic

VERSION = "collection-network-budget-v1"


class CollectionDeferred(TimeoutError):
    """No request was started; pending work must remain available for a later cycle."""


class CollectionBudget:
    def __init__(self, interval, *, started=None, reserve=5, clock=None):
        self.clock = clock or monotonic
        self.started = self.clock() if started is None else started
        self.network_seconds = max(0, interval - reserve)
        self.deadline = self.started + self.network_seconds
        self.enrichment_seconds = min(30, interval / 4)
        self.discovery_seconds = min(10, interval / 6)
        self.story_seconds = min(5, interval / 12)
        self.market_seconds = min(15, interval / 4)
        self.enrichment_spent = 0
        self.market_candidates_started = 0
        self.calls = {}

    @property
    def remaining(self):
        return max(0, self.deadline - self.clock())

    async def call(self, name, operation, timeout, *, enrichment=False, until=None):
        stats = self.calls.setdefault(
            name, {"started": 0, "timeouts": 0, "errors": 0, "deferred": 0, "seconds": 0}
        )
        allowed = min(timeout, self.remaining)
        if enrichment:
            allowed = min(allowed, max(0, self.enrichment_seconds - self.enrichment_spent))
        if until is not None:
            allowed = min(allowed, max(0, until - self.clock()))
        if allowed <= 0:
            stats["deferred"] += 1
            raise CollectionDeferred(
                "Collection time budget exhausted; no provider request started."
            )
        began = self.clock()
        stats["started"] += 1
        try:
            return await asyncio.wait_for(operation(), allowed)
        except TimeoutError:
            stats["timeouts"] += 1
            raise
        except Exception:
            stats["errors"] += 1
            raise
        finally:
            elapsed = max(0, self.clock() - began)
            stats["seconds"] += elapsed
            if enrichment:
                self.enrichment_spent += elapsed

    def report(self):
        return {
            "version": VERSION,
            "network_budget_seconds": self.network_seconds,
            "enrichment_budget_seconds": self.enrichment_seconds,
            "enrichment_wait_seconds": round(self.enrichment_spent, 4),
            "remaining_seconds": round(self.remaining, 4),
            "elapsed_seconds": round(max(0, self.clock() - self.started), 4),
            "market_candidates_started": self.market_candidates_started,
            "calls": {
                name: stats | {"seconds": round(stats["seconds"], 4)}
                for name, stats in self.calls.items()
            },
            "scope": "Provider waits share a monotonic cycle deadline. Storage finalization is allowed to finish and may overrun the nominal interval. Deferred work is not a failed provider request or a failed trade.",
        }


async def bounded(budget, name, operation, timeout, **limits):
    if budget is None:
        return await asyncio.wait_for(operation(), timeout)
    return await budget.call(name, operation, timeout, **limits)
