"""Real OS directory lock and SQLite lease; no providers or money on the network."""

import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_assets import FixtureAssets
from tests.test_news import FixtureNews, NewsFixtureProviders


def test_restart_recovers_crashed_lease_only_after_exclusive_directory_lock(settings):
    def make_app():
        return create_app(settings, NewsFixtureProviders(), False, FixtureNews, FixtureAssets)

    with TestClient(make_app()) as first:
        engine = first.app.state.service.opportunities
        with engine.store.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO opportunity_lease VALUES(1,'crashed-fixture-owner',?)",
                (time.time() + 600,),
            )
        # A second process must never clear a lease while this instance is alive.
        with pytest.raises(ValueError, match="data directory is in use"):
            with TestClient(make_app()):
                pass
        with engine.store.connect() as db:
            assert (
                db.execute("SELECT owner FROM opportunity_lease").fetchone()[0]
                == "crashed-fixture-owner"
            )
    with TestClient(make_app()) as restarted:
        engine = restarted.app.state.service.opportunities
        assert engine.acquire(), (
            "Exclusive OS lock proves the previous app is gone; no ten-minute wait"
        )
        engine.release()
