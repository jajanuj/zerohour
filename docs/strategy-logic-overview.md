# ZeroHour 策略邏輯總覽

> **文件定位**：彙整「目前 master 分支實際上線」的策略邏輯，供快速理解與查閱。
> 以程式碼為準逐檔核對整理（校準日 2026-07-06）；規格細節仍以 `docs/trading-system-impl.md`
>（經 `docs/harness/IMPL-MAP.md` 定位）、`docs/strategy-s4-spec.md`、`docs/scalper-spec.md` 為權威來源。
> 本文件為觀測性彙整，**修改任何公式或參數仍須先問老闆**（CLAUDE.md 紅線）。
> 姊妹篇：`docs/strategy-profit-critique.md`（操盤手視角的獲利面檢討）。

---

## 0. 專有名詞速查

| 名詞 | 說明 |
|------|------|
| **200MA（200 日移動平均線）** | 最近 200 個交易日收盤價的平均。價格在其上視為長期多頭、其下視為空頭，是最常用的牛熊分界線 |
| **緩衝帶（hysteresis）** | 在 200MA 上下各留 2% 的「不表態區」：多頭要跌破 MA×0.98 才轉空、空頭要站上 MA×1.02 才轉多，防止價格貼線時天天翻多翻空 |
| **QQQ** | 追蹤 NASDAQ-100 的美股 ETF，本系統用它代表「美國科技股大盤」做 S1 趨勢判斷 |
| **SOX（費半）** | 費城半導體指數。台股與半導體高度連動，故用它做方向確認 |
| **^TWII / TAIEX** | 台灣加權股價指數 |
| **0050** | 元大台灣 50 ETF（台積電權重約半），本系統唯一實際交易的標的 |
| **MTX（小台指）** | 台指期貨小型合約。S2 的 SHORT 訊號會「建議」賣 MTX，但目前執行層不做空（見 §2 S3 註記） |
| **三大法人** | 外資、投信、自營商。其「買賣差額」（買超=淨買入、賣超=淨賣出）常被視為台股籌碼面指標 |
| **信心度（confidence）** | S2 自訂的 0~1 分數，衡量美股訊號強度（波動幅度＋跨指數共振），同時當作訊號門檻與倉位加權 |
| **倉位（position）／曝險（exposure）** | 投入某標的的資金占總資產比例；曝險指所有持倉合計占比 |
| **固定停損（stop loss）** | 跌破「進場價 ×(1−12%)」無條件出場，鎖住單筆最大虧損 |
| **移動停利（trailing stop）** | 停利線隨持倉高點上移（高點 ×(1−15%)），只升不降，目的是讓獲利回吐有限度。**注意：目前生產只計算未觸發**，見 §4 |
| **時間停損（time stop）** | 持倉 N 天仍虧損就出場，避免死抱。**目前未接線**，見 §4 |
| **熔斷（circuit breaker）** | 單日虧損超過門檻即停止當日交易。**目前未接線**，見 §4 |
| **fail-open** | 失效保護策略：資料抓不到時「當作沒有這個因子」（係數 ×1.0）繼續運作，而不是整個停擺，但會發警告 |
| **paper trading（紙上交易）** | 訊號照算、下單只記錄在資料庫，不送真實券商。目前主系統即此模式 |
| **台美時間差** | 美股收盤（台北凌晨 04:00）到台股開盤（09:00）之間有 5 小時：美股方向已知、台股尚未開盤，本系統的核心前提 |
| **beta / alpha** | beta＝跟著大盤漲跌的部分；alpha＝超越大盤的超額報酬。策略的價值在 alpha |

---

## 1. 系統概觀

ZeroHour 利用台美市場時差：美股收盤（台北凌晨 04:00）後立即算訊號，
台股開盤日執行。目前主系統為 **paper 下單**（記錄於 DB，非真實券商成交），標的固定 `0050`。

每日排程（`src/tasks.py` beat_schedule，台北時間；**每天都跑，未過濾台股非交易日**）：

| 時間 | 任務 | 內容 |
|------|------|------|
| 04:00 | `fetch_us_market_data` | 抓美股收盤資料（NASDAQ / S&P500 / SOX / QQQ）入庫 |
| 04:05 | `generate_signal` | **S1+S2+S3+S4 訊號計算 + paper 下單**（本文件主體） |
| 04:07 | `check_black_swan` | 黑天鵝偵測 |
| 04:10 | `run_market_context` | 市場背景 Agent |
| 13:35 | `update_positions` | 台股收盤後更新持倉現價、績效快照、檢查固定停損 |
| 13:40 | `run_daily_review` | 每日覆盤 |
| 週五 14:00 | `run_weekly_review` | 週覆盤 |
| 週日 20:00 | `run_stock_selection` | Multi-Agent 選股掃描 |
| 23:00 | `daily_backup` | 每日資料備份 |

