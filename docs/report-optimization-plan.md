# 報表可觀測性優化計畫（Report Optimization Plan）

> 老闆核准日：2026-07-05。來源：參考外部 AI 交易報表設計，擷取 6 項優化。
> 執行者：本計畫為弱模型執行而寫，**照本文執行，禁止自行發揮**。規格不清 → 停下問老闆。

---

## 0. 目標與範圍

把訊號決策從「一句 reason」升級為**可稽核的逐條件明細**，並補上資料品質告示、
決策下一步、具體價位、watchlist 新面孔標記、Run 資訊與免責聲明。

**本計畫全部是觀測層/展示層工作。鐵律：**

1. **不改任何訊號公式、門檻、決策矩陣**。S1/S2/S3 在相同輸入下的
   `state / direction / confidence / final_action / suggested_position_pct` 必須與改動前
   bit-identical。
2. **既有測試一個字都不能改**（`git diff tests/` 只允許新增檔案）。既有測試失敗
   = 你改壞了決策邏輯 → revert 重來，不准改測試遷就代碼。
3. 本計畫列出的 schema 欄位已由老闆核准，**除此之外不得動任何 schema**。
4. 不新增任何依賴。
5. 遵守專案 CLAUDE.md 全部紅線（禁 `git add -A`、push 前 py_compile + pytest、
   push 後煙霧測試、每 phase 更新 PROGRESS.md）。

**執行順序：A → B → D → C → E → F**（C 依賴 B 的 conditions；D 獨立所以提前）。
每個 Phase = 一輪完整開發循環 = 一個 commit + push + 煙霧測試。

---

## 1. 共用資料結構規格（附錄，先讀）

### 1.1 Condition dict（逐條件明細，#1）

```json
{
  "name": "nasdaq_threshold",        // 機器名，snake_case，固定不變
  "label": "NASDAQ 波動",            // 顯示名（繁中）
  "passed": true,                    // true / false / null（null = 因短路未評估）
  "actual": "+2.10%",                // 實際值（顯示用字串）
  "threshold": "±1.5%"               // 門檻（顯示用字串）
}
```

### 1.2 Quality note dict（資料品質註記，#2）

```json
{
  "source": "signals",               // signals | portfolio | watchlist
  "level": "warn",                   // info | warn
  "message": "NASDAQ 漲跌幅缺失，以 0.0 代入（訊號可信度降低）"
}
```

### 1.3 Key level dict（關鍵價位，#6）

```json
{
  "label": "QQQ 出場緩衝下緣",
  "value": 512.34,
  "note": "跌破則 S1 轉空"
}
```

---

## Phase A — Schema 遷移（4 個新欄位，一次到位）

### A1. `src/database/models.py`

| 表 | 新欄位 | 型別 |
|----|--------|------|
| `TrendSignal` | `conditions` | `Column(JSON)`（nullable，S1 條件明細）|
| `TimeDiffSignalRecord` | `conditions` | `Column(JSON)`（nullable，S2+S3 條件明細合併）|
| `TimeDiffSignalRecord` | `next_step` | `Column(String(300))`（nullable）|
| `WatchlistItem` | `is_new` | `Column(Boolean, default=False)` |

### A2. `src/database/__init__.py`

在既有的啟動時 ALTER 清單（約 44-47 行，`portfolio_positions` 那幾條旁邊）**追加**：

```python
"ALTER TABLE trend_signals ADD COLUMN IF NOT EXISTS conditions JSON",
"ALTER TABLE time_diff_signals ADD COLUMN IF NOT EXISTS conditions JSON",
"ALTER TABLE time_diff_signals ADD COLUMN IF NOT EXISTS next_step VARCHAR(300)",
"ALTER TABLE watchlist ADD COLUMN IF NOT EXISTS is_new BOOLEAN DEFAULT FALSE",
```

（照既有 try/except pass 慣例執行；SQLite 本地不支援 `IF NOT EXISTS` 會被 except
吃掉，屬預期行為。）

### A3. 本地開發庫

`zerohour_dev.db` 已 gitignore、可拋棄：直接刪除，啟動時 `create_all` 會以新 schema 重建。

### A4. 驗證與提交

```
python -m py_compile src/database/models.py src/database/__init__.py
python -m pytest tests/unit -x -q
```

commit：`feat: schema 新增訊號條件明細/next_step/watchlist is_new 欄位（報表優化 Phase A）`
push → 煙霧測試（Bash 工具）→ 更新 PROGRESS.md。

---

## Phase B — #1 逐條件明細（訊號層 → 落庫 → API → 前端）

