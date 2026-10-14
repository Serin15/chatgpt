import time
from datetime import UTC, datetime

import pytest

from app.analysis import LEGACY_TOKEN_PROGRAM, analyze
from app.config import Settings
from app.models import Market
from app.store import Store

ADDRESS = "So11111111111111111111111111111111111111112"
OTHER = "11111111111111111111111111111111"


@pytest.fixture(autouse=True)
def isolate_external_configuration(monkeypatch):
    """Unit fixtures must never inherit production credentials or hosted settings."""
    keys = (
        "PULSE_AI_API_KEY",
        "OPENAI_API_KEY",
        "JUPITER_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "PULSE_AUTH_PASSWORD",
        "GOPLUS_ACCESS_TOKEN",
    )
    for key in keys:
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key + "_FILE", raising=False)
    for key in (
        "PULSE_HOSTED",
        "PULSE_PUBLIC_ORIGIN",
        "PULSE_AI_PROVIDER",
        "PULSE_AI_MODEL",
        "PULSE_OLLAMA_URL",
        "PAPER_SOLANA_EXECUTION",
        "BASE_RPC_URL",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path)


@pytest.fixture
def store(settings):
    return Store(settings)


def security():
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "rpc": {
            "program": LEGACY_TOKEN_PROGRAM,
            "mint_authority": None,
            "freeze_authority": None,
            "extensions": [],
            "slot": 42,
        },
        "goplus": {
            "mintable": {"status": "0"},
            "freezable": {"status": "0"},
            "none_transferable": "0",
            "transfer_fee": {},
            "default_account_state": "1",
        },
        "errors": [],
    }


def market(address=ADDRESS, **overrides):
    fields = dict(
        address=address,
        symbol="FIXTURE",
        name="Explicit test fixture",
        pair_address=OTHER,
        dex="test",
        price_usd=1,
        liquidity_usd=50000,
        volume_5m=20000,
        volume_1h=40000,
        change_5m=5,
        buys_5m=100,
        sells_5m=20,
    )
    return Market(**(fields | overrides))


def snapshot(settings, address=ADDRESS, **overrides):
    m, s = market(address, **overrides), security()
    return {
        "id": 1,
        "address": address,
        "at": m.observed_at,
        "market": m.model_dump(),
        "security": s,
        "analysis": analyze(m, s, settings, time.time()),
    }


def old_signal(store, snap, age=4):
    signal = store.signal(snap)
    with store.connect() as db:
        db.execute(
            "UPDATE signals SET at=? WHERE id=?",
            (datetime.fromtimestamp(time.time() - age, UTC).isoformat(), signal["id"]),
        )
    return signal["id"]
