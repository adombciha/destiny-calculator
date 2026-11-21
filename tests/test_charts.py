import unittest
from dataclasses import replace
from datetime import datetime
from xml.etree import ElementTree as ET

from destiny_calculator import (
    BirthData,
    calculate_bazi,
    calculate_ziwei,
    get_city,
    render_bazi_svg,
    render_ziwei_svg,
)


NS = {"s": "http://www.w3.org/2000/svg"}


class ChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.birth = BirthData(datetime(2000, 8, 16, 4), get_city("臺北"), "female")
        cls.ziwei = calculate_ziwei(cls.birth, datetime(2026, 10, 28, 12))
        cls.bazi = calculate_bazi(cls.birth, datetime(2026, 10, 28, 12))

    def test_fixed_palace_positions_and_all_stars_are_preserved(self):
        root = ET.fromstring(render_ziwei_svg(self.ziwei))
        groups = root.findall("s:g", NS)
        self.assertEqual(len(groups), 12)
        top_branches = [
            g.attrib["data-branch"] for g in groups if g.find("s:rect", NS).attrib["y"] == "76"
        ]
        self.assertEqual(top_branches, ["巳", "午", "未", "申"])
        expected_x = {
            "寅": 0,
            "卯": 0,
            "辰": 0,
            "巳": 0,
            "午": 350,
            "未": 700,
            "申": 1050,
            "酉": 1050,
            "戌": 1050,
            "亥": 1050,
            "子": 700,
            "丑": 350,
        }
        for group in groups:
            palace = self.ziwei.palaces[int(group.attrib["data-palace-index"])]
            self.assertEqual(
                int(group.find("s:rect", NS).attrib["x"]), expected_x[group.attrib["data-branch"]]
            )
            actual = [
                t.attrib["data-star"]
                for t in group.findall("s:text", NS)
                if "data-star" in t.attrib
            ]
            expected = [
                s.name for s in (*palace.major_stars, *palace.minor_stars, *palace.adjective_stars)
            ]
            self.assertEqual(actual, expected)

    def test_four_layers_coexist_and_do_not_mutate_natal(self):
        before = render_ziwei_svg(self.ziwei)
        root = ET.fromstring(
            render_ziwei_svg(self.ziwei, layers=("natal", "decadal", "yearly", "monthly"))
        )
        text = "".join(root.itertext())
        self.assertIn("年忌", text)
        self.assertIn("月忌", text)
        for layer in ("decadal", "yearly", "monthly"):
            self.assertEqual(len(root.findall(f'.//s:text[@data-layer="{layer}"]', NS)), 12)
        self.assertEqual(render_ziwei_svg(self.ziwei), before)
        for p in self.ziwei.palaces:
            for star in (*p.major_stars, *p.minor_stars, *p.adjective_stars):
                if star.mutagen:
                    self.assertIn("本" + star.mutagen, text)

    def test_text_is_escaped_and_invalid_xml_characters_are_rejected(self):
        birth = replace(self.birth, place=replace(self.birth.place, name='A&B <測試> "地點"'))
        raw = render_ziwei_svg(replace(self.ziwei, birth=birth))
        self.assertIn("&amp;", raw)
        self.assertIn("&lt;測試&gt;", raw)
        self.assertIn('A&B <測試> "地點"', "".join(ET.fromstring(raw).itertext()))
        invalid = replace(birth, place=replace(birth.place, name="bad\x00name"))
        with self.assertRaises(ValueError):
            render_bazi_svg(replace(self.bazi, birth=invalid))

    def test_bazi_columns_luck_and_periods_are_readable(self):
        text = "".join(ET.fromstring(render_bazi_svg(self.bazi)).itertext())
        self.assertLess(text.index("時柱"), text.index("日柱"))
        self.assertLess(text.index("月柱"), text.index("年柱"))
        self.assertIn("目前 → 辛巳", text)
        self.assertIn("2026-10-08 14:29:17+08:00", text)
        childhood = calculate_bazi(self.birth, self.birth.local_datetime)
        self.assertIn("尚未起運", "".join(ET.fromstring(render_bazi_svg(childhood)).itertext()))

    def test_invalid_layer_requests_fail_explicitly(self):
        for layers in ((), ("yearly",), ("natal", "natal"), ("natal", "invalid")):
            with self.subTest(layers=layers), self.assertRaises(ValueError):
                render_ziwei_svg(self.ziwei, layers=layers)
