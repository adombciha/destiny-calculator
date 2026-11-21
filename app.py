"""Local Streamlit interface for Chinese and Western natal charts."""

from base64 import b64encode
from datetime import UTC, date, datetime, time, timedelta
from functools import partial
from html import escape
from pathlib import Path

import streamlit as st

from destiny_calculator import (
    AmbiguousTimeError,
    BaziChart,
    BirthData,
    BirthPlace,
    NonexistentTimeError,
    calculate_bazi,
    calculate_ziwei,
    calculate_western,
    export_chart_json,
    export_report_json,
    get_city,
    list_cities,
    render_bazi_svg,
    render_ziwei_svg,
    render_western_svg,
    resolve_local_time,
)
from destiny_calculator.charts import ziwei_transformation_rows
from destiny_calculator.time_utils import DEFAULT_FLOW_YEARS, MAX_FLOW_YEARS
from destiny_calculator.western import WesternChart, format_zodiac
from destiny_calculator.ziwei import _browse_months, _browse_years


FOLDS = {"自動判定（重複時間需另選）": None, "第一次": 0, "第二次": 1}
SYSTEMS = {"ziwei": "紫微斗數", "bazi": "八字", "western": "西洋占星"}
MODES = {
    "本命": ("natal",),
    "大限": ("natal", "decadal"),
    "流年": ("natal", "yearly"),
    "流月": ("natal", "yearly", "monthly"),
}
EPHEMERIS_PATH = Path(__file__).resolve().parent / "data" / "ephemeris"


def calculate_results(birth, query):
    charts, errors = {}, {}
    for name, calculator in (("bazi", calculate_bazi), ("ziwei", calculate_ziwei)):
        try:
            charts[name] = calculator(birth, query.replace(tzinfo=None), fold=query.fold)
        except ValueError as error:
            errors[name] = str(error)
    try:
        charts["western"] = calculate_western(birth, ephemeris_path=EPHEMERIS_PATH)
    except ValueError as error:
        errors["western"] = str(error)
    return charts, errors


def adjacent_month_query(chart, direction):
    if direction not in (-1, 1):
        raise ValueError("direction must be -1 or 1.")
    birth = chart.birth
    period = chart.flow_month
    calculator = calculate_bazi if isinstance(chart, BaziChart) else calculate_ziwei
    if direction < 0 and period.starts_at.astimezone(UTC) <= birth.utc_datetime:
        return None
    target = (
        period.ends_at.astimezone(UTC)
        if direction > 0
        else period.starts_at.astimezone(UTC) - timedelta(seconds=1)
    )
    try:
        local = target.astimezone(birth.resolved_datetime.tzinfo)
        probe = calculator(birth, local.replace(tzinfo=None), fold=local.fold)
        target = max(probe.flow_month.starts_at.astimezone(UTC), birth.utc_datetime)
        local = target.astimezone(birth.resolved_datetime.tzinfo)
        return birth.resolve_query_time(local.replace(tzinfo=None), fold=local.fold)
    except ValueError:
        return None


def _reset_ziwei_browse(chart):
    st.session_state["ziwei_browse_anchor"] = chart
    st.session_state.pop("ziwei_browse_year", None)
    st.session_state.pop("ziwei_browse_period", None)


def _set_query(birth, query=None, *, ziwei_mode=None):
    try:
        resolved = birth.resolve_query_time() if query is None else query
        charts, errors = calculate_results(birth, resolved)
        if ziwei_mode is not None and "ziwei" not in charts:
            raise ValueError(errors["ziwei"])
        if not charts and errors:
            raise ValueError("；".join(f"{SYSTEMS[name]}：{error}" for name, error in errors.items()))
        st.session_state["report"] = (birth, resolved, charts, errors)
        st.session_state["query_date"] = resolved.date()
        st.session_state["query_time"] = resolved.timetz().replace(tzinfo=None)
        st.session_state["query_fold"] = "第二次" if resolved.fold else "第一次"
        st.session_state["use_now"] = query is None
        if query is None:
            _reset_ziwei_browse(charts.get("ziwei"))
        if ziwei_mode is not None:
            st.session_state["ziwei_mode"] = ziwei_mode
        st.session_state.pop("navigation_error", None)
    except ValueError as error:
        st.session_state["navigation_error"] = str(error)


def _clear():
    st.session_state.clear()


