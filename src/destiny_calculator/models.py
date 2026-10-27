"""Validated birth input shared by the chart engines."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import isfinite
from typing import Literal

from .time_utils import get_timezone, resolve_local_time


@dataclass(frozen=True, slots=True)
class BirthPlace:
    name: str
    latitude: float
    longitude: float
    timezone: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Place name must be a nonempty string.")
        for name, value, limit in (
            ("Latitude", self.latitude, 90),
            ("Longitude", self.longitude, 180),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not -limit <= value <= limit
                or not isfinite(value)
            ):
                raise ValueError(f"{name} must be a finite number between {-limit} and {limit}.")
        get_timezone(self.timezone)


@dataclass(frozen=True, slots=True)
class BirthData:
    local_datetime: datetime
    place: BirthPlace
    gender: Literal["male", "female"]
    fold: int | None = None
    resolved_datetime: datetime = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.place, BirthPlace):
            raise ValueError("place must be a BirthPlace.")
        if self.gender not in ("male", "female"):
            raise ValueError("gender must be 'male' or 'female' for traditional luck cycles.")
        resolved = resolve_local_time(self.local_datetime, self.place.timezone, self.fold)
        if self.local_datetime.second or self.local_datetime.microsecond:
            raise ValueError("Birth time must have minute precision; seconds must be zero.")
        object.__setattr__(self, "resolved_datetime", resolved)

    @property
    def utc_datetime(self) -> datetime:
        return self.resolved_datetime.astimezone(UTC)

    def resolve_query_time(
        self, local_datetime: datetime | None = None, *, fold: int | None = None
    ) -> datetime:
        if local_datetime is None:
            if fold is not None:
                raise ValueError("fold requires an explicit local query time.")
            local_now = datetime.now(UTC).astimezone(self.resolved_datetime.tzinfo)
            resolved = resolve_local_time(
                local_now.replace(tzinfo=None), self.place.timezone, local_now.fold
            )
        else:
            resolved = resolve_local_time(local_datetime, self.place.timezone, fold)
        # Same-zone datetime comparisons ignore fold, so compare UTC instants.
        if resolved.astimezone(UTC) < self.utc_datetime:
            raise ValueError("Query time cannot be earlier than birth time.")
        return resolved
