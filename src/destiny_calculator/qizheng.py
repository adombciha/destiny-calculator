"""Calculate a versioned Qizheng Siyu chart and traditional timing intervals."""

from bisect import bisect_right
from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import accumulate, pairwise
from math import isfinite
from pathlib import Path

from .bazi import CALENDAR_TIMEZONE, _solar
from .models import BirthData
from .time_utils import shift_local_years
from .timing import TimingPeriod
from .western import PLANETS, EphemerisFile, ephemeris_session, julian_days

RULE_VERSION = "qizheng-v1"
_BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
_STEMS = "甲乙丙丁戊己庚辛壬癸"
_PALACES = "戌酉申未午巳辰卯寅丑子亥"
_HOUSES = ("命宮", "相貌", "福德", "官祿", "遷移", "疾厄", "妻妾", "奴僕", "子女", "田宅", "兄弟", "財帛")

# Xinfa Lishu, Hengxing Lizhi II, as reproduced in Gujin Tushu Jicheng calendar vol. 53.
_MANSIONS = (
    ("壁", 4, 1), ("奎", 15, 32), ("婁", 28, 46), ("胃", 41, 46),
    ("昴", 53, 37), ("畢", 63, 16), ("參", 77, 14), ("觜", 78, 35),
    ("井", 90, 8), ("鬼", 120, 33), ("柳", 125, 9), ("星", 142, 9),
    ("張", 150, 32), ("翼", 168, 36), ("軫", 185, 36), ("角", 198, 39),
    ("亢", 209, 14), ("氐", 219, 54), ("房", 237, 48), ("心", 242, 34),
    ("尾", 250, 7), ("箕", 265, 43), ("斗", 275, 3), ("牛", 298, 54),
    ("女", 306, 35), ("虛", 318, 14), ("危", 328, 13), ("室", 348, 20),
)
_MANSION_STARTS = tuple(degrees + minutes / 60 for _, degrees, minutes in _MANSIONS)
_MANSION_MODEL = "xinfa-lishu-1628-fixed-tropical-v1"

# Zhang Guo Xing Zong, Gujin Tushu Jicheng arts vol. 568, transformation table.
_TRANSFORMATION_NAMES = ("天祿", "天暗", "天福", "天耗", "天蔭", "天貴", "天刑", "天印", "天囚", "天權")
_TRANSFORMATION_BODIES = (
    "MARS", "YUEBEI", "JUPITER", "VENUS", "SATURN", "MOON", "MERCURY", "ZIQI", "KETU", "RAHU",
)

# The first house is calculated separately using the childhood limit rule.
_HOUSE_MONTHS = (120, 132, 180, 96, 84, 132, 54, 54, 54, 60, 60)
_CHILDHOOD_HOUSES = (0, 11, 5, 6, 2, *range(3, 12))

# Niu (2015), pp. 417–418, takes a 10,228-day cycle and a published Ming-era longitude.
_ZIQI_EPOCH_JD = 2280289.5
_ZIQI_EPOCH_LONGITUDE = 284.58
_ZIQI_SPEED = 360 / 10228


@dataclass(frozen=True, slots=True)
class QizhengMansionSpan:
    name: str
    start_longitude: float
    end_longitude: float


_MANSION_SPANS = tuple(
    QizhengMansionSpan(name, start, end)
    for (name, _, _), (start, end) in zip(
        _MANSIONS, pairwise((*_MANSION_STARTS, _MANSION_STARTS[0]))
    )
)


@dataclass(frozen=True, slots=True)
class QizhengLuminary:
    code: str
    name: str
    longitude: float
    longitude_speed: float
    palace: str
    palace_degree: float
    mansion: str
    mansion_degree: float


@dataclass(frozen=True, slots=True)
class QizhengTransformation:
    name: str
    luminary_code: str
    luminary_name: str


@dataclass(frozen=True, slots=True)
class QizhengPeriod(TimingPeriod):
    palace: str
    house: str | None
    age: int
    year_ganzhi: str | None = None
    directed_longitude: float | None = None
    directed_palace: str | None = None
    directed_mansion: str | None = None
    directed_mansion_degree: float | None = None


