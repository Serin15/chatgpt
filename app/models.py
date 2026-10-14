import math
import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def epoch(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def freshness(observed_at, source_at=None, max_age=120, now=None):
    now = datetime.now(UTC).timestamp() if now is None else now
    try:
        receipt_age = now - epoch(observed_at)
        source_age = now - epoch(source_at) if source_at else None
        fresh = (
            0 <= receipt_age <= max_age and source_age is not None and 0 <= source_age <= max_age
        )
        return {
            "fresh": fresh,
            "age_seconds": round(receipt_age),
            "source_age_seconds": round(source_age) if source_age is not None else None,
        }
    except (ValueError, TypeError, OverflowError):
        return {"fresh": False, "age_seconds": None, "source_age_seconds": None}


def solana_address(value: str) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", value):
        raise ValueError("Adresă Solana invalidă")
    number = 0
    for char in value:
        number = number * 58 + alphabet.index(char)
    size = (number.bit_length() + 7) // 8 + len(value) - len(value.lstrip("1"))
    if size != 32:
        raise ValueError("Adresa Solana trebuie să reprezinte 32 bytes")
    return value


class AddToken(BaseModel):
    address: str

    @field_validator("address")
    @classmethod
    def validate_address(cls, value):
        return solana_address(value.strip())


class PaperBuy(BaseModel):
    address: str
    amount_usd: str = Field(max_length=32)
    signal_id: int
    account: Literal["scanner", "news"] = "scanner"


class SignalRequest(BaseModel):
    account: Literal["scanner", "news"] = "scanner"
    news_id: int | None = Field(default=None, gt=0)
    thesis: str = Field(default="", max_length=1000)


class AssetBuy(BaseModel):
    asset_id: str = Field(pattern=r"^[a-z0-9-]{1,80}$")
    amount_usd: str = Field(max_length=32)
    signal_id: int


class AssetWatch(BaseModel):
    asset_id: str = Field(pattern=r"^[a-z0-9-]{1,80}$")


class Market(BaseModel):
    address: str
    symbol: str
    name: str
    pair_address: str
    dex: str
    price_usd: float = Field(gt=0, allow_inf_nan=False)
    liquidity_usd: float = Field(ge=0, allow_inf_nan=False)
    volume_5m: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    volume_1h: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    change_5m: float | None = Field(default=None, allow_inf_nan=False)
    buys_5m: int | None = Field(default=None, ge=0)
    sells_5m: int | None = Field(default=None, ge=0)
    buyers_5m_reported: int | None = Field(default=None, ge=0)
    sellers_5m_reported: int | None = Field(default=None, ge=0)
    market_cap: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    fdv: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    pool_created_at: int | None = None
    observed_at: str = Field(default_factory=utcnow)
    source: str = "DEX Screener"


def number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError):
        return default
