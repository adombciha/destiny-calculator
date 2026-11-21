"""Shared interval representation for natal timing methods."""

from dataclasses import dataclass
from datetime import UTC, datetime

from .time_utils import MAX_FLOW_YEARS, shift_local_years


@dataclass(frozen=True, slots=True)
class TimingPeriod:
    method: str
    level: int
    label: str
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class TimingWindow:
    starts_at: datetime
    ends_at: datetime
    current: tuple[TimingPeriod, ...]
    periods: tuple[TimingPeriod, ...]


def timing_bounds(query: datetime, years: tuple[int, int]) -> tuple[datetime, datetime]:
    if not isinstance(query, datetime) or query.utcoffset() is None:
        raise ValueError("Timing query must include a timezone.")
    if (
        not isinstance(years, (tuple, list))
        or len(years) != 2
        or any(type(year) is not int or not 0 <= year <= MAX_FLOW_YEARS for year in years)
    ):
        raise ValueError(f"Timing years must be two integers between 0 and {MAX_FLOW_YEARS}.")
    return shift_local_years(query, -years[0]), shift_local_years(query, years[1])


def timing_window(
    periods: tuple[TimingPeriod, ...], query: datetime, years: tuple[int, int]
) -> TimingWindow:
    start, end = timing_bounds(query, years)
    instant, start_utc, end_utc = (value.astimezone(UTC) for value in (query, start, end))
    current, visible = [], []
    for period in periods:
        left, right = period.starts_at.astimezone(UTC), period.ends_at.astimezone(UTC)
        active = left <= instant < right
        if active:
            current.append(period)
        if active or (left < end_utc and right > start_utc):
            visible.append(period)
    return TimingWindow(start, end, tuple(current), tuple(visible))
