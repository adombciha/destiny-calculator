"""Ziwei sky charts with explicit rules and local lunar calendar periods."""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from importlib.metadata import version
from importlib.resources import files

from izthon.astro import by_solar
from izthon.astro.functional_astrolabe import FunctionalAstrolabe
from izthon.astro.functional_horoscope import FunctionalHoroscope, HoroscopeItem
from izthon.astro.functional_palace import FunctionalPalace
from izthon.data import STARS_INFO, earthly_branches, heavenly_stems
from izthon.i18n import kot, t, using_language
from izthon.lunar_lite import LunarDate, lunar_to_solar, solar_to_lunar
from izthon.star.functional_star import FunctionalStar
from izthon.util import time_to_index

from . import time_utils
from .models import BirthData


TRADITIONAL = str.maketrans({"闰": "閏", "腊": "臘"})
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
DISPLAY_NAMES = {"僕役": "交友", "三台": "三臺", "台輔": "臺輔"}
DEFAULT_FLOW_YEARS = time_utils.DEFAULT_FLOW_YEARS
MAX_FLOW_YEARS = time_utils.MAX_FLOW_YEARS
LUNAR_MONTH_NAMES = (
    "正月", "二月", "三月", "四月", "五月", "六月",
    "七月", "八月", "九月", "十月", "冬月", "臘月",
)
BRIGHTNESS_DATA = json.loads(
    files("destiny_calculator").joinpath("data/ziwei_brightness.json").read_text(encoding="utf-8")
)


@dataclass(frozen=True, slots=True)
class ZiweiStar:
    name: str
    brightness: str | None
    mutagen: str | None


@dataclass(frozen=True, slots=True)
class ZiweiPalace:
    index: int
    name: str
    gan_zhi: str
    is_body_palace: bool
    major_stars: tuple[ZiweiStar, ...]
    minor_stars: tuple[ZiweiStar, ...]
    adjective_stars: tuple[ZiweiStar, ...]
    decadal_age_range: tuple[int, int]
    ages: tuple[int, ...]
    yearly_ages: tuple[int, ...]
    changsheng_12: str
    boshi_12: str
    jiangqian_12: str
    suiqian_12: str


@dataclass(frozen=True, slots=True)
class ZiweiCycle:
    index: int
    gan_zhi: str
    palace_names: tuple[str, ...]
    mutagens: tuple[str, ...]
    stars: tuple[tuple[ZiweiStar, ...], ...]


@dataclass(frozen=True, slots=True)
class ZiweiPeriod(ZiweiCycle):
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class ZiweiChart:
    birth: BirthData
    lunar_date: str
    soul: str
    body: str
    five_elements_class: str
    zi_dou: str
    palaces: tuple[ZiweiPalace, ...]
    query_datetime: datetime
    query_lunar_date: str
    nominal_age: int
    current_luck: ZiweiCycle
    is_childhood: bool
    flow_year: ZiweiPeriod
    flow_month: ZiweiPeriod
    engine_version: str
    rules_version: str = "ziwei-reference-v2"


def _chart_config() -> dict:
    brightness = {key: list(info["brightness"]) for key, info in STARS_INFO.items()}
    for key in (
        "zuofuMin", "youbiMin", "tiankuiMin", "tianyueMin",
        "lucunMin", "tianmaMin", "dikongMin", "dijieMin",
    ):
        brightness[key] = [""] * 12
    # iztro v2.6.1, commit bb1781cc, corrected these three stars in the You palace.
    for key, value in (("taiyangMaj", "ping"), ("taiyinMaj", "wang"), ("qishaMaj", "wang")):
        brightness[key][7] = value
    return {
        "algorithm": "default",
        "year_divide": "normal",
        "horoscope_divide": "normal",
        "age_divide": "normal",
        "day_divide": "forward",
        "mutagens": {key: list(info["mutagen"]) for key, info in heavenly_stems.items()},
        "brightness": brightness,
    }


