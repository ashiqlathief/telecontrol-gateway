"""Simulated PV inverter (Modbus TCP, unit 1, holding registers) for demos and tests."""

import argparse
import asyncio

from pymodbus.server import ModbusTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice

RATED_W = 100_000
SIZE = 40_100
HOLDING = 3  # function code used for the datastore accessors


class InverterSim:
    def __init__(self, host: str = "127.0.0.1", port: int = 5020, available_w: int = 80_000):
        self.available_w = available_w
        device = SimDevice(1, [SimData(0, count=SIZE, values=0, datatype=DataType.REGISTERS)])
        self._address = (host, port)
        self._server = ModbusTcpServer(device, address=self._address)

    # register helpers -------------------------------------------------
    async def _set(self, addr: int, values: list[int]) -> None:
        await self._server.async_setValues(1, HOLDING, addr, values)

    async def _get(self, addr: int, count: int = 1) -> list[int]:
        return list(await self._server.async_getValues(1, HOLDING, addr, count))

    @staticmethod
    def _int32(value: int) -> list[int]:
        value &= 0xFFFF_FFFF
        return [value >> 16, value & 0xFFFF]

    async def get_limit(self) -> int:
        return (await self._get(40010))[0]

    async def set_limit(self, pct: int) -> None:
        await self._set(40010, [pct])

    async def refresh(self) -> None:
        """Recompute output from the available power and the limit register."""
        limit = await self.get_limit()
        power = min(self.available_w, RATED_W * limit // 100)
        status = 2 if power < self.available_w else 1
        await self._set(40000, self._int32(power) + self._int32(-1200) + [5001, status])

    # server lifecycle -------------------------------------------------
    async def start(self) -> asyncio.Task:
        task = asyncio.create_task(self._server.serve_forever())
        await self._wait_listening()
        await self.set_limit(100)
        await self.refresh()
        return task

    async def _wait_listening(self) -> None:
        host, port = self._address
        for _ in range(100):
            try:
                _, writer = await asyncio.open_connection(host, port)
            except OSError:
                await asyncio.sleep(0.05)
            else:
                writer.close()
                return
        raise RuntimeError("simulator did not start listening")

    async def stop(self) -> None:
        await self._server.shutdown()


async def _main(port: int) -> None:
    sim = InverterSim(port=port)
    task = await sim.start()

    async def physics() -> None:
        while True:
            await sim.refresh()
            await asyncio.sleep(0.5)

    await asyncio.gather(task, physics())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5020)
    asyncio.run(_main(ap.parse_args().port))