def _format(value):
    return value.isoformat(sep=" ", timespec="seconds")


def _input_error(error, local, place):
    if isinstance(error, AmbiguousTimeError):
        choices = [resolve_local_time(local, place.timezone, fold) for fold in (0, 1)]
        return "此當地時間因時區調整而出現兩次，請選第一次或第二次。" + "；".join(
            f"{'第一次' if i == 0 else '第二次'}：{_format(value)}，UTC {_format(value.astimezone(UTC))}"
            for i, value in enumerate(choices)
        )
    if isinstance(error, NonexistentTimeError):
        return "此當地時間因時區或夏令時間調整而不存在，請重新確認鐘錶時間。"
    return "請檢查日期、時間、座標與 IANA 時區；查詢不可早於出生。詳細原因：" + str(error)


def _keep_draft(defaults, visible):
    # Streamlit discards widget state when the widget is omitted from a run.
    state = st.session_state
    for key, default in defaults.items():
        saved_key = "draft_" + key
        if key in state:
            state[saved_key] = state[key]
        if visible:
            state.setdefault(key, state.get(saved_key, default))


def _birth_form():
    defaults = {
        "city": "臺北",
        "birth_date": date(2000, 8, 16),
        "birth_time": time(4),
        "gender": "女",
        "birth_fold": next(iter(FOLDS)),
        "use_now": True,
        "query_fold": next(iter(FOLDS)),
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)
    error_at, message, repeated = st.session_state.get("input_error", (None, "", False))

    st.subheader("出生資料")
    st.caption("初始值為公開示範資料。出生時間採當地鐘錶時間，填至分鐘。")
    city = st.selectbox("出生地", [c.name for c in list_cities()] + ["手動地點"], key="city")
    manual = city == "手動地點"
    _keep_draft(
        {"place_name": "手動地點", "timezone": "Asia/Taipei", "latitude": 25.05306, "longitude": 121.52639},
        manual,
    )
    if manual:
        place, zone = st.columns(2)
        place.text_input("地點名稱", max_chars=100, key="place_name")
        zone.text_input("IANA 時區", max_chars=100, key="timezone")
        north, east = st.columns(2)
        north.number_input("緯度（北正南負）", -90.0, 90.0, format="%.6f", key="latitude")
        east.number_input("經度（東正西負）", -180.0, 180.0, format="%.6f", key="longitude")
        if error_at == "地點":
            st.error(message)

    birth_day, birth_clock, gender = st.columns(3)
    birth_day.date_input(
        "出生日期（西元）",
        min_value=date(1900, 1, 1),
        max_value=date(2099, 12, 31),
        key="birth_date",
    )
    birth_clock.time_input("出生時間", step=60, key="birth_time")
    gender.selectbox("傳統排運性別", ["女", "男"], key="gender")
    if error_at == "出生時間" and not repeated:
        st.error(message)

    st.subheader("查詢時間")
    use_now = st.checkbox("使用目前時間查詢", key="use_now")
    _keep_draft({"query_date": date.today(), "query_time": time(12)}, not use_now)
    if use_now:
        st.caption("排盤時以出生地的目前時間查詢。取消勾選可指定時間。")
    else:
        query_day, query_clock = st.columns(2)
        query_day.date_input(
            "查詢日期（出生地時間）",
            min_value=date(1900, 1, 1),
            max_value=date(2099, 12, 31),
            key="query_date",
        )
        query_clock.time_input("查詢時間（含秒）", step=1, key="query_time")
    if error_at == "查詢時間" and not repeated:
        st.error(message)

    with st.expander("進階時間設定", expanded=repeated):
        st.caption("當地鐘錶因時區調整而出現兩次相同時間時，請選擇第一次或第二次。")
        st.selectbox("出生重複時刻", list(FOLDS), key="birth_fold")
        if error_at == "出生時間" and repeated:
            st.error(message)
        st.selectbox("查詢重複時刻", list(FOLDS), disabled=use_now, key="query_fold")
        if error_at == "查詢時間" and repeated and not use_now:
            st.error(message)

    st.caption("出生資料只在本次連線暫存。下載才會輸出檔案。")
    with st.container(horizontal=True):
        submitted = st.button("開始排盤", type="primary", key="submit_birth")
        st.button("清除資料與結果", type="tertiary", on_click=_clear)
    if not submitted:
        return

    with st.spinner("排盤中…"):
        _submit_birth()
    st.rerun()


