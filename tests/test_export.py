import json
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from destiny_calculator import (
    BirthData,
    calculate_bazi,
    calculate_ziwei,
    export_chart_json,
    export_report_json,
    get_city,
)


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.birth = BirthData(datetime(2000, 8, 16, 4), get_city("臺北"), "female")
        cls.bazi = calculate_bazi(cls.birth, datetime(2026, 10, 28, 12))
        cls.ziwei = calculate_ziwei(cls.birth, datetime(2026, 10, 28, 12))

    def test_report_preserves_time_rules_layers_and_null_values(self):
        stamp = datetime(2026, 10, 28, tzinfo=UTC)
        raw = export_report_json((self.bazi, self.ziwei), generated_at=stamp)
        report = json.loads(raw)
        self.assertIn("臺北", raw)
        self.assertEqual(report["birth"]["utc_datetime"], "2000-08-15T20:00:00+00:00")
        self.assertEqual(report["birth"]["place"]["timezone"], "Asia/Taipei")
        self.assertEqual(report["query_datetime"], "2026-10-28T12:00:00+08:00")
        self.assertEqual(report["results"]["bazi"]["data"]["rules_version"], "bazi-v1")
        ziwei = report["results"]["ziwei"]["data"]
        self.assertEqual(len(ziwei["palaces"]), 12)
        self.assertEqual(len(ziwei["flow_month"]["mutagens"]), 4)
        forecast = ziwei["flow_forecast"]
        self.assertEqual(forecast["starts_at"], report["query_datetime"])
        self.assertEqual(forecast["ends_at"], "2031-10-28T12:00:00+08:00")
        self.assertEqual(forecast["years"][0], ziwei["flow_year"])
        self.assertEqual(forecast["months"][0], ziwei["flow_month"])
        self.assertEqual(
            [period["gan_zhi"] for period in forecast["years"]],
            ["丙午", "丁未", "戊申", "己酉", "庚戌", "辛亥"],
        )
        self.assertTrue(
            any(s["mutagen"] is None for p in ziwei["palaces"] for s in p["major_stars"])
        )
        self.assertEqual(report["results"]["western"]["status"], "not_requested")
        self.assertEqual(raw, export_report_json((self.bazi, self.ziwei), generated_at=stamp))

    def test_ziwei_custom_range_keeps_both_leap_month_segments(self):
        single = json.loads(export_chart_json(self.ziwei, ziwei_years=(2, 5)))
        combined = json.loads(export_report_json((self.bazi, self.ziwei), ziwei_years=(2, 5)))
        forecast = single["results"]["ziwei"]["data"]["flow_forecast"]
        self.assertEqual(forecast, combined["results"]["ziwei"]["data"]["flow_forecast"])
        self.assertEqual(forecast["starts_at"], "2024-10-28T12:00:00+08:00")
        self.assertEqual(forecast["ends_at"], "2031-10-28T12:00:00+08:00")
        months = forecast["months"]
        self.assertEqual(
            [period["ends_at"] for period in months[:-1]],
            [period["starts_at"] for period in months[1:]],
        )
        self.assertEqual(
            [
                (period["starts_at"], period["ends_at"])
                for period in months
                if "2025-07-25" <= period["starts_at"] < "2025-08-23"
            ],
            [
                ("2025-07-25T00:00:00+08:00", "2025-08-09T00:00:00+08:00"),
                ("2025-08-09T00:00:00+08:00", "2025-08-23T00:00:00+08:00"),
            ],
        )
        self.assertLess(months[-1]["starts_at"], forecast["ends_at"])
        self.assertGreaterEqual(months[-1]["ends_at"], forecast["ends_at"])

    def test_ziwei_range_reports_birth_calendar_and_decade_limits(self):
        taipei = self.birth.place
        for local_birth, local_query, expected_end in (
            (datetime(2099, 4, 1, 12), datetime(2099, 12, 31, 12), "2100-01-01T00:00:00+08:00"),
            (datetime(1900, 1, 31), datetime(2022, 10, 1, 12), "2024-02-10T00:00:00+08:00"),
        ):
            with self.subTest(local_query=local_query):
                birth = BirthData(local_birth, taipei, "female")
                chart = calculate_ziwei(birth, local_query)
                report = json.loads(export_chart_json(chart, ziwei_years=(1, 5)))
                forecast = report["results"]["ziwei"]["data"]["flow_forecast"]
                self.assertEqual(forecast["ends_at"], expected_end)
                self.assertGreater(forecast["requested_ends_at"], expected_end)
                self.assertLess(forecast["months"][-1]["starts_at"], expected_end)
                self.assertGreaterEqual(forecast["months"][-1]["ends_at"], expected_end)
                if local_query.year == 2099:
                    self.assertEqual(forecast["starts_at"], birth.resolved_datetime.isoformat())
                    self.assertLess(forecast["requested_starts_at"], forecast["starts_at"])

    def test_ziwei_zero_years_keeps_the_current_periods(self):
        report = json.loads(export_chart_json(self.ziwei, ziwei_years=(0, 0)))
        data = report["results"]["ziwei"]["data"]
        self.assertEqual(data["flow_month"]["gan_zhi"], self.ziwei.flow_month.gan_zhi)
        forecast = data["flow_forecast"]
        self.assertEqual(forecast["starts_at"], forecast["ends_at"])
        self.assertEqual(forecast["years"], [])
        self.assertEqual(forecast["months"], [])
        with self.assertRaises(ValueError):
            export_chart_json(self.ziwei, ziwei_years=(-1, 5))

    def test_single_chart_and_partial_failure_are_distinct(self):
        single = json.loads(export_chart_json(self.bazi))
        self.assertEqual(single["results"]["ziwei"]["status"], "not_requested")
        partial = json.loads(
            export_report_json((self.bazi,), errors={"ziwei": "unsupported range"})
        )
        self.assertEqual(partial["results"]["ziwei"]["status"], "error")
        self.assertEqual(partial["errors"][0]["system"], "ziwei")
        self.assertEqual(partial["results"]["bazi"]["status"], "ok")

    def test_rejects_mixed_births_queries_duplicates_and_conflicting_errors(self):
        others = (
            replace(self.ziwei, query_datetime=self.ziwei.query_datetime + timedelta(seconds=1)),
            replace(self.ziwei, birth=replace(self.birth, gender="male")),
            self.bazi,
        )
        for other in others:
            with self.subTest(other=type(other).__name__), self.assertRaises(ValueError):
                export_report_json((self.bazi, other))
        with self.assertRaises(ValueError):
            export_report_json((self.bazi,), errors={"bazi": "conflicting status"})

    def test_rejects_empty_invalid_time_and_nonfinite_data(self):
        for charts in ((), (object(),)):
            with self.assertRaises(ValueError):
                export_report_json(charts)
        with self.assertRaises(ValueError):
            export_report_json((self.bazi,), generated_at=datetime(2026, 1, 1))
        invalid = replace(self.bazi, year=replace(self.bazi.year, elements=(float("nan"), "土")))
        with self.assertRaises(ValueError):
            export_chart_json(invalid)
