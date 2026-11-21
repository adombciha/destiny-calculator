"""He Luo Li Shu natal hexagrams and major and annual line periods."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from typing import Literal

from lunar_python import Lunar
from lunar_python.util import LunarUtil

from .bazi import CALENDAR_TIMEZONE, Pillar, _calendar_datetime, _solar, calculate_bazi
from .models import BirthData
from .timing import TimingPeriod

HELUO_RULE_VERSION = "heluo-1929-v1"

_STEM_NUMBERS = dict(zip("甲乙丙丁戊己庚辛壬癸", (6, 2, 8, 7, 1, 9, 3, 4, 6, 2)))
_BRANCH_NUMBERS = dict(zip("子丑寅卯辰巳午未申酉戌亥", (
    (1, 6), (5, 10), (3, 8), (3, 8), (5, 10), (7, 2),
    (7, 2), (5, 10), (9, 4), (9, 4), (5, 10), (1, 6),
)))

# The lowest bit is the bottom line. Hexagram rows are indexed by the upper trigram.
_TRIGRAMS = "坤震坎兌艮離巽乾"
_LUO_SHU = " 坎坤震巽 乾兌艮離"
_HEXAGRAMS = (
    ("坤", "復", "師", "臨", "謙", "明夷", "升", "泰"),
    ("豫", "震", "解", "歸妹", "小過", "豐", "恆", "大壯"),
    ("比", "屯", "坎", "節", "蹇", "既濟", "井", "需"),
    ("萃", "隨", "困", "兌", "咸", "革", "大過", "夬"),
    ("剝", "頤", "蒙", "損", "艮", "賁", "蠱", "大畜"),
    ("晉", "噬嗑", "未濟", "睽", "旅", "離", "鼎", "大有"),
    ("觀", "益", "渙", "中孚", "漸", "家人", "巽", "小畜"),
    ("否", "無妄", "訟", "履", "遯", "同人", "姤", "乾"),
)


@dataclass(frozen=True, slots=True)
class HeluoHexagram:
    """Lines run from bottom to top, with True for yang and a one-based yuan tang."""

    name: str
    upper_trigram: str
    lower_trigram: str
    lines: tuple[bool, ...]
    yuan_tang: int
    line_name: str


@dataclass(frozen=True, slots=True)
class HeluoPeriod(TimingPeriod):
    """The age bounds are inclusive nominal ages."""

    hexagram: HeluoHexagram
    phase: Literal["earlier", "later"]
    start_age: int
    end_age: int
    year_gan_zhi: str | None = None


@dataclass(frozen=True, slots=True)
class HeluoChart:
    birth: BirthData
    four_pillars: tuple[Pillar, Pillar, Pillar, Pillar]
    heaven_number: int
    earth_number: int
    earlier_heaven: HeluoHexagram
    later_heaven: HeluoHexagram
    periods: tuple[HeluoPeriod, ...]
    rule_version: str = HELUO_RULE_VERSION


def _line_name(line: int, yang: bool) -> str:
    return ("初九", "九二", "九三", "九四", "九五", "上九")[line] if yang else (
        "初六", "六二", "六三", "六四", "六五", "上六"
    )[line]


def _hexagram(bits: int, line: int) -> HeluoHexagram:
    upper, lower = bits >> 3, bits & 7
    lines = tuple(bool(bits & (1 << index)) for index in range(6))
    return HeluoHexagram(
        name=_HEXAGRAMS[upper][lower],
        upper_trigram=_TRIGRAMS[upper],
        lower_trigram=_TRIGRAMS[lower],
        lines=lines,
        yuan_tang=line + 1,
        line_name=_line_name(line, lines[line]),
    )


def _heaven_earth(pillars: tuple[Pillar, ...]) -> tuple[int, int]:
    heaven, earth = 0, 0
    for pillar in pillars:
        stem, branch = pillar.gan_zhi
        number = _STEM_NUMBERS[stem]
        odd, even = _BRANCH_NUMBERS[branch]
        heaven += odd
        earth += even
        if number % 2:
            heaven += number
        else:
            earth += number
    return heaven, earth


def _trigram(total: int, base: int, center: str) -> int:
    if total > base:
        total -= base
    digit = total % 10 or total // 10
    return _TRIGRAMS.index(center if digit == 5 else _LUO_SHU[digit])


def _yuan_tang(bits: int, hour_branch: int, birth: BirthData) -> int:
    half, hour = divmod(hour_branch, 6)
    if bits in (0, 63):
        line = half * 3 + hour % 3
        if (bits == 63 and birth.gender == "female") or (bits == 0 and birth.gender == "male"):
            instant = birth.utc_datetime.astimezone(CALENDAR_TIMEZONE)
            terms = _solar(instant).getLunar().getJieQiTable()
            summer = (
                _calendar_datetime(terms["夏至"]) <= instant < _calendar_datetime(terms["DONG_ZHI"])
            )
            if summer == (bits == 0):
                return 5 - line
        return line

    matching, opposite = [], []
    for line in range(6):
        group = matching if bool(bits & (1 << line)) == (half == 0) else opposite
        group.append(line)
    if len(matching) <= 3:
        matching *= 2
    return (matching + opposite)[hour]


def _later_heaven(bits: int, line: int, lunar_month: int) -> tuple[int, int]:
    changed = bits ^ (1 << line)
    # Kan, Zhun and Jian keep their trigram order for these seasonal exceptions.
    keeps_trigrams = (bits >> 3) == 2 and (bits & 7) in (1, 2, 4)
    if keeps_trigrams and line in (4, 5) and lunar_month % 2 == line - 4:
        return changed, line
    return ((changed & 7) << 3) | (changed >> 3), (line + 3) % 6


def _annual_lines(bits: int, line: int, start_year: int) -> Iterator[tuple[int, int]]:
    yang = bool(bits & (1 << line))
    # Even lunar year numbers are yang, as in the 1984 Jia Zi year.
    if not yang or start_year % 2:
        bits ^= 1 << line
    yield bits, line
    if yang:
        opposite = (line + 3) % 6
        bits ^= 1 << opposite
        yield bits, opposite
        bits ^= 1 << line
        yield bits, line
    for offset in range(1, 7 if yang else 6):
        changed = (line + offset) % 6
        bits ^= 1 << changed
        yield bits, changed


def _new_year(year: int, zone: tzinfo) -> datetime:
    solar = Lunar.fromYmd(year, 1, 1).getSolar()
    midnight = datetime(solar.getYear(), solar.getMonth(), solar.getDay(), tzinfo=zone)
    return midnight.astimezone(UTC).astimezone(zone)


def _periods(
    birth_at: datetime, birth_year: int, earlier: tuple[int, int], later: tuple[int, int]
) -> tuple[HeluoPeriod, ...]:
    year, start = birth_year, birth_at
    periods = []
    for phase, title, (bits, yuan_tang) in (("earlier", "先天", earlier), ("later", "後天", later)):
        for offset in range(6):
            line = (yuan_tang + offset) % 6
            major_start, first_age = start, year - birth_year + 1
            annual = []
            for annual_bits, annual_line in _annual_lines(bits, line, year):
                end = _new_year(year + 1, birth_at.tzinfo)
                hexagram = _hexagram(annual_bits, annual_line)
                year_name = LunarUtil.JIA_ZI[(year - 1984) % 60]
                age = year - birth_year + 1
                label = f"{year_name} {hexagram.name}{hexagram.line_name}（虛歲 {age}）"
                annual.append(HeluoPeriod(
                    method="heluo", level=2,
                    label=label,
                    starts_at=start, ends_at=end,
                    hexagram=hexagram, phase=phase,
                    start_age=age, end_age=age, year_gan_zhi=year_name,
                ))
                year, start = year + 1, end
            hexagram = _hexagram(bits, line)
            last_age = year - birth_year
            label = f"{title} {hexagram.name}{hexagram.line_name}（虛歲 {first_age}–{last_age}）"
            periods.append(HeluoPeriod(
                method="heluo", level=1,
                label=label,
                starts_at=major_start, ends_at=start,
                hexagram=hexagram, phase=phase,
                start_age=first_age, end_age=last_age,
            ))
            periods.extend(annual)
    return tuple(periods)


def calculate_heluo(birth: BirthData) -> HeluoChart:
    """Apply the 1929 edition's natal rules and advance nominal age at local Lunar New Year."""
    if not isinstance(birth, BirthData):
        raise ValueError("birth must be a BirthData.")
    bazi = calculate_bazi(birth, birth.local_datetime, fold=birth.fold)
    pillars = (bazi.year, bazi.month, bazi.day, bazi.hour)
    heaven, earth = _heaven_earth(pillars)
    lunar = _solar(birth.resolved_datetime).getLunar()
    birth_year = lunar.getYear()
    male = birth.gender == "male"
    heaven_above = (bazi.year.gan_zhi[0] in "甲丙戊庚壬") == male
    # The upper yuan begins in 1864 and the three yuan each run for 60 lunar years.
    center = ("艮" if male else "坤", "艮" if heaven_above else "坤", "離" if male else "兌")[
        (birth_year - 1864) // 60 % 3
    ]
    upper, lower = _trigram(heaven, 25, center), _trigram(earth, 30, center)
    if not heaven_above:
        upper, lower = lower, upper
    bits = (upper << 3) | lower
    hour_branch = "子丑寅卯辰巳午未申酉戌亥".index(bazi.hour.gan_zhi[1])
    earlier = bits, _yuan_tang(bits, hour_branch, birth)
    later = _later_heaven(*earlier, abs(lunar.getMonth()))
    return HeluoChart(
        birth=birth,
        four_pillars=pillars,
        heaven_number=heaven,
        earth_number=earth,
        earlier_heaven=_hexagram(*earlier),
        later_heaven=_hexagram(*later),
        periods=_periods(birth.resolved_datetime, birth_year, earlier, later),
    )