### B1. `src/signals/time_diff.py`（S2）

1. `TimeDiffSignal` dataclass 加欄位：`conditions: list = field(default_factory=list)`。
2. `generate()` 開頭（在第一個 if 之前）**先算好全部 4 個 condition dict**。
   這些全是純比較/純函數，提前計算不影響任何決策：

   | # | name | label | passed | actual | threshold |
   |---|------|-------|--------|--------|-----------|
   | 1 | `nasdaq_threshold` | NASDAQ 波動 | `abs(nasdaq_change_pct) >= self.nasdaq_threshold` | `f"{nasdaq_change_pct:+.2f}%"` | `f"±{self.nasdaq_threshold}%"` |
   | 2 | `sp500_aligned` | S&P500 同向 | `(sp500_change_pct > 0) == (nasdaq_change_pct > 0)` | `f"{sp500_change_pct:+.2f}%"` | `"與 NASDAQ 同向"` |
   | 3 | `sox_aligned` | SOX 同向 | `(sox_change_pct > 0) == (nasdaq_change_pct > 0)` | `f"{sox_change_pct:+.2f}%"` | `"與 NASDAQ 同向"` |
   | 4 | `min_confidence` | 信心度 | `confidence >= self.min_confidence` | `f"{confidence:.2f}"` | `f"≥{self.min_confidence}"` |

   第 4 項的 confidence 用 `self._calc_confidence(nasdaq_change_pct, sp500_change_pct,
   sox_change_pct, sox_aligned)` 提前算（純函數）。**注意：這個提前算出的值只放進
   condition dict；既有流程中原本計算 confidence 的位置與用法一律不動。**
3. 既有的 if/return 結構**一行都不改**，只在每個 return 的 `TimeDiffSignal(...)` 補
   `conditions=conditions`；`_neutral()` 加參數 `conditions: list` 並傳入。

### B2. `src/signals/ma200_filter.py`（S1）

1. `MA200Signal` dataclass 加欄位：`conditions: list = field(default_factory=list)`。
2. 條件清單：

   | # | name | label | passed | actual | threshold |
   |---|------|-------|--------|--------|-----------|
   | 1 | `data_sufficient` | 資料量 | `len(price_data) >= self.period` | `f"{len(price_data)} 筆"` | `f"≥{self.period} 筆"` |
   | 2 | `price_vs_ma200` | 價格 vs MA200 | `current_price > ma200_val`（原始比較，非緩衝後結果）| `f"{current_price:.2f}"` | `f"MA200 {ma200:.2f}"` |
   | 3 | `buffer_band` | 緩衝帶 | 見下 | `f"{current_price:.2f}"` | `f"下緣 {lower:.2f} / 上緣 {upper:.2f}"` |

   - 資料不足的 early return：只帶條件 1（passed=False）。
   - `ma200_val` 為 NaN：條件 2 帶 `passed=False, actual="MA200 未成形"`。
   - 條件 3 **只在 hysteresis 生效時**（`state != UNDEFINED and prev_state not in
     (None, UNDEFINED)`）加入：`prev_state == BULL` 時 `passed = current_price >= lower`；
     `prev_state == BEAR` 時 `passed = current_price > upper`。
3. 判斷邏輯（state / is_newly_crossed 的產生）一行不改。

### B3. `src/signals/aggregator.py`（S3）

1. `CombinedSignal` dataclass 加兩個欄位（`next_step` 本 phase 先加欄位、Phase C 才填值）：
   `conditions: list = field(default_factory=list)` 與 `next_step: str = ""`。
2. `aggregate()` 開頭組 2 個 condition：

   | name | label | passed | actual | threshold |
   |------|-------|--------|--------|-----------|
   | `s1_trend` | S1 趨勢 | `trend.state == TrendState.BULL` | `f"{trend.state.value}（{trend.distance_pct:+.1f}%）"` | `"BULL"` |
   | `s2_direction` | S2 方向 | `time_diff.direction == SignalDirection.LONG` | `time_diff.direction.value` | `"LONG"` |

   每個 return 分支都補 `conditions=conditions`。決策矩陣一行不改。

### B4. 落庫：`src/database/helpers.py` + `src/tasks.py`

1. `save_time_diff_signal(...)` 加參數 `conditions: list | None = None,
   next_step: str | None = None`，寫入對應欄位。
