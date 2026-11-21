import importlib.util
import unittest
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from math import nextafter
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from destiny_calculator import BirthData, BirthPlace, calculate_western
from destiny_calculator.jyotish import (
    _moon_nakshatra,
    _placements,
    _vimshottari_periods,
    calculate_jyotish,
)

EPHEMERIS = Path(__file__).resolve().parents[1] / "data" / "ephemeris"
HAS_EPHEMERIS = importlib.util.find_spec("swisseph") is not None and all(
    (EPHEMERIS / name).is_file() for name in ("sepl_18.se1", "semo_18.se1")
)


class JyotishRulesTests(unittest.TestCase):
    def test_navamsa_and_dasamsa_match_textbook_examples(self):
        # Vedic Astrology: An Integrated Approach, examples 16 and 17.
        d9 = _placements({"Lagna": 30, "Mercury": 71, "Jupiter": 229}, 9)
        self.assertEqual(
            [(p.sign, p.house) for p in d9],
            [("Capricorn", 1), ("Capricorn", 1), ("Sagittarius", 12)],
        )
        d10 = _placements({"Lagna": 30, "Mercury": 70, "Jupiter": 229}, 10)
        self.assertEqual(
            [(p.sign, p.house) for p in d10],
            [("Capricorn", 1), ("Virgo", 9), ("Capricorn", 1)],
        )

    def test_nakshatras_padas_and_divisions_use_half_open_boundaries(self):
        for longitude, expected in (
            (0, ("Ashwini", 1, "Ketu", 1)),
            (nextafter(10 / 3, 0), ("Ashwini", 1, "Ketu", 1)),
            (10 / 3, ("Ashwini", 2, "Ketu", 1)),
            (nextafter(40 / 3, 0), ("Ashwini", 4, "Ketu", 1)),
            (40 / 3, ("Bharani", 1, "Venus", 2)),
            (nextafter(360, 0), ("Revati", 4, "Mercury", 27)),
        ):
            with self.subTest(longitude=longitude):
                star = _moon_nakshatra(longitude)
                self.assertEqual(
                    (star.name, star.pada, star.lord, star.index), expected
                )

        for division, boundary, before, after in (
            (1, 30, "Aries", "Taurus"),
            (9, 10 / 3, "Aries", "Taurus"),
            (10, 3, "Aries", "Taurus"),
        ):
            placements = _placements(
                {"Lagna": nextafter(boundary, 0), "Moon": boundary}, division
            )
            self.assertEqual(
                [(p.sign, p.house) for p in placements], [(before, 1), (after, 2)]
            )

    def test_vimshottari_subperiods_keep_original_birth_period_proportions(self):
        # Example 50 supplies 2°23′ Aquarius and 2.24875 years of Mars remaining.
        birth = datetime(2000, 4, 28, 9, 50, tzinfo=UTC)
        periods = _vimshottari_periods(birth, 302 + 23 / 60)
        current = [period for period in periods if period.starts_at == birth]
        self.assertEqual(
            [p.label for p in current], ["Mars", "Mars/Ketu", "Mars/Ketu/Jupiter"]
        )
        self.assertEqual(current[0].ends_at, birth + timedelta(days=2.24875 * 365.2425))
        self.assertEqual(current[1].ends_at, birth + timedelta(days=0.14875 * 365.2425))
        self.assertEqual(current[2].ends_at, birth + timedelta(days=0.02625 * 365.2425))
        self.assertEqual(
            [p.label for p in periods if p.level == 1],
            [
                "Mars",
                "Rahu",
                "Jupiter",
                "Saturn",
                "Mercury",
                "Ketu",
                "Venus",
                "Sun",
                "Moon",
                "Mars",
            ],
        )
        for level in (1, 2, 3):
            with self.subTest(level=level):
                layer = [p for p in periods if p.level == level]
                self.assertEqual(layer[0].starts_at, birth)
                self.assertEqual(
                    layer[-1].ends_at, birth + timedelta(days=120 * 365.2425)
                )
                self.assertTrue(all(p.starts_at < p.ends_at for p in layer))
                self.assertTrue(
                    all(a.ends_at == b.starts_at for a, b in pairwise(layer))
                )


