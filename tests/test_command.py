"""Requirement 3: accept 0-100 only; write, read back, confirm only on match."""

import math

import pytest


@pytest.mark.parametrize("pct", [0, 1, 50, 99, 100, 50.0])
async def test_valid_limit_is_written_and_confirmed(gw, inverter, pct):
    conf = await gw.handle_limit_command(pct)
    assert conf.ok and conf.applied_pct == int(pct)
    assert inverter.limit_reg == int(pct)
    assert gw.state.get("limit_pct").value == int(pct)


@pytest.mark.parametrize("bad", [-1, -0.1, 100.1, 101, 1000, 50.5, math.nan, math.inf, -math.inf])
async def test_out_of_range_or_non_integer_is_rejected_and_not_written(gw, inverter, bad):
    conf = await gw.handle_limit_command(bad)
    assert not conf.ok and conf.reason == "out_of_range"
    assert inverter.write_calls == []
    assert inverter.limit_reg == 100  # untouched


@pytest.mark.parametrize("bad", [None, "50", True, [50]])
async def test_wrong_type_is_rejected(gw, inverter, bad):
    conf = await gw.handle_limit_command(bad)
    assert not conf.ok
    assert inverter.write_calls == []


async def test_readback_mismatch_gives_negative_confirmation(gw, inverter):
    inverter.clamp_to = 60  # inverter applies something else than asked
    conf = await gw.handle_limit_command(40)
    assert not conf.ok and conf.reason == "readback_mismatch"
    assert conf.applied_pct == 60
    # the state shows the real value, not the requested one
    assert gw.state.get("limit_pct").value == 60


async def test_write_ignored_by_device_is_not_confirmed(gw, inverter):
    inverter.ignore_writes = True
    conf = await gw.handle_limit_command(10)
    assert not conf.ok and conf.reason == "readback_mismatch"


async def test_write_failure_gives_negative_confirmation_after_retries(make_gateway, inverter):
    gw = make_gateway(write_retries=2)
    await gw.poll_once()
    inverter.fail_writes = True
    conf = await gw.handle_limit_command(30)
    assert not conf.ok and conf.reason == "write_failed"
    assert inverter.write_calls == [30, 30, 30]  # 1 try + 2 retries
    # true limit is unknown now: must not keep reporting the old one as valid
    assert not gw.state.get("limit_pct").valid


async def test_transient_write_failure_is_retried(make_gateway, inverter):
    gw = make_gateway(write_retries=1)
    calls = {"n": 0}
    original = inverter.write_limit

    async def flaky(pct):
        calls["n"] += 1
        if calls["n"] == 1:
            from gateway.inverter import InverterError

            raise InverterError("blip")
        await original(pct)

    inverter.write_limit = flaky
    conf = await gw.handle_limit_command(30)
    assert conf.ok and inverter.limit_reg == 30


async def test_readback_failure_gives_negative_confirmation(gw, inverter):
    original = inverter.write_limit

    async def write_then_die(pct):
        await original(pct)
        inverter.fail_reads = True

    inverter.write_limit = write_then_die
    conf = await gw.handle_limit_command(30)
    assert not conf.ok and conf.reason == "readback_failed"
    assert not gw.state.get("limit_pct").valid