2. `save_trend_signal(...)` 加參數 `conditions: list | None = None`，寫入。
3. `tasks.generate_signal`：
   - `save_time_diff_signal(...)` 傳 `conditions=time_diff.conditions + combined.conditions`
     （S2+S3 合併存，name 可區分）。`next_step` 本 phase 傳 None。
   - `save_trend_signal(...)` 傳 `conditions=trend.conditions`。

### B5. API：`src/api/schemas.py` + `src/api/routes.py`

1. `TrendSignalSchema`、`TimeDiffSignalSchema`、`CombinedSignalSchema` 各加
   `conditions: list[dict] = []`（**必須有預設值**，否則舊 Redis 快取 JSON 會 validate 失敗）。
2. `/signals/current` 組回應時填入三組 conditions。
3. **Redis 快取 key 換版**：`zrh:sig:current` → `zrh:sig:current:v2`（get 與 setex 兩處
   都換），避免 30 分鐘內讀到舊格式快取。
4. `/signals/history`（routes.py `get_signal_history`）：先讀 `SignalHistoryItem` schema
   現況，加 optional 欄位 `conditions: list[dict] = []` 與 `next_step: str = ""` 並在查詢
   結果中帶出。

### B6. 前端：`src/static/index.html`

1. 指數訊號卡（`id="index-detail"`）內、四條 sig-row 之下，新增一列「條件明細」：
   每個 condition 渲染一個 chip：`✓ label`（綠）/ `✗ label`（紅）/ `— label`（灰，
   passed=null）。`title` 屬性放 `actual vs threshold` 供 hover。
   新增 CSS class：`.cond-chip`、`.cond-chip.pass`、`.cond-chip.fail`、`.cond-chip.na`
   （跟隨現有 badge 樣式的變數用法）。
   資料來源：`/signals/current` 回應中 `time_diff.conditions + combined.conditions`。
2. 訊號歷史區（`id="signal-history-area"`）每列若有 conditions 就附同款 chips。
3. 遵守 LESSONS：渲染回呼必須有「清除所有未更新佔位」收尾（成功與 catch 都要）。

### B7. 新增測試：`tests/unit/test_condition_details.py`

至少涵蓋：
- S2 四種失敗路徑 + 成功路徑：conditions 長度恆為 4、各 passed 正確；
  並斷言 direction / confidence / trigger_reason 與既有行為一致。
- S1：資料不足（1 條）、正常 BULL/BEAR（2 條）、緩衝帶生效（3 條，帶內維持前態時
  buffer_band 的 passed 語意正確）。
- S3：四個決策分支的 conditions 各自正確。

### B8. 驗證與提交

```
python -m py_compile src/signals/time_diff.py src/signals/ma200_filter.py src/signals/aggregator.py src/database/helpers.py src/tasks.py src/api/schemas.py src/api/routes.py
python -m pytest tests/unit -x -q
```

確認 `git diff tests/` 只有新增檔。commit：
`feat: S1/S2/S3 逐條件明細（報表優化 Phase B）` → push → 煙霧測試 → PROGRESS.md。
手動檢查點：dashboard 指數訊號卡出現條件 chips，且 S1/S2/S3 顯示值與改前相同。

---

## Phase D — #2 資料品質註記（獨立，故排在 C 前）

### D1. 共用 helper：`src/data/normalizer.py`

新增 module-level 函數（把 routes.py `get_current_signals` 內的 `_safe_chg` 邏輯搬出來共用）：

```python
def safe_change_pct(d: dict | None) -> tuple[float, bool]:
    """回傳 (change_pct, was_defaulted)。None/NaN/不可轉 float 一律回 (0.0, True)。"""
```

### D2. `src/api/routes.py` — `/signals/current`

1. 刪掉內部 `_safe_chg`，改用 `safe_change_pct`。
2. `CurrentSignalsResponse`（schemas.py）加 `quality_notes: list[dict] = []`。
3. 產生 notes：
   - 任一指數 `was_defaulted=True` → `{"source":"signals","level":"warn",
     "message":"<指數名> 漲跌幅缺失，以 0.0 代入（訊號可信度降低）"}`
   - `len(qqq_df) < settings.ma_period` → warn「QQQ 歷史資料不足，S1 為 UNDEFINED」。

### D3. `src/api/routes.py` — `/portfolio`

1. `_fetch_price` 回傳值從 `(sym, price)` 改為 `(sym, price, note_or_None)`：
   - 走了 fallback 回看期 → info note「{sym} 無即時價，改用 {period} 歷史收盤」。
   - 最終 price 為 None → warn note「{sym} 價格無法取得」。
   - **呼叫端所有解包處同步改**（先 grep `_fetch_price` 確認全部呼叫點）。
