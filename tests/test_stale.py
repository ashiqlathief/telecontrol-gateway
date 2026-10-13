"""Requirement 2: a value older than 5 s is invalid and never re-sent as fresh."""


def point(gw, name):
    return gw.state.get(name)


async def test_fresh_values_are_converted_and_valid(gw):
    await gw.poll_once()                                  # 1. one poll of the pretend inverter (raw 50000 W, 1500 var, 5001 ...)
    assert point(gw, "active_power_kw").value == 50.0     # 2. converted to kW
    assert point(gw, "reactive_power_kvar").value == 1.5  #    converted to kvar
    assert point(gw, "frequency_hz").value == 50.01       #    converted to Hz
    assert point(gw, "status").value == 1                 #    status 1 = running
    assert all(p.valid for p in gw.snapshot())            # 3. all five points are marked valid


async def test_never_received_is_invalid(gw):
    # No poll has happened yet: there is nothing to send, so nothing may look valid.
    assert not any(p.valid for p in gw.snapshot())


async def test_value_exactly_at_limit_still_valid_then_invalid_after(gw, clock):
    await gw.poll_once()                           # 1. value stored at time 0
    clock.advance(5.0)                             # 2. exactly 5 s later ...
    assert point(gw, "active_power_kw").valid      #    ... still valid (limit is "older than 5 s")
    clock.advance(0.1)                             # 3. 5.1 s in total
    assert not point(gw, "active_power_kw").valid  #    now invalid


async def test_failed_read_does_not_refresh_old_value(gw, clock, inverter):
    await gw.poll_once()        # 1. one good poll
    inverter.fail_reads = True  # 2. inverter stops answering
    inverter.raw = None         # would blow up if the gateway tried to use it
    for _ in range(7):          # 3. seven failed polls, one per second
        clock.advance(1.0)
        await gw.poll_once()  # must swallow the error
    stale = point(gw, "active_power_kw")
    # 4. old value kept for diagnosis, but flagged IV: it was NOT refreshed by the failures
    assert stale.value == 50.0 and not stale.valid


async def test_recovery_makes_values_valid_again(gw, clock, inverter):
    await gw.poll_once()                       # 1. good poll
    inverter.fail_reads = True                 # 2. inverter goes away ...
    clock.advance(10)                          #    ... for 10 s
    await gw.poll_once()                       #    (this poll fails)
    inverter.fail_reads = False                # 3. inverter comes back
    await gw.poll_once()                       #    next poll succeeds
    assert point(gw, "active_power_kw").valid  # 4. value is valid again, nothing stays stuck


async def test_unknown_status_enum_is_not_forwarded(gw, clock, inverter):
    await gw.poll_once()                                              # 1. good poll, status = 1
    inverter.raw = type(inverter.raw)(0, 50_000, 0, 1_500, 5001, 42)  # 2. status 42
    clock.advance(6)                                                  # 3. 6 s pass so the old status is too old
    await gw.poll_once()
    assert not point(gw, "status").valid       # 4. 42 is not a real status: it was not stored
    assert point(gw, "active_power_kw").valid  #    other values from the same poll are fine


async def test_out_of_range_limit_register_is_ignored(gw, inverter):
    inverter.limit_reg = 250  # 1. inverter reports a limit of 250 % (impossible, valid is 0-100)
    await gw.poll_once()
    assert not point(gw, "limit_pct").valid  # 2. gateway does not publish it


def test_ioa_and_type_mapping(gw):
    # Checks the address table from the task PDF: which IOA carries which value and type.
    got = {p.name: (p.ioa, p.type_id) for p in gw.snapshot()}
    assert got == {
        "active_power_kw": (1001, "M_ME_NC_1"),
        "reactive_power_kvar": (1002, "M_ME_NC_1"),
        "frequency_hz": (1003, "M_ME_NC_1"),
        "limit_pct": (1004, "M_ME_NC_1"),
        "status": (1005, "M_ME_NB_1"),
    }
