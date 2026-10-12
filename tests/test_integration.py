"""End to end against a real pymodbus TCP server (the simulator)."""

import socket

import pytest

from gateway.config import Config
from gateway.gateway import Gateway
from gateway.inverter import InverterError, ModbusInverter
from sim.inverter_sim import InverterSim


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def sim():
    port = free_port()
    s = InverterSim(port=port, available_w=80_000)
    task = await s.start()
    s.port = port
    yield s
    await s.stop()
    task.cancel()


async def test_poll_and_limit_roundtrip_over_tcp(sim):
    inv = ModbusInverter("127.0.0.1", sim.port)
    gw = Gateway(inv, Config(port=sim.port))
    try:
        await gw.poll_once()
        got = {p.name: p for p in gw.snapshot()}
        assert got["active_power_kw"].value == 80.0
        assert got["reactive_power_kvar"].value == -1.2  # negative int32 survives the wire
        assert got["frequency_hz"].value == 50.01
        assert got["limit_pct"].value == 100
        assert all(p.valid for p in gw.snapshot())

        conf = await gw.handle_limit_command(25)
        assert conf.ok and await sim.get_limit() == 25
        await sim.refresh()
        await gw.poll_once()
        assert gw.state.get("active_power_kw").value == 25.0
        assert gw.state.get("status").value == 2  # curtailed
    finally:
        inv.close()


async def test_unreachable_inverter_raises_inverter_error():
    inv = ModbusInverter("127.0.0.1", free_port(), timeout_s=0.3)
    try:
        with pytest.raises(InverterError):
            await inv.read_limit()
    finally:
        inv.close()


async def test_gateway_survives_unreachable_inverter():
    inv = ModbusInverter("127.0.0.1", free_port(), timeout_s=0.3)
    gw = Gateway(inv, Config())
    try:
        await gw.poll_once()  # must not raise
        assert not any(p.valid for p in gw.snapshot())
        conf = await gw.handle_limit_command(50)
        assert not conf.ok and conf.reason == "write_failed"
    finally:
        inv.close()
