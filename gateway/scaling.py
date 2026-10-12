"""Pure conversions from raw Modbus register values to IEC 104 engineering units."""

STATUS_VALUES = frozenset({0, 1, 2, 3})  # off, running, curtailed, fault


def decode_int32_be(high: int, low: int) -> int:
    """Combine two 16-bit registers (big endian) into a signed int32."""
    value = ((high & 0xFFFF) << 16) | (low & 0xFFFF)
    return value - (1 << 32) if value & 0x8000_0000 else value


def to_kw(watts: int) -> float:
    return watts / 1000.0


def to_kvar(var: int) -> float:
    return var / 1000.0


def to_hz(raw: int) -> float:
    return raw / 100.0


def to_status(raw: int) -> int:
    """Reject unknown enum values instead of forwarding them."""
    if raw not in STATUS_VALUES:
        raise ValueError(f"unknown inverter status {raw}")
    return raw
