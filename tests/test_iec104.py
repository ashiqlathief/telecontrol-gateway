"""Part B: real IEC 104 traffic between a c104 client and the gateway's c104 server.

c104 calls are blocking, so they run in worker threads; the event loop stays free for the
gateway (the server's command callback needs it).
"""

import asyncio
import socket

import c104
import pytest

from gateway.iec104 import Iec104Server

MON = [
    (1001, c104.Type.M_ME_NC_1),
    (1002, c104.Type.M_ME_NC_1),
    (1003, c104.Type.M_ME_NC_1),
    (1004, c104.Type.M_ME_NC_1),
    (1005, c104.Type.M_ME_NB_1),
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _eventually(cond, timeout=5.0):
    for _ in range(int(timeout / 0.05)):
        if cond():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not reached")


class Peer:
    """The 'direct marketer'."""

    def __init__(self, port):
        self.client = c104.Client()
        self.conn = self.client.add_connection(ip="127.0.0.1", port=port, init=c104.Init.ALL)
        st = self.conn.add_station(common_address=1)
        self.p = {ioa: st.add_point(io_address=ioa, type=t) for ioa, t in MON}
        self.cmd = st.add_point(io_address=5001, type=c104.Type.C_SE_NC_1)

    async def connect(self):
        self.client.start()
        await _eventually(lambda: self.conn.is_connected)
        await asyncio.to_thread(self.conn.interrogation, 1, c104.Cot.ACTIVATION)

    async def send_limit(self, value) -> bool:
        self.cmd.value = value
        return await asyncio.to_thread(self.cmd.transmit, c104.Cot.ACTIVATION)

    def close(self):
        self.client.stop()


@pytest.fixture
async def iec(make_gateway, inverter):
    gw = make_gateway()
    port = _free_port()
    server = Iec104Server(gw, asyncio.get_running_loop(), ip="127.0.0.1", port=port)
    server.start()
    peer = Peer(port)
    yield gw, server, peer
    peer.close()
    server.stop()


async def test_values_reach_client_with_good_quality(iec):
    gw, server, peer = iec
    await gw.poll_once()
    server.publish()
    await peer.connect()
    await _eventually(lambda: peer.p[1001].value == 50.0)
    assert peer.p[1002].value == 1.5
    assert peer.p[1003].value == pytest.approx(50.01)
    assert peer.p[1004].value == 100
    assert int(peer.p[1005].value) == 1
    assert all(p.quality.is_good() for p in peer.p.values())


async def test_never_received_value_is_flagged_invalid(iec):
    _, _, peer = iec
    await peer.connect()
    await _eventually(lambda: peer.p[1001].quality is not None)
    assert not peer.p[1001].quality.is_good()  # nothing polled yet: IV, not a fake 0.0


async def test_stale_value_is_resent_with_iv_flag(iec, clock):
    gw, server, peer = iec
    await gw.poll_once()
    server.publish()
    await peer.connect()
    await _eventually(lambda: peer.p[1001].quality.is_good() and peer.p[1001].value == 50.0)
    clock.advance(6)  # same value, but older than 5 s
    server.publish()
    await _eventually(lambda: not peer.p[1001].quality.is_good())


async def test_valid_command_gets_positive_confirmation_and_is_applied(iec, inverter):
    _, _, peer = iec
    await peer.connect()
    assert await peer.send_limit(40.0) is True
    assert inverter.limit_reg == 40


@pytest.mark.parametrize("bad", [150.0, -5.0, 50.5, float("nan")])
async def test_bad_command_gets_negative_confirmation_and_is_not_written(iec, inverter, bad):
    _, _, peer = iec
    await peer.connect()
    assert await peer.send_limit(bad) is False
    assert inverter.write_calls == []


async def test_readback_mismatch_gives_negative_confirmation(iec, inverter):
    _, _, peer = iec
    inverter.clamp_to = 60
    await peer.connect()
    assert await peer.send_limit(40.0) is False


async def test_write_failure_gives_negative_confirmation(iec, inverter):
    _, _, peer = iec
    inverter.fail_writes = True
    await peer.connect()
    assert await peer.send_limit(40.0) is False


async def test_connected_client_keeps_link_alive(iec, clock):
    gw, server, peer = iec
    await peer.connect()
    for _ in range(3):
        clock.advance(40)
        server.supervise_link()
        await gw.check_link()
    assert not gw.fallback_active


async def test_without_client_the_link_times_out(iec, clock):
    gw, server, _ = iec
    clock.advance(61)
    server.supervise_link()  # nobody connected: no sign of life
    await gw.check_link()
    assert gw.fallback_active


async def test_disconnect_starts_the_timeout(iec, clock):
    gw, server, peer = iec
    await peer.connect()
    server.supervise_link()
    peer.close()
    await _eventually(lambda: not server._server.has_active_connections)
    clock.advance(61)
    server.supervise_link()
    await gw.check_link()
    assert gw.fallback_active


async def test_deactivation_command_is_refused_and_not_written(iec, inverter):
    _, _, peer = iec
    await peer.connect()
    peer.cmd.value = 40.0
    ok = await asyncio.to_thread(peer.cmd.transmit, c104.Cot.DEACTIVATION)
    assert ok is False
    assert inverter.write_calls == []
