import json
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from importlib.resources import files
from unittest.mock import patch

from destiny_calculator import (
    AmbiguousTimeError,
    BirthData,
    BirthPlace,
    NonexistentTimeError,
    get_city,
    list_cities,
    resolve_local_time,
)


class LocalTimeTests(unittest.TestCase):
    def test_taipei_reference_crosses_utc_date(self):
        result = resolve_local_time(datetime(2000, 8, 16, 4), "Asia/Taipei")
        self.assertEqual(result.astimezone(UTC), datetime(2000, 8, 15, 20, tzinfo=UTC))
        self.assertEqual(result.utcoffset(), timedelta(hours=8))

    def test_repeated_time_requires_explicit_choice(self):
        for local in (
            datetime(2024, 11, 3, 1, 30),
            datetime(2024, 11, 3, 1, 30, fold=1),
        ):
            with self.subTest(local=local), self.assertRaises(AmbiguousTimeError):
                resolve_local_time(local, "America/New_York")

    def test_both_repeated_occurrences_have_distinct_utc_instants(self):
        local = datetime(2024, 11, 3, 1, 30)
        for fold, hour in ((0, 5), (1, 6)):
            with self.subTest(fold=fold):
                result = resolve_local_time(local, "America/New_York", fold)
                self.assertEqual(result.fold, fold)
                self.assertEqual(result.astimezone(UTC), datetime(2024, 11, 3, hour, 30, tzinfo=UTC))

    def test_nonexistent_time_is_rejected_for_every_choice(self):
        for fold in (None, 0, 1):
            with self.subTest(fold=fold), self.assertRaises(NonexistentTimeError):
                resolve_local_time(datetime(2024, 3, 10, 2, 30), "America/New_York", fold)

    def test_non_hour_transition(self):
        local = datetime(2024, 4, 7, 1, 45)
        first = resolve_local_time(local, "Australia/Lord_Howe", 0)
        second = resolve_local_time(local, "Australia/Lord_Howe", 1)
        self.assertEqual(second.astimezone(UTC) - first.astimezone(UTC), timedelta(minutes=30))
        with self.assertRaises(NonexistentTimeError):
            resolve_local_time(datetime(2024, 10, 6, 2, 15), "Australia/Lord_Howe")

    def test_entire_skipped_date(self):
        with self.assertRaises(NonexistentTimeError):
            resolve_local_time(datetime(2011, 12, 30, 12), "Pacific/Apia")

    def test_historical_taiwan_daylight_saving(self):
        winter = resolve_local_time(datetime(1979, 1, 1, 12), "Asia/Taipei")
        summer = resolve_local_time(datetime(1979, 7, 1, 12), "Asia/Taipei")
        self.assertEqual(winter.utcoffset(), timedelta(hours=8))
        self.assertEqual(summer.utcoffset(), timedelta(hours=9))

    def test_unambiguous_time_has_canonical_fold(self):
        result = resolve_local_time(datetime(2000, 8, 16, 4), "Asia/Taipei", 1)
        self.assertEqual(result.fold, 0)

    def test_local_range_does_not_restrict_utc_year(self):
        result = resolve_local_time(datetime(1900, 1, 1), "Etc/GMT-14")
        self.assertEqual(result.astimezone(UTC).year, 1899)
        resolve_local_time(datetime(2099, 12, 31, 23, 59), "Etc/GMT+12")
        for year in (1899, 2100):
            with self.subTest(year=year), self.assertRaises(ValueError):
                resolve_local_time(datetime(year, 1, 1), "UTC")

    def test_invalid_input_types_and_folds(self):
        for value in (None, "2000-08-16", date(2000, 8, 16), datetime(2000, 8, 16, tzinfo=UTC)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                resolve_local_time(value, "UTC")
        for fold in (-1, 2, True, 0.0, "0"):
            with self.subTest(fold=fold), self.assertRaises(ValueError):
                resolve_local_time(datetime(2000, 8, 16), "UTC", fold)

    def test_invalid_or_unavailable_timezone(self):
        for name in (None, "", "Not/A_Timezone", "/etc/passwd", "../UTC"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "[Tt]ime zone"):
                resolve_local_time(datetime(2000, 8, 16), name)


class BirthDataTests(unittest.TestCase):
    def setUp(self):
        self.taipei = get_city("臺北")
        self.birth = BirthData(datetime(2000, 8, 16, 4), self.taipei, "female")

    def test_retains_input_and_resolves_utc(self):
        self.assertEqual(self.birth.local_datetime, datetime(2000, 8, 16, 4))
        self.assertIsNone(self.birth.local_datetime.tzinfo)
        self.assertEqual(self.birth.resolved_datetime.isoformat(), "2000-08-16T04:00:00+08:00")
        self.assertEqual(self.birth.utc_datetime.isoformat(), "2000-08-15T20:00:00+00:00")
        with self.assertRaises(FrozenInstanceError):
            self.birth.gender = "male"

    def test_manual_location_and_coordinate_override(self):
        place = BirthPlace("New York", 40.7, -74.0, "America/New_York")
        birth = BirthData(datetime(2024, 11, 3, 1, 30), place, "male", fold=1)
        self.assertEqual(birth.resolved_datetime.fold, 1)
        self.assertEqual(birth.utc_datetime, datetime(2024, 11, 3, 6, 30, tzinfo=UTC))
        adjusted = replace(self.taipei, latitude=25.04, longitude=121.56)
        self.assertEqual(adjusted.timezone, "Asia/Taipei")
        self.assertNotEqual(adjusted.latitude, self.taipei.latitude)

    def test_invalid_places_and_coordinates(self):
        for name in ("", "   ", None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                BirthPlace(name, 0, 0, "UTC")
        for field, limit in (("latitude", 90), ("longitude", 180)):
            for value in (limit + 1, -limit - 1, float("nan"), float("inf"), -float("inf"), True, "0", None, 10**1000):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    replace(self.taipei, **{field: value})
            for value in (-limit, limit):
                replace(self.taipei, **{field: value})

    def test_invalid_birth_fields(self):
        for gender in ("", "unknown", None, True):
            with self.subTest(gender=gender), self.assertRaises(ValueError):
                replace(self.birth, gender=gender)
        with self.assertRaises(ValueError):
            replace(self.birth, place="臺北")
        for local in (datetime(2000, 8, 16, 4, 0, 1), datetime(2000, 8, 16, 4, 0, 0, 1)):
            with self.subTest(local=local), self.assertRaisesRegex(ValueError, "minute precision"):
                replace(self.birth, local_datetime=local)

    def test_invalid_calendar_date_is_rejected_by_datetime(self):
        for values in ((2001, 2, 29), (2000, 13, 1), (2000, 1, 0), (2000, 1, 1, 24)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                BirthData(datetime(*values), self.taipei, "female")
        leap_birth = replace(self.birth, local_datetime=datetime(2000, 2, 29))
        self.assertEqual(leap_birth.local_datetime.day, 29)

    def test_birth_rejects_missing_time(self):
        place = BirthPlace("New York", 40.7, -74.0, "America/New_York")
        with self.assertRaises(NonexistentTimeError):
            BirthData(datetime(2024, 3, 10, 2, 30), place, "female")
        with self.assertRaises(AmbiguousTimeError):
            BirthData(datetime(2024, 11, 3, 1, 30), place, "female")

    def test_query_cannot_precede_birth(self):
        with self.assertRaisesRegex(ValueError, "earlier than birth"):
            self.birth.resolve_query_time(datetime(2000, 8, 16, 3, 59))
        self.assertEqual(self.birth.resolve_query_time(self.birth.local_datetime), self.birth.resolved_datetime)

    def test_query_orders_utc_instants_across_fold(self):
        place = BirthPlace("New York", 40.7, -74.0, "America/New_York")
        birth = BirthData(datetime(2024, 11, 3, 1, 45), place, "female", fold=0)
        query = birth.resolve_query_time(datetime(2024, 11, 3, 1, 15), fold=1)
        self.assertGreater(query.astimezone(UTC), birth.utc_datetime)
        birth = BirthData(datetime(2024, 11, 3, 1, 15), place, "female", fold=1)
        with self.assertRaises(ValueError):
            birth.resolve_query_time(datetime(2024, 11, 3, 1, 45), fold=0)

    def test_query_validates_dst_and_date_range(self):
        place = BirthPlace("New York", 40.7, -74.0, "America/New_York")
        birth = replace(self.birth, place=place)
        with self.assertRaises(AmbiguousTimeError):
            birth.resolve_query_time(datetime(2024, 11, 3, 1, 30))
        with self.assertRaises(NonexistentTimeError):
            birth.resolve_query_time(datetime(2024, 3, 10, 2, 30))
        with self.assertRaises(ValueError):
            birth.resolve_query_time(datetime(2100, 1, 1))

    def test_default_query_uses_birthplace_date(self):
        with patch("destiny_calculator.models.datetime") as clock:
            clock.now.return_value = datetime(2024, 12, 31, 20, 30, tzinfo=UTC)
            query = self.birth.resolve_query_time()
        self.assertEqual(query.isoformat(), "2025-01-01T04:30:00+08:00")

    def test_default_query_preserves_actual_fold(self):
        place = BirthPlace("New York", 40.7, -74.0, "America/New_York")
        birth = replace(self.birth, place=place)
        with patch("destiny_calculator.models.datetime") as clock:
            clock.now.return_value = datetime(2024, 11, 3, 6, 30, tzinfo=UTC)
            query = birth.resolve_query_time()
        self.assertEqual(query.fold, 1)
        self.assertEqual(query.astimezone(UTC), datetime(2024, 11, 3, 6, 30, tzinfo=UTC))
        with self.assertRaises(ValueError):
            birth.resolve_query_time(fold=0)


class CityTests(unittest.TestCase):
    def test_city_selection(self):
        self.assertEqual(tuple(city.name for city in list_cities()), ("臺北", "臺中", "高雄"))
        self.assertEqual(get_city("高雄").timezone, "Asia/Taipei")
        with self.assertRaisesRegex(ValueError, "Unknown built-in city"):
            get_city("London")

    def test_city_snapshot_has_attribution_and_provenance(self):
        resource = files("destiny_calculator").joinpath("data/cities.json")
        snapshot = json.loads(resource.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["source"], "GeoNames")
        self.assertEqual(snapshot["license"], "CC BY 4.0")
        date.fromisoformat(snapshot["retrieved_on"])
        self.assertEqual({city["geonameid"] for city in snapshot["cities"]}, {1668341, 1668399, 1673820})
        for city in snapshot["cities"]:
            self.assertIn(str(city["geonameid"]), city["source_url"])


if __name__ == "__main__":
    unittest.main()
