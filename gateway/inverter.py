"""Modbus access to the inverter, behind a small interface so tests can fake it."""

import asyncio
from dataclasses import dataclass
from typing import Protocol

from pymodbus.client import AsyncModbusTcpClient

REG_MEASUREMENTS = 40000  # 40000..40005, contiguous: P(2) Q(2) f(1) status(1)
REG_MEASUREMENTS_COUNT = 6
REG_LIMIT = 40010


class InverterError(Exception):
    """Any failure talking to the inverter (connection, timeout, Modbus exception)."""


@dataclass(frozen=True)
class RawMeasurements:
    p_hi: int
    p_lo: int
    q_hi: int
    q_lo: int
    freq: int
    status: int


class Inverter(Protocol):
    async def read_measurements(self) -> RawMeasurements: ...
    async def read_limit(self) -> int: ...
    async def write_limit(self, pct: int) -> None: ...


class ModbusInverter:
    def __init__(self, host: str, port: int, device_id: int = 1, timeout_s: float = 2.0):
        self._device_id = device_id
        self._client = AsyncModbusTcpClient(host, port=port, timeout=timeout_s, retries=0)
        self._timeout_s = timeout_s

    async def _ensure_connected(self) -> None:
        if not self._client.connected:
            await self._client.connect()
        if not self._client.connected:
            raise InverterError("not connected")

    async def _read(self, address: int, count: int) -> list[int]:
        try:
            async with asyncio.timeout(self._timeout_s * 2):
                await self._ensure_connected()
                rr = await self._client.read_holding_registers(
                    address, count=count, device_id=self._device_id
                )
        except Exception as exc:  # pymodbus raises its own exception types
            raise InverterError(f"read {address}: {exc!r}") from exc
        if rr.isError():
            raise InverterError(f"read {address}: {rr}")
        if len(rr.registers) != count:
            raise InverterError(f"read {address}: short response")
        return list(rr.registers)

    async def read_measurements(self) -> RawMeasurements:
        regs = await self._read(REG_MEASUREMENTS, REG_MEASUREMENTS_COUNT)
        return RawMeasurements(*regs)

    async def read_limit(self) -> int:
        return (await self._read(REG_LIMIT, 1))[0]

    async def write_limit(self, pct: int) -> None:
        try:
            async with asyncio.timeout(self._timeout_s * 2):
                await self._ensure_connected()
                wr = await self._client.write_register(REG_LIMIT, pct, device_id=self._device_id)
        except Exception as exc:
            raise InverterError(f"write {REG_LIMIT}: {exc!r}") from exc
        if wr.isError():
            raise InverterError(f"write {REG_LIMIT}: {wr}")

    def close(self) -> None:
        self._client.close()
