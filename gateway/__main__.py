"""Demo CLI. Stdin lines stand in for IEC 104: `limit 50` sends a C_SE_NC_1 command."""

import argparse
import asyncio
import logging
import sys

from .config import Config, FallbackMode
from .gateway import Gateway
from .iec104 import Iec104Server
from .inverter import ModbusInverter


async def _stdin_commands(gw: Gateway) -> None:
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            return
        parts = line.split()
        if len(parts) == 2 and parts[0] == "limit":
            try:
                value = float(parts[1])
            except ValueError:
                print("NEG-CONFIRM bad_number")
                continue
            print(await gw.handle_limit_command(value))
        elif parts == ["ping"]:
            gw.note_iec_activity()
            print("link alive")


async def _report(gw: Gateway) -> None:
    while True:
        await asyncio.sleep(1)
        for p in gw.snapshot():
            q = "OK " if p.valid else "IV "
            print(f"{q}IOA {p.ioa} {p.type_id} {p.name}={p.value}")
        print(f"fallback_active={gw.fallback_active}\n")


async def main() -> None:
    ap = argparse.ArgumentParser(prog="gateway")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--fallback", choices=[m.value for m in FallbackMode], default="hold")
    ap.add_argument("--fallback-limit", type=int, default=100)
    ap.add_argument("--iec-port", type=int, default=2404, help="IEC 104 listen port, 0 = off")
    ap.add_argument("--iec-timeout", type=float, default=60.0)
    a = ap.parse_args()
    cfg = Config(
        host=a.host,
        port=a.port,
        fallback_mode=FallbackMode(a.fallback),
        fallback_limit_pct=a.fallback_limit,
        iec_loss_timeout_s=a.iec_timeout,
    )
    gw = Gateway(ModbusInverter(cfg.host, cfg.port, cfg.device_id, cfg.modbus_timeout_s), cfg)
    iec = None
    on_cycle = None
    if a.iec_port:
        iec = Iec104Server(gw, asyncio.get_running_loop(), port=a.iec_port)
        iec.start()

        def on_cycle() -> None:
            iec.publish()
            iec.supervise_link()

    try:
        await asyncio.gather(gw.run(on_cycle), _stdin_commands(gw), _report(gw))
    finally:
        if iec:
            iec.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
