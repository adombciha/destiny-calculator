import importlib.util
import json
import unittest
from datetime import datetime, timedelta
from itertools import pairwise
from math import nextafter
from pathlib import Path

from destiny_calculator import BirthData, BirthPlace, get_city
from destiny_calculator.qizheng import (
    _MANSION_SPANS,
    _mansion,
    _ming_longitude,
    _palace,
    _timing_periods,
    _ziqi_longitude,
    calculate_qizheng,
)
from destiny_calculator.timing import timing_window

EPHEMERIS = Path(__file__).resolve().parents[1] / "data" / "ephemeris"
HAS_WESTERN = importlib.util.find_spec("swisseph") is not None and all(
    (EPHEMERIS / name).is_file() for name in ("sepl_18.se1", "semo_18.se1")
)


class QizhengRuleTests(unittest.TestCase):
    def test_historical_ecliptic_boundaries_include_wrap_and_narrow_mansions(self):
        self.assertEqual(len(_MANSION_SPANS), 28)
        self.assertEqual(len({span.name for span in _MANSION_SPANS}), 28)
        self.assertAlmostEqual(
            sum((span.end_longitude - span.start_longitude) % 360 for span in _MANSION_SPANS), 360
        )
        for previous, span in pairwise((_MANSION_SPANS[-1], *_MANSION_SPANS)):
            with self.subTest(mansion=span.name):
                self.assertEqual(previous.end_longitude, span.start_longitude)
                self.assertEqual(_mansion(span.start_longitude), (span.name, 0))
                self.assertEqual(_mansion(nextafter(span.start_longitude, 0))[0], previous.name)
        self.assertEqual(_mansion(0)[0], "室")
        self.assertAlmostEqual(_mansion(0)[1], 11 + 40 / 60)
        self.assertEqual(_mansion(198 + 39 / 60), ("角", 0))
        self.assertEqual(_mansion(77 + 14 / 60), ("參", 0))

    def test_qi_uses_niu_epoch_and_full_cycle(self):
        self.assertAlmostEqual(_ziqi_longitude(2280289.5), 284.58)
        self.assertAlmostEqual(_ziqi_longitude(2280289.5 + 10228 / 2), 104.58)
        self.assertAlmostEqual(_ziqi_longitude(2280289.5 - 10228), 284.58)

    def test_classical_ming_palace_and_minor_limit_examples(self):
        self.assertEqual(_palace(_ming_longitude(324, 9)), "午")
        birth = BirthData(datetime(1984, 7, 1, 12), get_city("臺北"), "female")
        periods = _timing_periods(birth.resolved_datetime, 243, "甲子")
        first = next(period for period in periods if period.level == 2 and period.age == 1)
        fifth = next(period for period in periods if period.level == 2 and period.age == 5)
        self.assertEqual((first.palace, first.directed_longitude, first.year_ganzhi), ("寅", 243, "甲子"))
        self.assertEqual((fifth.palace, fifth.year_ganzhi), ("戌", "戊辰"))
        # Renchen is the 29th sexagenary year after a Jiazi birth counted inclusively.
        renchen = next(period for period in periods if period.level == 2 and period.year_ganzhi == "壬辰")
        self.assertEqual((renchen.palace, renchen.age), ("戌", 29))

    def test_limit_transition_at_exact_birthday_and_half_year(self):
        birth = BirthData(datetime(2000, 2, 29, 12), get_city("臺北"), "female")
        periods = _timing_periods(birth.resolved_datetime, 112, "庚辰")
        major = [period for period in periods if period.level == 1]
        annual = [period for period in periods if period.level == 2]
        for layer in (major, annual):
            self.assertEqual(layer[0].starts_at, birth.resolved_datetime)
            self.assertTrue(all(left.ends_at == right.starts_at for left, right in pairwise(layer)))
        self.assertEqual(annual[1].starts_at.isoformat(), "2001-02-28T12:00:00+08:00")
        start = major[17].starts_at
        self.assertEqual((major[17].palace, major[17].house), ("申", "相貌"))
        self.assertEqual(annual[17].starts_at, start)
        self.assertEqual((annual[17].directed_palace, annual[17].directed_longitude), ("申", 90))
        before = timing_window(periods, start - timedelta(seconds=1), (0, 0)).current
        after = timing_window(periods, start, (0, 0)).current
        self.assertEqual(before, (major[16], annual[16]))
        self.assertEqual(after, (major[17], annual[17]))
        servants = next(period for period in major if period.house == "奴僕" and period.label.startswith("大限"))
        self.assertEqual(servants.ends_at.month, 8)
        self.assertEqual(servants.ends_at.day, 29)

    def test_latest_supported_birth_has_minor_limits_through_major_cycle(self):
        birth = BirthData(datetime(2099, 8, 16, 4), get_city("臺北"), "female")
        periods = _timing_periods(birth.resolved_datetime, 112, "己未")
        major = [period for period in periods if period.level == 1]
        annual = [period for period in periods if period.level == 2]
        self.assertGreaterEqual(annual[-1].ends_at, major[-1].ends_at)
        self.assertEqual(annual[5].starts_at.isoformat(), "2104-08-16T04:00:00+08:00")
        self.assertEqual(annual[5].year_ganzhi, "甲子")
        self.assertIsNotNone(annual[5].directed_longitude)


