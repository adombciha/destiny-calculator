# Destiny Calculator

以 Python 建立紫微斗數、八字及西洋占星排盤工具。

目前已完成出生資料與時間驗證，以及八字四柱、藏干、十神、五行、大運、流年與流月計算。紫微、西洋占星與圖形介面尚未實作。

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

共用時間核心使用標準庫，八字引擎固定採用 `lunar-python==1.4.8`；安裝時會使用 setuptools 作為建置工具。時區資料取自作業系統的 IANA 資料庫，部署環境必須提供相關資料；本輪已在 Linux／WSL 驗證。

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

## 城市資料來源

離線城市資料取自 [GeoNames](https://www.geonames.org/)，採 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)，查證日期為 2026-10-28。原始城市名稱改為繁體中文顯示；座標、時區、geonameid 與來源網址記錄於套件的 `data/cities.json`。

- [臺北](https://www.geonames.org/1668341/taipei.html)
- [臺中](https://www.geonames.org/1668399/taichung.html)
- [高雄](https://www.geonames.org/1673820/kaohsiung.html)

目前在本機處理出生資料，沒有預設存檔或線上排盤請求。海外八字已驗證跨時區節氣切換與當地日／時柱的選定案例；紫微及西洋占星仍待後續階段接入。
