"""Render calculated Chinese charts as standalone SVG documents."""

from datetime import datetime
import re
from math import cos, sin, radians
from xml.etree.ElementTree import Element, SubElement, tostring

from .bazi import BaziChart
from .ziwei import ZiweiChart
from .western import SIGNS, WesternChart, format_zodiac


FONT = "'Noto Sans CJK TC','Microsoft JhengHei','PingFang TC',sans-serif"
PAPER = "#f8f6f0"
INK = "#17262a"
MUTED_INK = "#4d605b"
BORDER = "#bdc9c1"
TEAL = "#175f58"
TEAL_TINT = "#eaf2ee"
AMBER = "#855617"
AMBER_TINT = "#fbf0df"
LAYER_LABELS = {"natal": "本", "decadal": "限", "yearly": "年", "monthly": "月"}
LAYER_COLORS = {
    "natal": INK,
    "decadal": "#704980",
    "yearly": "#205b83",
    "monthly": TEAL,
}
POSITIONS = (
    (0, 3),
    (0, 2),
    (0, 1),
    (0, 0),
    (1, 0),
    (2, 0),
    (3, 0),
    (3, 1),
    (3, 2),
    (3, 3),
    (2, 3),
    (1, 3),
)


def _text(parent, x, y, value, *, size=15, color=INK, **attributes):
    value = str(value)
    if any(
        not (
            c in "\t\n\r"
            or 0x20 <= ord(c) <= 0xD7FF
            or 0xE000 <= ord(c) <= 0xFFFD
            or 0x10000 <= ord(c) <= 0x10FFFF
        )
        for c in value
    ):
        raise ValueError("Chart text contains characters unsupported by XML.")
    node = SubElement(
        parent,
        "text",
        {"x": str(x), "y": str(y), "font-size": str(size), "fill": color, **attributes},
    )
    node.text = value
    return node


def _rect(parent, x, y, width, height, fill="#ffffff", stroke=BORDER):
    return SubElement(
        parent,
        "rect",
        {
            "x": str(x),
            "y": str(y),
            "width": str(width),
            "height": str(height),
            "fill": fill,
            "stroke": stroke,
        },
    )


def _wrap(value, width=40):
    lines, line, units = [], "", 0
    for character in re.findall(r"\d+|[^\d]", str(value)):
        size = sum(1 if ord(c) < 128 and c not in "MW@%#&" else 2 for c in character)
        if character == "\n" or units + size > width:
            lines.append(line)
            line, units = "", 0
            if character == "\n":
                continue
        line += character
        units += size
    if line:
        lines.append(line)
    return lines or [""]


def _document(width, height, title, description):
    svg = Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "width": str(width),
            "height": str(height),
            "viewBox": f"0 0 {width} {height}",
            "font-family": FONT,
            "role": "img",
            "aria-labelledby": "chart-title chart-description",
        },
    )
    SubElement(svg, "title", {"id": "chart-title"}).text = title
    SubElement(svg, "desc", {"id": "chart-description"}).text = description
    _rect(svg, 0, 0, width, height, PAPER, "none")
    _text(svg, 24, 36, title, size=29, color=TEAL, **{"font-weight": "bold"})
    return svg


def _date(value: datetime):
    return value.isoformat(sep=" ", timespec="seconds")


