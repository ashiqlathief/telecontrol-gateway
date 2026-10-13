"""Demo IEC 104 client (the 'direct marketer'): read values, send a limit.

python -m sim.demo_client --limit 40
python -m sim.demo_client --watch 60      # read once, then print every change for 60 s
"""

import argparse
import time

import c104


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2404)
    ap.add_argument("--limit", type=float, help="send C_SE_NC_1 on IOA 5001")
    ap.add_argument("--watch", type=int, default=3, help="seconds to stay connected and print every change")
    a = ap.parse_args()

    client = c104.Client()
    conn = client.add_connection(ip=a.host, port=a.port, init=c104.Init.ALL)
    station = conn.add_station(common_address=1)
    points = {
        ioa: station.add_point(io_address=ioa, type=t)
        for ioa, t in [
            (1001, c104.Type.M_ME_NC_1),
            (1002, c104.Type.M_ME_NC_1),
            (1003, c104.Type.M_ME_NC_1),
            (1004, c104.Type.M_ME_NC_1),
            (1005, c104.Type.M_ME_NB_1),
        ]
    }
    command = station.add_point(io_address=5001, type=c104.Type.C_SE_NC_1)

    client.start()
    for _ in range(50):
        if conn.is_connected:
            break
        time.sleep(0.1)
    else:
        raise SystemExit("could not connect")

    def show(title: str) -> None:
        print(title)
        for ioa, p in points.items():
            flag = "OK" if p.quality.is_good() else "INVALID"
            print(f"  {flag:7} IOA {ioa} {p.type} = {p.value}")

    conn.interrogation(1, wait_for_response=True)
    time.sleep(0.3)
    show("after general interrogation:")

    started = time.monotonic()

    def on_update(
        point: c104.Point, previous_info: c104.Information, message: c104.IncomingMessage
    ) -> c104.ResponseState:
        flag = "OK" if point.quality.is_good() else "INVALID"
        print(f"  [{time.monotonic() - started:5.1f} s] {flag:7} IOA {point.io_address} = {point.value}")
        return c104.ResponseState.SUCCESS

    # Registered after the first print, so only later changes show up.
    for p in points.values():
        p.on_receive(callable=on_update)

    if a.limit is not None:
        command.value = a.limit
        ok = command.transmit(c104.Cot.ACTIVATION)
        print(f"\nlimit {a.limit} % -> {'POSITIVE' if ok else 'NEGATIVE'} confirmation")

    if a.watch > 0:
        print(f"\nwatching for {a.watch} s, printing every change ...")
        time.sleep(a.watch)
        show("\nafter watching:")
    client.stop()


if __name__ == "__main__":
    main()
