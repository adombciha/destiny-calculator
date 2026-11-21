import importlib.util
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from destiny_calculator import BirthData, BirthPlace, calculate_western, get_city
from destiny_calculator.timing import timing_window
from destiny_calculator.western_timing import (
    _firdaria,
    _profections,
    _releasing,
    calculate_western_timing,
)


EPHEMERIS = Path(__file__).resolve().parents[1] / "data" / "ephemeris"
HAS_WESTERN = importlib.util.find_spec("swisseph") is not None and all(
    (EPHEMERIS / name).is_file() for name in ("sepl_18.se1", "semo_18.se1")
)


class WesternTimingTests(unittest.TestCase):
    birth = datetime(2000, 2, 29, 12, tzinfo=UTC)
    through = datetime(2090, 1, 1, tzinfo=UTC)

    def test_profections_switch_at_local_birthday_and_use_traditional_rulers(self):
        periods = tuple(_profections(self.birth, 0, self.through))
        self.assertEqual(periods[1].starts_at, datetime(2001, 2, 28, 12, tzinfo=UTC))
        self.assertEqual(periods[4].starts_at, datetime(2004, 2, 29, 12, tzinfo=UTC))
        self.assertEqual((periods[45].house, periods[45].lord), (10, "SATURN"))
        self.assertEqual((periods[46].house, periods[46].lord), (11, "SATURN"))
        boundary = periods[46].starts_at
        self.assertEqual(timing_window(periods, boundary, (0, 0)).current, (periods[46],))
        self.assertEqual(
            timing_window(periods, boundary - timedelta(microseconds=1), (0, 0)).current,
            (periods[45],),
        )

    def test_firdaria_sect_changes_order_but_nodes_follow_seven_planets(self):
        day = tuple(_firdaria(self.birth, True, self.through))
        night = tuple(_firdaria(self.birth, False, self.through))
        self.assertEqual([p.lord for p in day if p.level == 1][:3], ["SUN", "VENUS", "MERCURY"])
        self.assertEqual([p.lord for p in night if p.level == 1][:3], ["MOON", "SATURN", "JUPITER"])
        self.assertEqual([p.lord for p in night if p.level == 1][6:10], [
            "MERCURY", "NORTH_NODE", "SOUTH_NODE", "MOON",
        ])
        subperiods = [p for p in night if p.level == 2 and p.lord == "MOON"][:7]
        self.assertEqual([p.secondary_lord for p in subperiods], [
            "MOON", "SATURN", "JUPITER", "MARS", "SUN", "VENUS", "MERCURY",
        ])
        self.assertEqual(subperiods[-1].ends_at, night[0].ends_at)
        self.assertEqual(night[0].ends_at.year, 2009)

    def test_valens_gemini_long_period_jumps_to_sagittarius(self):
        periods = tuple(_releasing(self.birth, 2, "releasing_spirit", self.through))
        first = periods[0]
        self.assertEqual(first.ends_at - first.starts_at, timedelta(days=20 * 360))
        subperiods = [p for p in periods if p.level == 2 and p.starts_at < first.ends_at]
        self.assertEqual(subperiods[0].ends_at - first.starts_at, timedelta(days=600))
        self.assertEqual(subperiods[12].starts_at - first.starts_at, timedelta(days=211 * 30))
        self.assertEqual((subperiods[12].sign, subperiods[12].loosing_of_bond), ("射手", True))
        self.assertEqual((subperiods[13].sign, subperiods[13].ends_at), ("摩羯", first.ends_at))
        window = timing_window(periods, first.starts_at + timedelta(days=10), (1, 0))
        self.assertEqual(window.current, (first, subperiods[0]))
        self.assertEqual(window.periods[0].starts_at, self.birth)

    @unittest.skipUnless(HAS_WESTERN, "Install Swiss Ephemeris and data.")
    def test_sun_altitude_flips_lots_and_polar_location_still_has_firdaria(self):
        for hour, sect in ((4, "night"), (13, "day")):
            chart = calculate_western(
                BirthData(datetime(2000, 8, 16, hour), get_city("臺北"), "female"),
                ephemeris_path=EPHEMERIS,
            )
            timing = calculate_western_timing(chart, through=self.through)
            self.assertEqual(timing.sect, sect)
            sun, moon = chart.planets[:2]
            difference = moon.longitude - sun.longitude
            arc = difference if sect == "day" else -difference
            self.assertAlmostEqual(timing.lot_of_fortune, (chart.ascendant + arc) % 360)
            self.assertAlmostEqual(timing.lot_of_spirit, (chart.ascendant - arc) % 360)

        pole = BirthPlace("North Pole", 90, 0, "UTC")
        chart = calculate_western(BirthData(datetime(2000, 8, 16, 4), pole, "female"), ephemeris_path=EPHEMERIS)
        timing = calculate_western_timing(chart, through=self.through)
        self.assertIsNone(timing.ascendant)
        self.assertEqual({p.method for p in timing.periods}, {"firdaria"})
