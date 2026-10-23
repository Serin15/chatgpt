"""Independent RPC/GoPlus reads keep evidence and error order deterministic."""

import asyncio
from types import SimpleNamespace

from app.errors import ProviderError
from app.providers import Providers


def test_security_sources_overlap_and_keep_their_evidence():
    async def run():
        first, second = asyncio.Event(), asyncio.Event()

        async def rpc(address):
            first.set()
            await asyncio.wait_for(second.wait(), 0.2)
            return {"slot": 42}

        async def goplus(address):
            second.set()
            await asyncio.wait_for(first.wait(), 0.2)
            return {"mintable": {"status": "0"}}

        result = await Providers.security(SimpleNamespace(mint_info=rpc, goplus=goplus), "fixture")
        assert result["rpc"] == {"slot": 42}
        assert result["goplus"] == {"mintable": {"status": "0"}}
        assert result["errors"] == []

    asyncio.run(run())


def test_failed_source_keeps_independent_evidence_and_stable_error_order():
    async def run():
        async def rpc(address):
            await asyncio.sleep(0)
            raise ProviderError("rpc fixture unavailable")

        async def goplus(address):
            return {"fixture": True}

        result = await Providers.security(SimpleNamespace(mint_info=rpc, goplus=goplus), "fixture")
        assert result["rpc"] is None
        assert result["goplus"] == {"fixture": True}
        assert result["errors"] == ["rpc fixture unavailable"]

    asyncio.run(run())


def test_cancelled_security_read_finishes_both_provider_tasks():
    async def run():
        entered = {name: asyncio.Event() for name in ["rpc", "goplus"]}
        finished = set()

        async def source(name):
            entered[name].set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.add(name)

        reader = SimpleNamespace(
            mint_info=lambda _: source("rpc"), goplus=lambda _: source("goplus")
        )
        task = asyncio.create_task(Providers.security(reader, "fixture"))
        await asyncio.wait_for(asyncio.gather(*(e.wait() for e in entered.values())), 1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert finished == {"rpc", "goplus"}
        assert task.cancelled()

    asyncio.run(run())
