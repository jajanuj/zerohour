# ZeroHour — 開發進度追蹤

> 最後更新：2026-06-27

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
| `GET /api/v1/review/daily/latest` | ❌ 端點不存在（P2） |
| `GET /api/v1/review/weekly/latest` | ❌ 端點不存在（P3） |

---

## ❌ 尚未實作（第一階段剩餘）

1. **P2 每日覆盤完整流程**：Layer1→Layer2→Layer3(Gemini)→存 review_reports→Discord 推播
2. **P3 每週覆盤**：週五 14:00，本週訊號統計 + Gemini 彙整 + Dashboard 顯示
3. **P4 Discord 推播整合**：Webhook URL 待老闆提供，訊號觸發立即推播
4. **P5 GitHub Secrets / CI/CD**：FLY_API_TOKEN 等 Secrets 設定後自動部署

---

## ❌ 尚未實作（第二階段 — 等第一階段穩定後）

> 計劃文件 §13，目前只有空目錄和 DB 表格定義

| 功能 | 說明 |
|------|------|
| Market Context Agent | 分析整體市場環境（`src/agents/market_context_agent.py`，未建立）|
| 黑天鵝偵測 Agent | 偵測尾部風險事件（`src/agents/black_swan_agent.py`，未建立）|
| 基本面選股 Agent | 護城河 + 成長性分析 |
| 催化劑選股 Agent | 業績 / 新聞觸發因素 |
| 供應鏈選股 Agent | 台灣供應鏈相關性 |
| 技術面選股 Agent | 型態確認 |
| 選股整合 Pipeline | 輸出最終 Watchlist |
| Watchlist 管理 | DB 寫入 + Dashboard 顯示 |

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
