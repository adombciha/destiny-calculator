"""Calculate Lahiri sidereal natal charts and Moon-based Vimshottari periods."""

from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path

from .models import BirthData
from .timing import TimingPeriod
from .western import EphemerisFile, ephemeris_session, julian_days

_SIGNS = (
    "Aries",
    "Taurus",
    "Gemini",
    "Cancer",
    "Leo",
    "Virgo",
    "Libra",
    "Scorpio",
    "Sagittarius",
    "Capricorn",
    "Aquarius",
    "Pisces",
)
_GRAHAS = (
    ("SUN", "Sun"),
    ("MOON", "Moon"),
    ("MARS", "Mars"),
    ("MERCURY", "Mercury"),
    ("JUPITER", "Jupiter"),
    ("VENUS", "Venus"),
    ("SATURN", "Saturn"),
    ("MEAN_NODE", "Rahu"),
)
_NAKSHATRAS = (
    "Ashwini",
    "Bharani",
    "Krittika",
    "Rohini",
    "Mrigashira",
    "Ardra",
    "Punarvasu",
    "Pushya",
    "Ashlesha",
    "Magha",
    "Purva Phalguni",
    "Uttara Phalguni",
    "Hasta",
    "Chitra",
    "Swati",
    "Vishakha",
    "Anuradha",
    "Jyeshtha",
    "Mula",
    "Purva Ashadha",
    "Uttara Ashadha",
    "Shravana",
    "Dhanishtha",
    "Shatabhisha",
    "Purva Bhadrapada",
    "Uttara Bhadrapada",
    "Revati",
)
_DASAS = (
    ("Ketu", 7),
    ("Venus", 20),
    ("Sun", 6),
    ("Moon", 10),
    ("Mars", 7),
    ("Rahu", 18),
    ("Jupiter", 16),
    ("Saturn", 19),
    ("Mercury", 17),
)
_PADA_BOUNDARIES = tuple(i * 10 / 3 for i in range(108))
_DAYS_PER_YEAR = 365.2425
_CYCLE_YEARS = 120


@dataclass(frozen=True, slots=True)
class JyotishPlacement:
    body: str
    sign: str
    house: int
    longitude: float | None


@dataclass(frozen=True, slots=True)
class Nakshatra:
    name: str
    pada: int
    lord: str
    index: int


@dataclass(frozen=True, slots=True)
class VimshottariPeriod(TimingPeriod):
    lords: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class JyotishChart:
    birth: BirthData
    d1: tuple[JyotishPlacement, ...]
    d9: tuple[JyotishPlacement, ...]
    d10: tuple[JyotishPlacement, ...]
    moon_nakshatra: Nakshatra
    periods: tuple[VimshottariPeriod, ...]
    ayanamsha_degrees: float
    engine_version: str
    swiss_ephemeris_version: str
    ephemeris_revision: str
    ephemeris_files: tuple[EphemerisFile, ...]
    rule_version: str = "jyotish-v1"


def _pada_index(longitude: float) -> int:
    return bisect_right(_PADA_BOUNDARIES, longitude) - 1


def _moon_nakshatra(longitude: float) -> Nakshatra:
    index, pada = divmod(_pada_index(longitude), 4)
    return Nakshatra(
        _NAKSHATRAS[index], pada + 1, _DASAS[index % len(_DASAS)][0], index + 1
    )


