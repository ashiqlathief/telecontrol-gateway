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
    s = InverterSim(port=port, available_w=100_000)
    task = await s.start()
    s.port = port
    yield s
    await s.stop()
    task.cancel()


async def test_poll_and_limit_roundtrip_over_tcp(sim):
    inv = ModbusInverter("127.0.0.1", sim.port)  # 1. real Modbus client to the simulator
    gw = Gateway(inv, Config(port=sim.port))
    try:
        await gw.poll_once()  # 2. poll over a real TCP socket
        got = {p.name: p for p in gw.snapshot()}
        assert got["active_power_kw"].value == 100.0     # 3. 100 kW available in the simulator
        assert got["reactive_power_kvar"].value == -1.2  #    negative int32 survives the wire
        assert got["frequency_hz"].value == 50.01        #    frequency in Hz
        assert got["limit_pct"].value == 100             #    limit starts at 100 %
        assert all(p.valid for p in gw.snapshot())       #    everything valid

        conf = await gw.handle_limit_command(25)        # 4. send limit 25 %
        assert conf.ok and await sim.get_limit() == 25  # 5. confirmed, simulator holds 25
        await sim.refresh()                             # 6. simulated plant reacts to the limit
        await gw.poll_once()
        assert gw.state.get("active_power_kw").value == 25.0  # 7. now produces 25 kW
        assert gw.state.get("status").value == 2              #    status 2 = curtailed
    finally:
        inv.close()


async def test_unreachable_inverter_raises_inverter_error():
    inv = ModbusInverter("127.0.0.1", free_port(), timeout_s=0.3)  # 1. nothing listens on this port
    try:
        with pytest.raises(InverterError):  # 2. the read must fail cleanly as InverterError
            await inv.read_limit()
    finally:
        inv.close()


async def test_gateway_survives_unreachable_inverter():
    inv = ModbusInverter("127.0.0.1", free_port(), timeout_s=0.3)  # 1. dead inverter
    gw = Gateway(inv, Config())
    try:
        await gw.poll_once()                                  # 2. must not raise
        assert not any(p.valid for p in gw.snapshot())        # 3. no point looks valid
        conf = await gw.handle_limit_command(50)              # 4. a command ...
        assert not conf.ok and conf.reason == "write_failed"  # 5. ... gets a negative confirmation
    finally:
        inv.close()
