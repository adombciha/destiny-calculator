"""Resolve local civil time without silently changing ambiguous input."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class AmbiguousTimeError(ValueError):
    """The local time occurs twice and needs an explicit fold."""


class NonexistentTimeError(ValueError):
    """The local time was skipped by a time zone transition."""


def get_timezone(name: str) -> ZoneInfo:
    if not isinstance(name, str) or not name:
        raise ValueError("Time zone must be a nonempty IANA name.")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(f"Unknown or unavailable IANA time zone: {name}") from error


def resolve_local_time(
    local_datetime: datetime, timezone_name: str, fold: int | None = None
) -> datetime:
    if not isinstance(local_datetime, datetime) or local_datetime.tzinfo is not None:
        raise ValueError("Local time must be a datetime without tzinfo.")
    if not 1900 <= local_datetime.year <= 2099:
        raise ValueError("Local date must be between 1900-01-01 and 2099-12-31.")
    if fold is not None and (type(fold) is not int or fold not in (0, 1)):
        raise ValueError("fold must be 0, 1, or None.")

    zone = get_timezone(timezone_name)
    candidates = {}
    for occurrence in (0, 1):
        candidate = local_datetime.replace(tzinfo=zone, fold=occurrence)
        utc = candidate.astimezone(UTC)
        round_trip = utc.astimezone(zone)
        # Attaching tzinfo alone also accepts times skipped by a clock change.
        if round_trip.replace(tzinfo=None) == local_datetime:
            candidates[occurrence] = round_trip

    if not candidates:
        raise NonexistentTimeError("This local time does not exist in the selected time zone.")
    if fold is None and len({value.astimezone(UTC) for value in candidates.values()}) > 1:
        raise AmbiguousTimeError("This local time occurs twice; choose fold=0 or fold=1.")
    return candidates[fold if fold is not None else 0]
