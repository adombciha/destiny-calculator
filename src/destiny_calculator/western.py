"""Calculate tropical geocentric natal charts with verified Swiss Ephemeris data."""

from contextlib import contextmanager
from dataclasses import dataclass, replace
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from itertools import combinations
from hashlib import sha256
import json
from math import isfinite, isclose
from pathlib import Path
from threading import RLock

from .models import BirthData


SIGNS = (
    "牡羊",
    "金牛",
    "雙子",
    "巨蟹",
    "獅子",
    "處女",
    "天秤",
    "天蠍",
    "射手",
    "摩羯",
    "水瓶",
    "雙魚",
)
PLANETS = (
    ("SUN", "太陽"),
    ("MOON", "月亮"),
    ("MERCURY", "水星"),
    ("VENUS", "金星"),
    ("MARS", "火星"),
    ("JUPITER", "木星"),
    ("SATURN", "土星"),
    ("URANUS", "天王星"),
    ("NEPTUNE", "海王星"),
    ("PLUTO", "冥王星"),
)
ASPECTS = ((0, "合相"), (60, "六分相"), (90, "四分相"), (120, "三分相"), (180, "對分相"))
_LOCK = RLock()


def format_zodiac(longitude: float) -> str:
    if not isfinite(longitude):
        raise ValueError("Longitude must be finite.")
    seconds = round((longitude % 360) * 3600) % (360 * 3600)
    sign, within = divmod(seconds, 30 * 3600)
    degree, remainder = divmod(within, 3600)
    minute, second = divmod(remainder, 60)
    return f"{SIGNS[sign]} {degree:02}°{minute:02}′{second:02}″"


@dataclass(frozen=True, slots=True)
class EphemerisFile:
    name: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class WesternPlanet:
    code: str
    name: str
    longitude: float
    latitude: float
    distance_au: float
    longitude_speed: float
    retrograde: bool
    sign: str
    sign_longitude: float
    house: int | None
    returned_flags: int


@dataclass(frozen=True, slots=True)
class WesternAspect:
    first: str
    second: str
    name: str
    angle: int
    separation: float
    orb: float


@dataclass(frozen=True, slots=True)
class WesternChart:
    birth: BirthData
    planets: tuple[WesternPlanet, ...]
    house_cusps: tuple[float, ...] | None
    ascendant: float | None
    midheaven: float | None
    aspects: tuple[WesternAspect, ...]
    house_status: str
    house_error: str | None
    jd_tt: float
    jd_ut1: float
    requested_flags: int
    engine_version: str
    swiss_ephemeris_version: str
    ephemeris_revision: str
    ephemeris_files: tuple[EphemerisFile, ...]
    rules_version: str = "western-v1"
    zodiac: str = "tropical"
    house_system: str = "Placidus"
    aspect_orb_degrees: float = 6.0
    time_model: str = "Swiss Ephemeris UTC to TT/UT1; pre-1972 input treated as UT1"


def _verified_files(directory):
    directory = Path(directory).resolve()
    manifest = json.loads(
        files("destiny_calculator")
        .joinpath("data/ephemeris_manifest.json")
        .read_text(encoding="utf-8")
    )
    verified = []
    for entry in manifest["files"]:
        path = directory / entry["name"]
        try:
            data = path.read_bytes()
        except OSError as error:
            raise ValueError(
                f"Missing ephemeris file {entry['name']}; run scripts/download_ephemeris.py."
            ) from error
        if len(data) != entry["size_bytes"] or sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError(f"Ephemeris checksum mismatch: {entry['name']}.")
        verified.append(EphemerisFile(entry["name"], len(data), entry["sha256"]))
    return directory, manifest["source_revision"], tuple(verified)


def _house(longitude, cusps):
    matches = [
        i + 1
        for i, start in enumerate(cusps)
        if (longitude - start) % 360 < (cusps[(i + 1) % 12] - start) % 360
    ]
    if len(matches) != 1:
        raise ValueError("House cusps do not provide a unique ecliptic house.")
    return matches[0]


def _aspects(planets):
    result = []
    for first, second in combinations(planets, 2):
        difference = abs(first.longitude - second.longitude) % 360
        separation = min(difference, 360 - difference)
        for angle, name in ASPECTS:
            orb = abs(separation - angle)
            if orb <= 6:
                result.append(WesternAspect(first.code, second.code, name, angle, separation, orb))
    return tuple(result)


