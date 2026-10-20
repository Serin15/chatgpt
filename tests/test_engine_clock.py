"""Prospective declarations cannot use a coarse clock to admit a past cutoff."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import stamp


@pytest.mark.parametrize("offset", [-0.005, 0, 0.005])
def test_test_cutoff_must_be_strictly_future_on_the_capture_clock(
    client_engine, monkeypatch, offset
):
    _, engine = client_engine
    now = datetime.now(UTC).timestamp()
    monkeypatch.setattr("app.opportunities.utcnow", lambda: stamp(now))
    monkeypatch.setattr("app.opportunities.time", SimpleNamespace(time=lambda: now - 0.01))
    config = engine.config().model_copy(
        update={"test_from": datetime.fromtimestamp(now + offset, UTC)}
    )
    if offset <= 0:
        with pytest.raises(ValueError, match="declared before"):
            engine.configure(config)
    else:
        assert engine.configure(config)["test_from"] == stamp(now + offset).replace("+00:00", "Z")