def render_ziwei_svg(chart: ZiweiChart, *, layers=("natal",)) -> str:
    if not isinstance(chart, ZiweiChart):
        raise ValueError("chart must be a ZiweiChart.")
    if not layers or len(set(layers)) != len(layers) or any(v not in LAYER_LABELS for v in layers):
        raise ValueError("Select unique layers from natal, decadal, yearly, monthly.")
    if "natal" not in layers:
        raise ValueError("The natal layer is required as the fixed palace reference.")
    cycles = {"decadal": chart.current_luck, "yearly": chart.flow_year, "monthly": chart.flow_month}
    rows = []
    for palace in chart.palaces:
        lines = []
        for group, stars in (
            ("主", palace.major_stars),
            ("輔", palace.minor_stars),
            ("雜", palace.adjective_stars),
        ):
            for star in stars:
                tags = ["本" + star.mutagen] if star.mutagen else []
                for layer in layers:
                    if layer == "natal":
                        continue
                    tags.extend(
                        LAYER_LABELS[layer] + kind
                        for name, kind in zip(cycles[layer].mutagens, "祿權科忌")
                        if name == star.name
                    )
                label = f"{group} {star.name}" + (
                    f"（{star.brightness}）" if star.brightness else ""
                )
                if tags:
                    label += "  " + "／".join(tags)
                for i, part in enumerate(_wrap(label)):
                    lines.append(
                        (
                            part,
                            AMBER if group == "主" else INK,
                            {"data-star": star.name, "data-group": group} if i == 0 else {},
                        )
                    )
        details = [
            f"大限：{palace.decadal_age_range[0]}–{palace.decadal_age_range[1]} 虛歲",
            "流年：" + ", ".join(map(str, palace.yearly_ages)),
            "小限：" + ", ".join(map(str, palace.ages)),
            "長生：" + palace.changsheng_12 + "　博士：" + palace.boshi_12,
            "將前：" + palace.jiangqian_12 + "　歲前：" + palace.suiqian_12,
        ]
        for value in details:
            lines.extend((part, MUTED_INK, {}) for part in _wrap(value))
        for layer in layers:
            if layer == "natal":
                continue
            cycle = cycles[layer]
            label = f"{LAYER_LABELS[layer]}宮：{cycle.palace_names[palace.index]}"
            if cycle.index == palace.index:
                label += " ◇命宮"
            lines.append((label, LAYER_COLORS[layer], {"data-layer": layer}))
            flow_stars = cycle.stars[palace.index]
            if flow_stars:
                value = LAYER_LABELS[layer] + "曜：" + "、".join(s.name for s in flow_stars)
                lines.extend((part, LAYER_COLORS[layer], {}) for part in _wrap(value))
        rows.append(lines)
    width, cell_width, top = 1400, 350, 76
    cell_height = max(430, max(len(row) for row in rows) * 23 + 76)
    height = top + 4 * cell_height + 42
    title = "紫微斗數｜" + "・".join(
        {"natal": "本命", "decadal": "大限", "yearly": "流年", "monthly": "流月"}[layer]
        for layer in layers
    )
    svg = _document(width, height, title, "固定十二地支宮位；本命與運程四化分層顯示。")
    _text(
        svg,
        24,
        61,
        "時間基準：出生地民用時間；歲數為虛歲；本／限／年／月表示四化來源。",
        size=15,
        color=MUTED_INK,
    )
    for palace, lines in zip(chart.palaces, rows):
        column, row = POSITIONS[palace.index]
        x, y = column * cell_width, top + row * cell_height
        group = SubElement(
            svg, "g", {"data-palace-index": str(palace.index), "data-branch": palace.gan_zhi[-1]}
        )
        _rect(group, x, y, cell_width, cell_height)
        _rect(group, x, y, cell_width, 44, TEAL_TINT)
        _text(
            group,
            x + 14,
            y + 29,
            f"{palace.name}　{palace.gan_zhi}" + ("　身宮" if palace.is_body_palace else ""),
            size=20,
            color=TEAL,
            **{"font-weight": "bold"},
        )
        for n, (label, color, attrs) in enumerate(lines):
            _text(group, x + 14, y + 68 + n * 23, label, size=16, color=color, **attrs)
    x, y = cell_width + 26, top + cell_height + 44
    summary = [
        "出生：" + _date(chart.birth.resolved_datetime),
        f"地點：{chart.birth.place.name}　{chart.birth.place.timezone}",
        f"經緯度：{chart.birth.place.longitude}, {chart.birth.place.latitude}",
        "農曆：" + chart.lunar_date,
        f"命主：{chart.soul}　身主：{chart.body}",
        f"{chart.five_elements_class}　子斗：{chart.zi_dou}",
    ]
    if len(layers) > 1:
        summary.extend(
            [
                "查詢：" + _date(chart.query_datetime),
                f"{chart.query_lunar_date}　虛歲 {chart.nominal_age}",
                ("童限：" if chart.is_childhood else "大限：") + chart.current_luck.gan_zhi,
            ]
        )
    for layer in layers:
        if layer == "natal":
            continue
        cycle = cycles[layer]
        summary.append(
            f"{LAYER_LABELS[layer]}四化："
            + "　".join(name + "化" + kind for name, kind in zip(cycle.mutagens, "祿權科忌"))
        )
        if layer in ("yearly", "monthly"):
            period = cycles[layer]
            summary.extend(
                [
                    ("農曆流月：" if layer == "monthly" else "農曆流年：") + period.gan_zhi,
                    _date(period.starts_at),
                    "至 " + _date(period.ends_at) + "（不含）",
                ]
            )
    summary.extend(
        [
            "本命四化保留於星曜旁；運程不覆蓋本命。",
            f"引擎 izthon {chart.engine_version}",
            f"規則 {chart.rules_version}　版面 ziwei-svg-v1",
        ]
    )
    for value in summary:
        for part in _wrap(value, 76):
            _text(svg, x, y, part, size=16)
            y += 28
    if y > top + 3 * cell_height - 16:
        raise ValueError("The chart summary exceeds the available layout area.")
    _text(
        svg,
        24,
        height - 15,
        "參考規則已校準指定本命案例；其他流派與指定文墨流盤仍需獨立核對。",
        size=14,
        color=MUTED_INK,
    )
    return tostring(svg, encoding="unicode")


