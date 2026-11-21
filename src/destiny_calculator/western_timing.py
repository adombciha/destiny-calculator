"""Calculate birthday profections, Firdaria, and Valens zodiacal releasing."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite

from .time_utils import shift_local_years
from .timing import TimingPeriod
from .western import PLANETS, SIGNS, WesternChart, _LOCK


_NAMES = dict(PLANETS) | {"NORTH_NODE": "北交點", "SOUTH_NODE": "南交點"}
_RULERS = (
    "MARS", "VENUS", "MERCURY", "MOON", "SUN", "MERCURY",
    "VENUS", "MARS", "JUPITER", "SATURN", "SATURN", "JUPITER",
)
_FIRDARIA = (
    ("SUN", 10), ("VENUS", 8), ("MERCURY", 13), ("MOON", 9),
    ("SATURN", 11), ("JUPITER", 12), ("MARS", 7),
)
_NODES = (("NORTH_NODE", 3), ("SOUTH_NODE", 2))
_RELEASING_YEARS = (15, 8, 20, 25, 19, 20, 8, 15, 12, 27, 30, 12)


@dataclass(frozen=True, slots=True)
class WesternPeriod(TimingPeriod):
    lord: str
    secondary_lord: str | None = None
    sign: str | None = None
    house: int | None = None
    age: int | None = None
    loosing_of_bond: bool = False


@dataclass(frozen=True, slots=True)
class WesternTiming:
    rule_version: str
    sect: str
    sun_altitude_degrees: float
    ascendant: float | None
    lot_of_fortune: float | None
    lot_of_spirit: float | None
    spirit_start_sign: str | None
    periods: tuple[WesternPeriod, ...]


def _geometry(chart: WesternChart):
    import swisseph as swe

    sun, moon = chart.planets[:2]
    place = chart.birth.place
    ascendant = chart.ascendant if abs(place.latitude) < 90 else None
    with _LOCK:
        try:
            _, altitude, _ = swe.azalt(
                chart.jd_ut1, swe.ECL2HOR, (place.longitude, place.latitude, 0), 0, 15,
                (sun.longitude, sun.latitude, sun.distance_au),
            )
        except swe.Error as error:
            raise ValueError("Swiss Ephemeris could not determine the Sun's altitude.") from error
        if ascendant is None and abs(place.latitude) < 90:
            try:
                _, angles = swe.houses(chart.jd_ut1, place.latitude, place.longitude, b"W")
                ascendant = angles[0] % 360 if isfinite(angles[0]) else None
            except swe.Error:
                pass
    if not isfinite(altitude):
        raise ValueError("Invalid solar altitude returned by the ephemeris engine.")
    return altitude, ascendant, sun.longitude, moon.longitude


def _sign(longitude: float) -> int:
    return int((longitude % 360) // 30)


def _profections(birth, ascendant_sign: int, through: datetime):
    age = 0
    start = birth
    while start.astimezone(UTC) <= through:
        end = shift_local_years(birth, age + 1)
        house = age % 12 + 1
        sign = (ascendant_sign + house - 1) % 12
        lord = _RULERS[sign]
        yield WesternPeriod(
            "annual_profections", 1, f"第 {house} 宮 · {SIGNS[sign]} · {_NAMES[lord]}",
            start, end, lord, sign=SIGNS[sign], house=house, age=age,
        )
        age += 1
        start = end


def _firdaria(birth, day: bool, through: datetime):
    start = birth
    age = 0
    seq = _FIRDARIA if day else _FIRDARIA[3:] + _FIRDARIA[:3]
    lords = tuple(lord for lord, _ in _FIRDARIA)
    while start.astimezone(UTC) <= through:
        for lord, years in seq + _NODES:
            if start.astimezone(UTC) > through:
                return
            age += years
            end = shift_local_years(birth, age)
            yield WesternPeriod("firdaria", 1, _NAMES[lord], start, end, lord)
            if lord in lords:
                offset = lords.index(lord)
                start_utc = start.astimezone(UTC)
                duration = end.astimezone(UTC) - start_utc
                for index, secondary in enumerate(lords[offset:] + lords[:offset]):
                    left = start_utc + duration * index / 7
                    right = start_utc + duration * (index + 1) / 7
                    if left > through:
                        break
                    yield WesternPeriod(
                        "firdaria", 2, f"{_NAMES[lord]}／{_NAMES[secondary]}",
                        left, right, lord, secondary_lord=secondary,
                    )
            start = end


def _releasing(birth_utc: datetime, sign: int, method: str, through: datetime):
    start = birth_utc
    while start <= through:
        end = start + timedelta(days=_RELEASING_YEARS[sign] * 360)
        lord = _RULERS[sign]
        yield WesternPeriod(method, 1, SIGNS[sign], start, end, lord, sign=SIGNS[sign])
        sub_start, sub_sign, count = start, sign, 0
        while sub_start < end and sub_start <= through:
            loosing = count == 12
            if loosing:
                sub_sign = (sign + 6) % 12
            sub_end = min(end, sub_start + timedelta(days=_RELEASING_YEARS[sub_sign] * 30))
            secondary = _RULERS[sub_sign]
            suffix = "（對宮跳轉）" if loosing else ""
            yield WesternPeriod(
                method, 2, f"{SIGNS[sign]}／{SIGNS[sub_sign]}{suffix}",
                sub_start, sub_end, lord, secondary_lord=secondary,
                sign=SIGNS[sub_sign], loosing_of_bond=loosing,
            )
            sub_start, sub_sign, count = sub_end, (sub_sign + 1) % 12, count + 1
        start, sign = end, (sign + 1) % 12


def calculate_western_timing(chart: WesternChart, *, through: datetime) -> WesternTiming:
    if not isinstance(chart, WesternChart):
        raise ValueError("chart must be a WesternChart.")
    if not isinstance(through, datetime) or through.utcoffset() is None:
        raise ValueError("Timing horizon must include a timezone.")
    birth = chart.birth.resolved_datetime
    through = through.astimezone(UTC)
    altitude, ascendant, sun, moon = _geometry(chart)
    day = altitude >= 0
    fortune = spirit = spirit_start = None
    periods = list(_firdaria(birth, day, through))
    if ascendant is not None:
        arc = moon - sun if day else sun - moon
        fortune, spirit = (ascendant + arc) % 360, (ascendant - arc) % 360
        fortune_sign, spirit_sign = _sign(fortune), _sign(spirit)
        if spirit_sign == fortune_sign:
            spirit_sign = (spirit_sign + 1) % 12
        spirit_start = SIGNS[spirit_sign]
        periods.extend(_profections(birth, _sign(ascendant), through))
        for method, sign in (("releasing_fortune", fortune_sign), ("releasing_spirit", spirit_sign)):
            periods.extend(_releasing(birth.astimezone(UTC), sign, method, through))
    return WesternTiming(
        "western-time-lords-v1", "day" if day else "night", altitude,
        ascendant, fortune, spirit, spirit_start, tuple(periods),
    )