def _submit_birth():
    state = st.session_state
    stage = "地點"
    try:
        place = (
            BirthPlace(state.place_name, state.latitude, state.longitude, state.timezone)
            if state.city == "手動地點"
            else get_city(state.city)
        )
        stage = "出生時間"
        local = datetime.combine(state.birth_date, state.birth_time)
        birth = BirthData(
            local, place, "male" if state.gender == "男" else "female", fold=FOLDS[state.birth_fold]
        )
        stage = "查詢時間"
        if state.use_now:
            query = birth.resolve_query_time()
        else:
            local = datetime.combine(state.query_date, state.query_time)
            query = birth.resolve_query_time(local, fold=FOLDS[state.query_fold])
        charts, errors = calculate_results(birth, query)
        state["report"] = (birth, query, charts, errors)
        _reset_ziwei_browse(charts.get("ziwei"))
        state.pop("navigation_error", None)
        state.pop("input_error", None)
    except ValueError as error:
        state.pop("report", None)
        _reset_ziwei_browse(None)
        state.pop("navigation_error", None)
        message = (
            "地點設定無效：" + str(error)
            if stage == "地點"
            else _input_error(error, local, place)
        )
        state["input_error"] = stage, message, isinstance(error, AmbiguousTimeError)


def _navigation(chart, name):
    previous = adjacent_month_query(chart, -1)
    following = adjacent_month_query(chart, 1)
    label = "節氣月" if name == "bazi" else "農曆月／分段"
    with st.container(horizontal=True):
        st.button(
            "← 上一" + label,
            key=name + "_previous",
            disabled=previous is None,
            on_click=_set_query,
            args=(chart.birth, previous),
        )
        st.button("回到現在", key=name + "_now", on_click=_set_query, args=(chart.birth,))
        st.button(
            "下一" + label + " →",
            key=name + "_next",
            disabled=following is None,
            on_click=_set_query,
            args=(chart.birth, following),
        )
    if previous is None or following is None:
        st.caption("停用的方向沒有可查詢的分段。")


def _chart_preview(chart, renderer, name, alt, *, json_years=None, **options):
    svg = None
    try:
        svg = renderer(chart, **options)
    except ValueError as error:
        st.warning(f"命盤圖無法繪製。仍可查看完整資料與下載 JSON。原因：{error}")
    if svg is not None:
        st.image(svg, width="stretch", alt=alt)
        with st.expander("查看原尺寸命盤"):
            label = escape(alt, quote=True)
            encoded = b64encode(svg.encode("utf-8")).decode("ascii")
            st.html(
                f'<div role="region" aria-label="{label}" tabindex="0" '
                'style="max-height:70vh;overflow:auto">'
                f'<img alt="{label}" src="data:image/svg+xml;base64,{encoded}" '
                'style="display:block;max-width:none"></div>'
            )
    suffix = "natal" if isinstance(chart, WesternChart) else chart.query_datetime.date().isoformat()
    with st.container(horizontal=True):
        if svg is not None:
            st.download_button(
                "下載此盤 SVG",
                svg,
                file_name=f"{name}-{suffix}.svg",
                mime="image/svg+xml",
                key=name + "_svg",
                on_click="ignore",
            )
        st.download_button(
            "下載此盤完整 JSON",
            export_chart_json(chart)
            if json_years is None
            else partial(export_chart_json, chart, ziwei_years=json_years, bazi_years=json_years),
            file_name=f"{name}-{suffix}.json",
            mime="application/json",
            key=name + "_json",
            on_click="ignore",
        )