---

## 2. 訊號層（S1–S4）

### S1 — 200MA 趨勢過濾（`src/signals/ma200_filter.py`）

判斷大環境多空，標的為 **QQQ**（抓 2 年日線）。

- 收盤 > 200MA → `BULL`；< 200MA → `BEAR`；資料不足 200 筆或 MA 未成形 → `UNDEFINED`
- **緩衝帶**：帶入前一日狀態（DB `get_latest_trend_state("QQQ")`）時：
  - 前態 BULL → 需跌破 `MA200 × (1 − 2%)` 才轉 BEAR
  - 前態 BEAR → 需站上 `MA200 × (1 + 2%)` 才轉 BULL
  - 帶內維持前態
- 無前態（如回測逐日重算）→ 退回即時交叉判斷（**注意：回測引擎未帶前態，即無緩衝帶**）

### S2 — 台美時間差訊號（`src/signals/time_diff.py`）

美股收盤的方向性變動作為台股開盤的領先指標。四道條件全過才有方向：

1. `|NASDAQ 漲跌幅| ≥ 1.5%`（未達 → NEUTRAL）
2. S&P500 與 NASDAQ 同向（不同向 → NEUTRAL，視為板塊分化）
3. SOX（費半）與 NASDAQ 同向（生產啟用中；不同向 → NEUTRAL）
4. 信心度 ≥ 0.6（不足 → NEUTRAL）

**信心度公式**（`_calc_confidence`，上限 1.0）：

```
0.5（底分）
+ min((|NASDAQ%| − 1.5) × 0.1, 0.2)      # 超額波動加分
+ 0.2（若 SOX 同向）
+ 0.1（若 |S&P500%| > 1 且 |SOX%| > 2 且 SOX 同向）
```

方向映射：NASDAQ 漲 → `LONG`（建議 0050 BUY）；跌 → `SHORT`（建議 MTX SELL，
但目前 SHORT 不會被執行，見 S3）。

> 註：`TimeDiffSignal` 上有 `entry_window`（09:00–09:30）與 `exit_time`（13:25）欄位，
> 但執行層完全未使用——實際持倉是波段式持有，不是日內進出。

### S3 — 組合決策（`src/signals/aggregator.py`）

S1 判大環境 × S2 判短線，**兩者同向才進場**：

| S1 趨勢 | S2 方向 | 最終動作 |
|---------|---------|----------|
| BULL | LONG | **BUY** |
| BULL | SHORT / NEUTRAL | HOLD |
| BEAR | 任何 | **EXIT_ALL**（強制清倉） |
| UNDEFINED | 任何 | HOLD |

- **BUY 建議倉位** = `base 0.25 + 信心度 × (max − base)`，上限 `max`。
  生產 `max_position_pct = 0.30`、信心度門檻 0.6 → 實際落在 **28%–30%** 的窄區間。
- BUY 附帶：固定停損 12%、移動停利 15%（後者僅寫入建議，執行面見 §4）。
- 決策矩陣不會產生 `SELL`（做空路徑未實作）；空頭出場由 `EXIT_ALL` 承擔。

### S4 — 台股趨勢確認因子（`src/signals/taiex_confirm.py`，規格 `docs/strategy-s4-spec.md`）

**只縮放 S3 BUY 的建議倉位**（`effective = suggested × modifier`），
進出時點、決策矩陣、停損停利一律不變。兩個子指標：

1. TAIEX（^TWII）vs 200MA（復用 MA200Filter，不帶前態）
2. 三大法人 5 日合計買賣差額（TWSE BFI82U，單位億元；假日跳過，逐次 timeout 10s、
   總預算 30s、回看上限 10 天）

**係數表 v0**（`lookup_modifier`，強制夾限 [0.5, 1.0]）：

| TAIEX 趨勢 | 法人 5 日淨額 | 係數 |
|------------|---------------|------|
| BULL（站上 200MA） | 買超（≥0） | ×1.00 |
| BULL | 賣超 | ×0.75 |
| BEAR（跌破 200MA） | 任何 | ×0.50（台美背離） |
| 無資料（任一子指標失敗） | — | ×1.00 **fail-open** + Discord 警告 |

---

## 3. 執行層（`src/tasks.py::generate_signal`，paper）