def _brightness(name: str, index: int) -> str | None:
    row = BRIGHTNESS_DATA["brightness"].get(name)
    return BRIGHTNESS_DATA["levels"][row[(index + 2) % 12]] if row else None


def _stars(stars: list[FunctionalStar], index: int | None = None) -> tuple[ZiweiStar, ...]:
    result = []
    for star in stars:
        name = DISPLAY_NAMES.get(star.name, star.name)
        brightness = star.brightness or None
        if index is not None and name in BRIGHTNESS_DATA["brightness"]:
            brightness = _brightness(name, index)
        result.append(ZiweiStar(name, brightness, star.mutagen or None))
    return tuple(result)


def _adjectives(palace: FunctionalPalace, year_stem: int, year_branch: int) -> tuple[ZiweiStar, ...]:
    stars = _stars(
        [s for s in palace.adjective_stars if s.name not in {"截路", "空亡", "旬空"}],
        palace.index,
    )
    # Both empty-star pairs use the year's polarity to select the primary branch.
    polarity = year_stem % 2
    jie_start = (8 - 2 * (year_stem % 5)) % 12
    xun_start = (year_branch - year_stem + 10) % 12
    extra = [
        ("截空", (jie_start + polarity) % 12),
        ("副截", (jie_start + 1 - polarity) % 12),
        ("旬空", (xun_start + polarity) % 12),
        ("副旬", (xun_start + 1 - polarity) % 12),
        ("大耗", (year_branch + 6 + (1 if year_branch % 2 == 0 else -1)) % 12),
    ]
    branch = (palace.index + 2) % 12
    for name in (palace.suiqian_12, palace.jiangqian_12):
        if name in {"龍德", "劫煞"}:
            extra.append((name, branch))
    return stars + tuple(
        ZiweiStar(name, _brightness(name, palace.index), None)
        for name, target in extra if target == branch
    )


def _cycle(item: HoroscopeItem) -> ZiweiCycle:
    return ZiweiCycle(
        index=item.index,
        gan_zhi=item.heavenly_stem + item.earthly_branch,
        palace_names=tuple(DISPLAY_NAMES.get(name, name) for name in item.palace_names),
        mutagens=tuple(item.mutagen),
        stars=tuple(_stars(stars) for stars in item.stars),
    )


def _lunar_day(year: int, month: int, day: int = 1, *, leap: bool = False) -> date:
    solar = lunar_to_solar(f"{year}-{month}-{day}", leap)
    return date(solar.solar_year, solar.solar_month, solar.solar_day)


def _midnight(day: date, zone: tzinfo) -> datetime:
    # Round-trip to the first valid instant when a local midnight is skipped.
    return datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(UTC).astimezone(zone)


def _period(item: HoroscopeItem, start: date, end: date, zone: tzinfo) -> ZiweiPeriod:
    cycle = _cycle(item)
    return ZiweiPeriod(
        cycle.index, cycle.gan_zhi, cycle.palace_names, cycle.mutagens, cycle.stars,
        _midnight(start, zone), _midnight(end, zone),
    )


def _natal_chart(birth: BirthData) -> FunctionalAstrolabe:
    return by_solar(
        birth.local_datetime.date().isoformat(),
        time_to_index(birth.local_datetime.hour),
        "男" if birth.gender == "male" else "女",
        fix_leap=True,
        language="zh-TW",
        config=_chart_config(),
        plate="sky",
    )


def _lunar_month_dates(lunar: LunarDate) -> tuple[date, date]:
    month_start = _lunar_day(lunar.lunar_year, lunar.lunar_month, leap=lunar.is_leap)
    probe = month_start + timedelta(days=30)
    next_lunar = solar_to_lunar(probe)
    month_end = probe - timedelta(days=next_lunar.lunar_day - 1)
    if lunar.is_leap:
        split = month_start + timedelta(days=15)
        if lunar.lunar_day <= 15:
            month_end = split
        else:
            month_start = split
    return month_start, month_end


