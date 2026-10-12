"""Latest measurements with freshness tracking. Never serves a stale value as valid."""

from collections.abc import Callable
from dataclasses import dataclass

# name -> (IOA, IEC 104 type id)
POINTS: dict[str, tuple[int, str]] = {
    "active_power_kw": (1001, "M_ME_NC_1"),
    "reactive_power_kvar": (1002, "M_ME_NC_1"),
    "frequency_hz": (1003, "M_ME_NC_1"),
    "limit_pct": (1004, "M_ME_NC_1"),
    "status": (1005, "M_ME_NB_1"),
}


@dataclass(frozen=True)
class Point:
    ioa: int
    type_id: str
    name: str
    value: float | int | None  # None when never received
    valid: bool  # False -> IEC 104 quality bit IV (invalid) must be set
    age_s: float | None


class StateStore:
    def __init__(self, stale_after_s: float, clock: Callable[[], float]):
        self._stale_after_s = stale_after_s
        self._clock = clock
        self._values: dict[str, tuple[float | int, float]] = {}

    def update(self, name: str, value: float) -> None:
        if name not in POINTS:
            raise KeyError(name)
        self._values[name] = (value, self._clock())

    def invalidate(self, name: str) -> None:
        """Drop a value whose true state is unknown (e.g. failed inverter write)."""
        self._values.pop(name, None)

    def snapshot(self) -> list[Point]:
        now = self._clock()
        points = []
        for name, (ioa, type_id) in POINTS.items():
            entry = self._values.get(name)
            if entry is None:
                points.append(Point(ioa, type_id, name, None, False, None))
                continue
            value, stamp = entry
            age = now - stamp
            points.append(Point(ioa, type_id, name, value, age <= self._stale_after_s, age))
        return points

    def get(self, name: str) -> Point:
        return next(p for p in self.snapshot() if p.name == name)