1. 取 S2 輸入（NaN 一律走 `safe_change_pct`，缺值以 0.0 代入並記警告）
2. 算 S1（帶前態緩衝帶）→ S3 → S4 係數乘入 BUY 倉位
3. 訊號入庫：`time_diff_signals`、`trend_signals`（QQQ 與 TAIEX 各一列）
4. Discord 推播：**BUY / SELL / EXIT_ALL 才發，HOLD 不推**
5. `BUY` 且無持倉 → `PositionSizer` 算量後開倉；`SELL / EXIT_ALL` 且有持倉 → 平倉
6. 13:35 `update_positions` 以收盤價更新持倉並檢查**固定停損**

**成交價假設（重要）**：開倉與平倉都取 `get_historical(SYMBOL, "5d")` 最後一筆收盤價。
凌晨 04:05 台股尚未開盤，此價格是**前一交易日收盤價**——真實交易只能在 09:00 開盤後成交，
而開盤價通常已反映美股夜盤漲跌（跳空）。含義見 critique 文件 §1。

**費用假設**：paper 成交 `commission=0`（`database/helpers.py`），
無手續費、無證交稅、無滑價。`src/review/tax_calculator.py` 有完整台股費率表但只用於覆盤試算。

**無加碼/減碼**：有持倉時再出現 BUY 訊號不動作；一次只有一筆持倉。

---

## 4. 風控層（`src/risk/`）——設計 vs 實際接線

規格上是六層防護（`docs/trading-system-impl.md` §9），**實際接上生產執行流程的只有部分**：

| 層 | 機制 | 參數 | 生產接線狀態 |
|----|------|------|--------------|
| 1 | 單筆固定停損 | 進場價 ×(1−12%) | ✅ **有效**。13:35 以收盤價檢查（一天一次），觸發即平倉 |
| 2 | 移動停利 | 高點 ×(1−15%)，只升不降 | ⚠️ **未接線**。`update_position_price` 每日計算並寫入 DB 快照，但無任何代碼拿 `trailing_stop_price` 觸發平倉 |
| 3 | 時間停損 | 持倉 5 天仍虧損出場 | ⚠️ **未接線**。只存在 `stop_loss.py::StopLossManager`，該類僅被 `order_manager.py` 引用，而 `OrderManager` 無人 import（死代碼） |
| 4 | 曝險上限 | 單標的 ≤30%、總倉 ≤80% | ✅ **有效**（由 `PositionSizer` 在進場時執行：`min(建議倉位, 30%)` 且不超過總曝險 80% 剩餘空間）。獨立的 `ExposureCheck` 類未接線 |
| 5 | 趨勢過濾 | S1 BEAR → EXIT_ALL、禁新開倉 | ✅ **有效**（S3 決策矩陣） |
| 6 | 每日虧損熔斷 | 單日虧損 >5% 停止當日操作 | ⚠️ **未接線**（`DailyCircuitBreaker` 同在死代碼 `order_manager.py`）。另 `update_positions` 的 `daily_pnl` 實為**累計**損益，非單日 |

**實際的出場路徑只有三條**：固定停損 −12%（收盤檢查）、S1 轉 BEAR 的 EXIT_ALL、
（理論上的）SELL 訊號——最後者決策矩陣不會產生。

---

## 5. 可調參數清單

### 5.1 環境變數層（`.env` / `src/config.py`，改了重啟即生效，不需改代碼）

| 參數 | 生產值 | 作用 | 動它的效果 |
|------|--------|------|-----------|
| `trading_mode` | paper | paper / live / observe | 目前執行層只實作 paper 行為 |
| `initial_capital` | 1,000,000 | paper 起始資金 | 影響部位金額與績效基準 |
| `us_signal_threshold` | 1.5 | S2 NASDAQ 觸發門檻（%） | 調低→訊號變多但雜訊多；調高→次數更少 |
| `min_confidence` | 0.6 | S2 信心度下限 | 同上；也決定 BUY 倉位下緣（0.25+0.6×0.05=28%） |
| `ma_period` | 200 | S1/S4 均線期 | 調短→趨勢翻轉更靈敏、假訊號更多 |
| `ma200_enter_buffer_pct` | 0.02 | S1 空翻多需站上 MA×1.02 | 加大→更不易翻多（錯過起漲）；縮小→貼線抖動 |
| `ma200_exit_buffer_pct` | 0.02 | S1 多翻空需跌破 MA×0.98 | 加大→清倉更慢（多吃回檔）；縮小→易被洗出場 |
| `max_position_pct` | 0.30 | 單筆/單標的倉位上限 | 直接決定資金利用率與單筆風險 |
| `max_total_exposure_pct` | 0.80 | 總曝險上限 | 目前單標的下實際約束力低於前者 |
| `index_stop_loss_pct` | 0.12 | 固定停損 | 唯一有效的停損參數 |
| `trailing_stop_pct` | 0.15 | 移動停利 | **改了目前也不會觸發平倉**（未接線），只影響 DB 顯示值 |

