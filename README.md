# Mini telecontrol gateway

Sits between a Modbus TCP PV inverter and an IEC 60870-5-104 peer (direct marketer). It polls the inverter every second, converts values to IEC 104 units, flags stale data as invalid, and accepts active power limits with write / read-back / confirm.

## Run

Python 3.12.

```
python3 -m venv .venv && .venv/bin/pip install pymodbus c104 pytest pytest-asyncio ruff
.venv/bin/python -m pytest -q          # 76 tests, ~3 s
.venv/bin/ruff check .
```
Demo, four terminals (start them in this order):

```
# terminal 1: simulated inverter, 100 kW available
.venv/bin/python -m sim.inverter_sim --port 5020

# terminal 2: the gateway; IEC 104 server on :2404; prints all five points every second
.venv/bin/python -m gateway --port 5020

# terminal 3: the "direct marketer" watching; reads once, then prints every change for 60 s
.venv/bin/python -m sim.demo_client --watch 60

# terminal 4: a second "direct marketer" sending a limit
.venv/bin/python -m sim.demo_client --limit 40
```

`sim.demo_client` connects, does a general interrogation and prints IOA 1001-1005. With `--limit` it also sends `C_SE_NC_1` on IOA 5001 and prints the confirmation (positive/negative). With `--watch N` (default 3) it then stays connected for N seconds and prints every change with its time and quality flag, then prints the final values.

What to look for: run terminal 4 while terminal 3 is watching. Terminal 3 prints IOA 1001, 1004 and 1005 changing within about a second (100 kW to 40 kW, limit 100 to 40, status 1 to 2). Try `--limit 150` or `--limit 50.5` for a negative confirmation: nothing changes. Stop the inverter simulator, wait 6 s, run a client again: every point is printed as `INVALID`.

The gateway terminal also accepts typed lines as a shortcut without an IEC client: `limit 40`, `ping` (IEC link sign of life). Options: `--iec-port N` (0 = off), `--fallback hold|safe_limit`, `--fallback-limit N`, `--iec-timeout SECONDS`. Other 104 clients should work too (common address 1, IOAs as in the task); I only tested with `c104`'s own client.

### Demo video

[Watch the demo (mbclient.webm)](mbclient.webm)

## Layout

| File | Role |
|---|---|
| `gateway/scaling.py` | Pure register -> unit conversions (int32 BE, kW, kvar, Hz, status enum) |
| `gateway/state.py` | Latest values with timestamps; `valid=False` after 5 s; IOA / type table |
| `gateway/inverter.py` | pymodbus client behind a small `Inverter` protocol; all failures become `InverterError` |
| `gateway/gateway.py` | Polling, limit command with read-back, IEC link watchdog and fallback |
| `gateway/iec104.py` | c104 server: publishes points with quality flags, forwards commands, link supervision |
| `gateway/config.py` | All thresholds and the fallback policy |
| `sim/inverter_sim.py` | pymodbus server simulating the register map |
| `sim/demo_client.py` | c104 client acting as the direct marketer |
| `tests/` | Unit tests with a fake inverter and fake clock, plus Modbus TCP and IEC 104 integration tests |

## How to test

Automated (76 tests, ~3 s, no hardware, a fake clock replaces real waiting):

```
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```

Run one requirement at a time (add `-v` to see every test name). No real hardware is involved:
the inverter is either an in-memory fake or the simulator in `sim/`.

| Requirement | Command | What it proves |
|---|---|---|
| R1 scaling (12 tests) | `.venv/bin/python -m pytest -q tests/test_scaling.py` | int32 big-endian join, W to kW, 0.01 Hz, status enum |
| R2 stale data (8) | `.venv/bin/python -m pytest -q tests/test_stale.py` | valid at exactly 5 s, invalid after; a failed read does not refresh the old value; recovery |
| R3 commands (24) | `.venv/bin/python -m pytest -q tests/test_command.py` | 0-100 only; read-back mismatch, ignored write and write failure give a negative confirmation |
| R4 fallback (15) | `.venv/bin/python -m pytest -q tests/test_fallback.py` | nothing before 60 s; `hold` does not write; `safe_limit` writes once and retries on failure; any IEC activity resets the timer |
| Modbus over TCP, simulated inverter (3) | `.venv/bin/python -m pytest -q tests/test_integration.py` | the real Modbus code talks to the pymodbus simulator over a local socket; an unreachable inverter fails cleanly |
| IEC 104 over TCP, Part B (14) | `.venv/bin/python -m pytest -q tests/test_iec104.py` | a c104 client talks to the gateway's server: quality flags, confirmations, link loss |

A single test: `.venv/bin/python -m pytest -q tests/test_command.py -k readback_mismatch`.

"Tests prove the fix": to check a test is not empty, remove the guard it covers
(e.g. the `actual != pct` check in `gateway/gateway.py`) and run `pytest`; the matching test must fail.

Manual fault injection with the demo from the Run section:

| Do this | Expect |
|---|---|
| `--limit 150` or `--limit 50.5` | negative confirmation, inverter register unchanged |
| Stop the inverter simulator, wait 6 s, run the client | every point printed `INVALID` |
| Restart the simulator | points become valid again within ~1 s |
| Start the gateway with `--iec-timeout 10 --fallback safe_limit --fallback-limit 20`, send no IEC traffic | after 10 s log "IEC 104 silent ... fallback", inverter limit becomes 20 % |