@unittest.skipUnless(
    HAS_EPHEMERIS, "Install the western extra and pinned ephemeris data."
)
class JyotishEphemerisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.birth = BirthData(
            datetime(2000, 1, 1, 12),
            BirthPlace("Greenwich", 51.4779, 0, "UTC"),
            "female",
        )
        cls.chart = calculate_jyotish(cls.birth, ephemeris_path=EPHEMERIS)

    def test_geographic_poles_have_no_defined_lagna(self):
        pole = BirthData(
            self.birth.local_datetime, BirthPlace("Pole", 90, 0, "UTC"), "female"
        )
        with self.assertRaisesRegex(ValueError, "Lagna is undefined"):
            calculate_jyotish(pole, ephemeris_path=EPHEMERIS)

    def test_lahiri_chart_matches_direct_swiss_ephemeris_c_abi(self):
        # Swiss Ephemeris 2.10.03 C ABI at 2000-01-01 12:00 UTC, Greenwich.
        expected = (
            ("Lagna", 0.4223994021, "Aries", "Aries", "Aries"),
            ("Sun", 256.5157004022, "Sagittarius", "Leo", "Taurus"),
            ("Moon", 199.4705781394, "Libra", "Pisces", "Aries"),
            ("Mars", 304.1100832611, "Aquarius", "Scorpio", "Pisces"),
            ("Mercury", 248.0360609430, "Sagittarius", "Gemini", "Aquarius"),
            ("Jupiter", 1.3998655036, "Aries", "Aries", "Aries"),
            ("Venus", 217.7125708700, "Scorpio", "Virgo", "Virgo"),
            ("Saturn", 16.5424409095, "Aries", "Leo", "Virgo"),
            ("Rahu", 101.1874233528, "Cancer", "Libra", "Gemini"),
            ("Ketu", 281.1874233528, "Capricorn", "Aries", "Sagittarius"),
        )
        chart = self.chart
        for placements in (chart.d1, chart.d9, chart.d10):
            self.assertEqual(len(placements), len(expected))
            self.assertEqual(placements[0].house, 1)
        for (body, longitude, d1_sign, d9_sign, d10_sign), (d1, d9, d10) in zip(
            expected, zip(chart.d1, chart.d9, chart.d10)
        ):
            with self.subTest(body=body):
                self.assertEqual((d1.body, d9.body, d10.body), (body, body, body))
                self.assertAlmostEqual(d1.longitude, longitude, delta=1 / 3600)
                self.assertEqual(
                    (d1.sign, d9.sign, d10.sign), (d1_sign, d9_sign, d10_sign)
                )
        self.assertAlmostEqual(chart.ayanamsha_degrees, 23.8570923539, delta=1 / 3600)
        self.assertEqual(
            chart.ephemeris_revision, "ad0935c2993405b57db161240e0af7e451840efd"
        )
        self.assertEqual(
            (chart.moon_nakshatra.name, chart.moon_nakshatra.pada), ("Swati", 4)
        )

    def test_node_uses_mean_position_with_the_exact_opposition(self):
        # The true node is at 99.9759642222°, on the other side of the D9 boundary.
        birth = BirthData(datetime(2000, 1, 3, 12), self.birth.place, "female")
        chart = calculate_jyotish(birth, ephemeris_path=EPHEMERIS)
        rahu, ketu = chart.d1[-2:]
        self.assertAlmostEqual(rahu.longitude, 101.0814393307, delta=1 / 3600)
        self.assertEqual(chart.d9[-2].sign, "Libra")
        self.assertAlmostEqual((ketu.longitude - rahu.longitude) % 360, 180)

    def test_lagna_depends_on_place_and_grahas_use_resolved_utc(self):
        birth = BirthData(
            datetime(2000, 1, 1, 7),
            BirthPlace("New York", 40.7, -74, "America/New_York"),
            "male",
        )
        chart = calculate_jyotish(birth, ephemeris_path=EPHEMERIS)
        self.assertNotEqual(chart.d1[0].longitude, self.chart.d1[0].longitude)
        self.assertEqual(
            [p.longitude for p in chart.d1[1:]],
            [p.longitude for p in self.chart.d1[1:]],
        )
        self.assertEqual(chart.periods, self.chart.periods)

    def test_western_stays_tropical_and_jyotish_resets_external_sidereal_mode(self):
        import swisseph as swe

        western = calculate_western(self.birth, ephemeris_path=EPHEMERIS)
        swe.set_sid_mode(swe.SIDM_FAGAN_BRADLEY)
        self.assertEqual(
            calculate_jyotish(self.birth, ephemeris_path=EPHEMERIS), self.chart
        )
        self.assertEqual(
            calculate_western(self.birth, ephemeris_path=EPHEMERIS), western
        )

    def test_missing_data_and_file_mode_fallback_are_rejected(self):
        with (
            TemporaryDirectory() as directory,
            self.assertRaisesRegex(ValueError, "Missing ephemeris"),
        ):
            calculate_jyotish(self.birth, ephemeris_path=directory)
        with (
            patch("swisseph.calc", return_value=((0.0,) * 6, 65860)),
            self.assertRaisesRegex(ValueError, "flags were not honored"),
        ):
            calculate_jyotish(self.birth, ephemeris_path=EPHEMERIS)
