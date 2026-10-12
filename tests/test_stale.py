"""Requirement 2: a value older than 5 s is invalid and never re-sent as fresh."""


def point(gw, name):
    return gw.state.get(name)


async def test_fresh_values_are_converted_and_valid(gw):
    await gw.poll_once()
    assert point(gw, "active_power_kw").value == 50.0
    assert point(gw, "reactive_power_kvar").value == 1.5
    assert point(gw, "frequency_hz").value == 50.01
    assert point(gw, "status").value == 1
    assert all(p.valid for p in gw.snapshot())


async def test_never_received_is_invalid(gw):
    assert not any(p.valid for p in gw.snapshot())


async def test_value_exactly_at_limit_still_valid_then_invalid_after(gw, clock):
    await gw.poll_once()
    clock.advance(5.0)
    assert point(gw, "active_power_kw").valid
    clock.advance(0.1)
    assert not point(gw, "active_power_kw").valid


async def test_failed_read_does_not_refresh_old_value(gw, clock, inverter):
    await gw.poll_once()
    inverter.fail_reads = True
    inverter.raw = None  # would blow up if the gateway tried to use it
    for _ in range(7):
        clock.advance(1.0)
        await gw.poll_once()  # must swallow the error
    stale = point(gw, "active_power_kw")
    assert stale.value == 50.0 and not stale.valid  # last value kept for diagnosis, flagged IV


async def test_recovery_makes_values_valid_again(gw, clock, inverter):
    await gw.poll_once()
    inverter.fail_reads = True
    clock.advance(10)
    await gw.poll_once()
    inverter.fail_reads = False
    await gw.poll_once()
    assert point(gw, "active_power_kw").valid


async def test_unknown_status_enum_is_not_forwarded(gw, clock, inverter):
    await gw.poll_once()
    inverter.raw = type(inverter.raw)(0, 50_000, 0, 1_500, 5001, 42)
    clock.advance(6)
    await gw.poll_once()
    assert not point(gw, "status").valid  # old status aged out, 42 was not stored
    assert point(gw, "active_power_kw").valid


async def test_out_of_range_limit_register_is_ignored(gw, inverter):
    inverter.limit_reg = 250
    await gw.poll_once()
    assert not point(gw, "limit_pct").valid


def test_ioa_and_type_mapping(gw):
    got = {p.name: (p.ioa, p.type_id) for p in gw.snapshot()}
    assert got == {
        "active_power_kw": (1001, "M_ME_NC_1"),
        "reactive_power_kvar": (1002, "M_ME_NC_1"),
        "frequency_hz": (1003, "M_ME_NC_1"),
        "limit_pct": (1004, "M_ME_NC_1"),
        "status": (1005, "M_ME_NB_1"),
    }
