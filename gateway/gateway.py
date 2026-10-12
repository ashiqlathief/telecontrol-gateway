"""Gateway core: polling, limit commands with read-back, IEC 104 link supervision."""

import asyncio
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from .config import Config, FallbackMode
from .inverter import Inverter, InverterError
from .scaling import decode_int32_be, to_hz, to_kvar, to_kw, to_status
from .state import Point, StateStore

log = logging.getLogger("gateway")

LIMIT_MIN, LIMIT_MAX = 0, 100


@dataclass(frozen=True)
class Confirmation:
    """Activation confirmation for C_SE_NC_1. ok=False is a negative confirmation (P/N=1)."""

    ok: bool
    reason: str = ""
    applied_pct: int | None = None


class Gateway:
    def __init__(
        self,
        inverter: Inverter,
        config: Config | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.cfg = config or Config()
        self._inv = inverter
        self._clock = clock
        self.state = StateStore(self.cfg.stale_after_s, clock)
        self._lock = asyncio.Lock()  # one Modbus transaction sequence at a time
        self._last_iec_seen = clock()
        self.fallback_active = False
        self._fallback_applied = False

    # ---- measurements -------------------------------------------------

    async def poll_once(self) -> None:
        """Read the inverter. On any failure the old value is left alone and ages out."""
        try:
            async with self._lock:
                raw = await self._inv.read_measurements()
        except InverterError as exc:
            log.warning("measurement read failed: %s", exc)
        else:
            self.state.update("active_power_kw", to_kw(decode_int32_be(raw.p_hi, raw.p_lo)))
            self.state.update("reactive_power_kvar", to_kvar(decode_int32_be(raw.q_hi, raw.q_lo)))
            self.state.update("frequency_hz", to_hz(raw.freq))
            try:
                self.state.update("status", to_status(raw.status))
            except ValueError as exc:
                log.warning("%s; status left to go stale", exc)

        try:
            async with self._lock:
                limit = await self._inv.read_limit()
        except InverterError as exc:
            log.warning("limit read failed: %s", exc)
            return
        if LIMIT_MIN <= limit <= LIMIT_MAX:
            self.state.update("limit_pct", limit)
        else:
            log.warning("inverter reports limit %s outside 0-100; ignored", limit)

    def snapshot(self) -> list[Point]:
        return self.state.snapshot()

    # ---- commands -----------------------------------------------------

    def note_iec_activity(self) -> None:
        """Call on any sign of life from the IEC 104 peer (frame, keep-alive, command)."""
        self._last_iec_seen = self._clock()
        self.fallback_active = False
        self._fallback_applied = False

    async def handle_limit_command(self, value: float) -> Confirmation:
        self.note_iec_activity()
        pct = _validate_limit(value)
        if pct is None:
            log.warning("rejected limit command %r", value)
            return Confirmation(False, "out_of_range")
        async with self._lock:
            return await self._write_and_verify(pct)

    async def _write_and_verify(self, pct: int) -> Confirmation:
        """Write, read back, confirm only on exact match. Caller holds the lock."""
        last_exc: InverterError | None = None
        for _ in range(1 + self.cfg.write_retries):
            try:
                await self._inv.write_limit(pct)
                break
            except InverterError as exc:
                last_exc = exc
        else:
            # The register may or may not have changed: the true limit is unknown.
            self.state.invalidate("limit_pct")
            log.error("limit write failed after retries: %s", last_exc)
            return Confirmation(False, "write_failed")

        try:
            actual = await self._inv.read_limit()
        except InverterError as exc:
            self.state.invalidate("limit_pct")
            log.error("limit read-back failed: %s", exc)
            return Confirmation(False, "readback_failed")

        if LIMIT_MIN <= actual <= LIMIT_MAX:
            self.state.update("limit_pct", actual)
        else:
            self.state.invalidate("limit_pct")
        if actual != pct:
            log.error("read-back mismatch: wrote %s, inverter reports %s", pct, actual)
            return Confirmation(False, "readback_mismatch", applied_pct=actual)
        return Confirmation(True, applied_pct=actual)

    # ---- IEC 104 link supervision ------------------------------------

    async def check_link(self) -> None:
        """Run periodically. Applies the fallback once the IEC 104 peer is silent too long."""
        silent_s = self._clock() - self._last_iec_seen
        if silent_s <= self.cfg.iec_loss_timeout_s:
            return
        if not self.fallback_active:
            self.fallback_active = True
            log.error(
                "IEC 104 silent for %.0fs; fallback mode=%s", silent_s, self.cfg.fallback_mode.value
            )
        if self.cfg.fallback_mode is FallbackMode.SAFE_LIMIT and not self._fallback_applied:
            async with self._lock:
                result = await self._write_and_verify(self.cfg.fallback_limit_pct)
            self._fallback_applied = result.ok  # on failure, retry at the next check
            if not result.ok:
                log.error("fallback limit not applied (%s); will retry", result.reason)

    # ---- main loop ------------------------------------------------------

    async def run(self, on_cycle: Callable[[], None] | None = None) -> None:
        """Poll forever. `on_cycle` runs after each poll, before the link check."""
        while True:
            await self.poll_once()
            if on_cycle:
                on_cycle()
            await self.check_link()
            await asyncio.sleep(self.cfg.poll_interval_s)


def _validate_limit(value: object) -> int | None:
    """Return the limit as int if it is a finite whole number in 0-100, else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value != int(value):
        return None  # the register holds whole percent; never silently round a command
    pct = int(value)
    return pct if LIMIT_MIN <= pct <= LIMIT_MAX else None
