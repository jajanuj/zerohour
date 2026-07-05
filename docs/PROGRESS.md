# ZeroHour — 開發進度追蹤

> 結構規則：新條目寫在下方「📍 最新狀態」區**頂部**（一個 session 一個小節）。
> Session 啟動只讀本檔前 40 行。歷史細節在檔案下半部，按需查閱。
> 超過 250 行觸發壓縮（見 docs/harness/F-knowledge-protocol.md §4）。

---

## 📍 最新狀態（新的寫最上面）

### 2026-07-05 — S1 判斷週期定案：每日 + 2%/2% 緩衝帶（第二批風控項目 1）

**任務目標**：老闆要求分析 S1（200MA 趨勢過濾）該維持「每日」判斷還是照規格書改回「月底」判斷。
審查後發現：規格書一直寫的是月底，但生產環境從未真的接上月底邏輯（`check_monthly_trend` 只寫 DB、
不參與交易決策），實戰跑的、也是回測驗證過的都是「每日」。用回測引擎對照 6 組緩衝參數（0~3%）後，
老闆核准採用**每日判斷 + 出場緩衝 2% + 進場緩衝 2%**，並核准同步更新規格書與移除 `check_monthly_trend`。

**已完成到哪**：
- ✅ `src/signals/ma200_filter.py`：`MA200Filter` 加 `exit_buffer_pct`/`enter_buffer_pct` 建構參數與
  `calculate()` 的 `prev_state` 參數；帶入 `prev_state` 時套用緩衝帶（hysteresis），未帶入時退回原本
  即時交叉判斷（向後相容，回測引擎等既有呼叫方不受影響）
- ✅ `src/config.py` 新增 `ma200_exit_buffer_pct`/`ma200_enter_buffer_pct`（預設各 0.02），`.env.example`
  補上對應範例
- ✅ `src/database/helpers.py` 新增 `get_latest_trend_state(symbol)`：讀 `trend_signals` 表最新一筆狀態，
  供每日判斷時取得「前一日狀態」（沿用既有表，無 schema 異動）
- ✅ `src/tasks.py generate_signal()` 與 `src/api/routes.py get_current_signals()` 都接上緩衝帶邏輯
  （沿用第一批「Dashboard 顯示與實際下單參數必須一致」的原則）
- ✅ 移除 `src/tasks.py` 的 `check_monthly_trend` 任務與其 `monthly-trend-check` 排程（已確認無下游使用，
  移除後同步清掉沒用到的 `calendar` import）
- ✅ 規格書 `docs/trading-system-impl.md` §1 表格、每日時程圖、§4.1、§14 文件異動紀錄同步更新為
  「每日 + 緩衝帶」，並記錄決策理由；`docs/harness/IMPL-MAP.md` 章節行號重新校準（規格書改動後總行數
  3678→3688）
- **涉及檔案**：[src/signals/ma200_filter.py](../src/signals/ma200_filter.py)、[src/config.py](../src/config.py)、
  [src/database/helpers.py](../src/database/helpers.py)、[src/tasks.py](../src/tasks.py)、
  [src/api/routes.py](../src/api/routes.py)、[.env.example](../.env.example)、
  [docs/trading-system-impl.md](../trading-system-impl.md)、[docs/harness/IMPL-MAP.md](harness/IMPL-MAP.md)

**回測對照數據**（0050、2015-01-01~2024-12-31、S3 策略，六組同資料同條件公平對照，用於選參數，
非新的績效背書——樣本僅 5~10 筆交易，橫向比較有效但絕對數字有雜訊）：

| 出場緩衝 | 進場緩衝 | 年化 | 總報酬 | MDD | Sharpe | 交易數 | 勝率 | 翻轉次數 |
|---|---|---|---|---|---|---|---|---|
| 0%（基準） | 0% | +4.43% | +41.2% | -10.71% | 0.766 | 10 | 40% | 44 |
| **2%** | **2%**（採用）| **+4.54%** | **+42.4%** | -10.71% | **0.769** | 5 | 60% | **12** |

