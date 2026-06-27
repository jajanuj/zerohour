# ZeroHour — 開發進度追蹤

> 最後更新：2026-06-28（第三階段完成）

---

## ✅ 已完成且驗證通過

### 基礎設施
- [x] Git repo、目錄結構、pyproject.toml、.gitignore
- [x] Python 3.11、pydantic-settings 設定管理
- [x] Supabase PostgreSQL 連線（Session pooler IPv4）
- [x] Upstash Redis 連線（TLS，Celery broker/backend）
- [x] Fly.io 部署（東京，web×2 + worker + scheduler）
- [x] Docker build、GitHub Actions CI/CD 設定

### 核心交易引擎（第一階段）
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

### 覆盤模組（程式碼存在，模組邏輯測試通過）
- [x] Layer 1 合規檢查（`src/review/layer1_compliance.py`）
- [x] Layer 2 訊號品質分析（`src/review/layer2_signal_quality.py`）
- [x] Layer 3 AI 覆盤 Gemini（`src/review/layer3_ai_analysis.py`）
- [x] 市場環境分類器（`src/review/market_regime.py`）
- [x] 優勢衰減偵測（`src/review/edge_decay.py`）
- [x] 過度擬合防護（`src/review/overfit_guard.py`）
- [x] 穩定度評分（`src/review/stability_scorer.py`）
- [x] 基準比較器（`src/review/benchmark.py`）
- [x] 人為干預追蹤（`src/review/override_tracker.py`）
- [x] 策略版本管理（`src/review/version_manager.py`）
- [x] 稅後損益計算（`src/review/tax_calculator.py`）

### API / 前端
- [x] FastAPI Web Server（`/health`、`/signals/current`、`/positions`、`/performance`、`/backtest/run`）
- [x] Dashboard UI（`src/static/index.html`），即時從 API 抓取資料
- [x] Swagger UI（`/docs`）

### 憑證驗證
| 項目 | 狀態 |
|------|------|
| Supabase PostgreSQL | ✅ 連線成功，18 張表建立完成 |
| Gemini API（gemini-2.5-flash） | ✅ 回應正常 |
| Upstash Redis | ✅ Ping / Read / Write 驗證通過 |
| Telegram 推播 | ⏳ BOT_TOKEN 待設定 |

---

## ✅ P1 完成（2026-06-27）：資料持久化

### DB 寫入狀況

| 表格 | 說明 | 狀態 |
|------|------|------|
| `market_prices` | 美股每日收盤價 | ✅ 寫入（fetch_us_market_data，04:00） |
| `trend_signals` | S1 MA200 訊號紀錄 | ✅ 寫入（generate_signal + check_monthly_trend） |
| `time_diff_signals` | S2 時間差訊號紀錄 | ✅ 寫入（generate_signal，04:05） |
| `orders` | 訂單紀錄 | ✅ 寫入（open_position / close_position） |
| `fills` | 成交紀錄 | ✅ 寫入（open_position / close_position） |
| `positions` | 持倉快照 | ✅ 寫入（open/close/update_position_price） |
| `performance_snapshots` | 績效快照 | ✅ 寫入（update_positions，13:35） |
| `review_reports` | 覆盤報告 | ⏳ 待 P2 |
| `edge_decay_alerts` | 優勢衰減警報 | ⏳ 待 P2 |

### Celery 任務

| 任務 | 排程 | 狀態 |
|------|------|------|
| `fetch_us_market_data` | 04:00 | ✅ 儲存 market_prices |
| `generate_signal` | 04:05 | ✅ S1+S2+S3 + Paper 下單 + DB 寫入 |
| `update_positions` | 13:35 | ✅ 更新現價 + trailing stop + 績效快照 |
| `check_monthly_trend` | 月底 22:00 | ✅ 儲存 trend_signals |
| `run_daily_review` | 13:40 | ⏳ stub（P2 實作） |
| `run_weekly_review` | 週五 14:00 | ⏳ stub（P3 實作） |
| `daily_backup` | 23:00 | ✅ checkpoint log |

### API

| 端點 | 狀態 |
|------|------|
| `GET /api/v1/signals/current` | ✅ 即時計算 S1/S2/S3 |
| `GET /api/v1/positions` | ✅ 從 DB 讀取最新持倉 |
| `GET /api/v1/performance` | ✅ 從 DB 讀取最新績效快照 |
| `GET /api/v1/review/daily/latest` | ✅ 回傳最新每日覆盤 |
| `GET /api/v1/review/weekly/latest` | ✅ 回傳最新週覆盤 |

## ✅ P2 完成（2026-06-27）：每日覆盤完整流程

`run_daily_review`（13:40）：
- Layer1 合規檢查 → Layer2 訊號品質 → Layer3 Gemini AI 分析
- 市場環境分類（MA50/MA200/VIX）
- 儲存 `review_reports` 表格 → Discord 推播

## ✅ P3 完成（2026-06-27）：週覆盤

`run_weekly_review`（週五 14:00）：
- 彙整本週所有訊號 + 交易紀錄
- `run_weekly_ai_review`：Gemini 週報 prompt
- 儲存 `review_reports`（週一日期，避免 unique 衝突）
- Discord 週報推播
- Dashboard 週覆盤區塊（訊號品質 / 市場環境 / AI 摘要）

## ✅ P4 完成（2026-06-27）：Discord 推播

