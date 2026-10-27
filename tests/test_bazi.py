import unittest
from datetime import UTC, datetime, timedelta

from destiny_calculator import (
    AmbiguousTimeError,
    BirthData,
    BirthPlace,
    NonexistentTimeError,
    calculate_bazi,
    get_city,
)


class BaziTests(unittest.TestCase):
    def setUp(self):
        self.taipei = get_city("臺北")
        self.birth = BirthData(datetime(2000, 8, 16, 4), self.taipei, "female")

    def test_reference_b01_four_pillars(self):
        birth = BirthData(datetime(2005, 12, 23, 8, 37), self.taipei, "male")
        chart = calculate_bazi(birth, birth.local_datetime)
        self.assertEqual(
            tuple(p.gan_zhi for p in (chart.year, chart.month, chart.day, chart.hour)),
            ("乙酉", "戊子", "辛巳", "壬辰"),
        )

    def test_reference_b02_late_zi_hour_keeps_day_and_time_pair(self):
        birth = BirthData(datetime(1988, 2, 15, 23, 30), self.taipei, "male")
        chart = calculate_bazi(birth, birth.local_datetime)
        self.assertEqual(
            tuple(p.gan_zhi for p in (chart.year, chart.month, chart.day, chart.hour)),
            ("戊辰", "甲寅", "庚子", "戊子"),
        )

    def test_reference_b03_minute_based_luck_start(self):
        birth = BirthData(datetime(2022, 3, 9, 20, 51), self.taipei, "male")
        chart = calculate_bazi(birth, birth.local_datetime)
        self.assertEqual(chart.luck_start_offset, (8, 9, 2, 10))
        self.assertEqual(chart.luck_starts_at.isoformat(), "2030-12-12T06:51:00+08:00")
        self.assertTrue(chart.luck_forward)
        self.assertIsNone(chart.current_luck)

    def test_example_details_and_current_periods(self):
        chart = calculate_bazi(self.birth, datetime(2026, 10, 28, 12))
        self.assertEqual(
            tuple(p.gan_zhi for p in (chart.year, chart.month, chart.day, chart.hour)),
            ("庚辰", "甲申", "丙午", "庚寅"),
        )
        self.assertEqual(chart.year.hidden_stems, ("戊", "乙", "癸"))
        self.assertEqual(chart.year.elements, ("金", "土"))
        self.assertEqual(chart.year.stem_ten_god, "偏財")
        self.assertEqual(chart.year.hidden_ten_gods, ("食神", "正印", "正官"))
        self.assertEqual(chart.month.hidden_ten_gods, ("偏財", "七殺", "食神"))
        self.assertEqual(chart.day.hidden_ten_gods, ("劫財", "傷官"))
        self.assertFalse(chart.luck_forward)
        self.assertEqual(chart.luck_starts_at.isoformat(), "2003-07-01T00:00:00+08:00")
        self.assertEqual(chart.current_luck.pillar.gan_zhi, "辛巳")
        self.assertEqual(chart.current_luck.starts_at.isoformat(), "2023-07-01T00:00:00+08:00")
        self.assertEqual(chart.flow_year.pillar.gan_zhi, "丙午")
        self.assertEqual(chart.flow_month.pillar.gan_zhi, "戊戌")
        self.assertEqual(chart.flow_month.starts_at.isoformat(), "2026-10-08T14:29:17+08:00")
        self.assertEqual(chart.flow_month.ends_at.isoformat(), "2026-11-07T17:52:05+08:00")
        self.assertEqual(chart.engine_version, "1.4.8")
        self.assertEqual(chart.rules_version, "bazi-v1")

    def test_spring_boundary_changes_year_and_month_at_exact_second(self):
        before = calculate_bazi(self.birth, datetime(2026, 2, 4, 4, 2, 7))
        after = calculate_bazi(self.birth, datetime(2026, 2, 4, 4, 2, 8))
        self.assertEqual((before.flow_year.pillar.gan_zhi, before.flow_month.pillar.gan_zhi), ("乙巳", "己丑"))
        self.assertEqual((after.flow_year.pillar.gan_zhi, after.flow_month.pillar.gan_zhi), ("丙午", "庚寅"))
        self.assertEqual(before.flow_year.ends_at, after.flow_year.starts_at)
        self.assertEqual(before.flow_month.ends_at, after.flow_month.starts_at)

    def test_natal_year_and_month_use_instant_not_local_solar_term_clock(self):
        place = BirthPlace("New York", 40.7, -74.0, "America/New_York")
        before = BirthData(datetime(2026, 2, 3, 15, 2), place, "male")
        after = BirthData(datetime(2026, 2, 3, 15, 3), place, "male")
        first = calculate_bazi(before, before.local_datetime)
        second = calculate_bazi(after, after.local_datetime)
        self.assertEqual((first.year.gan_zhi, first.month.gan_zhi), ("乙巳", "己丑"))
        self.assertEqual((second.year.gan_zhi, second.month.gan_zhi), ("丙午", "庚寅"))

    def test_overseas_civil_day_and_hour_stay_local(self):
        taipei = BirthData(datetime(2005, 12, 23, 8, 37), self.taipei, "male")
        new_york = BirthData(
            datetime(2005, 12, 22, 19, 37),
            BirthPlace("New York", 40.7, -74.0, "America/New_York"),
            "male",
        )
        self.assertEqual(taipei.utc_datetime, new_york.utc_datetime)
        first = calculate_bazi(taipei, taipei.local_datetime)
        second = calculate_bazi(new_york, new_york.local_datetime)
        self.assertEqual((second.year.gan_zhi, second.month.gan_zhi), ("乙酉", "戊子"))
        self.assertEqual((second.day.gan_zhi, second.hour.gan_zhi), ("庚辰", "丙戌"))
        self.assertEqual(first.luck_starts_at.astimezone(UTC), second.luck_starts_at.astimezone(UTC))

    def test_overseas_flow_boundaries_represent_same_instants(self):
        taipei = calculate_bazi(self.birth, datetime(2026, 2, 4, 4, 2, 8))
        new_york_birth = BirthData(
            datetime(2000, 8, 15, 16),
            BirthPlace("New York", 40.7, -74.0, "America/New_York"),
            "female",
        )
        new_york = calculate_bazi(new_york_birth, datetime(2026, 2, 3, 15, 2, 8))
        self.assertEqual(taipei.flow_year.pillar.gan_zhi, new_york.flow_year.pillar.gan_zhi)
        self.assertEqual(taipei.flow_month.pillar.gan_zhi, new_york.flow_month.pillar.gan_zhi)
        self.assertEqual(taipei.flow_year.starts_at.astimezone(UTC), new_york.flow_year.starts_at.astimezone(UTC))
        self.assertEqual(taipei.flow_month.starts_at.astimezone(UTC), new_york.flow_month.starts_at.astimezone(UTC))

    def test_luck_period_changes_on_start_instant_not_january_first(self):
        before = calculate_bazi(self.birth, datetime(2023, 6, 30, 23, 59, 59))
        after = calculate_bazi(self.birth, datetime(2023, 7, 1))
        self.assertEqual(before.current_luck.pillar.gan_zhi, "壬午")
        self.assertEqual(after.current_luck.pillar.gan_zhi, "辛巳")
        self.assertEqual(before.current_luck.ends_at, after.current_luck.starts_at)

    def test_first_luck_start_is_inclusive(self):
        first = calculate_bazi(self.birth, datetime(2003, 7, 1))
        before = calculate_bazi(self.birth, datetime(2003, 6, 30, 23, 59, 59))
        self.assertEqual(first.current_luck.pillar.gan_zhi, "癸未")
        self.assertIsNone(before.current_luck)

    def test_date_range_and_long_luck_horizon(self):
        for local in (datetime(1900, 1, 1), datetime(2099, 12, 31, 23, 59)):
            with self.subTest(local=local):
                birth = BirthData(local, self.taipei, "female")
                chart = calculate_bazi(birth, local)
                instant = chart.query_datetime.astimezone(UTC)
                for period in (chart.flow_year, chart.flow_month):
                    self.assertLessEqual(period.starts_at.astimezone(UTC), instant)
                    self.assertGreater(period.ends_at.astimezone(UTC), instant)
        birth = BirthData(datetime(1900, 1, 1), self.taipei, "female")
        chart = calculate_bazi(birth, datetime(2099, 12, 31, 23, 59))
        self.assertIsNotNone(chart.current_luck)
        for first, second in zip(chart.luck_periods, chart.luck_periods[1:]):
            self.assertEqual(first.ends_at, second.starts_at)

    def test_query_validation_and_fold_are_preserved(self):
        with self.assertRaises(ValueError):
            calculate_bazi(None)
        with self.assertRaises(ValueError):
            calculate_bazi(self.birth, datetime(1999, 1, 1))
        birth = BirthData(
            datetime(2000, 8, 16, 4),
            BirthPlace("New York", 40.7, -74.0, "America/New_York"),
            "female",
        )
        with self.assertRaises(AmbiguousTimeError):
            calculate_bazi(birth, datetime(2024, 11, 3, 1, 30))
        with self.assertRaises(NonexistentTimeError):
            calculate_bazi(birth, datetime(2024, 3, 10, 2, 30))
        chart = calculate_bazi(birth, datetime(2024, 11, 3, 1, 30), fold=1)
        self.assertEqual(chart.query_datetime.fold, 1)
        self.assertEqual(chart.query_datetime.astimezone(UTC), datetime(2024, 11, 3, 6, 30, tzinfo=UTC))


if __name__ == "__main__":
    unittest.main()
