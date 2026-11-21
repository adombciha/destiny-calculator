import importlib.util
import unittest
from datetime import UTC, date, datetime, time
from pathlib import Path
from unittest.mock import patch

from destiny_calculator import BirthData, calculate_bazi, calculate_ziwei, get_city


HAS_UI = importlib.util.find_spec("streamlit") is not None
HAS_WESTERN = (
    importlib.util.find_spec("swisseph") is not None
    and (Path(__file__).resolve().parents[1] / "data/ephemeris/semo_18.se1").is_file()
)
if HAS_UI:
    from streamlit.testing.v1 import AppTest
    from app import adjacent_month_query


@unittest.skipUnless(HAS_UI, "Install the ui extra to run interface tests.")
class AppTests(unittest.TestCase):
    def new_app(self):
        return AppTest.from_file(
            str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30
        ).run()

    def submit(self, app):
        return app.button(key="submit_birth").click().run()

    def test_conditional_fields_keep_the_draft_until_submission(self):
        app = self.new_app()
        app.date_input(key="birth_date").set_value(date(2001, 7, 2))
        app.selectbox(key="city").set_value("手動地點").run()
        app.text_input(key="place_name").set_value("Demo place")
        app.selectbox(key="city").set_value("臺北").run()
        app.selectbox(key="city").set_value("手動地點").run()
        self.assertEqual(app.text_input(key="place_name").value, "Demo place")
        self.assertEqual(app.date_input(key="birth_date").value, date(2001, 7, 2))

        app.checkbox(key="use_now").uncheck().run()
        app.date_input(key="query_date").set_value(date(2023, 3, 25))
        app.time_input(key="query_time").set_value(time(12, 34, 56))
        app.checkbox(key="use_now").check().run()
        app.checkbox(key="use_now").uncheck().run()
        self.assertNotIn("report", app.session_state)
        self.assertEqual(app.date_input(key="query_date").value, date(2023, 3, 25))
        self.assertEqual(app.time_input(key="query_time").value, time(12, 34, 56))

    def test_svg_failure_keeps_its_details_and_json(self):
        with patch("destiny_calculator.render_bazi_svg", side_effect=ValueError("draw failed")):
            app = self.submit(self.new_app())
        self.assertFalse(app.exception)
        self.assertTrue(any("draw failed" in warning.value for warning in app.warning))
        bazi_tab = app.tabs[1]
        self.assertEqual(len(bazi_tab.get("dataframe")), 2)
        self.assertEqual(
            [button.proto.label for button in bazi_tab.get("download_button")],
            ["下載此盤完整 JSON"],
        )

    def test_public_example_layers_navigation_and_clear(self):
        app = self.submit(self.new_app())
        self.assertEqual(len(app.exception), 0)
        self.assertTrue({"bazi", "ziwei"}.issubset(app.session_state["report"][2]))
        app.radio(key="ziwei_mode").set_value("本命").run()
        app.checkbox(key="show_decadal").check().run()
        self.assertEqual(len(app.exception), 0)
        chart = app.session_state["report"][2]["bazi"]
        expected = chart.flow_month.ends_at
        app.button(key="bazi_next").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.session_state["report"][1].astimezone(UTC), expected.astimezone(UTC))
        self.assertEqual(app.session_state["query_time"].second, expected.second)
        next(b for b in app.button if b.label == "清除資料與結果").click().run()
        self.assertNotIn("report", app.session_state)
        self.assertEqual(len(app.exception), 0)

    def test_invalid_submission_removes_stale_report(self):
        app = self.submit(self.new_app())
        app.checkbox(key="use_now").uncheck().run()
        app.date_input(key="query_date").set_value(date(1999, 1, 1))
        self.submit(app)
        self.assertNotIn("report", app.session_state)
        self.assertTrue(app.error)
        self.assertFalse(app.exception)

    def test_partial_failure_still_shows_bazi(self):
        app = self.new_app()
        app.date_input(key="birth_date").set_value(date(1900, 1, 1))
        self.submit(app)
        self.assertIn("bazi", app.session_state["report"][2])
        self.assertNotIn("ziwei", app.session_state["report"][2])
        self.assertIn("ziwei", app.session_state["report"][3])
        self.assertTrue(app.warning)
        self.assertFalse(app.exception)

    def test_manual_place_requires_explicit_dst_fold(self):
        app = self.new_app()
        app.selectbox(key="city").set_value("手動地點").run()
        app.text_input(key="place_name").set_value("New York")
        app.text_input(key="timezone").set_value("America/New_York")
        app.number_input(key="latitude").set_value(40.7)
        app.number_input(key="longitude").set_value(-74.0)
        app.date_input(key="birth_date").set_value(date(2024, 11, 3))
        app.time_input(key="birth_time").set_value(time(1, 30))
        self.submit(app)
        self.assertTrue(app.error)
        self.assertIn("05:30", app.error[0].value)
        self.assertIn("06:30", app.error[0].value)
        app.selectbox(key="birth_fold").set_value("第二次")
        self.submit(app)
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(
            app.session_state["report"][0].utc_datetime, datetime(2024, 11, 3, 6, 30, tzinfo=UTC)
        )

    def test_month_navigation_respects_solar_seconds_leap_segments_and_birth(self):
        birth = BirthData(datetime(2000, 8, 16, 4), get_city("臺北"), "female")
        bazi = calculate_bazi(birth, datetime(2026, 10, 28, 12))
        self.assertEqual(adjacent_month_query(bazi, 1), bazi.flow_month.ends_at)
        ziwei = calculate_ziwei(birth, datetime(2023, 3, 25, 12))
        following = adjacent_month_query(ziwei, 1)
        self.assertEqual(following.isoformat(), "2023-04-06T00:00:00+08:00")
        second = calculate_ziwei(birth, following.replace(tzinfo=None))
        self.assertEqual(adjacent_month_query(second, -1).isoformat(), "2023-03-22T00:00:00+08:00")
        for calculator in (calculate_bazi, calculate_ziwei):
            self.assertIsNone(adjacent_month_query(calculator(birth, birth.local_datetime), -1))
            end = calculator(birth, datetime(2099, 12, 31, 12))
            self.assertIsNone(adjacent_month_query(end, 1))

    def test_sessions_do_not_share_birth_or_results(self):
        first = self.submit(self.new_app())
        second = self.new_app()
        self.assertNotIn("report", second.session_state)
        self.assertIn("report", first.session_state)

    @unittest.skipUnless(HAS_WESTERN, "Install western dependencies and ephemeris.")
    def test_three_charts_and_western_natal_stays_fixed_on_month_navigation(self):
        app = self.submit(self.new_app())
        self.assertEqual(set(app.session_state["report"][2]), {"bazi", "ziwei", "western"})
        natal = app.session_state["report"][2]["western"]
        app.button(key="bazi_next").click().run()
        self.assertEqual(app.session_state["report"][2]["western"], natal)
        self.assertFalse(app.exception)

    def test_missing_western_data_preserves_chinese_results(self):
        with patch(
            "destiny_calculator.western._verified_files",
            side_effect=ValueError("missing ephemeris"),
        ):
            app = self.submit(self.new_app())
        self.assertEqual(set(app.session_state["report"][2]), {"bazi", "ziwei"})
        self.assertIn("western", app.session_state["report"][3])
        self.assertTrue(app.warning)
        self.assertFalse(app.exception)
