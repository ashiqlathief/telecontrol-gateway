from dataclasses import dataclass
from enum import Enum


class FallbackMode(str, Enum):
    HOLD = "hold"  # keep the last confirmed limit
    SAFE_LIMIT = "safe_limit"  # write `fallback_limit_pct` to the inverter


@dataclass(frozen=True)
class Config:
    host: str = "127.0.0.1"
    port: int = 5020
    device_id: int = 1
    poll_interval_s: float = 1.0
    stale_after_s: float = 5.0
    # IEC 104 link supervision
    iec_loss_timeout_s: float = 60.0
    fallback_mode: FallbackMode = FallbackMode.HOLD
    fallback_limit_pct: int | None = None  # required for SAFE_LIMIT, no default on purpose
    # Inverter write handling
    write_retries: int = 2  # extra attempts after the first failed write
    modbus_timeout_s: float = 2.0

    def __post_init__(self) -> None:
        # A "safe" value that nobody chose is a guess; 100 % would not limit anything.
        if self.fallback_mode is FallbackMode.SAFE_LIMIT:
            pct = self.fallback_limit_pct
            if pct is None or not 0 <= pct <= 100:
                raise ValueError("safe_limit needs an explicit fallback_limit_pct in 0-100")