- `src/alerts/discord.py`：5 種推播（訊號/成交/停損/每日摘要/週覆盤）
- DISCORD_WEBHOOK_URL 已設定至 Fly.io secrets
- 整合到 generate_signal / update_positions / run_daily_review / run_weekly_review

---

## ✅ P5 完成（2026-06-27）：GitHub CI/CD

- FLY_API_TOKEN 設定至 GitHub Secrets
- `.github/workflows/deploy.yml` 加入 master 分支觸發
- push master 自動部署至 Fly.io

---

## ✅ 第二階段完成（2026-06-27）

### Agent 系統

| Agent | 檔案 | 排程 | 說明 |
|-------|------|------|------|
| Market Context | `src/agents/market_context_agent.py` | 04:10 每日 | Gemini 解讀美股背景對台股影響 |
| 黑天鵝偵測 | `src/agents/black_swan_agent.py` | 04:07 每日 | VIX/NASDAQ 純量化，無 LLM |
| 基本面 Agent | `src/agents/stock_selection/fundamental_agent.py` | 週日 20:00 | yfinance + Gemini |
| 催化劑 Agent | `src/agents/stock_selection/catalyst_agent.py` | 週日 20:00 | 財報日期 + 新聞 + Gemini |
| 供應鏈 Agent | `src/agents/stock_selection/supply_chain_agent.py` | 週日 20:00 | 靜態知識庫 + Gemini |
| 技術面 Agent | `src/agents/stock_selection/technical_agent.py` | 週日 20:00 | RSI/MACD/MA，純量化 |
| 選股 Pipeline | `src/agents/stock_selection/pipeline.py` | 週日 20:00 | 整合 4 Agent → Watchlist |

### 股票池
15 支台灣科技供應鏈股（2330.TW、2454.TW、2317.TW 等），分數 ≥ 60 進入 Watchlist，最多 8 支。

### 新 API 端點
| 端點 | 說明 |
|------|------|
| `GET /api/v1/agents/market-context/latest` | 最新市場背景分析 |
| `GET /api/v1/agents/black-swan/status` | 近 7 天黑天鵝狀態 |
| `GET /api/v1/watchlist` | 目前 Watchlist |

### Dashboard 新區塊
- 市場背景卡片（驅動力 / 台股關聯度 / 信心修正值）
- 黑天鵝偵測卡片（NONE / WATCH / ALERT / CRITICAL）
- Watchlist 表格（代號 / 分數 / 推薦 / 論點 / 進場條件）

---

---

## ✅ 第三階段完成（2026-06-28）

### 新功能：手動觸發 API
`POST /api/v1/tasks/{task_name}` — 8 個允許的任務名稱

| 任務名稱 | 說明 |
|---------|------|
| `fetch_us_market_data` | 抓取美股資料 |
| `generate_signal` | 生成今日 S1/S2/S3 訊號 |
| `update_positions` | 更新持倉現價 |
| `run_daily_review` | 執行每日覆盤 |
| `run_weekly_review` | 執行週覆盤 |
| `run_market_context` | 市場背景 Agent |
| `check_black_swan` | 黑天鵝偵測 |
| `run_stock_selection` | 選股 Pipeline |

### 新功能：資金曲線圖
- `GET /api/v1/performance/history?days=60` — 每日資金快照
- Dashboard Chart.js 折線圖，顯示 NT$ 總資金 + 報酬率

### 新功能：S1/S2/S3 回測比較
- `POST /api/v1/backtest/compare` — 三策略並排回測
- BacktestEngine 加入 `strategy` 參數（S1/S2/S3）
- Dashboard 表格顯示，最佳值綠色標注

### 新功能：訊號歷史頁
- `GET /api/v1/signals/history?days=30` — 近 30 天訊號紀錄
- Dashboard 表格：日期 / S2 方向 / 信心 / 三大指數 / S1 趨勢 / 建議動作

### 新功能：E2E 測試套件
- `tests/e2e/test_api_e2e.py` — httpx API 測試（17 個 test case）
- `tests/e2e/test_dashboard_playwright.py` — Playwright 瀏覽器測試（需 `pip install playwright pytest-playwright`）

### DB helpers 新增
- `get_performance_history(days)` → `performance_snapshots` 表
- `get_signal_history(days)` → `time_diff_signals` 表 + 對應最近 `trend_signals`

---

## 📋 建議優先順序（第一階段補完）

| 優先 | 項目 | 說明 |
|------|------|------|
| P1 | 資料持久化 | 訊號、訂單、持倉寫入 Supabase，API 從 DB 讀取 |
| P2 | 每日覆盤完整流程 | Layer1+2+3 串接 → 存 DB → Telegram |
| P3 | 每週覆盤 | 週五 14:00，Gemini 分析 + Dashboard 顯示 |
| P4 | Telegram 推播整合 | 設定 BOT_TOKEN，訊號觸發立即推播 |
| P5 | GitHub Secrets / CI/CD | 自動部署啟用 |

---

## 📌 技術決策記錄

| 決策 | 原因 |
|------|------|
| SQLite 作為本地開發 DB | 無需本地安裝 PostgreSQL，prod 仍用 Supabase |
| pydantic-settings 管理設定 | 型別安全 + .env 自動載入 |
| Alembic 使用 sync URL | alembic 本身不支援 async，env.py 自動轉換 |
| Celery rediss:// + CERT_NONE | Upstash Redis TLS 要求，URL 直接附加 ssl_cert_reqs |
| Gemini 取代 Claude API | 避免額外付費，gemini-2.5-flash 免費方案夠用 |
