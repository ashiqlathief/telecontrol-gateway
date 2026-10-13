"""Requirement 3: accept 0-100 only; write, read back, confirm only on match."""

import math

import pytest


@pytest.mark.parametrize("pct", [0, 1, 50, 99, 100, 50.0])
async def test_valid_limit_is_written_and_confirmed(gw, inverter, pct):
    # Runs once per value in the list above: edges (0, 100), middle, and 50.0 (a whole float).
    conf = await gw.handle_limit_command(pct)           # 1. marketer sends a valid limit
    assert conf.ok and conf.applied_pct == int(pct)     # 2. gateway confirms positively
    assert inverter.limit_reg == int(pct)               # 3. the inverter register really holds it
    assert gw.state.get("limit_pct").value == int(pct)  # 4. gateway reports the new limit


@pytest.mark.parametrize("bad", [-1, -0.1, 100.1, 101, 1000, 50.5, math.nan, math.inf, -math.inf])
async def test_out_of_range_or_non_integer_is_rejected_and_not_written(gw, inverter, bad):
    conf = await gw.handle_limit_command(bad)             # 1. marketer sends nonsense (150, 50.5, NaN ...)
    assert not conf.ok and conf.reason == "out_of_range"  # 2. negative confirmation with reason
    assert inverter.write_calls == []                     # 3. the inverter was never even asked to write
    assert inverter.limit_reg == 100                      # 4. its limit is untouched


@pytest.mark.parametrize("bad", [None, "50", True, [50]])
async def test_wrong_type_is_rejected(gw, inverter, bad):
    # Not a number at all: nothing, text, True (a bool is not a percentage), a list.
    conf = await gw.handle_limit_command(bad)  # 1. send the wrong type
    assert not conf.ok                         # 2. negative confirmation
    assert inverter.write_calls == []          # 3. nothing was written


async def test_readback_mismatch_gives_negative_confirmation(gw, inverter):
    inverter.clamp_to = 60                     # 1. inverter secretly applies 60, whatever you ask
    conf = await gw.handle_limit_command(40)   # 2. marketer asks the gateway for 40 %
    assert not conf.ok                         # 3. gateway must NOT confirm
    assert conf.reason == "readback_mismatch"  #    and must say why
    assert conf.applied_pct == 60              #    and report the real value
    # the state shows the real value, not the requested one
    assert gw.state.get("limit_pct").value == 60


async def test_write_ignored_by_device_is_not_confirmed(gw, inverter):
    inverter.ignore_writes = True             # 1. inverter accepts the write but does not apply it
    conf = await gw.handle_limit_command(10)  # 2. marketer asks for 10 %
    # 3. read-back still says 100, which differs from 10: no confirmation
    assert not conf.ok and conf.reason == "readback_mismatch"


async def test_write_failure_gives_negative_confirmation_after_retries(make_gateway, inverter):
    gw = make_gateway(write_retries=2)                    # 1. gateway may retry a failed write twice
    await gw.poll_once()                                  # 2. first read the limit, so it is valid before the failure
    inverter.fail_writes = True                           # 3. every write now fails
    conf = await gw.handle_limit_command(30)              # 4. marketer asks for 30 %
    assert not conf.ok and conf.reason == "write_failed"  # 5. negative confirmation
    assert inverter.write_calls == [30, 30, 30]           # 6. 1 try + 2 retries, then it gave up
    # true limit is unknown now: must not keep reporting the old one as valid
    assert not gw.state.get("limit_pct").valid            # 7. limit point is marked invalid, not guessed


async def test_transient_write_failure_is_retried(make_gateway, inverter):
    gw = make_gateway(write_retries=1)  # 1. one retry allowed
    calls = {"n": 0}
    original = inverter.write_limit

    async def flaky(pct):  # 2. replacement write: the first call fails, later calls work
        calls["n"] += 1
        if calls["n"] == 1:
            from gateway.inverter import InverterError

            raise InverterError("blip")
        await original(pct)

    inverter.write_limit = flaky
    conf = await gw.handle_limit_command(30)     # 3. marketer asks for 30 %
    assert conf.ok and inverter.limit_reg == 30  # 4. retry worked: confirmed and applied


async def test_readback_failure_gives_negative_confirmation(gw, inverter):
    original = inverter.write_limit

    async def write_then_die(pct):  # 1. write works, then the inverter drops off
        await original(pct)
        inverter.fail_reads = True

    inverter.write_limit = write_then_die
    conf = await gw.handle_limit_command(30)                 # 2. marketer asks for 30 %
    assert not conf.ok and conf.reason == "readback_failed"  # 3. cannot verify, so no confirm
    assert not gw.state.get("limit_pct").valid               # 4. real limit unknown: point marked invalid