翻轉次數 44→12（-73%）、交易數砍半、勝率提升，MDD 六組全部相同（12% 硬停損仍在後面兜底，緩衝帶
不影響崩盤保護），故採用 2%/2%。

**下一步（第二批剩餘，尚未核准）**：
1. `PositionSizer`（`src/risk/position_sizer.py`）lot_size 邏輯在資金不足一張時仍會強制買滿 1 張（超買）
2. `DailyCircuitBreaker`（`src/risk/exposure.py`）熔斷狀態存在記憶體，worker 重啟即歸零，要不要落地到 Redis？
3. Harness 制度建設遺留：deploy.yml 測試閘門 patch、API 認證 X-API-Key、`.env.tmp` 檔案本體待老闆手動確認刪除

**User 已核准 vs 尚未核准**：
- 已核准並已執行：每日+2%/2%緩衝帶實作、規格書更新、`check_monthly_trend` 移除
- 尚未核准：上面「下一步」1–3 項

**驗證**：`python -m py_compile`（8 個改動檔案全過）、`python -m pytest tests/unit -x -q` → 47 passed；
`git status --short` 見下方 commit 前狀態

### 2026-07-05 — 建立「交接檔案」SOP（觸發詞制度化）

**任務目標**：老闆希望以後只要說「準備交接檔案」或「開始新對話」，模型就自動完成交接流程，
不用每次重貼一長串步驟；且原本那串步驟裡有 `.claude/harness/06-HANDOVER-LETTER.md`、
`npm run build/lint` 等**別的專案**的路徑與指令，需要改成本專案實際規格。

**已完成到哪**：
- ✅ 新增 [docs/harness/H-handover-procedure.md](harness/H-handover-procedure.md)：定義觸發詞、4 步驟 SOP
  （更新 PROGRESS.md 頂部條目 → 踩坑檢查 → `py_compile`+`pytest`+`git status` 驗證 → commit+push）
- ✅ [CLAUDE.md](../CLAUDE.md) 檔案路由表加一行指向 H 檔（老闆本輪對話明示同意修改 CLAUDE.md）
- ✅ [docs/harness/README.md](harness/README.md) 索引補上 H 檔
- ✅ SOP 內建紅線：踩坑教訓不得寫成「被權限/安全機制擋下就換方法繞過」——上一輪 session 曾因為
  這樣寫被 auto-mode 分類器擋下 commit，已把這個判準寫進 H 檔 §2，避免下次重蹈
- **涉及檔案**：`docs/harness/H-handover-procedure.md`（新增）、`CLAUDE.md`、`docs/harness/README.md`

**下一步**：無待辦，這是一次性制度建立。以後老闆說「準備交接檔案」時，模型應直接照 H 檔執行，
不需要老闆再貼步驟。

**User 已核准**：本輪對話中，老闆明確要求建立此 SOP 並修正別專案路徑——視為對 H 檔新增與
CLAUDE.md/README.md 路由更新的明示同意。

**驗證**：`python -m py_compile`（改動的 .py 檔全過，本次無 .py 改動）、
`pytest tests/unit -x -q` → 47 passed、`git status --short` 僅本次三個文件變更

### 2026-07-05 — 策略邏輯風控修復（第一批：讓已寫好的防線真的生效）【交接用完整版】

**任務目標**：老闆要求「檢查目前策略邏輯，有沒有改善地方」→ 審查後發現三個「規則寫了但沒接上執行」的問題，
老闆核准做「第一批」（保命類，不涉及策略設計變更）。

