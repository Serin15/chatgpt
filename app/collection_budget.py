"""Monotonic limits for provider waits, without interrupting durable writes."""

import asyncio
from time import monotonic

VERSION = "collection-network-budget-v2"


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
        self.enrichment_wait = 0
        self.enrichment_reserved = 0
        self.deadline_exhausted = False
        self.exhausted_groups = set()
        self.market_candidates_started = 0
        self.calls = {}

    @property
    def remaining(self):
        if self.deadline_exhausted:
            return 0
        return max(0, self.deadline - self.clock())

    async def call(self, name, operation, timeout, *, enrichment=False, until=None):
        stats = self.calls.setdefault(
            name, {
                "started": 0, "timeouts": 0, "budget_timeouts": 0,
                "provider_timeouts": 0, "errors": 0, "deferred": 0, "seconds": 0,
            }
        )
        cycle_left = self.remaining
        allowed = min(timeout, cycle_left)
        if enrichment:
            allowed = min(allowed, max(
                0, self.enrichment_seconds - self.enrichment_spent - self.enrichment_reserved
            ))
        group_left = None
        if until is not None:
            group_left = 0 if until in self.exhausted_groups else max(0, until - self.clock())
            allowed = min(allowed, group_left)
        if allowed <= 0:
            stats["deferred"] += 1
            raise CollectionDeferred(
                "Collection time budget exhausted; no provider request started."
            )
        began = self.clock()
        stats["started"] += 1
        if enrichment:
            self.enrichment_reserved += allowed
        timer = asyncio.timeout(allowed)
        try:
            async with timer:
                return await operation()
        except TimeoutError:
            stats["timeouts"] += 1
            stats["budget_timeouts" if timer.expired() else "provider_timeouts"] += 1
            raise
        except Exception:
            stats["errors"] += 1
            raise
        finally:
            elapsed = max(0, self.clock() - began)
            stats["seconds"] += elapsed
            # Event-loop timers may fire before a coarse monotonic clock reports
            # the whole allowance (notably on Windows). An expired timer spends
            # its admitted allowance; a provider's own early TimeoutError does not.
            if timer.expired():
                if allowed == cycle_left:
                    self.deadline_exhausted = True
                if group_left is not None and allowed == group_left:
                    self.exhausted_groups.add(until)
            if enrichment:
                self.enrichment_reserved -= allowed
                self.enrichment_wait += elapsed
                self.enrichment_spent += max(elapsed, allowed if timer.expired() else 0)

    def report(self):
        return {
            "version": VERSION,
            "network_budget_seconds": self.network_seconds,
            "enrichment_budget_seconds": self.enrichment_seconds,
            "enrichment_wait_seconds": round(self.enrichment_wait, 4),
            "enrichment_accounted_seconds": round(self.enrichment_spent, 4),
            "enrichment_reserved_seconds": round(self.enrichment_reserved, 4),
            "cycle_deadline_exhausted": self.deadline_exhausted,
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
