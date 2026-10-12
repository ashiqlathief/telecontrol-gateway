# Mini telecontrol gateway

Sits between a Modbus TCP PV inverter and an IEC 60870-5-104 peer (direct marketer).It polls the inverter every second, converts values to IEC 104 units, flags stale data as invalid, and accepts active power limits with write / read-back / confirm.

**Scope:** Part A (core logic, tests) and Part B (a real IEC 104 server using the open-source `c104` library, with a demo client). The server is a basic controlled station:see "What is missing" for what it does not do.

## How it works

```
direct marketer  <-- IEC 104 -->  gateway  <-- Modbus TCP -->  PV inverter
(reads values,                    (converts, checks,            (registers
 sends limits)                     verifies, fails safe)         40000-40010)
```

**Every second (poll cycle):**
1. Read registers 40000-40005 (P, Q, f, status) and 40010 (limit) from the inverter.
2. Convert to IEC 104 units (W to kW, 0.01 Hz to Hz) and store with a receive timestamp.
3. Publish changed values to the IEC 104 peer. Values older than 5 s go out with the IV flag.
4. Check how long the IEC 104 peer has been silent; after 60 s run the fallback policy.

**On a limit command (C_SE_NC_1, IOA 5001):**
1. Validate: whole number 0-100, otherwise negative confirmation, nothing written.
2. Write register 40010 (retry on failure), then read it back.
3. Positive confirmation only if the read-back equals the command. Any failure gives a
   negative confirmation, and the limit point is invalidated if its true value is unknown.

The rule behind all of it: a wrong value is worse than no value, so the gateway reports
"invalid" or "rejected" instead of guessing.

## Run

Python 3.12.

```
python3 -m venv .venv && .venv/bin/pip install pymodbus c104 pytest pytest-asyncio ruff
.venv/bin/python -m pytest -q          # 70 tests, ~3 s
.venv/bin/ruff check .
```
Demo, three terminals:

```
.venv/bin/python -m sim.inverter_sim --port 5020        # simulated inverter, 80 kW available
.venv/bin/python -m gateway --port 5020                 # gateway; IEC 104 server on :2404
.venv/bin/python -m sim.demo_client --limit 40          # the "direct marketer"
```

The client connects, does a general interrogation, prints IOA 1001-1005, sends `C_SE_NC_1` on IOA 5001 and prints the confirmation (positive/negative) and the updated values. Try `--limit 150` or `--limit 50.5` for a negative confirmation. Stop the inverter simulator, wait 6 s, run the client again: every point is printed as `INVALID`.

The gateway terminal also accepts typed lines as a shortcut without an IEC client: `limit 40`, `ping` (IEC link sign of life). Options: `--iec-port N` (0 = off), `--fallback hold|safe_limit`, `--fallback-limit N`, `--iec-timeout SECONDS`. Other 104 clients should work too (common address 1, IOAs as in the task); I only tested with `c104`'s own client.

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

## Design decisions and what is missing

The reasoning behind each requirement (stale data, limit commands with read-back, the
fallback default and why, the IEC 104 layer) and the full list of what is missing for use on
a real plant are in [`tex/wattsinn_questions_explained.pdf`](tex/wattsinn_questions_explained.pdf)
(sections 3 and 6: implementation and limitations). The two written answers are in `ANSWERS.md`.

In short: the default fallback on IEC 104 link loss is **hold the last limit** (configurable
to a safe preset); stale values go out with the IV flag; a command is confirmed only after
a read-back match. Not covered: a full IEC 104 feature set, real-device verification and a
plant controller.