**已完成到哪（第一批，已 push 並煙霧測試通過）**：
- ✅ EXIT_ALL 接上執行與推播 — 200MA 轉空時過去完全靜默不清倉，`src/tasks.py generate_signal()` 只處理 BUY/SELL；現改為 SELL/EXIT_ALL 共用平倉分支，且 signal_alert 加入 EXIT_ALL；前端 [index.html](../src/static/index.html) 加對應徽章與警示文案
- ✅ 倉位計算改用帳戶現況＋信心加權 — 過去用固定 `INITIAL_CAPITAL × max_position_pct`，虧損後仍照初始 100 萬開倉；改為 `PositionSizer` 讀當前現金+持倉市值，套用 `combined.suggested_position_pct`（信心加權 25~40%）並檢查總曝險上限，超限時記警告日誌並跳過下單
- ✅ SignalAggregator 參數統一走 settings — `tasks.py` 與 `routes.py` 過去用預設值 `max_position_pct=0.40`，與 `.env` 的 `max_position_pct=0.30` 不同步（Dashboard 顯示與實際下單倉位不一致）；兩處都改為顯式傳入 settings
- ✅ 順手修正 SELL 推播抓錯持倉數量的 bug（`open_positions[0]` → 對應 symbol 的部位）
- **涉及檔案**：`src/tasks.py`（generate_signal 主要改動）、`src/api/routes.py`（SignalAggregator 參數對齊）、`src/alerts/discord.py`（EXIT_ALL 顏色/標籤）、`src/static/index.html`（前端徽章與警示文案）
- **Commit**：8715192（harness 制度）→ 65dfb55（策略修復本體）
- **部署驗證**：GitHub Actions Test & Lint / Deploy to Fly.io 均 success；`curl /api/v1/positions` → 200

**下一步（第二批，尚未核准，需老闆逐項決策）**：
1. S1 要維持現行「每日」判斷，還是照規格書 §1 改回「月底」判斷 + 加緩衝帶（避免價格貼 MA200 時天天多空翻轉）？
2. `PositionSizer`（`src/risk/position_sizer.py`）lot_size 邏輯在資金不足一張時仍會強制買滿 1 張（超買），要不要修？
3. `DailyCircuitBreaker`（`src/risk/exposure.py`）熔斷狀態存在記憶體，worker 重啟即歸零，要不要落地到 Redis？
4. Harness 制度建設（前一 session）遺留：deploy.yml 測試閘門 patch（`docs/harness/A-diagnosis.md` 痛點三）、API 認證 X-API-Key、`.env.tmp` 檔案本體待老闆手動確認刪除

**User 已核准 vs 尚未核准**：
- 已核准並已執行：上述「已完成到哪」四項（第一批）
- 尚未核准（等老闆回應）：上面「下一步」1–4 項，任何一項都不得未經同意直接動 `src/risk/`、`src/signals/` 或 CI 設定

**驗證**：`python -m py_compile`（改動檔案全過）、`python -m pytest tests/unit -x -q` → 47 passed；`git status` 乾淨（無未提交變更）
（本專案為 Python/FastAPI，無 `package.json`，故不適用 `npm run build/lint`；harness 索引在 `docs/harness/`，非 `.claude/harness/`）

### 2026-07-04 — Harness 制度建設（Fable 5 一次性 session）
- ✅ 建立 `docs/harness/` 制度檔案（A–G + LESSONS + IMPL-MAP），CLAUDE.md 重寫為路由中心
- ✅ 防錯：.gitignore 補 `.env*`/`*.db`；`.claude/settings.json` deny 高危 git 指令
- ⏳ 待老闆決定：deploy.yml 測試閘門 patch（見 A-diagnosis.md 痛點三）
- ⚠️ 已知問題：web 256MB 記憶體吃緊；API 無認證（任何人可打 /tasks 端點）

### 2026-07-04 — 持倉顯示修正
- ✅ N/A 股價（債券 ETF 回看期 5d→1mo→3mo）、具體出售建議（股數+獲利額）、損益四欄重構（e0fa40e）

### 2026-06-29~07-03 — 效能與穩定性
- ✅ Redis 價格快取 + timeout 防掛死（de23a68）、NaN 500 修正（927165b）、OOM 502 修正 + 訊號快取 30 分（d178cae）