### 5.2 寫死在代碼層（改動需編修代碼＝依紅線先問老闆）

| 參數 | 值 | 位置 |
|------|-----|------|
| 交易標的 `SYMBOL` | "0050" | `src/tasks.py:14` |
| S3 `base_position_pct` | 0.25 | `aggregator.py` 建構子預設（tasks.py 未傳入） |
| S2 信心度公式權重 | 底分 0.5／超額×0.1 上限 0.2／SOX +0.2／共振 +0.1（門檻 \|SP500\|>1、\|SOX\|>2） | `time_diff.py::_calc_confidence` |
| S2 `require_sox_confirmation` | True | `time_diff.py` 建構子預設 |
| 時間停損 `time_stop_days` | 5（未接線） | `stop_loss.py::StopLossConfig` |
| 熔斷 `max_daily_loss_pct` | 0.05（未接線） | `exposure.py::DailyCircuitBreaker` |
| S4 係數表 | 1.00 / 0.75 / 0.50 | `taiex_confirm.py::lookup_modifier` |
| S4 係數夾限 | [0.5, 1.0] | `taiex_confirm.py` 常數 |
| S4 法人淨額門檻 | ≥0 即買超；回看 5 交易日 | `taiex_confirm.py` |
| S4 網路預算 | 逐次 10s／總 30s／回看 10 天 | `taiex_confirm.py` 建構子預設 |
| 排程時刻 | 04:00/04:05/…（見 §1） | `tasks.py::beat_schedule` |
| 回測費用 | 手續費 0.1% + 滑價 0.1% | `backtest/engine.py::BacktestConfig` |

---

## 6. 回測引擎與生產的已知差異（`src/backtest/engine.py`）

回測與生產共用 S1/S2/S3 模組，但**下列差異使回測數字不能直接外推到生產**：

| 項目 | 回測 | 生產 |
|------|------|------|
| 標的 | 預設 QQQ（同標的算訊號、同標的交易） | 訊號看美股、交易 0050 |
| 移動停利 | **有執行**（`max(trailing, fixed)` 逐日檢查） | 未接線 |
| S1 緩衝帶 | 無（未帶前態，即時交叉） | 有（±2%） |
| 倉位上限 | Aggregator 預設 0.40（S1 純趨勢模式 0.95） | 0.30 |
| 費用 | 手續費 0.1% + 滑價 0.1% | paper 記 0 |
| S4 | 不參與 | 參與（縮 BUY 倉位） |

---

## 7. Scalper — 股期影線區間刷單（獨立模組，`scalper/`）

> 老闆編號「策略三」；**與主系統完全隔離**：只跑老闆本地機器（macOS），
> 不部署 Fly.io、不 import `src/`。權威規格：`docs/scalper-spec.md`。

**一句話**：在前一根已完成 60 分 K 的 [low, high] 區間內，用股票期貨掛單做均值回歸，
抓 1 tick 價差，高勝率小獲利，靠硬規則控制破區間虧損。

v0 核心規則：現價在區間下半掛買/上半掛賣（只做回歸不追突破）；成交後掛 +1 tick
反向限價出場；反向 2 ticks 市價停損；薄盤（對手五檔 < 20 口）與掃單
（30 秒單邊主動成交 > 30 口）過濾；破區間 → 平倉停機至下根 K；日虧 ≥ 3,000 元熔斷、
連 3 筆虧損休 30 分鐘；結算日/除權息/黑天鵝日不出勤。交易時段 09:05–13:15。

**狀態**：Phase 0 完成（決策核心 + 回測 + 測試）；真金下單（A7）**未核准、代碼鎖定**
（`ShioajiBrokerAdapter` 下單方法全部 `raise NotImplementedError`）。

---

## 8. 相關文件

| 主題 | 文件 |
|------|------|
| 獲利面檢討（操盤手視角） | `docs/strategy-profit-critique.md` |
| 完整系統規格 | `docs/trading-system-impl.md`（先查 `docs/harness/IMPL-MAP.md` 行號） |
| S4 規格 | `docs/strategy-s4-spec.md` |
| Scalper 規格 | `docs/scalper-spec.md` |
| 報表可觀測性（conditions/next_step 等欄位由來） | `docs/report-optimization-plan.md` |
| 進度與歷史 | `docs/PROGRESS.md` |