def _divisional_sign(longitude: float, division: int) -> int:
    sign = int(longitude // 30)
    if division == 1:
        return sign
    if division == 9:
        return _pada_index(longitude) % len(_SIGNS)
    # Dasamsa starts at the natal sign for odd signs and at its ninth for even signs.
    return (sign + (8 if sign % 2 else 0) + int(longitude // 3) % 10) % len(_SIGNS)


def _placements(
    positions: dict[str, float], division: int
) -> tuple[JyotishPlacement, ...]:
    lagna_sign = _divisional_sign(positions["Lagna"], division)
    placements = []
    for body, longitude in positions.items():
        sign = _divisional_sign(longitude, division)
        placements.append(
            JyotishPlacement(
                body,
                _SIGNS[sign],
                (sign - lagna_sign) % len(_SIGNS) + 1,
                longitude if division == 1 else None,
            )
        )
    return tuple(placements)


def _dasa_divisions(
    start: float, end: float, first_lord: int
) -> Iterator[tuple[int, float, float]]:
    lower = start
    elapsed = 0
    for offset in range(len(_DASAS)):
        lord = (first_lord + offset) % len(_DASAS)
        elapsed += _DASAS[lord][1]
        upper = (
            end
            if elapsed == _CYCLE_YEARS
            else start + (end - start) * elapsed / _CYCLE_YEARS
        )
        yield lord, lower, upper
        lower = upper


def _vimshottari_periods(birth: datetime, longitude: float) -> tuple[VimshottariPeriod, ...]:
    nakshatra_index = _pada_index(longitude) // 4
    first_lord = nakshatra_index % len(_DASAS)
    nakshatra_start = _PADA_BOUNDARIES[nakshatra_index * 4]
    elapsed_fraction = (longitude - nakshatra_start) / (40 / 3)
    cycle_start = -elapsed_fraction * _DASAS[first_lord][1]
    cycle_end = cycle_start + _CYCLE_YEARS
    periods = []

    def append_period(
        lord: int, start: float, end: float, parents: tuple[str, ...]
    ) -> None:
        starts_at = birth + timedelta(days=max(start, 0) * _DAYS_PER_YEAR)
        ends_at = birth + timedelta(days=min(end, _CYCLE_YEARS) * _DAYS_PER_YEAR)
        if starts_at >= ends_at:
            return
        lords = (*parents, _DASAS[lord][0])
        periods.append(
            VimshottariPeriod(
                method="vimshottari",
                level=len(lords),
                label="/".join(lords),
                starts_at=starts_at,
                ends_at=ends_at,
                lords=lords,
            )
        )
        if len(lords) < 3:
            # Subperiod proportions use the original period, including any pre-birth portion.
            for child_lord, child_start, child_end in _dasa_divisions(start, end, lord):
                append_period(child_lord, child_start, child_end, lords)

    for lord, start, end in _dasa_divisions(cycle_start, cycle_end, first_lord):
        append_period(lord, start, end, ())
    append_period(first_lord, cycle_end, cycle_end + _DASAS[first_lord][1], ())
    return tuple(periods)


def calculate_jyotish(birth: BirthData, *, ephemeris_path: str | Path) -> JyotishChart:
    if not isinstance(birth, BirthData):
        raise ValueError("birth must be a BirthData.")
    if abs(birth.place.latitude) == 90:
        raise ValueError("Jyotish Lagna is undefined at the geographic poles.")
    utc = birth.utc_datetime
    with ephemeris_session(ephemeris_path) as (swe, version, revision, verified):
        try:
            swe.set_sid_mode(swe.SIDM_LAHIRI)
            sidereal_flags = swe.FLG_SIDEREAL | swe.FLG_NONUT
            planet_flags = sidereal_flags | swe.FLG_SWIEPH | swe.FLG_SPEED
            jd_tt, jd_ut1 = julian_days(swe, utc)
            _, angles = swe.houses_ex(
                jd_ut1,
                birth.place.latitude,
                birth.place.longitude,
                b"W",
                sidereal_flags,
            )
            ayanamsha = swe.get_ayanamsa(jd_tt)
            if not angles or not isfinite(angles[0]) or not isfinite(ayanamsha):
                raise ValueError(
                    "Invalid sidereal Lagna or ayanamsha returned by the ephemeris engine."
                )
            positions = {"Lagna": angles[0] % 360}
            for code, body in _GRAHAS:
                values, returned = swe.calc(jd_tt, getattr(swe, code), planet_flags)
                if returned != planet_flags:
                    raise ValueError(
                        "The requested sidereal Swiss Ephemeris flags were not honored."
                    )
                if len(values) != 6 or not all(isfinite(value) for value in values):
                    raise ValueError(
                        "Invalid planetary position returned by the ephemeris engine."
                    )
                positions[body] = values[0] % 360
        except swe.Error as error:
            raise ValueError(
                "Swiss Ephemeris calculation failed: " + str(error)
            ) from error
        swiss_ephemeris_version = swe.version
    positions["Ketu"] = (positions["Rahu"] + 180) % 360

    return JyotishChart(
        birth=birth,
        d1=_placements(positions, 1),
        d9=_placements(positions, 9),
        d10=_placements(positions, 10),
        moon_nakshatra=_moon_nakshatra(positions["Moon"]),
        periods=_vimshottari_periods(utc, positions["Moon"]),
        ayanamsha_degrees=ayanamsha,
        engine_version=version,
        swiss_ephemeris_version=swiss_ephemeris_version,
        ephemeris_revision=revision,
        ephemeris_files=verified,
    )