### 下一步候選（老闆確認後執行）
1. API 認證（X-API-Key）— 高優先，端點全裸奔中
2. deploy.yml 測試閘門 — patch 已備好在 A-diagnosis.md
3. 每日任務加非交易日過濾 — 省 Gemini 免費額度（RPD 上限 20）

---

## 📚 歷史紀錄（2026-06-29 前的累積狀態，僅供查閱）

## ✅ 已完成且驗證通過

### 基礎設施
- [x] Git repo、目錄結構、pyproject.toml、.gitignore
- [x] Python 3.11、pydantic-settings 設定管理
- [x] Supabase PostgreSQL 連線（Session pooler IPv4）
- [x] Upstash Redis 連線（TLS，Celery broker/backend）
- [x] Fly.io 部署（東京，web×2 + worker + scheduler）
- [x] Docker build、GitHub Actions CI/CD（main + master 雙分支觸發）

### 核心交易引擎（第一階段 §1–11）
- [x] S1：MA200 趨勢過濾器（`src/signals/ma200_filter.py`）
- [x] S2：台美時間差訊號（`src/signals/time_diff.py`）
- [x] S3：組合策略決策（`src/signals/aggregator.py`）
- [x] 停損管理（`src/risk/stop_loss.py`）
- [x] 倉位計算（`src/risk/position_sizer.py`）
- [x] 曝險控制 + 熔斷機制（`src/risk/exposure.py`）
- [x] Paper Broker 模擬下單（`src/execution/brokers/paper.py`）
- [x] 訂單管理器（`src/execution/order_manager.py`）
- [x] 成交追蹤（`src/execution/fill_tracker.py`）
- [x] 回測引擎（`src/backtest/engine.py`）— 0050 2015-2024，年化+8%，Sharpe 1.18

### DB 寫入狀況（18 張表）

| 表格 | 說明 | 狀態 |
|------|------|------|
| `market_prices` | 美股每日收盤價 | ✅ 寫入（04:00）|
| `trend_signals` | S1 MA200 訊號 | ✅ 寫入 |
| `time_diff_signals` | S2 時間差訊號 | ✅ 寫入 |
| `orders` | 訂單紀錄 | ✅ 寫入 |
| `fills` | 成交紀錄 | ✅ 寫入 |
| `positions` | 持倉快照 | ✅ 寫入 |
| `performance_snapshots` | 績效快照 | ✅ 寫入（13:35）|
| `review_reports` | 每日/週覆盤報告 | ✅ 寫入 |
| `edge_decay_alerts` | 優勢衰減警報 | ✅ 寫入 |
| `manual_overrides` | 人為干預紀錄 | ✅ 建立 |
| `strategy_versions` | 策略版本管理 | ✅ 建立 |
| `agent_market_contexts` | 每日市場背景 | ✅ 寫入（04:10）|
| `black_swan_alerts` | 黑天鵝事件 | ✅ 寫入 |
| `watchlist` | 選股候選名單 | ✅ 寫入（週日20:00）|
| `agent_run_logs` | Agent 執行紀錄 | ✅ 建立 |
| `portfolio_positions` | 持倉匯入（TW+US）| ✅ 建立（手動上傳）|
| `orders`/`fills` 相關 | 訂單/成交 | ✅ 寫入 |

### Celery 排程任務

| 任務 | 排程 | 狀態 |
|------|------|------|
| `fetch_us_market_data` | 04:00 | ✅ |
| `check_black_swan` | 04:07 | ✅ |
| `generate_signal` | 04:05 | ✅ S1+S2+S3 + Paper 下單 |
| `run_market_context` | 04:10 | ✅ Gemini 市場背景 |
| `update_positions` | 13:35 | ✅ 更新現價 + trailing stop |
| `run_daily_review` | 13:40 | ✅ Layer1+2+3 → Discord |
| `run_weekly_review` | 週五 14:00 | ✅ Gemini 週報 → Discord |
| `run_stock_selection` | 週日 20:00 | ✅ 4-Agent Pipeline |
| `check_monthly_trend` | 月底 22:00 | ✅ |
| `daily_backup` | 23:00 | ✅ checkpoint log |
| `run_monthly_review` | 月底 22:05 | ❌ **未實作**（計劃 §12.11）|

