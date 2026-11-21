import importlib.util
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

from destiny_calculator import (
    BirthData,
    BirthPlace,
    calculate_western,
    export_chart_json,
    get_city,
    render_western_svg,
)
from destiny_calculator.western import _aspects, _house, format_zodiac


EPHEMERIS = Path(__file__).resolve().parents[1] / "data" / "ephemeris"
HAS_WESTERN = importlib.util.find_spec("swisseph") is not None and all(
    (EPHEMERIS / name).is_file() for name in ("sepl_18.se1", "semo_18.se1")
)


@unittest.skipUnless(HAS_WESTERN, "Install the western extra and pinned ephemeris data.")
class WesternTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.birth = BirthData(datetime(2000, 8, 16, 4), get_city("臺北"), "female")
        cls.chart = calculate_western(cls.birth, ephemeris_path=EPHEMERIS)

    def angle_close(self, actual, expected):
        difference = abs(actual - expected) % 360
        self.assertLessEqual(min(difference, 360 - difference), 1 / 3600)

    def test_upstream_w01_w02_fixed_file_references(self):
        import swisseph as swe

        swe.set_ephe_path(str(EPHEMERIS))
        position, flags = swe.calc_ut(2452275.499255786, swe.SUN, swe.FLG_SWIEPH | swe.FLG_SPEED)
        self.assertEqual(flags, 258)
        self.angle_close(position[0], 280.38296810621137)
        cusps, angles = swe.houses(2452275.499255786, 0, 0, b"P")
        expected = (
            191.0989364639854,
            222.65039973002735,
            251.72382204055555,
            279.3768461762848,
            307.79074786727415,
            338.5782564089493,
            11.09893646398541,
            42.650399730027345,
            71.72382204055555,
            99.3768461762848,
            127.79074786727413,
            158.5782564089493,
        )
        for actual, reference in zip(cusps, expected):
            self.angle_close(actual, reference)
        self.angle_close(angles[0], expected[0])
        self.angle_close(angles[1], expected[9])

    def test_complete_birth_pipeline_matches_direct_native_c_abi_fixture(self):
        reference = json.loads(
            Path(__file__).with_name("fixtures").joinpath("western_reference.json").read_text()
        )
        chart = self.chart
        self.assertEqual(chart.birth.utc_datetime.isoformat(), reference["utc"])
        self.assertEqual(chart.ephemeris_revision, reference["ephemeris_revision"])
        self.assertAlmostEqual(chart.jd_tt, reference["jd_tt"], places=9)
        self.assertAlmostEqual(chart.jd_ut1, reference["jd_ut1"], places=9)
        for planet, vector in zip(chart.planets, reference["planet_vectors"]):
            self.angle_close(planet.longitude, vector[0])
            self.assertAlmostEqual(planet.latitude, vector[1], places=8)
            self.assertAlmostEqual(planet.longitude_speed, vector[3], places=8)
            self.assertEqual(planet.retrograde, vector[3] < 0)
            self.assertIn(planet.house, range(1, 13))
            self.assertEqual(planet.returned_flags, 258)
        for actual, expected in zip(chart.house_cusps, reference["cusps"]):
            self.angle_close(actual, expected)
        self.angle_close(chart.ascendant, reference["ascendant"])
        self.angle_close(chart.midheaven, reference["midheaven"])
        self.assertEqual(len(chart.planets), 10)

    def test_same_instant_keeps_planets_but_changes_angles(self):
        new_york = BirthData(
            datetime(2000, 8, 15, 16), BirthPlace("New York", 40.7, -74, "America/New_York"), "male"
        )
        other = calculate_western(new_york, ephemeris_path=EPHEMERIS)
        self.assertEqual(new_york.utc_datetime, self.birth.utc_datetime)
        self.assertEqual(
            [p.longitude for p in other.planets], [p.longitude for p in self.chart.planets]
        )
        self.assertNotEqual(other.ascendant, self.chart.ascendant)

    def test_missing_and_corrupt_files_fail_without_fallback(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)
            with self.assertRaisesRegex(ValueError, "Missing ephemeris"):
                calculate_western(self.birth, ephemeris_path=path)
            (path / "sepl_18.se1").write_bytes((EPHEMERIS / "sepl_18.se1").read_bytes())
            with self.assertRaisesRegex(ValueError, "semo_18"):
                calculate_western(self.birth, ephemeris_path=path)
            (path / "sepl_18.se1").write_bytes(b"invalid ephemeris")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                calculate_western(self.birth, ephemeris_path=path)

    def test_invalid_flags_and_nonfinite_positions_are_rejected(self):
        for values, flags in (((1.0,) * 6, 260), ((float("nan"),) * 6, 258)):
            with patch("swisseph.calc", return_value=(values, flags)), self.assertRaises(
                ValueError
            ):
                calculate_western(self.birth, ephemeris_path=EPHEMERIS)

    def test_polar_houses_remain_unavailable_in_chart_json_and_svg(self):
        birth = replace(self.birth, place=BirthPlace("Polar test", 89, 0, "UTC"))
        chart = calculate_western(birth, ephemeris_path=EPHEMERIS)
        self.assertEqual(chart.house_status, "unavailable")
        self.assertIsNone(chart.house_cusps)
        self.assertIsNone(chart.ascendant)
        self.assertTrue(all(p.house is None for p in chart.planets))
        self.assertEqual(
            json.loads(export_chart_json(chart))["results"]["western"]["status"], "partial"
        )
        root = ET.fromstring(render_western_svg(chart))
        self.assertIn("宮位不可用", "".join(root.itertext()))
        self.assertEqual(len(root.findall(".//*[@data-house-index]")), 0)

    def test_aspects_wrap_inclusive_orb_and_house_boundaries(self):
        first, second = self.chart.planets[:2]
        pair = (replace(first, longitude=359), replace(second, longitude=1))
        aspect = _aspects(pair)[0]
        self.assertEqual((aspect.name, aspect.separation, aspect.orb), ("合相", 2, 2))
        for longitude, count in ((66, 1), (66.0001, 0)):
            self.assertEqual(
                len(_aspects((replace(first, longitude=0), replace(second, longitude=longitude)))),
                count,
            )
        cusps = tuple((350 + 30 * i) % 360 for i in range(12))
        self.assertEqual(_house(0, cusps), 1)
        self.assertEqual(_house(20, cusps), 2)
        self.assertEqual(format_zodiac(29.999999), "金牛 00°00′00″")
        self.assertEqual(format_zodiac(359.999999), "牡羊 00°00′00″")

    def test_date_limits_and_external_engine_settings(self):
        import swisseph as swe

        swe.set_ephe_path("/missing")
        swe.set_delta_t_userdef(1.0)
        again = calculate_western(self.birth, ephemeris_path=EPHEMERIS)
        self.assertEqual(again.planets, self.chart.planets)
        for local, place in (
            (datetime(1900, 1, 1), BirthPlace("Guam", 13.4, 144.7, "Pacific/Guam")),
            (datetime(2099, 12, 31, 23, 59), BirthPlace("New York", 40.7, -74, "America/New_York")),
        ):
            with self.subTest(local=local):
                chart = calculate_western(
                    BirthData(local, place, "female"), ephemeris_path=EPHEMERIS
                )
                self.assertEqual(len(chart.planets), 10)

    def test_svg_has_all_planets_and_unequal_house_geometry(self):
        root = ET.fromstring(render_western_svg(self.chart))
        self.assertEqual(len(root.findall(".//*[@data-planet]")), 10)
        self.assertEqual(len(root.findall(".//*[@data-house-index]")), 12)
        self.assertNotAlmostEqual((self.chart.house_cusps[1] - self.chart.house_cusps[0]) % 360, 30)

    def test_missing_optional_dependency_is_an_actionable_error(self):
        import builtins

        original = builtins.__import__

        def without_swiss(name, *args, **kwargs):
            if name == "swisseph":
                raise ImportError("not installed")
            return original(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=without_swiss), self.assertRaisesRegex(
            ValueError, "western"
        ):
            calculate_western(self.birth, ephemeris_path=EPHEMERIS)
