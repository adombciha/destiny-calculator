# Destiny Calculator

本機 Streamlit 命盤工具。輸入一次出生資料後，可查看紫微斗數、八字、西洋占星、印度占星、七政四餘與河洛理數。介面提供運限時間軸、原有三種 SVG 命盤和各系統的 JSON 報告。

## 本機 GUI

在專案根目錄安裝介面與天文排盤的可選依賴，並取得固定版本的官方星曆。

```bash
uv pip install --python .venv/bin/python -e '.[ui,western]'
.venv/bin/python scripts/download_ephemeris.py
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

瀏覽器開啟 **http://127.0.0.1:8501**。在主畫面的出生資料區可使用預填的公開示範資料，或輸入出生日期、當地時間與傳統排運性別。出生地可搜尋城市，或手動填寫地點名稱、經緯度與 IANA 時區。

查詢時間可使用目前時間，或指定出生地的日期與時間。當出生或查詢時間因夏令時間等時區調整而出現兩次，展開「進階時間設定」，在對應欄位選擇第一次或第二次。確認後按「開始排盤」。

結果區顯示最後一次提交的出生資料及目前查詢時間。選「編輯出生資料」可回到表單修改並重新排盤。切換命盤分頁後，可展開完整資料表，也可選「查看原尺寸命盤」放大閱讀。

- **紫微斗數**提供本命、大限、流年、流月，可在其他圖層加顯大限。月份導覽依農曆月及閏月分段切換。
- **八字**顯示四柱、藏干、十神、起運及當前大運。節氣年月區間顯示精確起訖，月份導覽依節氣切換。
- **西洋占星**顯示本命圓盤，並提供年度小限、法達星限和福點／精神點黃道分期。
- **印度占星**顯示 Lahiri D1、D9、D10、月宿與 Vimshottari 的三層運限。
- **七政四餘**顯示十一曜、命宮、宿度、十干化曜與童限、大限、小限及生日行度。
- **河洛理數**顯示先後天卦、元堂、大運爻和流年卦爻。
- **運限時間軸**用同一段日期比較上述四套運限。可直接跳到指定日期，並查看當期及完整區段。「多年瀏覽與 JSON 匯出範圍」控制回溯與預測年數。

每個系統可下載單盤 JSON。紫微、八字與西洋本命另提供 SVG。「下載合併 JSON 報告」包含所有可用命盤及個別計算錯誤。「清除資料與結果」清除本次連線的輸入與結果。出生資料預設僅暫存於本機記憶體，下載的 SVG 與 JSON 含出生資訊。

本機已在 Python 3.15.2、Linux／WSL 驗證 Streamlit 1.66.1 與 pyswisseph 2.10.3.2。若編譯時找不到 Python 建置設定中的 `clang`，可指定本機已安裝的編譯器後重試：

```bash
CC=cc CXX=c++ uv pip install --python .venv/bin/python -e '.[ui,western]'
```

西洋套件採 AGPL；目前為本機使用，對外發布或提供公開服務前須確認適用授權。Windows 原生與 macOS 尚未驗證。SVG 依讀取裝置的中文字型呈現，建議具備 Microsoft JhengHei、Noto Sans CJK TC 或 PingFang TC。

## 環境與安裝

使用 Python **3.15.2**。已建立本機環境時：

```bash
source .venv/bin/activate
uv pip install --python .venv/bin/python -e .
```

新環境須先準備 Python 3.15.2，再執行：

```bash
python3.15 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

共用時間核心使用標準庫，八字引擎固定採用 `lunar-python==1.4.8`，紫微引擎固定採用 `izthon==0.2.0`；安裝時會使用 setuptools 作為建置工具。時區資料取自作業系統的 IANA 資料庫，部署環境必須提供相關資料；目前已在 Linux／WSL 驗證。

## 使用方式

```python
from datetime import datetime

from destiny_calculator import BirthData, get_city

birth = BirthData(
    local_datetime=datetime(2000, 8, 16, 4, 0),
    place=get_city("臺北"),
    gender="female",
)

print(birth.resolved_datetime.isoformat())
# 2000-08-16T04:00:00+08:00
print(birth.utc_datetime.isoformat())
# 2000-08-15T20:00:00+00:00

query = birth.resolve_query_time(datetime(2026, 10, 28, 12, 0))
print(query.isoformat())
# 2026-10-28T12:00:00+08:00
```

