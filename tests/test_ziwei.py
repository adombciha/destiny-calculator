import unittest
from dataclasses import FrozenInstanceError, asdict
from datetime import UTC, datetime
from unittest.mock import patch

from izthon.astro import by_solar, get_config, reset_config, set_config

from destiny_calculator import (
    AmbiguousTimeError,
    BirthData,
    BirthPlace,
    NonexistentTimeError,
    calculate_ziwei,
    get_city,
)


class ZiweiTests(unittest.TestCase):
    def setUp(self):
        self.taipei = get_city("臺北")
        self.birth = BirthData(datetime(2000, 8, 16, 4), self.taipei, "female")

    def test_reference_z01_natal_chart(self):
        chart = calculate_ziwei(self.birth, datetime(2023, 8, 19, 3, 12))
        self.assertEqual(chart.lunar_date, "二〇〇〇年七月十七")
        # The reference profile takes the soul star from the birth-year branch.
        self.assertEqual((chart.soul, chart.body, chart.five_elements_class), ("廉貞", "文昌", "木三局"))
        soul = next(p for p in chart.palaces if p.name == "命宮")
        body = next(p for p in chart.palaces if p.is_body_palace)
        self.assertEqual((soul.gan_zhi, body.gan_zhi), ("壬午", "丙戌"))
        self.assertEqual(soul.decadal_age_range, (3, 12))
        self.assertEqual(
            [(p.gan_zhi[-1], tuple(s.name for s in p.major_stars)) for p in chart.palaces],
            [
                ("寅", ("武曲", "天相")), ("卯", ("太陽", "天梁")),
                ("辰", ("七殺",)), ("巳", ("天機",)), ("午", ("紫微",)),
                ("未", ()), ("申", ("破軍",)), ("酉", ()),
                ("戌", ("廉貞", "天府")), ("亥", ("太陰",)),
                ("子", ("貪狼",)), ("丑", ("天同", "巨門")),
            ],
        )
        mutagens = {
            s.mutagen: s.name
            for p in chart.palaces for s in (*p.major_stars, *p.minor_stars)
            if s.mutagen
        }
        self.assertEqual(mutagens, {"祿": "太陽", "權": "武曲", "科": "太陰", "忌": "天同"})
        self.assertEqual(chart.engine_version, "0.2.0")
        self.assertEqual(chart.rules_version, "ziwei-reference-v2")

    def test_reference_z02_flows(self):
        chart = calculate_ziwei(self.birth, datetime(2023, 8, 19, 3, 12))
        self.assertEqual(chart.nominal_age, 24)
        self.assertFalse(chart.is_childhood)
        self.assertEqual((chart.current_luck.index, chart.current_luck.gan_zhi), (2, "庚辰"))
        self.assertEqual((chart.flow_year.index, chart.flow_year.gan_zhi), (1, "癸卯"))
        self.assertEqual((chart.flow_month.index, chart.flow_month.gan_zhi), (3, "庚申"))
        self.assertEqual(chart.flow_month.starts_at.isoformat(), "2023-08-16T00:00:00+08:00")
        self.assertEqual(chart.flow_month.ends_at.isoformat(), "2023-09-15T00:00:00+08:00")
        self.assertEqual(chart.flow_year.mutagens, ("破軍", "巨門", "太陰", "貪狼"))
        for cycle in (chart.current_luck, chart.flow_year, chart.flow_month):
            self.assertEqual(len(cycle.palace_names), 12)
            self.assertEqual(cycle.palace_names[cycle.index], "命宮")
            self.assertEqual(len(cycle.stars), 12)
            self.assertTrue(any(cycle.stars))

    def test_corrected_you_palace_brightness(self):
        cases = (
            (datetime(2005, 12, 23, 5, 30), "太陽", "平"),
            (datetime(2005, 12, 23, 1, 30), "太陰", "旺"),
            (datetime(2023, 3, 22), "七殺", "旺"),
        )
        for local, name, brightness in cases:
            with self.subTest(star=name):
                birth = BirthData(local, self.taipei, "female")
                chart = calculate_ziwei(birth, local)
                palace = next(p for p in chart.palaces if p.gan_zhi[-1] == "酉")
                star = next(s for s in palace.major_stars if s.name == name)
                self.assertEqual(star.brightness, brightness)

    def test_unverified_brightness_is_not_invented(self):
        chart = calculate_ziwei(self.birth, self.birth.local_datetime)
        left = next(s for p in chart.palaces for s in p.minor_stars if s.name == "左輔")
        self.assertEqual(left.brightness, "廟")
        ungraded = {s.name: s for p in chart.palaces for s in p.adjective_stars if s.name in {"天巫", "天廚", "陰煞", "封誥", "臺輔", "月德", "蜚廉", "龍德", "劫煞"}}
        self.assertTrue(all(s.brightness is None for s in ungraded.values()))
        with self.assertRaises(FrozenInstanceError):
            left.brightness = "廟"
        self.assertEqual(len(asdict(chart)["palaces"]), 12)

    def test_lunar_new_year_changes_year_age_and_month_at_midnight(self):
        before = calculate_ziwei(self.birth, datetime(2025, 1, 28, 23, 59, 59))
        after = calculate_ziwei(self.birth, datetime(2025, 1, 29))
        self.assertEqual((before.flow_year.gan_zhi, after.flow_year.gan_zhi), ("甲辰", "乙巳"))
        self.assertEqual((before.nominal_age, after.nominal_age), (25, 26))
        self.assertEqual((before.flow_month.gan_zhi, after.flow_month.gan_zhi), ("丁丑", "戊寅"))
        self.assertEqual(before.flow_year.ends_at, after.flow_year.starts_at)
        self.assertEqual(before.flow_month.ends_at, after.flow_month.starts_at)

    def test_regular_month_boundary(self):
        before = calculate_ziwei(self.birth, datetime(2023, 8, 15, 23, 59, 59))
        after = calculate_ziwei(self.birth, datetime(2023, 8, 16))
        self.assertEqual((before.flow_month.index, after.flow_month.index), (2, 3))
        self.assertEqual((before.flow_month.gan_zhi, after.flow_month.gan_zhi), ("己未", "庚申"))
        self.assertEqual(before.flow_month.ends_at, after.flow_month.starts_at)

    def test_leap_month_has_two_intervals(self):
        first = calculate_ziwei(self.birth, datetime(2025, 7, 25))
        before = calculate_ziwei(self.birth, datetime(2025, 8, 8, 23, 59, 59))
        after = calculate_ziwei(self.birth, datetime(2025, 8, 9))
        next_month = calculate_ziwei(self.birth, datetime(2025, 8, 23))
        self.assertIn("閏六月十五", before.query_lunar_date)
        self.assertEqual((first.flow_month.index, before.flow_month.index), (4, 4))
        self.assertEqual((before.flow_month.gan_zhi, after.flow_month.gan_zhi), ("癸未", "甲申"))
        self.assertEqual(after.flow_month.index, 5)
        self.assertEqual(first.flow_month.starts_at.isoformat(), "2025-07-25T00:00:00+08:00")
        self.assertEqual(before.flow_month.ends_at, after.flow_month.starts_at)
        self.assertEqual(after.flow_month.ends_at, next_month.flow_month.starts_at)

    def test_childhood_and_first_decade(self):
        before = calculate_ziwei(self.birth, datetime(2002, 2, 11, 23, 59))
        after = calculate_ziwei(self.birth, datetime(2002, 2, 12))
        self.assertTrue(before.is_childhood)
        self.assertEqual(before.nominal_age, 2)
        self.assertEqual(before.current_luck.index, 0)
        self.assertFalse(after.is_childhood)
        self.assertEqual(after.nominal_age, 3)
        self.assertEqual(after.current_luck.index, 4)

    def test_decade_changes_with_nominal_age(self):
        before = calculate_ziwei(self.birth, datetime(2022, 1, 31, 23, 59))
        after = calculate_ziwei(self.birth, datetime(2022, 2, 1))
        self.assertEqual((before.nominal_age, after.nominal_age), (22, 23))
        self.assertEqual((before.current_luck.index, after.current_luck.index), (3, 2))

    def test_time_branch_boundary_and_late_zi_day(self):
        charts = []
        for local in (datetime(2000, 8, 16, 22, 59), datetime(2000, 8, 16, 23), datetime(2000, 8, 17)):
            birth = BirthData(local, self.taipei, "female")
            charts.append(calculate_ziwei(birth, local))
        placements = [[p.major_stars for p in chart.palaces] for chart in charts]
        self.assertNotEqual(placements[0], placements[1])
        self.assertEqual(placements[1], placements[2])

    def test_leap_birth_after_fifteenth_and_late_zi_exception(self):
        charts = []
        for local in (
            datetime(2023, 4, 5, 12), datetime(2023, 4, 6, 12),
            datetime(2023, 4, 5, 23), datetime(2023, 4, 6, 23),
        ):
            birth = BirthData(local, self.taipei, "female")
            chart = calculate_ziwei(birth, local)
            charts.append(next(p.gan_zhi for p in chart.palaces if p.name == "命宮"))
        self.assertEqual(charts[2], charts[3])
        self.assertNotEqual(charts[0], charts[1])

    def test_birth_date_range_and_long_query_rejection(self):
        birth = BirthData(datetime(1900, 1, 30), self.taipei, "female")
        with self.assertRaisesRegex(ValueError, "1900-01-31"):
            calculate_ziwei(birth, birth.local_datetime)
        for local in (datetime(1900, 1, 31), datetime(2099, 12, 31, 23, 59)):
            with self.subTest(local=local):
                birth = BirthData(local, self.taipei, "female")
                chart = calculate_ziwei(birth, local)
                instant = chart.query_datetime.astimezone(UTC)
                for period in (chart.flow_year, chart.flow_month):
                    self.assertLessEqual(period.starts_at.astimezone(UTC), instant)
                    self.assertGreater(period.ends_at.astimezone(UTC), instant)
        birth = BirthData(datetime(1900, 1, 31), self.taipei, "female")
        with self.assertRaisesRegex(ValueError, "twelve decadal cycles"):
            calculate_ziwei(birth, datetime(2099, 12, 31))

    def test_query_validation_and_dst_fold(self):
        with self.assertRaises(ValueError):
            calculate_ziwei(None)
        with self.assertRaises(ValueError):
            calculate_ziwei(self.birth, datetime(1999, 1, 1))
        birth = BirthData(
            datetime(2000, 8, 16, 4),
            BirthPlace("New York", 40.7, -74, "America/New_York"),
            "female",
        )
        with self.assertRaises(AmbiguousTimeError):
            calculate_ziwei(birth, datetime(2024, 11, 3, 1, 30))
        with self.assertRaises(NonexistentTimeError):
            calculate_ziwei(birth, datetime(2024, 3, 10, 2, 30))
        first = calculate_ziwei(birth, datetime(2024, 11, 3, 1, 30), fold=0)
        second = calculate_ziwei(birth, datetime(2024, 11, 3, 1, 30), fold=1)
        self.assertEqual(second.query_datetime.astimezone(UTC), datetime(2024, 11, 3, 6, 30, tzinfo=UTC))
        self.assertEqual(first.flow_month, second.flow_month)
        self.assertEqual(second.flow_month.starts_at.utcoffset().total_seconds(), -4 * 3600)
        self.assertEqual(second.flow_month.ends_at.utcoffset().total_seconds(), -5 * 3600)

    def test_default_query_uses_birth_timezone(self):
        fixed = datetime(2026, 10, 28, 12, tzinfo=UTC)
        with patch("destiny_calculator.models.datetime") as clock:
            clock.now.return_value = fixed
            chart = calculate_ziwei(self.birth)
        self.assertEqual(chart.query_datetime.isoformat(), "2026-10-28T20:00:00+08:00")

    def test_rules_are_isolated_from_external_engine_configuration(self):
        original = get_config()
        self.addCleanup(set_config, original)
        self.addCleanup(reset_config)
        set_config({
            "algorithm": "zhongzhou", "year_divide": "exact", "horoscope_divide": "exact",
            "age_divide": "birthday", "day_divide": "current",
            "mutagens": {"庚": ["紫微", "天機", "太陽", "武曲"]},
            "brightness": {"紫微": ["陷"] * 12, "左輔": ["陷"] * 12},
        })
        external = get_config()
        chart = calculate_ziwei(self.birth, datetime(2025, 1, 29))
        soul = next(p for p in chart.palaces if p.name == "命宮")
        self.assertEqual(soul.major_stars[0].brightness, "廟")
        self.assertEqual(chart.flow_year.gan_zhi, "乙巳")
        left = next(s for p in chart.palaces for s in p.minor_stars if s.name == "左輔")
        self.assertEqual(left.brightness, "廟")
        sun = next(s for p in chart.palaces for s in p.major_stars if s.name == "太陽")
        self.assertEqual(sun.mutagen, "祿")
        self.assertEqual(get_config(), external)

    def test_reference_empty_star_pairs_and_year_branch_stars(self):
        chart = calculate_ziwei(self.birth, self.birth.local_datetime)
        locations = {
            s.name: (p.gan_zhi[-1], s.brightness)
            for p in chart.palaces for s in p.adjective_stars
        }
        self.assertEqual(locations["截空"], ("午", "廟"))
        self.assertEqual(locations["副截"], ("未", "廟"))
        self.assertEqual(locations["旬空"], ("申", "廟"))
        self.assertEqual(locations["副旬"], ("酉", "廟"))
        self.assertEqual(locations["大耗"], ("亥", "陷"))
        self.assertEqual(locations["龍德"], ("亥", None))
        self.assertEqual(locations["劫煞"], ("巳", None))
        self.assertNotIn("截路", locations)
        self.assertNotIn("空亡", locations)

    def test_empty_star_polarities_across_sexagenary_cycle(self):
        for year in range(1940, 2000):
            with self.subTest(year=year):
                birth = BirthData(datetime(year, 7, 1, 12), self.taipei, "male")
                chart = calculate_ziwei(birth, birth.local_datetime)
                locations = {
                    s.name: "子丑寅卯辰巳午未申酉戌亥".index(p.gan_zhi[-1])
                    for p in chart.palaces for s in p.adjective_stars
                    if s.name in {"截空", "副截", "旬空", "副旬"}
                }
                self.assertEqual(len(locations), 4)
                self.assertEqual(locations["截空"] % 2, (year - 4) % 2)
                self.assertEqual(locations["旬空"] % 2, (year - 4) % 2)
                self.assertEqual(locations["截空"] // 2, locations["副截"] // 2)
                self.assertEqual(locations["旬空"] // 2, locations["副旬"] // 2)
                natal = by_solar(f"{year}-7-1", 6, "男", language="zh-TW", config={"algorithm": "zhongzhou", "year_divide": "normal"})
                primary = next(p.earthly_branch for p in natal.palaces if any(s.name == "截空" for s in p.adjective_stars))
                self.assertEqual(locations["截空"], "子丑寅卯辰巳午未申酉戌亥".index(primary))

    def test_yearly_ages_zi_dou_and_display_names(self):
        chart = calculate_ziwei(self.birth, datetime(2020, 1, 25, 12))
        self.assertEqual(chart.zi_dou, "申")
        self.assertEqual(chart.palaces[chart.flow_month.index].gan_zhi[-1], chart.zi_dou)
        self.assertEqual(chart.palaces[2].yearly_ages[:5], (1, 13, 25, 37, 49))
        self.assertEqual(sorted(age for p in chart.palaces for age in p.yearly_ages), list(range(1, 121)))
        self.assertEqual(next(p for p in chart.palaces if p.name == "交友").gan_zhi, "丁亥")
        self.assertIn("交友", chart.flow_year.palace_names)
        self.assertNotIn("僕役", chart.flow_year.palace_names)
        self.assertEqual(next(p for p in chart.palaces if p.gan_zhi[-1] == "戌").suiqian_12, "歲破")

    def test_calibration_table_uses_canonical_traditional_names(self):
        from destiny_calculator.ziwei import BRIGHTNESS_DATA, DISPLAY_NAMES

        natal = by_solar("2000-8-16", 2, "女", language="zh-TW")
        names = {
            DISPLAY_NAMES.get(s.name, s.name)
            for p in natal.palaces for s in (*p.major_stars, *p.minor_stars, *p.adjective_stars)
        } | {"截空", "副截", "副旬", "大耗"}
        for name, row in BRIGHTNESS_DATA["brightness"].items():
            with self.subTest(star=name):
                self.assertIn(name, names)
                self.assertEqual(len(row), 12)
                self.assertTrue(all(type(value) is int and 0 <= value <= 7 for value in row))
        self.assertIn("MIT License", BRIGHTNESS_DATA["license"])
