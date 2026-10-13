import pytest

from gateway.scaling import decode_int32_be, to_hz, to_kvar, to_kw, to_status


def test_int32_big_endian_positive():
    # Power is a 32-bit number split over two 16-bit registers: high half first.
    # 0x0001_86A0 = 100000
    assert decode_int32_be(0x0001, 0x86A0) == 100_000


def test_int32_big_endian_negative():
    # Both halves all ones must decode to -1, not 4294967295 (signed number).
    # -1 as int32 = 0xFFFF_FFFF
    assert decode_int32_be(0xFFFF, 0xFFFF) == -1


def test_watts_to_kw():
    assert to_kw(50_000) == 50.0  # 50000 W -> 50.0 kW


def test_var_to_kvar_keeps_sign():
    assert to_kvar(-2_500) == -2.5  # negative reactive power stays negative


def test_frequency_raw_to_hz():
    assert to_hz(5002) == pytest.approx(50.02)  # raw is in 0.01 Hz steps


@pytest.mark.parametrize("raw", [0, 1, 2, 3])
def test_status_valid(raw):
    assert to_status(raw) == raw  # off, running, curtailed, fault pass through


@pytest.mark.parametrize("raw", [4, 99, 65535])
def test_status_unknown_value_rejected(raw):
    with pytest.raises(ValueError):  # a status that is not 0-3 is refused, not guessed
        to_status(raw)
