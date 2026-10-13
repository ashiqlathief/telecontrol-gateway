"""
Part B: real IEC 104 traffic between a c104 client and the gateway's c104 server.

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
    await gw.poll_once()                                      # 1. gateway polls the pretend inverter (50 kW, 1.5 kvar, 50.01 Hz ...)
    server.publish()                                          # 2. gateway pushes the values into the IEC 104 server
    await peer.connect()                                      # 3. client (the marketer) connects and asks for all values
    await _eventually(lambda: peer.p[1001].value == 50.0)     # 4. wait until 50 kW arrives
    assert peer.p[1002].value == 1.5                          # 5. reactive power in kvar
    assert peer.p[1003].value == pytest.approx(50.01)         #    frequency in Hz
    assert peer.p[1004].value == 100                          #    limit in %
    assert int(peer.p[1005].value) == 1                       #    status 1 = running
    assert all(p.quality.is_good() for p in peer.p.values())  # 6. every point has good quality


async def test_never_received_value_is_flagged_invalid(iec):
    _, _, peer = iec
    await peer.connect()                                         # 1. client connects before any poll happened
    await _eventually(lambda: peer.p[1001].quality is not None)  # 2. wait for the point to arrive
    assert not peer.p[1001].quality.is_good()                    # 3. it carries the invalid flag, not a fake 0.0


async def test_stale_value_is_resent_with_iv_flag(iec, clock):
    gw, server, peer = iec
    await gw.poll_once()  # 1. one poll, then publish
    server.publish()
    await peer.connect()                                                                      # 2. client connects
    await _eventually(lambda: peer.p[1001].quality.is_good() and peer.p[1001].value == 50.0)  # 3. fresh
    clock.advance(6)                                                                          # 4. 6 s pass with no new poll
    server.publish()                                                                          # 5. gateway publishes again
    await _eventually(lambda: not peer.p[1001].quality.is_good())                             # 6. same number, now flagged IV


async def test_valid_command_gets_positive_confirmation_and_is_applied(iec, inverter):
    _, _, peer = iec
    await peer.connect()                        # 1. client connects
    assert await peer.send_limit(40.0) is True  # 2. sends 40 %: positive confirmation
    assert inverter.limit_reg == 40             # 3. the inverter register really holds 40


@pytest.mark.parametrize("bad", [150.0, -5.0, 50.5, float("nan")])
async def test_bad_command_gets_negative_confirmation_and_is_not_written(iec, inverter, bad):
    _, _, peer = iec
    await peer.connect()                        # 1. client connects
    assert await peer.send_limit(bad) is False  # 2. 150, -5, 50.5 or NaN: negative confirmation
    assert inverter.write_calls == []           # 3. the inverter was never asked to write


async def test_readback_mismatch_gives_negative_confirmation(iec, inverter):
    _, _, peer = iec
    inverter.clamp_to = 60                       # 1. inverter secretly applies 60, whatever you ask
    await peer.connect()                         # 2. client connects
    assert await peer.send_limit(40.0) is False  # 3. asks for 40: read-back says 60, no confirm


async def test_write_failure_gives_negative_confirmation(iec, inverter):
    _, _, peer = iec
    inverter.fail_writes = True                  # 1. inverter refuses every write
    await peer.connect()                         # 2. client connects
    assert await peer.send_limit(40.0) is False  # 3. negative confirmation


async def test_connected_client_keeps_link_alive(iec, clock):
    gw, server, peer = iec
    await peer.connect()  # 1. client connects and stays connected
    for _ in range(3):    # 2. three rounds of 40 s = 120 s in total
        clock.advance(40)
        server.supervise_link()    #    gateway checks the IEC link
        await gw.check_link()      #    and the fallback watchdog
    assert not gw.fallback_active  # 3. connected client = sign of life, so no fallback


async def test_without_client_the_link_times_out(iec, clock):
    gw, server, _ = iec
    clock.advance(61)        # 1. 61 s pass and nobody ever connected
    server.supervise_link()  # 2. no sign of life
    await gw.check_link()
    assert gw.fallback_active  # 3. fallback becomes active


async def test_disconnect_starts_the_timeout(iec, clock):
    gw, server, peer = iec
    await peer.connect()  # 1. client connects ...
    server.supervise_link()
    peer.close()                                                          # 2. ... then disconnects
    await _eventually(lambda: not server._server.has_active_connections)  # 3. wait until gone
    clock.advance(61)                                                     # 4. 61 s pass
    server.supervise_link()
    await gw.check_link()
    assert gw.fallback_active  # 5. fallback becomes active


async def test_deactivation_command_is_refused_and_not_written(iec, inverter):
    _, _, peer = iec
    await peer.connect()                                                    # 1. client connects
    peer.cmd.value = 40.0                                                   # 2. prepares a 40 % command ...
    ok = await asyncio.to_thread(peer.cmd.transmit, c104.Cot.DEACTIVATION)  # 3. ... sent as "cancel"
    assert ok is False                                                      # 4. refused
    assert inverter.write_calls == []                                       # 5. nothing was written