### API 端點

| 端點 | 狀態 |
|------|------|
| `GET /api/v1/signals/current` | ✅ |
| `GET /api/v1/signals/history?days=30` | ✅ |
| `GET /api/v1/positions` | ✅ |
| `GET /api/v1/performance` | ✅ |
| `GET /api/v1/performance/history?days=60` | ✅ |
| `GET /api/v1/review/daily/latest` | ✅ |
| `GET /api/v1/review/weekly/latest` | ✅ |
| `GET /api/v1/agents/market-context/latest` | ✅ |
| `GET /api/v1/agents/black-swan/status` | ✅ |
| `GET /api/v1/watchlist` | ✅ |
| `GET /api/v1/watchlist/prices` | ✅ 即時價格 + 觸發分析 |
| `POST /api/v1/watchlist/prices` | ✅ 部位計算機 |
| `GET /api/v1/portfolio` | ✅ TW+US 持倉 + 匯率 |
| `POST /api/v1/portfolio/import` | ✅ 自動偵測 TW/US CSV |
| `POST /api/v1/tasks/{task_name}` | ✅ 8 個任務手動觸發 |
| `POST /api/v1/backtest/run` | ✅ |
| `POST /api/v1/backtest/compare` | ✅ S1/S2/S3 比較 |

### 超出計劃新增的功能（本次 Sessions）

| 功能 | 說明 |
|------|------|
| Watchlist 即時股價 | `fast_info.last_price` + ±30% 合理性檢查 |
| 進場觸發評分 | 0–7 分制，5 個指標，「立即進場/等待確認/繼續觀察/暫勿進場」 |
| 部位計算機 | 輸入總資金 + 風險 % → 各股建議部位 |
| 持倉追蹤（台股）| 國泰世華 CSV 匯入，止損/獲利追蹤 |
| 持倉追蹤（美股）| 複委託 CSV 匯入，碎股/USD/匯率換算 |
| 今日結論 | 市場背景卡片新增 context_summary + key_risks |
| 止損/目標價 | Watchlist 每股顯示止損（-12%）+ 獲利目標（+24%，2:1 R/R）|
| 52 週位置 | Watchlist 顯示目前股價在年度高低點的百分位 |
| 成交量比 | 近 20 日均量對比 |

### 憑證驗證

| 項目 | 狀態 |
|------|------|
| Supabase PostgreSQL | ✅ 18 張表 |
| Gemini API（gemini-2.5-flash）| ✅ |
| Upstash Redis | ✅ |
| Discord Webhook | ✅ 5 種推播（替代原計劃 Telegram）|
| Telegram BOT_TOKEN | ❌ **已由 Discord 取代，不再需要** |

---

## ❌ 計劃中但未實作

| 項目 | 計劃章節 | 說明 | 優先度 |
|------|---------|------|--------|
| `run_monthly_review` Celery 任務 | §12.11 | 月底執行穩定度評分、月度回測比對、AI 分析頻率自動調整 | 低 |
| `ShadowTestResult` DB 表 | §12.3 | A/B 影子測試結果記錄（新版本上線前比較用）| 低 |
| 真實券商 Adapter | §4.6 | IBKR / 元大期貨連線（`paper` only）| 待策略驗證後 |
| `08:55` 集合競價確認任務 | §2.3 | 開盤前最終確認 + 委託送出 | 待真實下單前 |
| API 認證（JWT Bearer）| §6.1 | 原計劃有 Token 驗證，現在 API 完全公開 | 中（見優化建議）|

