import json
import unittest
from datetime import UTC, datetime, timedelta
from itertools import pairwise

from destiny_calculator.export import export_chart_json
from destiny_calculator.heluo import (
    _hexagram,
    _later_heaven,
    _trigram,
    _yuan_tang,
    calculate_heluo,
)
from destiny_calculator.models import BirthData, BirthPlace
from destiny_calculator.timing import timing_window


class HeluoTests(unittest.TestCase):
    def setUp(self):
        self.taipei = BirthPlace("臺北", 25.03, 121.56, "Asia/Taipei")

    def test_classic_jia_zi_example(self):
        birth = BirthData(datetime(1984, 3, 27, 8), self.taipei, "male")
        chart = calculate_heluo(birth)
        self.assertEqual(chart.rule_version, "heluo-1929-v1")
        self.assertEqual(
            tuple(pillar.gan_zhi for pillar in chart.four_pillars), ("甲子", "丁卯", "庚申", "庚辰")
        )
        self.assertEqual((chart.heaven_number, chart.earth_number), (31, 34))
        first, later = chart.earlier_heaven, chart.later_heaven
        self.assertEqual((first.name, first.upper_trigram, first.lower_trigram), ("姤", "乾", "巽"))
        self.assertEqual((first.yuan_tang, first.line_name), (6, "上九"))
        self.assertEqual(first.lines, (False, True, True, True, True, True))
        self.assertEqual((later.name, later.upper_trigram, later.lower_trigram), ("中孚", "巽", "兌"))
        self.assertEqual((later.yuan_tang, later.line_name), (3, "六三"))

        major = [period for period in chart.periods if period.level == 1]
        annual = [period for period in chart.periods if period.level == 2]
        self.assertEqual(len(major), 12)
        self.assertEqual(len(annual), 99)
        self.assertEqual([period.label for period in major[:7]], [
            "先天 姤上九（虛歲 1–9）", "先天 姤初六（虛歲 10–15）", "先天 姤九二（虛歲 16–24）",
            "先天 姤九三（虛歲 25–33）", "先天 姤九四（虛歲 34–42）", "先天 姤九五（虛歲 43–51）",
            "後天 中孚六三（虛歲 52–57）",
        ])
        self.assertEqual([period.label.split()[1].split("（")[0] for period in annual[:9]], [
            "姤上九", "訟六三", "困上六", "兌初九", "隨六二", "革九三", "既濟六四", "明夷六五", "賁上九",
        ])
        self.assertEqual(annual[9].label, "癸酉 乾初九（虛歲 10）")
        self.assertEqual(annual[15].label, "己卯 遯六二（虛歲 16）")
        self.assertEqual(annual[16].label, "庚辰 旅六五（虛歲 17）")

    def test_timing_uses_local_lunar_new_year_and_half_open_periods(self):
        new_york = BirthPlace("紐約", 40.7, -74.0, "America/New_York")
        birth = BirthData(datetime(1984, 3, 27, 8), new_york, "male")
        chart = calculate_heluo(birth)
        major = [period for period in chart.periods if period.level == 1]
        annual = [period for period in chart.periods if period.level == 2]
        self.assertEqual(annual[0].starts_at, birth.resolved_datetime)
        self.assertEqual(annual[0].ends_at.isoformat(), "1985-02-20T00:00:00-05:00")
        for periods in (major, annual):
            for previous, following in pairwise(periods):
                self.assertEqual(previous.ends_at, following.starts_at)
        for beginning, following in ((annual[0], annual[1]), (major[0], major[1])):
            end = beginning.ends_at
            self.assertIn(beginning, timing_window(chart.periods, end - timedelta(seconds=1), (0, 0)).current)
            self.assertNotIn(beginning, timing_window(chart.periods, end, (0, 0)).current)
            self.assertIn(following, timing_window(chart.periods, end, (0, 0)).current)

    def test_report_exports_structured_hexagrams_and_ages(self):
        birth = BirthData(datetime(1984, 3, 27, 8), self.taipei, "male")
        report = json.loads(export_chart_json(calculate_heluo(birth), timing_years=(0, 2)))
        data = report["results"]["heluo"]["data"]
        current_major, current_annual = data["timing"]["current"]
        self.assertEqual(current_major["hexagram"], data["earlier_heaven"])
        self.assertEqual(current_major["phase"], "earlier")
        self.assertEqual((current_major["start_age"], current_major["end_age"]), (1, 9))
        self.assertIsNone(current_major["year_gan_zhi"])
        self.assertEqual(current_annual["year_gan_zhi"], "甲子")
        self.assertEqual((current_annual["start_age"], current_annual["end_age"]), (1, 1))
        second_annual = next(
            p for p in data["timing"]["periods"] if p["level"] == 2 and p["start_age"] == 2
        )
        hexagram = second_annual["hexagram"]
        self.assertEqual((hexagram["name"], hexagram["yuan_tang"], hexagram["line_name"]), ("訟", 3, "六三"))

    def test_center_number_pure_hexagrams_and_seasonal_exceptions(self):
        self.assertEqual(_trigram(25, 25, "艮"), 4)
        self.assertEqual(_trigram(35, 25, "艮"), 2)
        self.assertEqual(_trigram(30, 30, "艮"), 1)
        self.assertEqual(_trigram(55, 30, "兌"), 3)

        for bits, gender, before, after in ((63, "female", 5, 0), (0, "male", 0, 5)):
            before_solstice = BirthData(datetime(1984, 6, 21, 13, 2), self.taipei, gender)
            after_solstice = BirthData(datetime(1984, 6, 21, 13, 3), self.taipei, gender)
            with self.subTest(bits=bits):
                self.assertEqual(_yuan_tang(bits, 0, before_solstice), before)
                self.assertEqual(_yuan_tang(bits, 0, after_solstice), after)

        for bits, fifth_odd, fifth_even, top_odd, top_even in (
            (18, "比", "師", "渙", "井"),
            (17, "豫", "復", "益", "恆"),
            (20, "剝", "謙", "漸", "蠱"),
        ):
            for line, month, expected_name in (
                (4, 1, fifth_odd), (4, 2, fifth_even), (5, 1, top_odd), (5, 2, top_even)
            ):
                with self.subTest(bits=bits, line=line, month=month):
                    self.assertEqual(_hexagram(*_later_heaven(bits, line, month)).name, expected_name)

    def test_classic_yuan_tang_line_sequences(self):
        birth = BirthData(datetime(1984, 3, 27, 8), self.taipei, "male")
        for bits, first_branch, expected in (
            (2, 0, (2, 2, 1, 3, 4, 5)),
            (57, 6, (2, 3, 2, 3, 1, 4)),
            (44, 0, (3, 4, 6, 3, 4, 6)),
            (9, 6, (2, 3, 5, 6, 1, 4)),
            (61, 0, (1, 3, 4, 5, 6, 2)),
        ):
            with self.subTest(bits=bits):
                branches = range(first_branch, first_branch + 6)
                result = tuple(_yuan_tang(bits, branch, birth) + 1 for branch in branches)
                self.assertEqual(result, expected)

    def test_birth_range_limits_and_fold(self):
        new_york = BirthPlace("紐約", 40.7, -74.0, "America/New_York")
        for birth, end_date in (
            (BirthData(datetime(1900, 1, 1), self.taipei, "male"), "1900-01-31"),
            (BirthData(datetime(2099, 12, 31, 23, 59), self.taipei, "female"), "2100-02-09"),
            (BirthData(datetime(2025, 11, 2, 1, 30), new_york, "female", fold=1), "2026-02-17"),
        ):
            with self.subTest(birth=birth):
                chart = calculate_heluo(birth)
                annual = next(period for period in chart.periods if period.level == 2)
                self.assertEqual(annual.starts_at.astimezone(UTC), birth.utc_datetime)
                self.assertEqual(annual.ends_at.date().isoformat(), end_date)


if __name__ == "__main__":
    unittest.main()
