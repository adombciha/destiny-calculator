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
        groups = root.findall("s:g[@data-palace-index]", NS)
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

    def test_ziwei_transformation_table_is_independent_of_overlays(self):
        birth = BirthData(datetime.fromisoformat("1972-08-16 04:00"), self.birth.place, "female")
        chart = calculate_ziwei(birth, datetime.fromisoformat("1983-10-28 12:00"))
        all_layers = ("natal", "decadal", "yearly", "monthly")
        expected = [
            ["層次", "祿", "權", "科", "忌"],
            ["本命", "天梁", "紫微", "左輔", "武曲"],
            ["大限", "天機", "天梁", "紫微", "太陰"],
            ["流年", "破軍", "巨門", "太陰", "貪狼"],
            ["流月", "天梁", "紫微", "左輔", "武曲"],
        ]
        for layers in (("natal",), ("natal", "yearly"), all_layers):
            with self.subTest(layers=layers):
                root = ET.fromstring(render_ziwei_svg(chart, layers=layers))
                table = root.find('.//s:g[@data-section="transformations"]', NS)
                self.assertEqual(
                    [[cell.text for cell in row.findall("s:text", NS)] for row in table],
                    expected,
                )
                summary = root.find('s:g[@data-section="summary"]', NS)
                text = [node.text for node in summary.findall("s:text", NS)]
                self.assertIn("查詢：1983-10-28 12:00:00+08:00", text)
                ziwei = root.find('.//s:text[@data-star="紫微"]', NS).text
                self.assertIn("本權", ziwei)
                self.assertEqual("限科" in ziwei, "decadal" in layers)
                for layer in all_layers[1:]:
                    self.assertEqual(
                        len(root.findall(f'.//s:text[@data-layer="{layer}"]', NS)),
                        12 if layer in layers else 0,
                    )
                for layer, label, period in (
                    ("yearly", "農曆流年", chart.flow_year),
                    ("monthly", "農曆流月", chart.flow_month),
                ):
                    self.assertEqual(f"{label}：{period.gan_zhi}" in text, layer in layers)
                    if layer in layers:
                        self.assertIn(period.starts_at.isoformat(sep=" "), text)
                        self.assertIn(f"至 {period.ends_at.isoformat(sep=' ')}（不含）", text)
        childhood = calculate_ziwei(birth, birth.local_datetime)
        child_svg = ET.fromstring(render_ziwei_svg(childhood))
        table = child_svg.find('.//s:g[@data-section="transformations"]', NS)
        self.assertEqual(
            [cell.text for cell in table[2].findall("s:text", NS)],
            ["童限", "天同", "天機", "文昌", "廉貞"],
        )

    def test_ziwei_summary_and_table_fit_with_long_location(self):
        birth = replace(self.birth, place=replace(self.birth.place, name="臺" * 50 + "9" * 50))
        chart = replace(self.ziwei, birth=birth)
        root = ET.fromstring(
            render_ziwei_svg(chart, layers=("natal", "decadal", "yearly", "monthly"))
        )
        palace = root.find("s:g[@data-palace-index]/s:rect", NS)
        width, height = (int(palace.attrib[key]) for key in ("width", "height"))
        top = 76 + height
        summary = root.find('s:g[@data-section="summary"]', NS)
        for text in summary.findall(".//s:text", NS):
            self.assertGreater(float(text.attrib["x"]), width)
            self.assertLess(float(text.attrib["x"]), 3 * width)
            self.assertGreater(float(text.attrib["y"]), top)
            self.assertLess(float(text.attrib["y"]), top + 2 * height)
        for rect in summary.findall(".//s:rect", NS):
            x, y, w, h = (int(rect.attrib[key]) for key in ("x", "y", "width", "height"))
            self.assertGreater(x, width)
            self.assertLess(x + w, 3 * width)
            self.assertGreater(y, top)
            self.assertLess(y + h, top + 2 * height)

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