---

## 🔧 優化建議（已識別）

### 高優先：安全性

**1. API 缺乏認證** — 所有端點目前無驗證，包括 `POST /api/v1/tasks/{task_name}`（可觸發 Gemini API 呼叫導致額外費用）。計劃 §6.1 原有 Bearer Token 但從未實作。
- **建議做法**：加入簡單 `X-API-Key` header 驗證（Fly.io secret 管理）

### 高優先：效能

**2. ✅ Redis 快取（已實作 2026-06-29）** — `_fetch_price`、`_fetch_usd_twd`、`_fetch_one` 均加入 Upstash Redis 快取（TTL = 300s）。快取命中時直接從 Redis 回傳，跳過 yfinance 請求。另加 `asyncio.wait_for` 逾時（portfolio 25s、watchlist 30s），使用 `pool.shutdown(wait=False)` 防止伺服器掛死。
- **快取 Key 格式**：`zrh:price:{sym}`、`zrh:rate:usdtwd`、`zrh:wl:{sym}`
- **效果**：第一次載入仍需等 yfinance（一次性），後續 5 分鐘內幾乎秒開

### 中優先：功能完整性

**3. 每日任務未排除非交易日** — `generate_signal`、`run_daily_review`、`update_positions` 每天都跑，包含週六、週日、台灣市場休假日。非交易日執行不會產生錯誤（因為 yfinance 不回傳新資料），但多餘的 Gemini API 呼叫會浪費配額。
- **建議做法**：任務開頭加台灣市場是否開市檢查

**4. GitHub CI 沒有阻擋部署** — `deploy.yml` 沒有 `needs: [test]`，所以測試失敗時仍會部署。這是 CI/CD 的品質漏洞。
- **建議做法**：在 deploy.yml 加 `needs: [test]`（需要先確認 test.yml 全通過）

### 低優先：計劃完整性

**5. 月度覆盤未實作** — §12.11 的 `run_monthly_review` 包含穩定度評分計算、月度回測比對、AI 分析頻率自動調整，是策略優化迴路的重要環節。

**6. ShadowTestResult 表缺少** — 若未來需要 A/B 測試策略版本，目前資料庫沒有對應的記錄表。

---

## 📋 建議下一步優先順序

| 優先 | 項目 | 預估工作量 |
|------|------|-----------|
| 1 | API 認證（X-API-Key）| 小（30 分鐘）|
| 2 | Redis 快取 Watchlist/Portfolio 價格 | 中（2 小時）|
| 3 | 每日任務加市場日過濾 | 小（1 小時）|
| 4 | deploy.yml 加 `needs: [test]` | 微（10 分鐘）|
| 5 | `run_monthly_review` 實作 | 中（3 小時）|

---

## 📌 技術決策記錄

| 決策 | 原因 |
|------|------|
| SQLite 作為本地開發 DB | 無需本地安裝 PostgreSQL，prod 仍用 Supabase |
| pydantic-settings 管理設定 | 型別安全 + .env 自動載入 |
| Alembic 使用 sync URL | alembic 本身不支援 async，env.py 自動轉換 |
| Celery rediss:// + CERT_NONE | Upstash Redis TLS 要求，URL 直接附加 ssl_cert_reqs |
| Gemini 取代 Claude API（覆盤/選股）| 避免額外付費，gemini-2.5-flash 免費方案夠用 |
| Discord 取代 Telegram（推播）| BOT_TOKEN 設定複雜，Discord Webhook 更簡單 |
| 持倉 CSV 手動上傳（非 API 串接）| 國泰世華無公開 API，手動匯出 CSV 最穩定 |
| 複委託美股 CSV 自動偵測格式 | 有「代號」欄 = 美股格式，否則 = 台股格式，分 market 儲存 |
| 止損 12%（Numeric，非除100）| `index_stop_loss_pct = 0.12`，直接 `price × (1-0.12)`，不得再除 100 |