def _bazi(chart, json_years):
    pillars = (("年柱", chart.year), ("月柱", chart.month), ("日柱", chart.day), ("時柱", chart.hour))
    with st.container(horizontal=True):
        for label, pillar in pillars:
            st.metric(label, pillar.gan_zhi, border=True, width=112)
    current = chart.current_luck
    if current is not None:
        st.write(f"**當前大運**　{current.pillar.gan_zhi} · {current.pillar.stem_ten_god}")
    else:
        st.write("**當前大運**　此查詢時刻無適用大運")
    _navigation(chart, "bazi")
    st.caption(
        f"節氣流年 {chart.flow_year.pillar.gan_zhi}：{_format(chart.flow_year.starts_at)} 至 {_format(chart.flow_year.ends_at)}（不含）"
    )
    st.caption(
        f"節氣流月 {chart.flow_month.pillar.gan_zhi}：{_format(chart.flow_month.starts_at)} 至 {_format(chart.flow_month.ends_at)}（不含）"
    )
    _chart_preview(
        chart, render_bazi_svg, "bazi", "八字四柱、大運及節氣流年流月命盤", json_years=json_years,
    )
    with st.expander("四柱與大運完整資料"):
        st.subheader("四柱", anchor=False)
        st.dataframe(
            [
                {
                    "柱": label,
                    "干支": p.gan_zhi,
                    "天干十神": p.stem_ten_god,
                    "五行（干／支）": "／".join(p.elements),
                    "藏干": "、".join(p.hidden_stems),
                    "藏干十神": "、".join(p.hidden_ten_gods),
                }
                for label, p in pillars
            ],
            hide_index=True,
        )
        st.subheader("大運", anchor=False)
        st.dataframe(
            [
                {
                    "大運": p.pillar.gan_zhi,
                    "十神": p.pillar.stem_ten_god,
                    "開始": _format(p.starts_at),
                    "結束（不含）": _format(p.ends_at),
                    "當前": p == chart.current_luck,
                }
                for p in chart.luck_periods
            ],
            hide_index=True,
        )


def _ziwei_browser(chart, years):
    with st.expander("紫微多年流年流月瀏覽", key="ziwei_browse_open", on_change="rerun") as panel:
        if not panel.open:
            return
        state = st.session_state
        anchor = state.get("ziwei_browse_anchor") or chart
        state["ziwei_browse_anchor"] = anchor
        st.caption(f"瀏覽基準 {_format(anchor.query_datetime)}。下載範圍以畫面目前的查詢時間起算。")
        year_ranges = {year: (start, end) for year, start, end in _browse_years(anchor, years)}
        if not year_ranges:
            st.info("這個範圍沒有可瀏覽的農曆期間。")
            return
        if state.get("ziwei_browse_year") not in year_ranges:
            state.pop("ziwei_browse_year", None)
        current = chart.query_datetime.astimezone(UTC)
        default_year = next(
            (
                year for year, (start, end) in year_ranges.items()
                if start.astimezone(UTC) <= current < end.astimezone(UTC)
            ),
            min(year_ranges),
        )
        year = st.number_input(
            "農曆年",
            min_value=min(year_ranges),
            max_value=max(year_ranges),
            value=default_year,
            key="ziwei_browse_year",
            on_change=state.pop,
            args=("ziwei_browse_period", None),
        )
        periods = {"流年": year_ranges[year]}
        periods.update({label: (start, end) for label, start, end in _browse_months(*year_ranges[year])})
        if state.get("ziwei_browse_period") not in periods:
            state.pop("ziwei_browse_period", None)
        selected = st.radio("流年或農曆月", tuple(periods), horizontal=True, key="ziwei_browse_period")
        start, end = periods[selected]
        if years == (0, 0):
            st.caption(f"當期查詢 {_format(anchor.query_datetime)}")
            query = anchor.query_datetime
        else:
            st.caption(f"有效期間 {_format(start)} 至 {_format(end)}（不含）")
            query = chart.query_datetime if start.astimezone(UTC) <= current < end.astimezone(UTC) else start
        if st.button("查看命盤", key="ziwei_browse_view"):
            mode = "流年" if selected == "流年" else "流月"
            # Apply the selection before the next run creates the query widgets.
            state["ziwei_browse_request"] = (chart.birth, query, mode)
            st.rerun()