def render_bazi_svg(chart: BaziChart) -> str:
    if not isinstance(chart, BaziChart):
        raise ValueError("chart must be a BaziChart.")
    width, row_height = 1400, 54
    subtitle = f"出生：{_date(chart.birth.resolved_datetime)}　{chart.birth.place.name}　{chart.birth.place.timezone}"
    subtitle_lines = _wrap(subtitle, 150)
    top = max(160, 95 + len(subtitle_lines) * 23)
    height = top + 7 * row_height + 180 + len(chart.luck_periods) * 58 + 80
    svg = _document(
        width,
        height,
        "八字｜本命・大運・節氣流年流月",
        "四柱由畫面左至右為時、日、月、年；每柱有明確標題。",
    )
    for i, line in enumerate(subtitle_lines):
        _text(svg, 24, 68 + i * 22, line, size=16)
    _text(
        svg,
        24,
        top - 35,
        "查詢：" + _date(chart.query_datetime) + "　｜時間基準：出生地民用時間",
        size=16,
    )
    pillars = (chart.hour, chart.day, chart.month, chart.year)
    values = [
        ("四柱", ("時柱", "日柱", "月柱", "年柱")),
        (
            "天干十神",
            tuple("日主（比肩）" if i == 1 else p.stem_ten_god for i, p in enumerate(pillars)),
        ),
        ("天干", tuple(p.gan_zhi[0] for p in pillars)),
        ("地支", tuple(p.gan_zhi[1] for p in pillars)),
        ("五行（干／支）", tuple("／".join(p.elements) for p in pillars)),
        ("藏干", tuple("、".join(p.hidden_stems) for p in pillars)),
        ("藏干十神", tuple("、".join(p.hidden_ten_gods) for p in pillars)),
    ]
    for row, (label, cells) in enumerate(values):
        y = top + row * row_height
        _rect(svg, 16, y, 190, row_height, TEAL_TINT)
        _text(svg, 30, y + 34, label, size=17, color=TEAL)
        for column, value in enumerate(cells):
            x = 206 + column * 294
            _rect(svg, x, y, 294, row_height, AMBER_TINT if column == 1 else "#ffffff")
            _text(svg, x + 14, y + 34, value, size=28 if row in (2, 3) else 17)
    y = top + 7 * row_height + 36
    offset = chart.luck_start_offset
    _text(
        svg,
        24,
        y,
        f"{'順行' if chart.luck_forward else '逆行'}　出生後 {offset[0]} 年 {offset[1]} 月 {offset[2]} 日 {offset[3]} 小時起運；起運：{_date(chart.luck_starts_at)}",
        size=16,
    )
    y += 38
    current = chart.current_luck
    _text(
        svg,
        24,
        y,
        "目前大運：" + (current.pillar.gan_zhi if current else "尚未起運"),
        size=21,
        color=TEAL,
        **{"font-weight": "bold"},
    )
    for label, period in (("節氣流年", chart.flow_year), ("節氣流月", chart.flow_month)):
        y += 32
        _text(
            svg,
            24,
            y,
            f"{label}：{period.pillar.gan_zhi}（{period.pillar.stem_ten_god}）　{_date(period.starts_at)} 至 {_date(period.ends_at)}（不含）",
            size=16,
        )
    y += 24
    for period in chart.luck_periods:
        selected = period == current
        _rect(svg, 16, y, width - 32, 58, TEAL_TINT if selected else "#ffffff")
        _text(
            svg,
            30,
            y + 23,
            ("目前 → " if selected else "")
            + period.pillar.gan_zhi
            + "　"
            + period.pillar.stem_ten_god,
            size=18,
            color=TEAL if selected else INK,
        )
        _text(
            svg,
            30,
            y + 46,
            _date(period.starts_at) + " 至 " + _date(period.ends_at) + "（不含）",
            size=15,
        )
        y += 58
    _text(
        svg,
        24,
        height - 35,
        f"引擎 lunar-python {chart.engine_version}　規則 {chart.rules_version}　版面 bazi-svg-v1",
        size=14,
    )
    _text(
        svg,
        24,
        height - 13,
        "出生時間若為估計，起運時刻不代表具有相同真實精度；未啟用真太陽時校正。",
        size=14,
        color=MUTED_INK,
    )
    return tostring(svg, encoding="unicode")