出生時間使用不含 `tzinfo` 的 `datetime`，精確到分鐘，秒與微秒必須為零；地點提供明確的 IANA 時區。出生及查詢日期限當地西曆 1900-01-01 至 2099-12-31，查詢時刻不得早於出生時刻。`gender` 為傳統排運使用的 `male` 或 `female`。

`birth.local_datetime` 保留輸入，`resolved_datetime` 保留換算後的當地時間與有效 `fold`，`utc_datetime` 提供 UTC。`birth.resolve_query_time()` 未指定時間時，使用目前瞬間在出生地的當地時間。

## 八字試排

```python
from datetime import datetime

from destiny_calculator import BirthData, calculate_bazi, get_city

birth = BirthData(datetime(2000, 8, 16, 4, 0), get_city("臺北"), "female")
chart = calculate_bazi(birth, datetime(2026, 10, 28, 12, 0))

print(" ".join(p.gan_zhi for p in (chart.year, chart.month, chart.day, chart.hour)))
# 庚辰 甲申 丙午 庚寅
print(chart.luck_starts_at.isoformat())
# 2003-07-01T00:00:00+08:00
print(chart.current_luck.pillar.gan_zhi)
# 辛巳
print(chart.flow_year.pillar.gan_zhi, chart.flow_month.pillar.gan_zhi)
# 丙午 戊戌
```

每柱包含 `gan_zhi`、`hidden_stems`、`elements`、`stem_ten_god` 與 `hidden_ten_gods`。十神一律相對本命日干，日柱天干與自身的關係為比肩；未提供旺衰或五行加權評分。

`luck_periods` 列出支援查詢範圍內的大運；`current_luck` 在起運前為 `None`。大運、流年及流月均包含 `starts_at` 與 `ends_at`，以開始包含、結束不包含的區間表示。`luck_start_offset` 依序為起運年、月、日、小時，`engine_version` 與 `rules_version` 記錄計算基線。

計算採以下固定規則：

- 年柱以立春、月柱以十二個「節」的精確時刻切換。
- 日柱使用當地民用日期及 `sect=2` 晚子時規則，日柱與時柱保留套件原始組合；不校正真太陽時。
- 節氣與起運使用引擎的固定 UTC+8 時間基準，結果轉回出生地時區；不用歷史 `Asia/Shanghai` 時區取代固定 UTC+8。
- 起運使用 `getYun(gender, 2)` 分鐘差折算；大運從實際起運時刻每十個 UTC+8 西曆年切換，閏日沿用引擎的日期修正規則，不以一月一日切換。
- 省略查詢時間時使用出生地目前時刻。若查詢時間有夏令時間歧義，`calculate_bazi(..., fold=1)` 的 `fold` 是查詢時刻的選擇。