def _ziwei(chart, json_years):
    _navigation(chart, "ziwei")
    _ziwei_browser(chart, json_years)
    columns = st.columns((3, 2))
    st.session_state.setdefault("ziwei_mode", "流月")
    mode = columns[0].radio("命盤層次", list(MODES), horizontal=True, key="ziwei_mode")
    extra = columns[1].checkbox("同時顯示大限", key="show_decadal", disabled=mode == "大限")
    layers = MODES[mode]
    if extra and "decadal" not in layers:
        layers = ("natal", "decadal", *layers[1:])
    st.caption(
        f"農曆流年 {chart.flow_year.gan_zhi}：{_format(chart.flow_year.starts_at)} 至 {_format(chart.flow_year.ends_at)}（不含）"
    )
    st.caption(
        f"農曆流月 {chart.flow_month.gan_zhi}：{_format(chart.flow_month.starts_at)} 至 {_format(chart.flow_month.ends_at)}（不含）"
    )
    st.caption(f"查詢農曆日期：{chart.query_lunar_date}。閏月前後段分開查詢。")
    with st.expander("四化總表（文字）"):
        st.table(
            [
                dict(zip(("層次", "祿", "權", "科", "忌"), (label, *stars)))
                for label, stars in ziwei_transformation_rows(chart)
            ]
        )
    _chart_preview(
        chart,
        render_ziwei_svg,
        "ziwei-" + MODES[mode][-1],
        "紫微十二宮：" + "、".join(
            label for label, mode_layers in MODES.items() if mode_layers[-1] in layers
        ),
        json_years=json_years,
        layers=layers,
    )
    with st.expander("十二宮完整資料"):

        def stars(values):
            return "、".join(
                s.name
                + (f"（{s.brightness}）" if s.brightness else "")
                + ("化" + s.mutagen if s.mutagen else "")
                for s in values
            )

        st.subheader("本命十二宮", anchor=False)
        st.dataframe(
            [
                {
                    "本命宮": p.name,
                    "干支": p.gan_zhi,
                    "身宮": p.is_body_palace,
                    "主星": stars(p.major_stars),
                    "輔星": stars(p.minor_stars),
                    "雜曜": stars(p.adjective_stars),
                    "大限虛歲": f"{p.decadal_age_range[0]}–{p.decadal_age_range[1]}",
                    "流年虛歲": ", ".join(map(str, p.yearly_ages)),
                    "小限虛歲": ", ".join(map(str, p.ages)),
                    "長生": p.changsheng_12,
                    "博士": p.boshi_12,
                    "將前": p.jiangqian_12,
                    "歲前": p.suiqian_12,
                }
                for p in chart.palaces
            ],
            hide_index=True,
        )
        for label, cycle in (
            ("大限／童限", chart.current_luck),
            ("流年", chart.flow_year),
            ("流月", chart.flow_month),
        ):
            st.subheader(f"{label} {cycle.gan_zhi}", anchor=False)
            st.caption("四化：" + "、".join(s + "化" + kind for s, kind in zip(cycle.mutagens, "祿權科忌")))
            st.dataframe(
                [
                    {
                        "本命宮": p.name,
                        "此層宮名": cycle.palace_names[p.index],
                        "運限星曜": stars(cycle.stars[p.index]),
                    }
                    for p in chart.palaces
                ],
                hide_index=True,
            )


def _western(chart):
    st.caption("西洋本命盤以出生瞬間計算。流年與流月查詢只影響紫微及八字。")
    alt = "西洋本命圓盤，含十天體及主要相位"
    if chart.house_status != "ok":
        st.warning("此地點與時刻的 Placidus 宮位不可用。仍可查看天體與相位。")
    else:
        alt = "西洋本命圓盤，含十天體、Placidus 宮位及主要相位"
        columns = st.columns(2)
        columns[0].metric("上升 ASC", format_zodiac(chart.ascendant))
        columns[1].metric("天頂 MC", format_zodiac(chart.midheaven))
    _chart_preview(chart, render_western_svg, "western", alt)
    with st.expander("天體、相位與宮位資料" if chart.house_cusps else "天體與相位資料"):
        st.subheader("天體", anchor=False)
        st.dataframe(
            [
                {
                    "天體": p.name,
                    "星座位置": format_zodiac(p.longitude),
                    "黃經": p.longitude,
                    "黃緯": p.latitude,
                    "距離 AU": p.distance_au,
                    "黃經速度（度／日）": p.longitude_speed,
                    "逆行": p.retrograde,
                    "宮號": p.house,
                }
                for p in chart.planets
            ],
            hide_index=True,
        )
        names = {p.code: p.name for p in chart.planets}
        st.subheader("相位", anchor=False)
        st.dataframe(
            [
                {
                    "天體一": names[a.first],
                    "天體二": names[a.second],
                    "相位": a.name,
                    "實際夾角": a.separation,
                    "容許度差": a.orb,
                }
                for a in chart.aspects
            ],
            hide_index=True,
        )
        if chart.house_cusps:
            st.subheader("宮頭", anchor=False)
            st.dataframe(
                [
                    {"宮號": i + 1, "宮頭": format_zodiac(c), "黃經": c}
                    for i, c in enumerate(chart.house_cusps)
                ],
                hide_index=True,
            )
        st.caption(
            f"固定星曆來源：{chart.ephemeris_revision}；Swiss Ephemeris {chart.swiss_ephemeris_version}。"
        )


