"""Requirement 4: behaviour when the IEC 104 link is silent > 60 s."""

from gateway.config import FallbackMode


async def test_no_fallback_within_timeout(gw, clock):
    clock.advance(60)
    await gw.check_link()
    assert not gw.fallback_active


async def test_hold_mode_flags_fallback_but_does_not_write(make_gateway, clock, inverter):
    gw = make_gateway(fallback_mode=FallbackMode.HOLD)
    await gw.handle_limit_command(40)
    inverter.write_calls.clear()
    clock.advance(61)
    await gw.check_link()
    assert gw.fallback_active
    assert inverter.write_calls == []
    assert inverter.limit_reg == 40  # last limit held


async def test_safe_limit_mode_writes_configured_value(make_gateway, clock, inverter):
    gw = make_gateway(fallback_mode=FallbackMode.SAFE_LIMIT, fallback_limit_pct=30)
    clock.advance(61)
    await gw.check_link()
    assert gw.fallback_active
    assert inverter.limit_reg == 30


async def test_safe_limit_is_written_once_not_every_tick(make_gateway, clock, inverter):
    gw = make_gateway(fallback_mode=FallbackMode.SAFE_LIMIT, fallback_limit_pct=30)
    clock.advance(61)
    for _ in range(5):
        await gw.check_link()
    assert inverter.write_calls == [30]


async def test_failed_fallback_write_is_retried_on_next_check(make_gateway, clock, inverter):
    gw = make_gateway(fallback_mode=FallbackMode.SAFE_LIMIT, fallback_limit_pct=30, write_retries=0)
    inverter.fail_writes = True
    clock.advance(61)
    await gw.check_link()
    assert gw.fallback_active and inverter.limit_reg == 100
    inverter.fail_writes = False
    await gw.check_link()
    assert inverter.limit_reg == 30


async def test_custom_timeout_is_respected(make_gateway, clock):
    gw = make_gateway(iec_loss_timeout_s=10)
    clock.advance(11)
    await gw.check_link()
    assert gw.fallback_active


async def test_activity_resets_timer_and_clears_fallback(make_gateway, clock):
    gw = make_gateway(fallback_mode=FallbackMode.SAFE_LIMIT, fallback_limit_pct=30)
    clock.advance(61)
    await gw.check_link()
    assert gw.fallback_active
    gw.note_iec_activity()
    assert not gw.fallback_active
    clock.advance(30)
    await gw.check_link()
    assert not gw.fallback_active


async def test_command_counts_as_link_activity(gw, clock):
    clock.advance(50)
    await gw.handle_limit_command(70)
    clock.advance(50)  # 100 s since start but only 50 s since the command
    await gw.check_link()
    assert not gw.fallback_active


async def test_rejected_command_still_proves_link_alive(gw, clock):
    clock.advance(50)
    await gw.handle_limit_command(500)
    clock.advance(50)
    await gw.check_link()
    assert not gw.fallback_active
