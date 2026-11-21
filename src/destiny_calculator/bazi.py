"""BaZi charts with local civil days and UTC+8 solar-term boundaries."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from importlib.metadata import version

from lunar_python import Lunar, Solar
from lunar_python.util import LunarUtil

from .models import BirthData
from .time_utils import MAX_FLOW_YEARS, shift_local_years

CALENDAR_TIMEZONE = timezone(timedelta(hours=8))
TRADITIONAL = str.maketrans({"财": "財", "伤": "傷", "杀": "殺"})


@dataclass(frozen=True, slots=True)
class Pillar:
    gan_zhi: str
    hidden_stems: tuple[str, ...]
    elements: tuple[str, str]
    stem_ten_god: str
    hidden_ten_gods: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BaziPeriod:
    pillar: Pillar
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class BaziChart:
    birth: BirthData
    year: Pillar
    month: Pillar
    day: Pillar
    hour: Pillar
    luck_forward: bool
    luck_start_offset: tuple[int, int, int, int]
    luck_starts_at: datetime
    luck_periods: tuple[BaziPeriod, ...]
    query_datetime: datetime
    current_luck: BaziPeriod | None
    flow_year: BaziPeriod
    flow_month: BaziPeriod
    engine_version: str
    rules_version: str = "bazi-v1"


def _solar(value: datetime) -> Solar:
    return Solar.fromYmdHms(
        value.year, value.month, value.day, value.hour, value.minute, value.second
    )


def _calendar_datetime(solar: Solar) -> datetime:
    return datetime(
        solar.getYear(), solar.getMonth(), solar.getDay(),
        solar.getHour(), solar.getMinute(), solar.getSecond(),
        tzinfo=CALENDAR_TIMEZONE,
    )


def _pillar(gan_zhi: str, day_stem: str) -> Pillar:
    stem, branch = gan_zhi
    hidden = tuple(LunarUtil.ZHI_HIDE_GAN[branch])
    return Pillar(
        gan_zhi=gan_zhi,
        hidden_stems=hidden,
        elements=(LunarUtil.WU_XING_GAN[stem], LunarUtil.WU_XING_ZHI[branch]),
        stem_ten_god=LunarUtil.SHI_SHEN[day_stem + stem].translate(TRADITIONAL),
        hidden_ten_gods=tuple(
            LunarUtil.SHI_SHEN[day_stem + item].translate(TRADITIONAL) for item in hidden
        ),
    )


def _li_chun(year: int) -> Solar:
    return Solar.fromYmd(year, 7, 1).getLunar().getJieQiTable()["立春"]


def _flow_year(query: datetime, lunar: Lunar, day_stem: str) -> BaziPeriod:
    year = lunar.getSolar().getYear()
    spring = _calendar_datetime(_li_chun(year))
    if query.astimezone(UTC) < spring.astimezone(UTC):
        start, end = _calendar_datetime(_li_chun(year - 1)), spring
    else:
        start, end = spring, _calendar_datetime(_li_chun(year + 1))
    return BaziPeriod(
        _pillar(lunar.getEightChar().getYear(), day_stem),
        start.astimezone(query.tzinfo), end.astimezone(query.tzinfo),
    )


def _flow_month(query: datetime, lunar: Lunar, day_stem: str) -> BaziPeriod:
    return BaziPeriod(
        _pillar(lunar.getEightChar().getMonth(), day_stem),
        _calendar_datetime(lunar.getPrevJie().getSolar()).astimezone(query.tzinfo),
        _calendar_datetime(lunar.getNextJie().getSolar()).astimezone(query.tzinfo),
    )


def _flow_forecast(
    chart: BaziChart, years: tuple[int, int]
) -> dict[str, datetime | list[BaziPeriod]]:
    if not isinstance(years, (tuple, list)) or len(years) != 2 or any(
        type(value) is not int or not 0 <= value <= MAX_FLOW_YEARS for value in years
    ):
        raise ValueError(f"BaZi forecast needs two whole year counts between 0 and {MAX_FLOW_YEARS}.")
    before, after = years
    query = chart.query_datetime
    zone = query.tzinfo
    requested_start = shift_local_years(query, -before)
    requested_end = shift_local_years(query, after)
    start = max(requested_start.astimezone(UTC), chart.birth.utc_datetime)
    end = min(requested_end.astimezone(UTC), datetime(2100, 1, 1, tzinfo=zone).astimezone(UTC))
    annual, monthly, luck = [], [], []
    if start < end:
        luck = [
            period for period in chart.luck_periods
            if period.starts_at.astimezone(UTC) < end and period.ends_at.astimezone(UTC) > start
        ]
        day_stem = chart.day.gan_zhi[0]
        cursor = start
        while cursor < end:
            local_cursor = cursor.astimezone(zone)
            lunar = _solar(cursor.astimezone(CALENDAR_TIMEZONE)).getLunar()
            if not annual or annual[-1].ends_at.astimezone(UTC) <= cursor:
                annual.append(_flow_year(local_cursor, lunar, day_stem))
            month = _flow_month(local_cursor, lunar, day_stem)
            monthly.append(month)
            next_cursor = month.ends_at.astimezone(UTC)
            if next_cursor <= cursor:
                raise ValueError("BaZi forecast did not advance to the next solar term.")
            cursor = next_cursor

    return {
        "requested_starts_at": requested_start,
        "requested_ends_at": requested_end,
        "starts_at": start.astimezone(zone),
        "ends_at": end.astimezone(zone),
        "years": annual,
        "months": monthly,
        "luck_periods": luck,
    }


def calculate_bazi(
    birth: BirthData,
    query_datetime: datetime | None = None,
    *,
    fold: int | None = None,
) -> BaziChart:
    if not isinstance(birth, BirthData):
        raise ValueError("birth must be a BirthData.")
    query = birth.resolve_query_time(query_datetime, fold=fold)
    local_eight = _solar(birth.resolved_datetime).getLunar().getEightChar()
    local_eight.setSect(2)

    # The engine's solar terms are fixed UTC+8, not historical Asia/Shanghai time.
    calendar_birth = birth.utc_datetime.astimezone(CALENDAR_TIMEZONE)
    calendar_eight = _solar(calendar_birth).getLunar().getEightChar()
    calendar_eight.setSect(2)
    day_stem = local_eight.getDayGan()
    yun = calendar_eight.getYun(1 if birth.gender == "male" else 0, 2)
    start_solar = yun.getStartSolar()
    zone = birth.resolved_datetime.tzinfo
    luck_periods = []
    for cycle in yun.getDaYun((2100 - calendar_birth.year) // 10 + 2)[1:]:
        index = cycle.getIndex() - 1
        starts_at = _calendar_datetime(start_solar.nextYear(index * 10)).astimezone(zone)
        ends_at = _calendar_datetime(start_solar.nextYear((index + 1) * 10)).astimezone(zone)
        if starts_at.year > 2099:
            break
        luck_periods.append(BaziPeriod(_pillar(cycle.getGanZhi(), day_stem), starts_at, ends_at))
    query_utc = query.astimezone(UTC)
    current_luck = next(
        (
            period for period in luck_periods
            if period.starts_at.astimezone(UTC) <= query_utc < period.ends_at.astimezone(UTC)
        ),
        None,
    )

    query_lunar = _solar(query.astimezone(CALENDAR_TIMEZONE)).getLunar()

    return BaziChart(
        birth=birth,
        year=_pillar(calendar_eight.getYear(), day_stem),
        month=_pillar(calendar_eight.getMonth(), day_stem),
        day=_pillar(local_eight.getDay(), day_stem),
        hour=_pillar(local_eight.getTime(), day_stem),
        luck_forward=yun.isForward(),
        luck_start_offset=(
            yun.getStartYear(), yun.getStartMonth(), yun.getStartDay(), yun.getStartHour()
        ),
        luck_starts_at=_calendar_datetime(start_solar).astimezone(zone),
        luck_periods=tuple(luck_periods),
        query_datetime=query,
        current_luck=current_luck,
        flow_year=_flow_year(query, query_lunar, day_stem),
        flow_month=_flow_month(query, query_lunar, day_stem),
        engine_version=version("lunar-python"),
    )