def main():
    st.set_page_config(page_title="命盤計算器", layout="wide")
    browse_request = st.session_state.pop("ziwei_browse_request", None)
    if browse_request is not None:
        birth, query, mode = browse_request
        _set_query(birth, query, ziwei_mode=mode)
    # Download links from the previous report stay mounted while Streamlit reruns.
    st.html(
        '<style>[data-testid="stApp"]:is([data-test-script-state="running"],'
        '[data-test-script-state="rerunRequested"]) [data-testid="stDownloadButton"]'
        '{visibility:hidden}</style>'
    )
    st.title("命盤計算器", anchor=False)
    if "report" not in st.session_state:
        st.write("一次輸入出生資料，查看紫微斗數、八字與西洋本命盤。")
        with st.container(border=True):
            _birth_form()
        return

    birth, query, charts, errors = st.session_state["report"]
    with st.container(border=True):
        st.subheader("本次命盤", anchor=False)
        st.text(f"已提交的出生資料：{_format(birth.resolved_datetime)} · {birth.place.name}")
        st.text(f"查詢時間：{_format(query)} · {birth.place.timezone}")
    with st.expander("編輯出生資料"):
        st.caption("按「開始排盤」後才會更新結果。")
        _birth_form()

    if "navigation_error" in st.session_state:
        st.warning("查詢時間未更新，仍顯示上次結果。原因：" + st.session_state["navigation_error"])
    if not charts:
        st.error("三種命盤皆無法計算。請查看各分頁的原因，再重新排盤。")
    elif errors:
        st.warning("部分命盤無法計算：" + "、".join(SYSTEMS[name] for name in SYSTEMS if name in errors))
    flow_years = DEFAULT_FLOW_YEARS
    if "ziwei" in charts or "bazi" in charts:
        with st.expander("多年瀏覽與 JSON 匯出範圍"):
            st.caption("紫微瀏覽與兩種命盤的 JSON 共用年數。匯出以畫面目前的查詢時間為基準。")
            past, future = st.columns(2)
            flow_years = (
                past.number_input(
                    "回溯年數",
                    min_value=0,
                    max_value=MAX_FLOW_YEARS,
                    value=DEFAULT_FLOW_YEARS[0],
                    key="ziwei_years_before",
                ),
                future.number_input(
                    "預測年數",
                    min_value=0,
                    max_value=MAX_FLOW_YEARS,
                    value=DEFAULT_FLOW_YEARS[1],
                    key="ziwei_years_after",
                ),
            )
    if charts:
        st.download_button(
            "下載合併 JSON 報告" if not errors else "下載合併 JSON 報告（部分結果）",
            partial(
                export_report_json, tuple(charts.values()), errors=errors,
                ziwei_years=flow_years, bazi_years=flow_years,
            ),
            file_name=f"destiny-report-{query.date().isoformat()}.json",
            mime="application/json",
            key="report_json",
            on_click="ignore",
        )
    tabs = st.tabs(list(SYSTEMS.values()), key="chart_tabs", on_change="rerun")
    renderers = (
        ("ziwei", partial(_ziwei, json_years=flow_years)),
        ("bazi", partial(_bazi, json_years=flow_years)),
        ("western", _western),
    )
    for tab, (name, render) in zip(tabs, renderers):
        with tab:
            if name in charts:
                render(charts[name])
            else:
                st.warning(f"{SYSTEMS[name]}無法計算。原因：{errors[name]}")
    with st.expander("計算規則與資料來源"):
        for name, label in SYSTEMS.items():
            if name in charts:
                chart = charts[name]
                st.write(f"{label}｜引擎 {chart.engine_version}｜規則 {chart.rules_version}")
        st.caption(
            "八字以立春及十二節切換年月；紫微以農曆年月及閏月規則切換。出生採民用時間，未校正真太陽時。城市資料：GeoNames，CC BY 4.0；內建城市為代表座標，可改用手動地點。"
        )


if __name__ == "__main__":
    main()
