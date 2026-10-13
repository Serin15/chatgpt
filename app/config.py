import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    scan_interval_seconds: int = 90
    rpc_url: str = "https://api.mainnet-beta.solana.com"
    goplus_token: str | None = None
    initial_balance: Decimal = Decimal("100")
    min_liquidity: Decimal = Decimal("25000")
    max_allocation: Decimal = Decimal("0.20")
    max_exposure: Decimal = Decimal("0.50")
    daily_loss_limit: Decimal = Decimal("0.10")
    max_price_impact: Decimal = Decimal("0.02")
    swap_fee: Decimal = Decimal("0.003")
    network_fee_usd: Decimal = Decimal("0.01")
    min_position: Decimal = Decimal("2")
    max_snapshot_age: int = 120
    min_signal_delay: int = 3
    reference_fee: Decimal = Decimal("0.006")
    reference_slippage: Decimal = Decimal("0.005")

    def __post_init__(self):
        for key in ("initial_balance", "min_liquidity", "min_position"):
            value = getattr(self, key)
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{key} trebuie să fie pozitiv și finit")
        for key in ("max_allocation", "max_exposure", "daily_loss_limit", "max_price_impact"):
            value = getattr(self, key)
            if not value.is_finite() or not 0 < value <= 1:
                raise ValueError(f"{key} trebuie să fie în (0, 1]")
        if not self.swap_fee.is_finite() or not 0 <= self.swap_fee < 1:
            raise ValueError("swap_fee trebuie să fie în [0, 1)")
        if not self.network_fee_usd.is_finite() or self.network_fee_usd < 0:
            raise ValueError("network_fee_usd invalid")
        for key in ("reference_fee", "reference_slippage"):
            value = getattr(self, key)
            if not value.is_finite() or not 0 <= value < 1:
                raise ValueError(f"{key} invalid")

    @classmethod
    def from_environment(cls):
        defaults = cls()
        names = {
            "initial_balance": "PAPER_START_USD",
            "min_liquidity": "MIN_LIQUIDITY_USD",
            "max_allocation": "MAX_ALLOCATION",
            "max_exposure": "MAX_EXPOSURE",
            "daily_loss_limit": "DAILY_LOSS_LIMIT",
            "max_price_impact": "MAX_PRICE_IMPACT",
            "swap_fee": "SIM_SWAP_FEE",
            "network_fee_usd": "SIM_NETWORK_FEE_USD",
            "min_position": "MIN_POSITION_USD",
            "reference_fee": "SIM_CEX_FEE",
            "reference_slippage": "SIM_REFERENCE_SLIPPAGE",
        }
        rules = {
            key: Decimal(os.getenv(name, str(getattr(defaults, key))))
            for key, name in names.items()
        }
        return cls(
            data_dir=Path(os.getenv("DATA_DIR", "data")),
            scan_interval_seconds=max(60, int(os.getenv("SCAN_INTERVAL_SECONDS", "90"))),
            rpc_url=os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"),
            goplus_token=os.getenv("GOPLUS_ACCESS_TOKEN") or None,
            **rules,
        )