@unittest.skipUnless(HAS_WESTERN, "Install the western extra and pinned ephemeris data.")
class QizhengEphemerisTests(unittest.TestCase):
    def test_natal_positions_and_transformation_reference(self):
        birth = BirthData(datetime(2000, 8, 16, 4), get_city("臺北"), "female")
        chart = calculate_qizheng(birth, ephemeris_path=EPHEMERIS)
        reference = json.loads(
            Path(__file__).with_name("fixtures").joinpath("western_reference.json").read_text()
        )
        self.assertEqual(chart.ephemeris_revision, reference["ephemeris_revision"])
        for luminary, vector in zip(chart.luminaries[:7], reference["planet_vectors"]):
            self.assertAlmostEqual(luminary.longitude, vector[0], places=8)
            self.assertAlmostEqual(luminary.longitude_speed, vector[3], places=8)
        self.assertEqual(len(chart.luminaries), 11)
        rahu, ketu, ziqi, yuebei = chart.luminaries[-4:]
        self.assertEqual(tuple(body.code for body in (rahu, ketu, ziqi, yuebei)), ("RAHU", "KETU", "ZIQI", "YUEBEI"))
        self.assertAlmostEqual((ketu.longitude - rahu.longitude) % 360, 180)
        # Direct calls to the native Swiss Ephemeris ABI at the fixture's TT epoch.
        self.assertAlmostEqual(rahu.longitude, 113.00228062016751, places=8)
        self.assertAlmostEqual(yuebei.longitude, 288.6923518070998, places=8)
        self.assertEqual((chart.birth_year_ganzhi, chart.birth_hour_branch), ("庚辰", "寅"))
        self.assertEqual((chart.ming_palace, chart.ming_mansion), ("未", "井"))
        self.assertAlmostEqual(chart.ming_longitude, reference["planet_vectors"][0][0] - 30, places=8)
        self.assertEqual(tuple(rule.luminary_code for rule in chart.transformations), (
            "MERCURY", "ZIQI", "KETU", "RAHU", "MARS", "YUEBEI", "JUPITER", "VENUS", "SATURN", "MOON",
        ))

    def test_longitude_and_solar_term_apply_to_birth_instant(self):
        new_york = BirthPlace("New York", 40.7, -74, "America/New_York")
        taipei = BirthData(datetime(2000, 8, 16, 4), get_city("臺北"), "female")
        new_york_birth = BirthData(datetime(2000, 8, 15, 16), new_york, "female")
        first = calculate_qizheng(taipei, ephemeris_path=EPHEMERIS)
        second = calculate_qizheng(new_york_birth, ephemeris_path=EPHEMERIS)
        self.assertEqual(first.luminaries, second.luminaries)
        self.assertNotEqual(first.ming_palace, second.ming_palace)
        for minute, ganzhi in ((2, "乙巳"), (3, "丙午")):
            birth = BirthData(datetime(2026, 2, 3, 15, minute), new_york, "male")
            self.assertEqual(calculate_qizheng(birth, ephemeris_path=EPHEMERIS).birth_year_ganzhi, ganzhi)
