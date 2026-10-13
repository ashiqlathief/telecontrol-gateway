"""Requirement 4: behaviour when the IEC 104 link is silent > 60 s."""

import pytest

from gateway.config import Config, FallbackMode


async def test_no_fallback_within_timeout(gw, clock):
    clock.advance(60)              # 1. exactly 60 s of silence: not "more than 60 s" yet
    await gw.check_link()          # 2. the watchdog runs
    assert not gw.fallback_active  # 3. nothing happens


async def test_hold_mode_flags_fallback_but_does_not_write(make_gateway, clock, inverter):
    gw = make_gateway(fallback_mode=FallbackMode.HOLD)  # 1. the default policy: hold
    await gw.handle_limit_command(40)                   # 2. marketer sets 40 %
    inverter.write_calls.clear()                        #    forget that write, we only watch for new ones
    clock.advance(61)                                   # 3. link silent for 61 s
    await gw.check_link()
    assert gw.fallback_active          # 4. the gateway knows it is in fallback
    assert inverter.write_calls == []  # 5. but it wrote nothing
    assert inverter.limit_reg == 40    # 6. the last limit is held


async def test_safe_limit_mode_writes_configured_value(make_gateway, clock, inverter):
    gw = make_gateway(fallback_mode=FallbackMode.SAFE_LIMIT, fallback_limit_pct=30)  # 1. policy 30 %
    clock.advance(61)                                                                # 2. link silent for 61 s
    await gw.check_link()
    assert gw.fallback_active        # 3. fallback is on
    assert inverter.limit_reg == 30  # 4. the inverter was limited to 30 %


async def test_safe_limit_is_written_once_not_every_tick(make_gateway, clock, inverter):
    gw = make_gateway(fallback_mode=FallbackMode.SAFE_LIMIT, fallback_limit_pct=30)
    clock.advance(61)
    for _ in range(5):  # watchdog runs five times in a row
        await gw.check_link()
    assert inverter.write_calls == [30]  # only one write, not five


async def test_failed_fallback_write_is_retried_on_next_check(make_gateway, clock, inverter):
    gw = make_gateway(fallback_mode=FallbackMode.SAFE_LIMIT, fallback_limit_pct=30, write_retries=0)
    inverter.fail_writes = True  # 1. inverter refuses writes
    clock.advance(61)
    await gw.check_link()                                    # 2. fallback tries 30 % and fails
    assert gw.fallback_active and inverter.limit_reg == 100  # 3. still at 100 %, fallback is on
    inverter.fail_writes = False                             # 4. inverter works again
    await gw.check_link()                                    # 5. next watchdog run tries again
    assert inverter.limit_reg == 30                          # 6. now it worked


async def test_custom_timeout_is_respected(make_gateway, clock):
    gw = make_gateway(iec_loss_timeout_s=10)  # 1. timeout configured to 10 s instead of 60
    clock.advance(11)
    await gw.check_link()
    assert gw.fallback_active  # 2. 11 s is enough to trigger


async def test_activity_resets_timer_and_clears_fallback(make_gateway, clock):
    gw = make_gateway(fallback_mode=FallbackMode.SAFE_LIMIT, fallback_limit_pct=30)
    clock.advance(61)
    await gw.check_link()
    assert gw.fallback_active      # 1. link lost, fallback is on
    gw.note_iec_activity()         # 2. the marketer's client is heard again
    assert not gw.fallback_active  # 3. fallback is cleared
    clock.advance(30)              # 4. 30 s later (timer restarted from the sign of life)
    await gw.check_link()
    assert not gw.fallback_active  # 5. still fine


async def test_command_counts_as_link_activity(gw, clock):
    clock.advance(50)
    await gw.handle_limit_command(70)  # 1. a command at t=50 s proves the link is alive
    clock.advance(50)                  # 100 s since start but only 50 s since the command
    await gw.check_link()
    assert not gw.fallback_active  # 2. so no fallback


async def test_rejected_command_still_proves_link_alive(gw, clock):
    clock.advance(50)
    await gw.handle_limit_command(500)  # 1. invalid command, rejected ... but it did arrive
    clock.advance(50)
    await gw.check_link()
    assert not gw.fallback_active  # 2. so the link counts as alive


async def test_fallback_never_raises_an_already_lower_limit(make_gateway, clock, inverter):
    gw = make_gateway(fallback_mode=FallbackMode.SAFE_LIMIT, fallback_limit_pct=30)
    await gw.handle_limit_command(20)  # 1. marketer curtailed the plant to 20 %
    inverter.write_calls.clear()  #    only watch for new writes
    clock.advance(61)  # 2. link lost
    await gw.check_link()
    assert gw.fallback_active  # 3. fallback is on ...
    assert inverter.write_calls == []  # 4. ... but 30 % would RAISE the limit, so nothing is written
    assert inverter.limit_reg == 20  # 5. the plant stays at 20 %


async def test_fallback_not_written_when_current_limit_unknown(make_gateway, clock, inverter):
    gw = make_gateway(fallback_mode=FallbackMode.SAFE_LIMIT, fallback_limit_pct=30)
    inverter.fail_reads = True  # 1. cannot read the current limit
    clock.advance(61)
    await gw.check_link()
    assert inverter.write_calls == []  # 2. no blind write that might raise the limit
    inverter.fail_reads = False  # 3. inverter readable again
    await gw.check_link()
    assert inverter.limit_reg == 30  # 4. next check applies the fallback


def test_safe_limit_requires_explicit_value():
    with pytest.raises(ValueError):  # no value given: refuse, do not guess 100 %
        Config(fallback_mode=FallbackMode.SAFE_LIMIT)


@pytest.mark.parametrize("bad", [-1, 101])
def test_safe_limit_value_must_be_in_range(bad):
    with pytest.raises(ValueError):
        Config(fallback_mode=FallbackMode.SAFE_LIMIT, fallback_limit_pct=bad)


def test_hold_mode_needs_no_fallback_value():
    assert Config().fallback_limit_pct is None  # the default policy works without it