2. `/portfolio` 回應 JSON 加 `quality_notes` list 收集上述 notes。

### D4. `src/tasks.py` — NaN 舊坑修復（老闆已核准，屬 LESSONS 既載 bug 的修復）

`generate_signal` 第 152-154 行的 `... or 0.0` 模式**擋不住 NaN**（NaN 是 truthy，
LESSONS 2026-06 舊坑；routes.py 已修但 tasks.py 漏了）。改用 `safe_change_pct`，
`was_defaulted=True` 時 `logger.warning`。**除此之外 generate_signal 不做其他行為變更。**

### D5. 前端

1. `announce-area`（已存在）：`/signals/current` 的 `quality_notes` 渲染為黃色告示條
   （warn 黃、info 灰），無 notes 時清空。
2. portfolio 區塊：`portfolio-msg`（已存在）顯示 portfolio 的 quality_notes。

### D6. 新增測試 + 驗證與提交

- `tests/unit/test_data_quality.py`：`safe_change_pct` 對 None / NaN / 字串 / 正常值
  四種輸入；（若既有測試結構允許）`_fetch_price` note 產生邏輯。
- 驗證命令同前（py_compile 改過的檔 + pytest）。commit：
  `feat: 資料品質註記 + 修復 tasks.py NaN or-0.0 舊坑（報表優化 Phase D）`
  → push → 煙霧測試 → PROGRESS.md。

---

## Phase C — #3 決策下一步 + #6 關鍵價位（依賴 Phase B）

### C1. `src/signals/aggregator.py` — 填 `next_step`

1. `__init__` 加兩個**僅供文案使用**的參數（預設 0.0，不參與任何決策）：
   `ma200_enter_buffer_pct: float = 0.0`、`ma200_exit_buffer_pct: float = 0.0`。
2. 各分支 next_step 模板（只用現有數值，不引入新計算）：

   | 分支 | next_step |
   |------|-----------|
   | BEAR → EXIT_ALL | `f"等待 QQQ 收盤重新站上 {trend.ma200 * (1 + self.ma200_enter_buffer_pct):.2f}（MA200 進場緩衝上緣）"`（`trend.ma200 <= 0` 時退回 `"等待 S1 趨勢轉多"`）|
   | UNDEFINED → HOLD | `"等待 200 日均線資料累積完成"` |
   | BULL × LONG → BUY | `f"依建議倉位 {position_pct:.0%} 執行，停損 {self.index_stop_loss_pct:.0%}"` |
   | BULL × 其他 → HOLD | 取 `time_diff.conditions` 第一個 `passed == False` 的項目 → `f"等待 {label} 達標（目前 {actual}，需 {threshold}）"`；找不到則 `"等待 S2 訊號轉 LONG"` |

3. 兩個呼叫端（routes.py `get_current_signals`、tasks.py `generate_signal`）建構
   `SignalAggregator` 時帶入 `settings.ma200_enter_buffer_pct` / `settings.ma200_exit_buffer_pct`。
4. tasks.generate_signal 的 `save_time_diff_signal(...)` 改傳 `next_step=combined.next_step`。

### C2. `src/api/routes.py` — key_levels（#6）

1. `CombinedSignalSchema` 加 `next_step: str = ""` 與 `key_levels: list[dict] = []`。
2. `/signals/current` 中計算 key_levels（全部由既有值導出）：
   - `trend.ma200 > 0` 時恆有兩條：
     `{"label":"QQQ 出場緩衝下緣","value":round(ma200*(1-exit_buffer),2),"note":"跌破則 S1 轉空"}`、
     `{"label":"QQQ 進場緩衝上緣","value":round(ma200*(1+enter_buffer),2),"note":"站上則 S1 轉多"}`。
   - `final_action == "BUY"` 時追加：抓 0050 最新收盤
     （`TWMarketFetcher.get_historical("0050", period="5d")`，**必須**
     `loop.run_in_executor` + `asyncio.wait_for(..., timeout=10)` + NaN/空值防護，
     LESSONS 鐵則），成功則追加
     `{"label":"0050 進場參考價","value":close,"note":"最新收盤"}` 與
     `{"label":"0050 停損價","value":round(close*(1-stop_loss_pct),2),"note":f"-{stop_loss_pct:.0%}"}`；
     失敗 → 不追加，並補 quality note（warn，「0050 收盤價無法取得，關鍵價位不完整」）。
3. **快取 key 再換版** `zrh:sig:current:v2` → `v3`（回應結構又變了）。

### C3. 前端