八字算法及曆法來源為 [lunar-python](https://github.com/6tail/lunar-python)，採 [MIT 授權](https://github.com/6tail/lunar-python/blob/v1.4.8/LICENSE)。目前已核對計畫中的三個上游案例與節氣邊界，結果仍應以相同流派設定的參考盤進一步比對。

## 紫微試排

```python
from datetime import datetime

from destiny_calculator import BirthData, calculate_ziwei, get_city

birth = BirthData(datetime(2000, 8, 16, 4, 0), get_city("臺北"), "female")
chart = calculate_ziwei(birth, datetime(2023, 8, 19, 3, 12))

print(chart.lunar_date, chart.soul, chart.body, chart.five_elements_class)
# 二〇〇〇年七月十七 廉貞 文昌 木三局
soul_palace = next(p for p in chart.palaces if p.name == "命宮")
print(soul_palace.gan_zhi, soul_palace.decadal_age_range)
# 壬午 (3, 12)
print(chart.nominal_age, chart.current_luck.gan_zhi)
# 24 庚辰
print(chart.flow_year.gan_zhi, chart.flow_month.gan_zhi)
# 癸卯 庚申
print(chart.flow_month.starts_at.isoformat(), chart.flow_month.ends_at.isoformat())
# 2023-08-16T00:00:00+08:00 2023-09-15T00:00:00+08:00
```

`palaces` 依寅至丑排列，索引為 0 至 11，每宮保留干支、身宮標記、主輔雜曜、生年四化、大限虛歲範圍、小限年齡 `ages`、流年虛歲 `yearly_ages` 及各組十二神。`zi_dou` 提供子年斗君。每顆星包含 `name`、`brightness`、`mutagen`；來源表留白或未收錄的亮度、沒有四化的星曜以 `None` 表示。結果使用不可變 dataclass 與 tuple，不保留可變的引擎物件。

`current_luck`、`flow_year`、`flow_month` 各自保留命宮 `index`、`gan_zhi`、十二宮的 `palace_names`、四化星名 `mutagens`，以及依本命宮索引排列的運限星曜 `stars`。`mutagens` 的四顆星依序為祿、權、科、忌；生年四化在本命星曜，運限四化分開保留。

`nominal_age` 是查詢虛歲；`is_childhood=True` 表示尚未進入首個大限，此時 `current_luck` 是引擎童限。正式大限的歲數範圍可由 `palaces[current_luck.index].decadal_age_range` 取得，依農曆新年增歲，與八字的起運時間分開處理。

流年、流月提供有時區的 `starts_at`、`ends_at`，開始包含、結束不包含。閏月初一至十五日、十六日至月底分成兩個期間；即使相鄰月份盤面相同，仍保留各自農曆期間。十二宮、運限宮名與四化資料可用於 SVG 疊盤；目前提供 SVG 與 JSON，尚無 PNG 或 PDF 匯出 API。

固定規則與限制：

- 天盤，十四主星及運程保留 `algorithm=default`；出生年、流年、虛歲以農曆新年切換，流月依農曆月與閏月修正，不用八字節氣月。
- 本命校準規則版本為 `ziwei-reference-v2`：命主按生年地支取星；補齊截空／副截、旬空／副旬、年支大耗，以及龍德、劫煞。兩組空曜的正副依年干陰陽選取，不整套切換至 zhongzhou，保留已核對的天傷、天使位置。
- 顯示統一為交友宮、三臺、臺輔；歲前十二神的大耗名稱校為歲破，博士十二神的官府顯示為參考盤的官符，兩個星系仍各自保留，沒有全域合併同名星。
- 出生與查詢使用出生地的當地民用日期、時辰，不校正真太陽時；23 時使用引擎 `forward` 晚子時安星規則。閏月十五日後安星的晚子時例外沿用引擎，不能當作整盤所有欄位都前進一天。
- 支援出生日期 **1900-01-31 至 2099-12-31**；早於引擎農曆資料起點、超出十二個大限的查詢，均明確拋出 `ValueError`。
- 查詢時區歧義沿用 `calculate_ziwei(..., fold=1)`；省略查詢時使用出生地目前時刻。
- 每次傳入完整固定設定，避免外部引擎設定影響四化或亮度，並記錄 `engine_version` 與 `rules_version`。
- 已納入 iztro 2.6.1 的酉宮太陽、太陰、七殺亮度修正，另以附有 MIT 授權及固定來源版本的完整十二地支資料列，補充 40 顆輔雜曜的亮度；沒有依個人出生日期硬填答案。
- 與使用者提供的文墨本命參考逐欄核對：70 個主輔雜曜的位置／名稱、60 項亮度、十二宮干支與身宮、命主／身主／子斗、大限歲數、流年／小限歲數及各組十二神一致。這個結果只代表該參考案例，不代表其他日期、流派或流年流月已全面相容。
- 出生時刻若僅為估計，計算結果也應視為對應該估計值；起運日期及小時不代表能確認到相同精度。命理格局、八字貴人及文字解讀尚未自動產生。

紫微算法來源為 [izthon](https://github.com/TaoracleHQ/izthon) 與 [iztro](https://github.com/SylarLong/iztro)，均採 MIT 授權；亮度修正依據 [iztro 原始修正](https://github.com/SylarLong/iztro/commit/bb1781cc5da481b1e741ec4da4e4936e91ab6a36)。目前的原版對照及公開案例驗證，不等於所有日期、流派與海外地方農曆均已獨立驗證。

輔雜曜亮度資料取自 [ziwei-doushu 的固定版本資料表](https://github.com/Renhuai123/ziwei-doushu/blob/ff9a1470ebe652e57b9d690f5d01db9a04f47aae/lib/ziwei/school-tables.generated.ts)，星名對照依 [school-data.ts](https://github.com/Renhuai123/ziwei-doushu/blob/ff9a1470ebe652e57b9d690f5d01db9a04f47aae/lib/ziwei/school-data.ts)，只取所需的輔雜曜資料並統一繁體名稱；來源、地支順序、亮度編碼與完整 MIT 授權一同保存在 `data/ziwei_brightness.json`。該資料表為第三方參考，不是文墨天機官方公開表。

## 西洋本命與匯出 API

```python
from datetime import datetime
from pathlib import Path
from destiny_calculator import (
    BirthData, get_city, calculate_bazi, calculate_ziwei, calculate_western,
    render_bazi_svg, render_ziwei_svg, render_western_svg, export_report_json,
)

birth = BirthData(datetime(2000, 8, 16, 4), get_city("臺北"), "female")
query = datetime(2026, 10, 28, 12)
bazi = calculate_bazi(birth, query)
ziwei = calculate_ziwei(birth, query)
western = calculate_western(birth, ephemeris_path=Path("data/ephemeris"))
print(round(western.ascendant, 6), round(western.midheaven, 6))
# 123.246063 28.052252

ziwei_svg = render_ziwei_svg(ziwei, layers=("natal", "decadal", "yearly", "monthly"))
bazi_svg = render_bazi_svg(bazi)
western_svg = render_western_svg(western)
report_json = export_report_json((bazi, ziwei, western))
```

渲染函式回傳獨立 SVG 字串，匯出函式回傳 UTF-8 JSON 字串，不自行寫入檔案。`export_chart_json(chart)` 可匯出單盤；合併報告會拒絕出生資料不同、重複系統或中式查詢時刻不一致的資料。`destiny-report-v1` 保留 UTC、IANA 時區、原始民用輸入、各系統狀態、規則版本、四化層、原始角度及星曆識別。純西洋本命匯出沒有運程查詢時刻，該欄為 null。

西洋使用回歸黃道、地心視位置、Placidus、十天體；相位為合／六分／四分／三分／對分，統一容許度 6°，不包含 ASC／MC 相位。UTC 透過 Swiss Ephemeris 轉為 TT／UT1；1972 年前及遠期日期沿用引擎時間模型，不能視為實測地球自轉資料。高緯度宮位無解時保留天體及相位，宮頭／角點／落宮留空，JSON 狀態為 partial，不改用其他宮位制。

星曆固定為官方 [Swiss Ephemeris commit ad0935c2](https://github.com/aloistr/swisseph/tree/ad0935c2993405b57db161240e0af7e451840efd/ephe) 的 DE431 資料；來源與兩檔 SHA-256 在 `data/ephemeris_manifest.json`。實際星曆位於專案的 `data/ephemeris/`，受 Git 忽略，未包含在 Python 套件內；更換工作目錄呼叫 API 時請傳絕對路徑。缺檔、雜湊不符或回傳模式退回 Moshier 均報錯，不在計算時自動下載。

## 運限規則與 JSON

- **西洋時間主星**依出生地太陽真高度判定日夜。年度小限用生日與整宮守護星，閏日生在平年以 2 月 28 日換段。法達以 Abu Maʿshar 日夜順序排列，交點置於首輪末尾，75 年後沿用同序循環。黃道分期採 Valens 福點／精神點、360 日年、30 日月及前兩層，次期走完一圈後按原典跳至對宮。 [《Anthologies》卷四](https://raw.githubusercontent.com/janegca/latex-valens/main/Valens-Anthologies-Annotated.pdf) · [法達規則引文](https://birchfieldastrology.com/wp-content/uploads/2020/07/firdar_revision-02-2020-07-13.pdf)
- **印度占星**採 Lahiri、地心、平均羅喉與整宮。Vimshottari 依月亮宿內黃經弧長算出生餘運，每年 365.2425 日，涵蓋出生後 120 個固定年。 [分盤與大運算例](https://www.vedicastrologer.org/articles/vedic_astro_textbook.pdf)
- **七政四餘**使用 Swiss Ephemeris 七曜、平均月交點和平均月球遠地點。紫炁採明代躔度為錨點與 10,228 日週期。二十八宿採《新法曆書》1628 年固定黃道宿界。命宮用當地視太陽時支，十干化曜用 UTC+8 立春年干。童限與百六大限用等寬宮位換算，行度輸出各生日的快照。採用當日距星、不同交點或古制不等宮的排盤會出現差異。 [黃道宿度表](https://zh.wikisource.org/zh-hant/欽定古今圖書集成/曆象彙編/曆法典/第053卷) · [《張果星宗》影印](https://zh.wikisource.org/wiki/Index:Gujin_Tushu_Jicheng,_Volume_468_(1700-1725).djvu) · [紫炁推算考證](https://faculty.ustc.edu.cn/niuweixing/en/lwcg/64060/content/20711.htm)
- **河洛理數**採 1929 年文明書局本。以現有八字四柱起卦、按農曆正月初一換流年，先天與後天各走六爻。農曆閏月沿用原月序。 [《河洛理數》卷一](https://www.shidianguji.com/zh/book/NA09030/chapter/1m8od60nhc1me)

`calculate_jyotish(birth, ephemeris_path=...)`、`calculate_qizheng(birth, ephemeris_path=...)` 與 `calculate_heluo(birth)` 回傳本命及運限資料。`calculate_western_timing(western_chart, through=...)` 以已算好的西洋本命盤產生時間主星。

`export_report_json(charts, query_datetime=query, timing_years=(2, 5))` 會在 `results` 附加所選系統，西洋時間主星放在 `results.western.data.timing`。`timing.starts_at` 和 `timing.ends_at` 為查詢時窗，`current` 為查詢時刻的區段，`periods` 為與時窗相交的區段及當期。每段附原始起訖，開始包含、結束不含。`export_chart_json` 支援相同參數。

## 自訂地點與夏令時間

內建 `list_cities()` 提供臺北、臺中、高雄。其他地點可自行指定經緯度及時區：

```python
from datetime import datetime

from destiny_calculator import BirthData, BirthPlace

place = BirthPlace("New York", 40.7, -74.0, "America/New_York")
birth = BirthData(datetime(2024, 11, 3, 1, 30), place, "male", fold=1)
print(birth.utc_datetime.isoformat())
# 2024-11-03T06:30:00+00:00
```

重複時刻若未指定 `fold`，會拋出 `AmbiguousTimeError`；`fold=0` 選擇第一次，`fold=1` 選擇第二次。不存在的時刻會拋出 `NonexistentTimeError`，不會自動修正。一般時刻的有效 `fold` 統一為 0。查詢時間適用相同驗證規則。

內建城市使用代表點。實際出生地座標可用 `dataclasses.replace(get_city("臺北"), latitude=..., longitude=...)` 修正；修改座標不會自動推測或更換時區。

## 測試

安裝專案後執行：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

測試涵蓋 UTC 跨日、臺灣歷史夏令時間、重複及不存在的時刻、半小時時區變更、整日跳過、日期範圍、非法座標與輸入，以及跨夏令時間的查詢先後順序。八字測試另涵蓋上游四柱及起運案例、晚子時、立春前後一秒、大運精確切換、海外節氣與當地日／時柱，以及查詢範圍兩端。

紫微測試涵蓋公開本命及運程案例、三顆星的酉宮亮度修正、農曆新年與月份切換、閏月分段、童限及大限切換、晚子時與閏月安星例外、日期及運限限制、查詢時區與外部設定隔離，以及六十甲子的正副空曜、亮度表星名與格式、子斗及流年歲數。個人參考盤只在記憶體中驗證，不寫入測試或文件。

## 城市資料來源

未安裝可選介面或天文依賴時，相關測試會跳過。核心 API 可獨立匯入。西洋、印度與七政的天文位置測試用同版 Swiss Ephemeris 原生 C ABI 和固定星曆核對。運限測試另涵蓋分盤界線、福點及精神點、對宮跳轉、生日行度及河洛古籍命例。

離線城市資料取自 [GeoNames](https://www.geonames.org/)，採 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)，查證日期為 2026-10-28。原始城市名稱改為繁體中文顯示；座標、時區、geonameid 與來源網址記錄於套件的 `data/cities.json`。

- [臺北](https://www.geonames.org/1668341/taipei.html)
- [臺中](https://www.geonames.org/1668399/taichung.html)
- [高雄](https://www.geonames.org/1673820/kaohsiung.html)

出生資料在本機處理。排盤由本機星曆和曆法套件計算，匯出由使用者觸發。
