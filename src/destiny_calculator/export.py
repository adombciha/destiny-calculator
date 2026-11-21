"""Serialize calculated charts without writing personal data to disk."""

import json
import platform
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime

from .bazi import BaziChart
from .bazi import _flow_forecast as _bazi_flow_forecast
from .heluo import HeluoChart
from .jyotish import JyotishChart
from .qizheng import QizhengChart
from .time_utils import DEFAULT_FLOW_YEARS
from .timing import timing_bounds, timing_window
from .western import WesternChart
from .western_timing import calculate_western_timing
from .ziwei import ZiweiChart
from .ziwei import _flow_forecast as _ziwei_flow_forecast


Chart = BaziChart | ZiweiChart | WesternChart | JyotishChart | QizhengChart | HeluoChart
_SYSTEMS = {
    BaziChart: "bazi", ZiweiChart: "ziwei", WesternChart: "western",
    JyotishChart: "jyotish", QizhengChart: "qizheng", HeluoChart: "heluo",
}


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
    charts: tuple[Chart, ...],
    *,
    errors: dict[str, str] | None = None,
    generated_at: datetime | None = None,
    ziwei_years: tuple[int, int] = DEFAULT_FLOW_YEARS,
    bazi_years: tuple[int, int] = DEFAULT_FLOW_YEARS,
    query_datetime: datetime | None = None,
    timing_years: tuple[int, int] | None = None,
) -> str:
    if not charts:
        raise ValueError("At least one calculated chart is required.")
    names = [next((name for kind, name in _SYSTEMS.items() if isinstance(c, kind)), None) for c in charts]
    if None in names:
        raise ValueError("Unsupported chart system.")
    first = charts[0]
    timed = [c for c in charts if isinstance(c, (BaziChart, ZiweiChart))]
    periods_requested = timing_years is not None or any(
        isinstance(c, (JyotishChart, QizhengChart, HeluoChart)) for c in charts
    )
    query = query_datetime if query_datetime is not None else (
        timed[0].query_datetime if timed else first.birth.resolved_datetime if periods_requested else None
    )
    if query is not None:
        if not isinstance(query, datetime) or query.utcoffset() is None:
            raise ValueError("query_datetime must include a timezone.")
        query = query.astimezone(first.birth.resolved_datetime.tzinfo)
        if query.astimezone(UTC) < first.birth.utc_datetime:
            raise ValueError("Query time cannot be earlier than birth time.")
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
    errors = errors or {}
    results = {
        name: {"status": "not_requested"}
        for name in _SYSTEMS.values()
        if name in ("bazi", "ziwei", "western") or name in names or name in errors
    }
    years = DEFAULT_FLOW_YEARS if timing_years is None else timing_years
    if periods_requested:
        _, horizon = timing_bounds(query, years)
    for chart, name in zip(charts, names):
        if results[name]["status"] != "not_requested":
            raise ValueError("A report cannot contain duplicate chart systems.")
        data = {f.name: _value(getattr(chart, f.name)) for f in fields(chart) if f.name not in ("birth", "periods")}
        status = "ok"
        if isinstance(chart, BaziChart):
            data["flow_forecast"] = _value(_bazi_flow_forecast(chart, bazi_years))
        elif isinstance(chart, ZiweiChart):
            data["flow_forecast"] = _value(_ziwei_flow_forecast(chart, ziwei_years))
        elif isinstance(chart, WesternChart):
            if chart.house_status != "ok":
                status = "partial"
            if periods_requested:
                try:
                    timing = calculate_western_timing(chart, through=horizon)
                except ValueError as error:
                    data["timing_error"] = str(error)
                    status = "partial"
                else:
                    data["timing"] = {
                        **{f.name: _value(getattr(timing, f.name)) for f in fields(timing) if f.name != "periods"},
                        **_value(timing_window(timing.periods, query, years)),
                    }
        else:
            data["timing"] = _value(timing_window(chart.periods, query, years))
        results[name] = {"status": status, "data": data}
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
    chart: Chart,
    *,
    ziwei_years: tuple[int, int] = DEFAULT_FLOW_YEARS,
    bazi_years: tuple[int, int] = DEFAULT_FLOW_YEARS,
    query_datetime: datetime | None = None,
    timing_years: tuple[int, int] | None = None,
) -> str:
    return export_report_json(
        (chart,), ziwei_years=ziwei_years, bazi_years=bazi_years,
        query_datetime=query_datetime, timing_years=timing_years,
    )
