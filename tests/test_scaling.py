import pytest

from gateway.scaling import decode_int32_be, to_hz, to_kvar, to_kw, to_status


def test_int32_big_endian_positive():
    # 0x0001_86A0 = 100000
    assert decode_int32_be(0x0001, 0x86A0) == 100_000


def test_int32_big_endian_negative():
    # -1 as int32 = 0xFFFF_FFFF
    assert decode_int32_be(0xFFFF, 0xFFFF) == -1


def test_watts_to_kw():
    assert to_kw(50_000) == 50.0


def test_var_to_kvar_keeps_sign():
    assert to_kvar(-2_500) == -2.5


def test_frequency_raw_to_hz():
    assert to_hz(5002) == pytest.approx(50.02)


@pytest.mark.parametrize("raw", [0, 1, 2, 3])
def test_status_valid(raw):
    assert to_status(raw) == raw


@pytest.mark.parametrize("raw", [4, 99, 65535])
def test_status_unknown_value_rejected(raw):
    with pytest.raises(ValueError):
        to_status(raw)