def _flow_periods(
    horoscope: FunctionalHoroscope, query: datetime
) -> tuple[ZiweiPeriod, ZiweiPeriod]:
    lunar = solar_to_lunar(query.date())
    year_start = _lunar_day(lunar.lunar_year, 1)
    year_end = _lunar_day(lunar.lunar_year + 1, 1)
    month_start, month_end = _lunar_month_dates(lunar)
    zone = query.tzinfo
    return (
        _period(horoscope.yearly, year_start, year_end, zone),
        _period(horoscope.monthly, month_start, month_end, zone),
    )


def _flow_bounds(
    chart: ZiweiChart, years: tuple[int, int]
) -> tuple[datetime, datetime, datetime, datetime]:
    if len(years) != 2 or any(
        type(value) is not int or not 0 <= value <= MAX_FLOW_YEARS for value in years
    ):
        raise ValueError(f"Ziwei forecast needs two whole year counts between 0 and {MAX_FLOW_YEARS}.")
    before, after = years
    query = chart.query_datetime
    zone = query.tzinfo
    requested_start = time_utils.shift_local_years(query, -before)
    requested_end = time_utils.shift_local_years(query, after)
    start = max(requested_start.astimezone(UTC), chart.birth.utc_datetime).astimezone(zone)
    end = min(requested_end.astimezone(UTC), _midnight(date(2100, 1, 1), zone).astimezone(UTC))
    if start.astimezone(UTC) < end:
        birth_lunar_year = solar_to_lunar(chart.birth.local_datetime.date()).lunar_year
        last_age = max(p.decadal_age_range[1] for p in chart.palaces)
        # Nominal age reaches last_age + 1 at this lunar new year.
        first_unsupported_year = birth_lunar_year + last_age
        if first_unsupported_year <= end.astimezone(zone).year:
            limit = _midnight(_lunar_day(first_unsupported_year, 1), zone).astimezone(UTC)
            end = min(end, limit)
    return requested_start, requested_end, start, end.astimezone(zone)


def _browse_years(
    chart: ZiweiChart, years: tuple[int, int]
) -> tuple[tuple[int, datetime, datetime], ...]:
    _, _, cursor, end = _flow_bounds(chart, years)
    if tuple(years) == (0, 0):
        year = solar_to_lunar(cursor.date()).lunar_year
        return ((year, cursor, chart.flow_month.ends_at),)

    periods = []
    end_utc = end.astimezone(UTC)
    while cursor.astimezone(UTC) < end_utc:
        year = solar_to_lunar(cursor.date()).lunar_year
        next_year = _midnight(_lunar_day(year + 1, 1), cursor.tzinfo)
        periods.append((year, cursor, min(next_year, end, key=lambda value: value.astimezone(UTC))))
        cursor = next_year
    return tuple(periods)


def _browse_months(start: datetime, end: datetime) -> tuple[tuple[str, datetime, datetime], ...]:
    periods = []
    cursor = start
    end_utc = end.astimezone(UTC)
    while cursor.astimezone(UTC) < end_utc:
        lunar = solar_to_lunar(cursor.date())
        label = LUNAR_MONTH_NAMES[lunar.lunar_month - 1]
        if lunar.is_leap:
            half = "前半" if lunar.lunar_day <= 15 else "後半"
            label = f"閏{label}（{half}）"
        _, month_end = _lunar_month_dates(lunar)
        next_month = _midnight(month_end, cursor.tzinfo)
        periods.append((label, cursor, min(next_month, end, key=lambda value: value.astimezone(UTC))))
        cursor = next_month
    return tuple(periods)


