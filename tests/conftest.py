import pytest

from gateway.config import Config
from gateway.gateway import Gateway
from gateway.inverter import InverterError, RawMeasurements


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeInverter:
    """In-memory inverter with switchable failure modes."""

    def __init__(self):
        self.limit_reg = 100
        self.raw = RawMeasurements(0, 50_000, 0, 1_500, 5001, 1)  # 50 kW, 1.5 kvar, 50.01 Hz
        self.fail_reads = False
        self.fail_writes = False
        self.write_calls: list[int] = []
        self.ignore_writes = False  # device accepts the write but does not apply it
        self.clamp_to: int | None = None  # device silently applies a different value

    async def read_measurements(self) -> RawMeasurements:
        if self.fail_reads:
            raise InverterError("down")
        return self.raw

    async def read_limit(self) -> int:
        if self.fail_reads:
            raise InverterError("down")
        return self.limit_reg

    async def write_limit(self, pct: int) -> None:
        self.write_calls.append(pct)
        if self.fail_writes:
            raise InverterError("write refused")
        if self.ignore_writes:
            return
        self.limit_reg = self.clamp_to if self.clamp_to is not None else pct


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def inverter():
    return FakeInverter()


@pytest.fixture
def make_gateway(clock, inverter):
    def _make(**cfg):
        return Gateway(inverter, Config(**cfg), clock)

    return _make


@pytest.fixture
def gw(make_gateway):
    return make_gateway()
