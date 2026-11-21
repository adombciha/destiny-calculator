"""Serialize calculated charts without writing personal data to disk."""

import json
import platform
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime

from .bazi import BaziChart
from .western import WesternChart
from .ziwei import DEFAULT_FLOW_YEARS, ZiweiChart, _flow_forecast


def _value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {f.name: _value(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (tuple, list)):
        return [_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _value(item) for key, item in value.items()}
    return value


def export_report_json(
    charts: tuple[BaziChart | ZiweiChart | WesternChart, ...],
    *,
    errors: dict[str, str] | None = None,
    generated_at: datetime | None = None,
    ziwei_years: tuple[int, int] = DEFAULT_FLOW_YEARS,
) -> str:
    if not charts:
        raise ValueError("At least one calculated chart is required.")
    if any(not isinstance(c, (BaziChart, ZiweiChart, WesternChart)) for c in charts):
        raise ValueError("Only BaZi, Ziwei and Western charts are supported.")
    first = charts[0]
    timed = [c for c in charts if not isinstance(c, WesternChart)]
    query = timed[0].query_datetime if timed else None
    if any(c.birth != first.birth for c in charts) or any(
        c.query_datetime.astimezone(UTC) != query.astimezone(UTC) for c in timed
    ):
        raise ValueError("Charts must share the same birth data and query instant.")
    generated_at = generated_at or datetime.now(UTC)
    if (
        not isinstance(generated_at, datetime)
        or generated_at.tzinfo is None
        or generated_at.utcoffset() is None
    ):
        raise ValueError("generated_at must include a timezone.")
    results = {name: {"status": "not_requested"} for name in ("bazi", "ziwei", "western")}
    for chart in charts:
        name = (
            "bazi"
            if isinstance(chart, BaziChart)
            else "ziwei" if isinstance(chart, ZiweiChart) else "western"
        )
        if results[name]["status"] != "not_requested":
            raise ValueError("A report cannot contain duplicate chart systems.")
        data = _value(chart)
        data.pop("birth")
        if isinstance(chart, ZiweiChart):
            data["flow_forecast"] = _value(_flow_forecast(chart, ziwei_years))
        results[name] = {
            "status": (
                "partial"
                if isinstance(chart, WesternChart) and chart.house_status != "ok"
                else "ok"
            ),
            "data": data,
        }
    errors = errors or {}
    for name in errors:
        if name not in results or results[name]["status"] != "not_requested":
            raise ValueError("Errors must name a supported system without a successful chart.")
        results[name] = {"status": "error"}
    birth = _value(first.birth)
    birth["utc_datetime"] = first.birth.utc_datetime.isoformat()
    birth["fold"] = first.birth.resolved_datetime.fold
    payload = {
        "schema_version": "destiny-report-v1",
        "generated_at": generated_at.isoformat(),
        "birth": birth,
        "query_datetime": query.isoformat() if query else None,
        "results": results,
        "errors": [
            {"system": name, "code": "calculation_failed", "message": message}
            for name, message in errors.items()
        ],
        "provenance": {
            "python": platform.python_version(),
            "timezone_database_version": None,
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)


def export_chart_json(
    chart: BaziChart | ZiweiChart | WesternChart,
    *,
    ziwei_years: tuple[int, int] = DEFAULT_FLOW_YEARS,
) -> str:
    return export_report_json((chart,), ziwei_years=ziwei_years)
