from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from .errors import ValidationError

MAX_DUTY = 100


@dataclass(frozen=True, slots=True)
class CurvePoint:
    temperature: float
    duty: int


@dataclass(frozen=True, slots=True)
class FanCurve:
    """Fan duty as a function of temperature, drawn as straight lines between points.

    Below the first point the first duty holds, and above the last point the
    last duty holds, so the fan never falls off either end of the curve.
    """

    points: tuple[CurvePoint, ...]

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValidationError("a fan curve needs at least two points")
        temperatures = [point.temperature for point in self.points]
        if temperatures != sorted(set(temperatures)):
            raise ValidationError("fan curve temperatures must rise from point to point")
        if any(not 0 <= point.duty <= MAX_DUTY for point in self.points):
            raise ValidationError("fan curve duties must be between 0 and 100")

    @classmethod
    def of(cls, pairs: Sequence[tuple[float, int]]) -> FanCurve:
        """Build a curve from (temperature, duty) pairs.

        @param pairs: the points, in rising temperature order.
        @return: the curve.
        """
        return cls(tuple(CurvePoint(temperature, duty) for temperature, duty in pairs))

    def duty_at(self, temperature: float) -> int:
        """Read the curve.

        @param temperature: the sensor's reading.
        @return: the duty the fan should run at.
        """
        first, last = self.points[0], self.points[-1]
        if temperature <= first.temperature:
            return first.duty
        if temperature >= last.temperature:
            return last.duty
        for low, high in zip(self.points, self.points[1:], strict=False):
            if temperature <= high.temperature:
                share = (temperature - low.temperature) / (high.temperature - low.temperature)
                return round(low.duty + (high.duty - low.duty) * share)
        return last.duty

    def moved(self, index: int, point: CurvePoint) -> FanCurve:
        """Move one point, keeping it between its neighbours so the curve stays valid.

        @param index: which point.
        @param point: where the user dragged it.
        @return: the changed curve.
        """
        low = self.points[index - 1].temperature + 1 if index > 0 else 0.0
        high = self.points[index + 1].temperature - 1 if index < len(self.points) - 1 else 110.0
        clamped = CurvePoint(max(low, min(high, point.temperature)), max(0, min(MAX_DUTY, point.duty)))
        points = list(self.points)
        points[index] = clamped
        return FanCurve(tuple(points))


class FanMode(StrEnum):
    FIXED = "fixed"
    CURVE = "curve"


@dataclass(frozen=True, slots=True)
class FanSetting:
    """How one fan should be driven: a fixed duty, or a curve following a sensor."""

    mode: FanMode
    duty: int = 50
    curve: FanCurve | None = None
    sensor: str = "cpu.temp"

    def __post_init__(self) -> None:
        if not 0 <= self.duty <= MAX_DUTY:
            raise ValidationError("fan duty must be between 0 and 100")
        if self.mode is FanMode.CURVE and self.curve is None:
            raise ValidationError("a curve setting needs a curve")

    @classmethod
    def fixed(cls, duty: int) -> FanSetting:
        """@return: a setting that holds the fan at one duty."""
        return cls(FanMode.FIXED, duty=duty)

    @classmethod
    def following(cls, sensor: str, curve: FanCurve) -> FanSetting:
        """@return: a setting that follows a sensor along a curve."""
        return cls(FanMode.CURVE, curve=curve, sensor=sensor)

    def target(self, readings: Mapping[str, float]) -> int | None:
        """Work out the duty this setting asks for right now.

        @param readings: the latest sensor values.
        @return: the duty, or None when the sensor it follows has not reported.
        """
        if self.mode is FanMode.FIXED or self.curve is None:
            return self.duty
        reading = readings.get(self.sensor)
        return None if reading is None else self.curve.duty_at(reading)


PRESET_CURVES: Mapping[str, FanCurve] = {
    "Quiet": FanCurve.of([(30, 25), (50, 35), (65, 55), (80, 80), (90, 100)]),
    "Balanced": FanCurve.of([(30, 35), (50, 50), (65, 70), (80, 90), (88, 100)]),
    "Performance": FanCurve.of([(30, 50), (45, 65), (60, 85), (75, 100)]),
}


class PumpMode(StrEnum):
    QUIET = "quiet"
    BALANCED = "balanced"
    EXTREME = "extreme"