def render_western_svg(chart: WesternChart) -> str:
    if not isinstance(chart, WesternChart):
        raise ValueError("chart must be a WesternChart.")
    width = 1400
    height = 1560 + len(chart.aspects) * 28
    svg = _document(
        width,
        height,
        "西洋占星｜本命",
        "回歸黃道、地心視位置、Placidus；圖上的行星位置對應原始黃經。",
    )
    for i, part in enumerate(
        _wrap(
            f"出生：{_date(chart.birth.resolved_datetime)}　{chart.birth.place.name}　{chart.birth.place.timezone}",
            150,
        )
    ):
        _text(svg, 24, 70 + i * 23, part, size=16)
    center_x, center_y, radius = 700, 560, 360
    reference = chart.ascendant if chart.ascendant is not None else 0
    wheel_stroke = "#788981"

    def point(longitude, distance):
        angle = radians(longitude - reference)
        return center_x - distance * cos(angle), center_y + distance * sin(angle)

    def line(first, second, color=wheel_stroke, **attrs):
        SubElement(
            svg,
            "line",
            {
                "x1": str(first[0]),
                "y1": str(first[1]),
                "x2": str(second[0]),
                "y2": str(second[1]),
                "stroke": color,
                **attrs,
            },
        )

    for distance in (radius, radius + 44, 270):
        SubElement(
            svg,
            "circle",
            {
                "cx": str(center_x),
                "cy": str(center_y),
                "r": str(distance),
                "fill": "none",
                "stroke": wheel_stroke,
            },
        )
    for i, sign in enumerate(SIGNS):
        line(point(i * 30, radius), point(i * 30, radius + 44))
        x, y = point(i * 30 + 15, radius + 22)
        _text(svg, x, y + 6, sign, size=19, color=TEAL, **{"text-anchor": "middle"})
    if chart.house_cusps:
        for i, cusp in enumerate(chart.house_cusps):
            line(point(cusp, 270), point(cusp, radius), **{"data-house-index": str(i + 1)})
            span = (chart.house_cusps[(i + 1) % 12] - cusp) % 360
            x, y = point(cusp + span / 2, 343)
            _text(svg, x, y, i + 1, size=15, **{"text-anchor": "middle"})
        for name, angle in (("ASC", chart.ascendant), ("MC", chart.midheaven)):
            x, y = point(angle, radius + 68)
            _text(svg, x, y, name, size=20, color=TEAL, **{"text-anchor": "middle"})
    else:
        _text(
            svg,
            700,
            130,
            "Placidus 宮位不可用；此圖僅顯示黃道位置與天體相位。",
            color=AMBER,
            **{"text-anchor": "middle"},
        )
    by_code = {p.code: p for p in chart.planets}
    aspect_dashes = {60: "6 4", 90: "2 3", 180: "2 3"}
    for aspect in chart.aspects:
        if aspect.angle == 0:
            continue
        first, second = by_code[aspect.first], by_code[aspect.second]
        line(
            point(first.longitude, 270),
            point(second.longitude, 270),
            AMBER if aspect.angle in (90, 180) else TEAL,
            **{
                "stroke-dasharray": aspect_dashes.get(aspect.angle, "none"),
                "opacity": "0.75",
            },
        )
    labels = {-1: [], 1: []}
    for planet in chart.planets:
        x, y = point(planet.longitude, 305)
        SubElement(
            svg,
            "circle",
            {
                "cx": str(x),
                "cy": str(y),
                "r": "4",
                "fill": TEAL,
                "data-planet": planet.code,
            },
        )
        side = -1 if x < center_x else 1
        labels[side].append([max(170, min(930, y)), planet, (x, y)])
    for side, entries in labels.items():
        entries.sort(key=lambda entry: entry[0])
        for i in range(1, len(entries)):
            entries[i][0] = max(entries[i][0], entries[i - 1][0] + 27)
        if entries and entries[-1][0] > 930:
            entries[-1][0] = 930
            for i in range(len(entries) - 2, -1, -1):
                entries[i][0] = min(entries[i][0], entries[i + 1][0] - 27)
        for y, planet, marker in entries:
            x = 265 if side < 0 else 1135
            line(marker, (x, y - 5))
            label = f"{planet.name} {format_zodiac(planet.longitude)}" + (
                " R" if planet.retrograde else ""
            )
            _text(
                svg,
                x - 7 if side < 0 else x + 7,
                y,
                label,
                size=16,
                **{"text-anchor": "end" if side < 0 else "start"},
            )
    _text(
        svg,
        24,
        1008,
        "R 表示逆行。相位線：長虛線＝六分相，實線＝三分相，點線＝四分相／對分相。合相見下表。",
        size=15,
        color=MUTED_INK,
    )
    y = 1040
    _text(
        svg,
        24,
        y,
        "天體　｜星座內度數　｜黃經　｜黃緯　｜黃經速度（度／日）　｜宮位",
        size=18,
        color=TEAL,
        **{"font-weight": "bold"},
    )
    for planet in chart.planets:
        y += 32
        _text(
            svg,
            24,
            y,
            f"{planet.name}　{planet.sign} {planet.sign_longitude:.4f}°　｜{planet.longitude:.6f}°　｜{planet.latitude:.6f}°　｜{planet.longitude_speed:.6f}"
            + (" R" if planet.retrograde else "")
            + f"　｜{planet.house if planet.house else '不可用'}",
            size=16,
        )
    y += 42
    _text(
        svg,
        24,
        y,
        "主要相位｜合相／六分相／四分相／三分相／對分相，統一容許度 6°（含）",
        size=18,
        color=TEAL,
        **{"font-weight": "bold"},
    )
    for aspect in chart.aspects:
        y += 28
        _text(
            svg,
            24,
            y,
            f"{by_code[aspect.first].name}－{by_code[aspect.second].name}：{aspect.name}　夾角 {aspect.separation:.4f}°　容許度差 {aspect.orb:.4f}°",
            size=15,
        )
    _text(
        svg,
        24,
        height - 78,
        f"pyswisseph {chart.engine_version}／Swiss Ephemeris {chart.swiss_ephemeris_version}　規則 {chart.rules_version}　版面 western-svg-v1",
        size=14,
    )
    _text(svg, 24, height - 52, "星曆來源版本：" + chart.ephemeris_revision, size=14)
    _text(
        svg,
        24,
        height - 26,
        "位置與計算使用完整精度；圖上度數為格式化顯示。宮位不可用時不擅自改用其他宮位制。",
        size=14,
    )
    return tostring(svg, encoding="unicode")
