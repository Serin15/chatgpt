"""Isolated storage delays must not freeze the application's event loop."""

import asyncio
from threading import Event

import pytest

from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import seed


@pytest.mark.parametrize("stage", ["snapshot", "outcomes", "coverage"])
def test_collection_storage_delay_allows_other_tasks_to_run(client_engine, monkeypatch, stage):
    _, engine = client_engine
    seed(engine)
    target, method = {
        "snapshot": (engine.service.store, "save_snapshot"),
        "outcomes": (engine, "update_outcomes"),
        "coverage": (engine.sampling, "coverage"),
    }[stage]
    original = getattr(target, method)
    entered, release, finished = Event(), Event(), Event()
    observed = []

    def delayed(*args, **kwargs):
        entered.set()
        release.wait(2)
        finished.set()
        return original(*args, **kwargs)

    monkeypatch.setattr(target, method, delayed)

    async def run():
        async def probe():
            while not entered.is_set():
                await asyncio.sleep(0.001)
            observed.append(not finished.is_set())
            release.set()

        probe_task = asyncio.create_task(probe())
        try:
            await engine.cycle(refresh_discovery=False)
        finally:
            release.set()
            await probe_task

    asyncio.run(run())
    assert observed == [True], "Storage work blocked the event loop until it finished"


def test_cancelled_collection_retains_lease_until_its_write_finishes(client_engine, monkeypatch):
    _, engine = client_engine
    seed(engine)
    original = engine.service.store.save_snapshot
    entered, release, finished = Event(), Event(), Event()

    def delayed(*args, **kwargs):
        entered.set()
        release.wait(2)
        result = original(*args, **kwargs)
        finished.set()
        return result

    monkeypatch.setattr(engine.service.store, "save_snapshot", delayed)

    async def run():
        task = asyncio.create_task(engine.cycle(refresh_discovery=False))
        try:
            while not entered.is_set():
                await asyncio.sleep(0.001)
            task.cancel()
            await asyncio.sleep(0)
            assert not finished.is_set() and not task.done()
            assert engine.lock.locked()
            with engine.store.connect() as db:
                assert (
                    db.execute("SELECT owner FROM opportunity_lease WHERE id=1").fetchone()[0]
                    == engine.owner
                )
        finally:
            release.set()
            try:
                await task
            except asyncio.CancelledError:
                pass
        assert finished.is_set() and task.cancelled()
        assert not engine.lock.locked()
        with engine.store.connect() as db:
            assert db.execute("SELECT owner FROM opportunity_lease WHERE id=1").fetchone() is None

    asyncio.run(run())