@dataclass(frozen=True, slots=True)
class QizhengChart:
    birth: BirthData
    luminaries: tuple[QizhengLuminary, ...]
    ming_palace: str
    ming_longitude: float
    ming_palace_degree: float
    ming_mansion: str
    ming_mansion_degree: float
    birth_year_ganzhi: str
    birth_hour_branch: str
    transformations: tuple[QizhengTransformation, ...]
    periods: tuple[QizhengPeriod, ...]
    jd_tt: float
    jd_ut1: float
    engine_version: str
    swiss_ephemeris_version: str
    ephemeris_revision: str
    ephemeris_files: tuple[EphemerisFile, ...]
    rule_version: str = RULE_VERSION
    mansion_model: str = _MANSION_MODEL
    mansion_spans: tuple[QizhengMansionSpan, ...] = _MANSION_SPANS
    lunar_points_model: str = "rahu-mean-ascending-ketu-descending-yuebei-mean-apogee-v1"
    ziqi_model: str = "niu-2015-1531-tropical-10228-v1"
    timing_model: str = "zhang-guo-equal-palace-bai-liu-v1"
    calendar_model: str = "birth-year-li-chun-utc-plus-8-civil-birthday-timing-v1"


def _palace(longitude: float) -> str:
    return _PALACES[int((longitude % 360) // 30)]


def _mansion(longitude: float) -> tuple[str, float]:
    longitude %= 360
    span = _MANSION_SPANS[bisect_right(_MANSION_STARTS, longitude) - 1]
    return span.name, (longitude - span.start_longitude) % 360


def _ming_longitude(sun_longitude: float, hour_branch: int) -> float:
    # Align the Sun to the birth hour and read the equal palace at the Mao hour.
    return (sun_longitude + 30 * (hour_branch - 3)) % 360


def _ziqi_longitude(jd_ut1: float) -> float:
    return (_ZIQI_EPOCH_LONGITUDE + _ZIQI_SPEED * (jd_ut1 - _ZIQI_EPOCH_JD)) % 360


def _age_month_boundary(birth_time: datetime, months: int) -> datetime:
    years, remainder = divmod(months, 12)
    if remainder == 0:
        return shift_local_years(birth_time, years)
    month_offset = birth_time.month - 1 + remainder
    year = birth_time.year + years + month_offset // 12
    month = month_offset % 12 + 1
    day = min(birth_time.day, monthrange(year, month)[1])
    boundary = birth_time.replace(year=year, month=month, day=day, fold=0)
    return boundary.astimezone(UTC).astimezone(birth_time.tzinfo)


def _timing_periods(
    birth_time: datetime, ming_longitude: float, birth_year_ganzhi: str
) -> tuple[QizhengPeriod, ...]:
    ming_branch = _BRANCHES.index(_palace(ming_longitude))
    birth_stem = _STEMS.index(birth_year_ganzhi[0])
    birth_branch = _BRANCHES.index(birth_year_ganzhi[1])
    ming_degree = ming_longitude % 30
    # The first three-degree band enters the next limit at nominal age eleven.
    childhood_years = 10 + int(ming_degree // 3)
    durations = (12 * childhood_years, *_HOUSE_MONTHS)
    edges = tuple(accumulate(durations, initial=0))
    periods = []

    for year in range(childhood_years):
        house = _CHILDHOOD_HOUSES[year] if year < len(_CHILDHOOD_HOUSES) else 0
        branch = _BRANCHES[(ming_branch + house) % 12]
        periods.append(QizhengPeriod(
            method="qizheng", level=1, label=f"童限 {branch}宮 · {_HOUSES[house]}",
            starts_at=shift_local_years(birth_time, year),
            ends_at=shift_local_years(birth_time, year + 1), palace=branch, house=_HOUSES[house],
            age=year + 1,
        ))

    for index, (start, end) in enumerate(pairwise(edges[1:]), 1):
        branch = _BRANCHES[(ming_branch + index) % 12]
        periods.append(QizhengPeriod(
            method="qizheng", level=1, label=f"大限 {branch}宮 · {_HOUSES[index]}",
            starts_at=_age_month_boundary(birth_time, start),
            ends_at=_age_month_boundary(birth_time, end), palace=branch, house=_HOUSES[index],
            age=start // 12 + 1,
        ))

    major_years = (edges[-1] + 11) // 12
    for year in range(max(2100 - birth_time.year, major_years)):
        age_months = year * 12
        active = bisect_right(edges, age_months) - 1
        branch = _BRANCHES[(ming_branch - year) % 12]
        # The minor limit advances the natal year label on each civil birthday.
        ganzhi = _STEMS[(birth_stem + year) % 10] + _BRANCHES[(birth_branch + year) % 12]
        longitude = directed_palace = mansion = degree = None
        label = f"小限 {branch}宮 · {ganzhi}"
        if active < len(durations):
            # Interpolate the arc from the natal degree, then traverse each full palace westward.
            elapsed = (age_months - edges[active]) / durations[active]
            distance = ming_degree * elapsed if active == 0 else ming_degree + 30 * (active - 1 + elapsed)
            longitude = (ming_longitude - distance) % 360
            # At a directional cusp the new limit rules the moment of ingress.
            directed_palace = _BRANCHES[(ming_branch + active) % 12]
            mansion, degree = _mansion(longitude)
            label += f" · 生日行度 {directed_palace}宮 {mansion}{degree:.2f}°"
        periods.append(QizhengPeriod(
            method="qizheng", level=2, label=label, palace=branch, house=None,
            starts_at=shift_local_years(birth_time, year),
            ends_at=shift_local_years(birth_time, year + 1), age=year + 1, year_ganzhi=ganzhi,
            directed_longitude=longitude, directed_palace=directed_palace,
            directed_mansion=mansion, directed_mansion_degree=degree,
        ))
    return tuple(periods)


def calculate_qizheng(birth: BirthData, *, ephemeris_path: str | Path) -> QizhengChart:
    if not isinstance(birth, BirthData):
        raise ValueError("birth must be a BirthData.")
    with ephemeris_session(ephemeris_path) as (swe, wrapper_version, revision, verified):
        flags = swe.FLG_SWIEPH | swe.FLG_SPEED
        try:
            jd_tt, jd_ut1 = julian_days(swe, birth.utc_datetime)
            positions = []
            for code, name, swiss_code in (
                *((code, name, code) for code, name in PLANETS[:7]),
                ("RAHU", "羅睺", "MEAN_NODE"), ("YUEBEI", "月孛", "MEAN_APOG"),
            ):
                values, returned = swe.calc(jd_tt, getattr(swe, swiss_code), flags)
                if returned != flags or len(values) != 6 or not all(isfinite(v) for v in values):
                    raise ValueError("Invalid Qizheng position or ephemeris flags.")
                positions.append((code, name, values[0] % 360, values[3]))
            apparent_day = (
                jd_ut1 + birth.place.longitude / 360 + swe.time_equ(jd_ut1) + 0.5
            ) % 1
            swiss_version = swe.version
        except swe.Error as error:
            raise ValueError("Swiss Ephemeris calculation failed: " + str(error)) from error
    if not isfinite(apparent_day):
        raise ValueError("Invalid local apparent solar time returned by the ephemeris engine.")
    _, _, rahu, node_speed = positions[-2]
    positions.insert(-1, ("KETU", "計都", (rahu + 180) % 360, node_speed))
    positions.insert(-1, ("ZIQI", "紫炁", _ziqi_longitude(jd_ut1), _ZIQI_SPEED))
    luminaries = tuple(
        QizhengLuminary(code, name, longitude, speed, _palace(longitude), longitude % 30, *_mansion(longitude))
        for code, name, longitude, speed in positions
    )
    hour_branch = int((apparent_day * 24 + 1) // 2) % 12
    ming_longitude = _ming_longitude(luminaries[0].longitude, hour_branch)
    ming_mansion, ming_mansion_degree = _mansion(ming_longitude)
    year_ganzhi = _solar(birth.utc_datetime.astimezone(CALENDAR_TIMEZONE)).getLunar().getYearInGanZhiExact()
    stem = _STEMS.index(year_ganzhi[0])
    names = {body.code: body.name for body in luminaries}
    transformation_codes = _TRANSFORMATION_BODIES[stem:] + _TRANSFORMATION_BODIES[:stem]
    transformations = tuple(
        QizhengTransformation(name, code, names[code])
        for name, code in zip(_TRANSFORMATION_NAMES, transformation_codes)
    )
    return QizhengChart(
        birth=birth, luminaries=luminaries, ming_palace=_palace(ming_longitude),
        ming_longitude=ming_longitude, ming_palace_degree=ming_longitude % 30,
        ming_mansion=ming_mansion, ming_mansion_degree=ming_mansion_degree,
        birth_year_ganzhi=year_ganzhi, birth_hour_branch=_BRANCHES[hour_branch],
        transformations=transformations,
        periods=_timing_periods(birth.resolved_datetime, ming_longitude, year_ganzhi),
        jd_tt=jd_tt, jd_ut1=jd_ut1, engine_version=wrapper_version,
        swiss_ephemeris_version=swiss_version, ephemeris_revision=revision, ephemeris_files=verified,
    )