今日進場計畫卡（`entry-symbol` / `entry-position` / `entry-stoploss` / `entry-reason`
所在卡片）：
1. `entry-reason` 保留顯示 `combined.reason`；其下新增一行「下一步」顯示 `next_step`
   （灰色小字，同參考報表的「下一步：」樣式）。
2. 新增「關鍵價位」小表：逐條渲染 key_levels（label、value、note）。

### C4. 新增測試 + 驗證與提交

- `tests/unit/test_next_step.py`：四個分支的 next_step 文案正確；`ma200<=0` 退化路徑；
  「取第一個失敗條件」路徑。
- 驗證命令同前。commit：`feat: 決策下一步與關鍵價位（報表優化 Phase C）`
  → push → 煙霧測試 → PROGRESS.md。
- 手動檢查點：HOLD 時下一步顯示具體門檻與現值；MA200 緩衝上下緣價位正確
  （手算 ma200×(1±buffer) 核對）。

---

## Phase E — #5 Watchlist 新面孔標記

### E1. `src/database/helpers.py`

1. `save_watchlist`：在「標記舊項 expired」迴圈中順便收集
   `prev_symbols = {old.symbol for old in ...}`；插入新項時
   `is_new = bool(prev_symbols) and (item["symbol"] not in prev_symbols)`。
   **注意：`prev_symbols` 為空（首次生成，無前期可比）時全部 `is_new=False`**，
   避免第一輪全場標 NEW 的噪音。
2. `get_watchlist` 回傳 dict 加 `"is_new": bool(r.is_new)`。

### E2. API + 前端 + Discord

1. `WatchlistItemSchema` 加 `is_new: bool = False`。
2. 前端 `watchlist-area`：`is_new` 的標的加黃色 `NEW` 徽章（參考報表的新面孔★語意）。
3. `tasks.run_stock_selection`：組 `top_symbols` 字串時，新面孔 symbol 前加 `★`
   （只改字串內容，`watchlist_update` 介面不動）。

### E3. 新增測試 + 驗證與提交

- `tests/unit/test_watchlist_new_faces.py`：首次全 False；第二次僅新進 symbol 為 True；
  舊 symbol 續留為 False。（沿用 tests/unit 既有的 DB helper 測試模式。）
- commit：`feat: watchlist 新面孔標記（報表優化 Phase E）` → push → 煙霧測試 → PROGRESS.md。

---

## Phase F — #4 Run 資訊 + 免責聲明

1. `CurrentSignalsResponse` 加 `from_cache: bool = False`。快取命中路徑改為：
   `return CurrentSignalsResponse.model_validate_json(_cached).model_copy(update={"from_cache": True})`。
   （寫入快取的一律存 `from_cache=False` 原樣。）
2. 前端 header：`last-update-time` 旁，`from_cache=true` 時顯示灰色「快取」徽章。
3. 訊號歷史列顯示 `#<DB id>`（`SignalHistoryItem` 若無 id 欄位則加 `id: int = 0`）。
4. 頁面 footer 新增一行（灰色小字置底）：
   「本內容由系統自動生成，僅供參考，不構成任何投資建議或操作指示」。
5. commit：`feat: 訊號快取標示、Run 編號與免責聲明（報表優化 Phase F）`
   → push → 煙霧測試 → PROGRESS.md。

---

## 總驗收清單（全部完成後逐項打勾）

- [ ] `git log` 共 6 個 feature commit（A/B/D/C/E/F），每個都有對應煙霧測試 200 證明
- [ ] `git diff <起點>..HEAD -- tests/` 只有新增檔案，無既有測試改動
- [ ] 既有 + 新增測試全綠（貼 pytest 輸出）
- [ ] Dashboard：條件 chips、下一步、關鍵價位、品質告示、NEW 徽章、快取徽章、免責聲明全部可見
- [ ] 相同市場輸入下，S1 state / S2 direction+confidence / S3 action 與改前一致（用訊號歷史對照）
- [ ] `docs/PROGRESS.md` 六個 phase 都有條目

## 風險與回退

- 每 phase 獨立 commit，出問題 `git revert <該 commit>` 單獨回退。
- Redis 快取 key 已隨結構改版換版（v2/v3），不會新舊混讀。
- 新增的外部呼叫只有 Phase C 的 0050 收盤（單次、timeout 10s、NaN 防護），
  在 30 分鐘快取的 endpoint 內，記憶體與併發風險可忽略（web 256MB 天花板意識）。
- 若同一 phase 連續失敗 2 次 → 停手，按 CLAUDE.md 紅線回報老闆。
