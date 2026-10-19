"""Reproduce differing UTC/time.time precision without accepting future captures."""

import asyncio
from datetime import UTC, datetime

import pytest

from tests.conftest import ADDRESS, market, security
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import stamp


@pytest.mark.parametrize("future", [None, "market", "security"])
def test_screening_uses_the_capture_clock_but_rejects_actual_future_data(
    client_engine, monkeypatch, future
):
    _, engine = client_engine
    now = datetime.now(UTC).timestamp()
    m = market(ADDRESS, observed_at=stamp(now + (0.001 if future == "market" else 0)))
    s = security() | {"observed_at": stamp(now + (0.001 if future == "security" else 0))}

    async def quoted(_):
        return m

    async def screened(_):
        return s

    monkeypatch.setattr(engine.service.providers, "market", quoted)
    monkeypatch.setattr(engine.service.providers, "security", screened)
    monkeypatch.setattr("app.service.utcnow", lambda: stamp(now))
    monkeypatch.setattr("time.time", lambda: now - 0.01)
    captured = asyncio.run(engine.service.refresh(ADDRESS))
    assert captured["analysis"]["paper_allowed"] is (future is None)
