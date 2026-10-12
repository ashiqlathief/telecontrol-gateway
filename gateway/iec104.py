"""IEC 60870-5-104 server (controlled station) on top of the c104 library.

Monitoring points 1001-1005 mirror the gateway state; command point 5001 (C_SE_NC_1) is
forwarded to `Gateway.handle_limit_command`. The c104 stack runs in its own threads; the
gateway is asyncio, so commands cross over with `run_coroutine_threadsafe`.
"""

import asyncio
import logging

import c104

from .gateway import Gateway
from .state import Point

log = logging.getLogger("gateway.iec104")

COMMON_ADDRESS = 1
IOA_LIMIT_COMMAND = 5001
_TYPES = {"M_ME_NC_1": c104.Type.M_ME_NC_1, "M_ME_NB_1": c104.Type.M_ME_NB_1}


class Iec104Server:
    def __init__(
        self,
        gateway: Gateway,
        loop: asyncio.AbstractEventLoop,
        ip: str = "0.0.0.0",
        port: int = 2404,
        command_timeout_s: float = 10.0,
    ):
        self._gw = gateway
        self._loop = loop
        self._command_timeout_s = command_timeout_s
        self._server = c104.Server(ip=ip, port=port)
        station = self._server.add_station(common_address=COMMON_ADDRESS)
        self._points = {
            p.name: station.add_point(io_address=p.ioa, type=_TYPES[p.type_id])
            for p in gateway.snapshot()
        }
        self._published: dict[str, tuple[float | int | None, bool]] = {}
        self._command = station.add_point(io_address=IOA_LIMIT_COMMAND, type=c104.Type.C_SE_NC_1)
        self._command.on_receive(self._on_command)
        self.publish()  # every point starts out invalid so a client's first read is honest

    def start(self) -> None:
        self._server.start()

    def stop(self) -> None:
        self._server.stop()

    # ---- monitoring direction -----------------------------------------

    def publish(self) -> None:
        """Push changed values / validity to the clients. Called once per poll cycle."""
        for p in self._gw.snapshot():
            key = (p.value, p.valid)
            if self._published.get(p.name) == key:
                continue
            self._published[p.name] = key
            self._write(self._points[p.name], p)

    @staticmethod
    def _write(point: "c104.Point", p: Point) -> None:
        # A stale or never-received value is sent with IV set; it must not look fresh.
        raw = p.value if p.value is not None else 0
        point.value = c104.Int16(int(raw)) if p.type_id == "M_ME_NB_1" else float(raw)
        point.quality = c104.Quality() if p.valid else c104.Quality.Invalid
        point.transmit(c104.Cot.SPONTANEOUS)

    # ---- link supervision ---------------------------------------------

    def supervise_link(self) -> None:
        """A client with an active data transfer connection counts as sign of life.
        104 itself closes the connection on t1/t3 timeouts, so a dead peer drops out here."""
        if self._server.has_active_connections:
            self._gw.note_iec_activity()

    # ---- control direction --------------------------------------------

    def _on_command(
        self,
        point: c104.Point,
        previous_info: c104.Information,
        message: c104.IncomingMessage,
    ) -> c104.ResponseState:
        """Runs in a c104 thread; blocks until the gateway has written and verified."""
        self._gw.note_iec_activity()
        if message.is_test or message.cot != c104.Cot.ACTIVATION:
            return c104.ResponseState.FAILURE
        future = asyncio.run_coroutine_threadsafe(
            self._gw.handle_limit_command(point.value), self._loop
        )
        try:
            conf = future.result(timeout=self._command_timeout_s)
        except Exception:
            future.cancel()
            log.exception("limit command failed")
            return c104.ResponseState.FAILURE
        return c104.ResponseState.SUCCESS if conf.ok else c104.ResponseState.FAILURE