@contextmanager
def ephemeris_session(ephemeris_path: str | Path):
    try:
        import swisseph as swe

        wrapper_version = version("pyswisseph")
    except (ImportError, PackageNotFoundError) as error:
        raise ValueError(
            "Install destiny-calculator[western] to calculate astronomical charts."
        ) from error
    directory, revision, verified = _verified_files(ephemeris_path)
    # Swiss Ephemeris stores its path and time settings outside individual calls.
    with _LOCK:
        swe.set_ephe_path(str(directory))
        swe.set_delta_t_userdef(swe.DELTAT_AUTOMATIC)
        swe.set_tid_acc(swe.TIDAL_AUTOMATIC)
        yield swe, wrapper_version, revision, verified


def julian_days(swe, utc):
    days = swe.utc_to_jd(
        utc.year,
        utc.month,
        utc.day,
        utc.hour,
        utc.minute,
        utc.second + utc.microsecond / 1_000_000,
        swe.GREG_CAL,
    )
    if not all(isfinite(value) for value in days):
        raise ValueError("Invalid Julian day returned by the ephemeris engine.")
    return days


def calculate_western(birth: BirthData, *, ephemeris_path: str | Path) -> WesternChart:
    if not isinstance(birth, BirthData):
        raise ValueError("birth must be a BirthData.")
    planets = []
    cusps = ascendant = midheaven = None
    house_error = None
    with ephemeris_session(ephemeris_path) as (swe, wrapper_version, revision, verified):
        flags = swe.FLG_SWIEPH | swe.FLG_SPEED
        try:
            jd_tt, jd_ut1 = julian_days(swe, birth.utc_datetime)
            for code, name in PLANETS:
                values, returned = swe.calc(jd_tt, getattr(swe, code), flags)
                if returned != flags:
                    raise ValueError(
                        "The requested Swiss Ephemeris file mode and speed flags were not honored."
                    )
                if len(values) != 6 or not all(isfinite(v) for v in values):
                    raise ValueError("Invalid planetary position returned by the ephemeris engine.")
                longitude = values[0] % 360
                planets.append(
                    WesternPlanet(
                        code,
                        name,
                        longitude,
                        values[1],
                        values[2],
                        values[3],
                        values[3] < 0,
                        SIGNS[int(longitude // 30)],
                        longitude % 30,
                        None,
                        returned,
                    )
                )
            try:
                raw_cusps, angles = swe.houses(
                    jd_ut1, birth.place.latitude, birth.place.longitude, b"P"
                )
                if (
                    len(raw_cusps) != 12
                    or len(angles) < 2
                    or not all(isfinite(v) for v in (*raw_cusps, *angles[:2]))
                ):
                    raise ValueError("Invalid Placidus house geometry.")
                candidate = tuple(v % 360 for v in raw_cusps)
                arcs = tuple(
                    (candidate[(i + 1) % 12] - value) % 360 for i, value in enumerate(candidate)
                )
                if not all(0 < v < 360 for v in arcs) or not isclose(sum(arcs), 360, abs_tol=1e-7):
                    raise ValueError("Placidus house cusps do not partition the zodiac.")
                planets = [replace(p, house=_house(p.longitude, candidate)) for p in planets]
                cusps, ascendant, midheaven = candidate, angles[0] % 360, angles[1] % 360
            except (swe.Error, ValueError):
                house_error = "Placidus houses are unavailable for this birth location and time."
                planets = [replace(p, house=None) for p in planets]
        except swe.Error as error:
            raise ValueError("Swiss Ephemeris calculation failed: " + str(error)) from error
    return WesternChart(
        birth=birth,
        planets=tuple(planets),
        house_cusps=cusps,
        ascendant=ascendant,
        midheaven=midheaven,
        aspects=_aspects(planets),
        house_status="ok" if cusps else "unavailable",
        house_error=house_error,
        jd_tt=jd_tt,
        jd_ut1=jd_ut1,
        requested_flags=flags,
        engine_version=wrapper_version,
        swiss_ephemeris_version=swe.version,
        ephemeris_revision=revision,
        ephemeris_files=verified,
    )