def _flow_forecast(
    chart: ZiweiChart, years: tuple[int, int]
) -> dict[str, datetime | list[ZiweiPeriod]]:
    requested_start, requested_end, start, end = _flow_bounds(chart, years)
    annual, monthly = [], []
    end_utc = end.astimezone(UTC)
    if start.astimezone(UTC) < end_utc:
        natal = _natal_chart(chart.birth)
        cursor = start
        while cursor.astimezone(UTC) < end_utc:
            horoscope = natal.horoscope(cursor.replace(tzinfo=None))
            year, month = _flow_periods(horoscope, cursor)
            if not annual or annual[-1].starts_at != year.starts_at:
                annual.append(year)
            monthly.append(month)
            if month.ends_at.astimezone(UTC) <= cursor.astimezone(UTC):
                raise ValueError("Ziwei forecast did not advance to the next lunar period.")
            cursor = month.ends_at

    return {
        "requested_starts_at": requested_start,
        "requested_ends_at": requested_end,
        "starts_at": start,
        "ends_at": end,
        "years": annual,
        "months": monthly,
    }


def calculate_ziwei(
    birth: BirthData,
    query_datetime: datetime | None = None,
    *,
    fold: int | None = None,
) -> ZiweiChart:
    if not isinstance(birth, BirthData):
        raise ValueError("birth must be a BirthData.")
    query = birth.resolve_query_time(query_datetime, fold=fold)
    if birth.local_datetime.date() < date(1900, 1, 31):
        raise ValueError("Ziwei birth dates must be between 1900-01-31 and 2099-12-31.")
    natal = _natal_chart(birth)
    horoscope = natal.horoscope(query.replace(tzinfo=None))
    if not 0 <= horoscope.decadal.index < 12:
        raise ValueError("Ziwei query exceeds the engine's twelve decadal cycles.")

    birth_lunar = natal.raw_dates["lunar_date"]
    year_gan, year_zhi = natal.raw_dates["chinese_date"].yearly
    year_stem = "甲乙丙丁戊己庚辛壬癸".index(year_gan)
    year_branch = BRANCHES.index(year_zhi)
    with using_language("zh-TW"):
        soul = t(earthly_branches[kot(year_zhi)]["soul"])
    flow_year, flow_month = _flow_periods(horoscope, query)

    palaces = tuple(
        ZiweiPalace(
            index=p.index,
            name=DISPLAY_NAMES.get(p.name, p.name),
            gan_zhi=p.heavenly_stem + p.earthly_branch,
            is_body_palace=p.is_body_palace,
            major_stars=_stars(p.major_stars, p.index),
            minor_stars=_stars(p.minor_stars, p.index),
            adjective_stars=_adjectives(p, year_stem, year_branch),
            decadal_age_range=p.decadal.range,
            ages=tuple(p.ages),
            yearly_ages=tuple(((p.index + 2 - year_branch) % 12) + 1 + 12 * i for i in range(10)),
            changsheng_12=p.changsheng_12,
            boshi_12="官符" if p.boshi_12 == "官府" else p.boshi_12,
            jiangqian_12=p.jiangqian_12,
            suiqian_12="歲破" if p.suiqian_12 == "大耗" else p.suiqian_12,
        )
        for p in natal.palaces
    )
    return ZiweiChart(
        birth=birth,
        lunar_date=natal.lunar_date.translate(TRADITIONAL),
        soul=soul,
        body=natal.body,
        five_elements_class=natal.five_elements_class,
        zi_dou=BRANCHES[
            (time_to_index(birth.local_datetime.hour) % 12 - birth_lunar.lunar_month
             - int(birth_lunar.is_leap and birth_lunar.lunar_day > 15) + 1) % 12
        ],
        palaces=palaces,
        query_datetime=query,
        query_lunar_date=horoscope.lunar_date.translate(TRADITIONAL),
        nominal_age=horoscope.age.nominal_age,
        current_luck=_cycle(horoscope.decadal),
        is_childhood=horoscope.age.nominal_age < min(p.decadal_age_range[0] for p in palaces),
        flow_year=flow_year,
        flow_month=flow_month,
        engine_version=version("izthon"),
    )
