# SCALPER-SPEC — 策略三：股期影線區間刷單 實作規格書

> **讀者**：負責實作的模型（Sonnet/Haiku）。派工時引用本檔章節號（例：「實作 §6，驗收條件見該節」）。
> **狀態**：2026-07-05 老闆已核准 A1-A6、A8（對話明示「a1-a8,b1-b5全部核准」）。
> **A7（真金下單）不在核准範圍內**——本規格書設計上就把它排除在外，Phase 4 前需另案取得明示核准。
> Phase 0（`scalper/` 骨架、核心決策模組、單元測試）已依此核准實作完成，見下方狀態欄。
> **本模組跑在老闆本地機器（macOS），不部署到 Fly.io。** 生產系統（src/）一行都不准動，除非該節明確列出。

---

## §0. 待核准清單（動工前逐項取得老闆同意）

| # | 項目 | 紅線類別 | 狀態 |
|---|------|----------|------|
| A1 | 新增頂層目錄 `scalper/`（獨立模組，不 import src/）| 架構新增 | ✅ 已核准、已實作 |
| A2 | 新依賴 `shioaji`：只裝老闆本地機器，禁止進生產依賴 | 新增依賴 | ✅ 已核准、已實作（見下方修正說明）|
| A3 | 風險參數 v0：單筆停損 2 ticks、同向庫存上限 1 口、日虧熔斷 3,000 元、連 3 筆虧損休 30 分鐘 | 資金參數 | ✅ 已核准、已實作於 `scalper/config.py` |
| A4 | 保證金撥款額度（建議 50,000 元 = 1 口保證金 + 緩衝）| 資金參數 | ✅ 已核准（僅金額決策，無對應代碼）|
| A5 | Phase 3 前：Supabase 新表 `scalper_trades`、`scalper_daily_stats`（設計見 §10）| DB schema | ✅ 已核准，**尚未實作**（Phase 3 前才建表，見下方進度）|
| A6 | Phase 3 前：生產 API 新增唯讀端點 `GET /api/v1/black-swan/latest`（供本地程式查警報狀態）| API 介面 | ✅ 已核准，**尚未實作**（Phase 3 前才動 `src/`）|
| A7 | Phase 4 真金下單：**屆時另行取得明示核准，本規格書的核准不含此項** | 真金 | ⬜ 鎖定（`ShioajiBrokerAdapter` 全部下單方法已寫死 `raise NotImplementedError`）|
| A8 | CLAUDE.md 路由表加一行指向本檔 | 規則檔 | ✅ 已核准、已實作 |

**A2 修正說明**：規劃時假設用 `requirements-scalper.txt`，但實測發現本專案依賴管理已統一用
`pyproject.toml` 的 `[project.optional-dependencies]`（`dev`、`backtest` 已是此模式），
故比照辦理新增 `scalper` extra group，而非另開一份 requirements 檔。功能等價（`pip install
shioaji` 只在明確加 `.[scalper]` 才會安裝），且 `docker/Dockerfile` 只執行 `pip install
".[dev]"`，scalper extra 不會進生產環境。已驗證 `shioaji` 套件名稱與版本（`pip index versions
shioaji` → 最新 1.5.5），寫入 `pyproject.toml` 為 `shioaji>=1.5.0,<2.0.0`。另新增 `.dockerignore`
排除 `scalper/`、`tests/`、`docs/` 等目錄，確保 `COPY . .` 不會把這些帶進生產 image。

### Phase 0 實作進度（本輪已完成）

`scalper/` 已建立以下模組，全數通過 `python -m py_compile` 與 `pytest tests/unit -x -q`
（115 passed，含 64 個 scalper 專屬測試，覆蓋 §12 要求的核心邏輯）：

| 模組 | 狀態 | 備註 |
|------|------|------|
| `config.py` | ✅ 完成 | pydantic settings，讀 `.env.scalper` |
| `range_engine.py` | ✅ 完成+測試 | 60分K聚合、參考區間、跨日/缺K處理 |
| `grid.py` | ✅ 完成+測試 | §1 v0 規則表核心：進場/逆選擇過濾/停損/區間失效/暫停恢復 |
| `risk_guard.py` | ✅ 完成+測試 | 熔斷/庫存上限/連虧冷卻/結算日過濾 |
| `broker.py` | ✅ 完成+測試 | SimBrokerAdapter（可測）+ ShioajiBrokerAdapter（全數 raise，A7 鎖定）|
| `replay.py` | ✅ 完成+測試 | 悲觀成交模型 + 回測編排（含停利/停損/風控擋單情境）|
| `recorder.py` | ✅ 完成+測試 | SQLite tick 落地 + 完整性驗證 |
| `notify.py` | ✅ 完成+測試 | Discord webhook（mock 測試）|
| `feed.py` | ⚠️ 完成，**未驗證** | Shioaji 連線/訂閱，方法名以官方文件為準，需 Phase 0 §5 實測校正 |
| `contracts.py` | ⚠️ 部分驗證 | 離線量能排行已測試；即時五檔取樣需盤中連線才能驗證 |
| `runner.py` | ⚠️ 骨架 | record 模式邏輯完整但未實測；sim 模式僅骨架，待 Phase 3 補完 |

**老闆下一步需要做的事**（Phase 0 §5 任務 0-1~0-5，見下方章節）：
1. 永豐申請模擬環境 API Key/Secret，填入本地 `scalper/.env`（複製自 `scalper/.env.example`）
2. 本地 `pip install ".[scalper]"` 驗證 shioaji 安裝（macOS 若失敗，備援方案見 §2）
3. 盤中執行 `feed.py` 的登入+訂閱，實測校正官方 API 呼叫方式
4. 執行標的流動性掃描（`contracts.py`），選定 2-3 檔進入 Phase 1 錄製名單

環境變數（老闆自填本地 `.env.scalper`，模型禁止讀取或寫入其內容）：
`SHIOAJI_API_KEY`、`SHIOAJI_SECRET_KEY`、`SHIOAJI_CA_PATH`（Phase 4 才需要）、`SHIOAJI_CA_PASSWORD`（Phase 4）、`SCALPER_DISCORD_WEBHOOK`。

## §1. 策略定義

**一句話**：在前一根已完成 60 分 K 的高低點（含影線）構成的區間內，用股票期貨掛單做均值回歸，抓 1 tick 價差，高勝率小獲利，靠硬規則控制破區間的不對稱虧損。

### v0 規則表（回測起點，參數由 Phase 2 數據修正）

| 規則 | v0 值 | 說明 |
|------|-------|------|
| 參考區間 | 前一根**已完成** 60 分 K 的 [low, high] | 當根 K 進行中不重算區間 |
| 掛買條件 | 現價位於區間下半部（< mid）| mid = (high+low)/2 |
| 掛賣條件 | 現價位於區間上半部（> mid）| 只做回歸方向，不追突破 |
| 出場 | 成交後立刻掛 +1 tick 反向限價單 | 目標利潤固定 1 tick |
| 單筆停損 | 成交後價格反向 2 ticks → 市價出場 | 賺1賠2 → 損益兩平勝率 ≈ 67%＋成本 |
| 逆選擇過濾 1 | 對手方五檔合計量 < 門檻（v0=20 口）→ 撤單不掛 | 薄盤不玩 |
| 逆選擇過濾 2 | 最近 30 秒單邊主動成交量 > 門檻（v0=30 口）→ 撤單暫停 60 秒 | 有人在掃單就閃開 |
| 區間失效 | 成交價突破參考區間 high/low → 平倉 + 停機至下一根 60 分 K 完成 | 趨勢日不對抗 |
| 交易時段 | 09:05–13:15（台北時間）| 現貨（09:00–13:30）開盤後才有真流動性 |
| 每日熔斷 | 日淨虧 ≥ 3,000 元 → 當日停機；連 3 筆虧損 → 休 30 分鐘 | A3 待核准參數 |
| 日曆過濾 | 股期結算日（每月第三個週三）、標的除權息日、黑天鵝警報日 → 整日不出勤 | 見 §8 黑天鵝接口 |

### 合約與成本常數（實作時以期交所/券商公告為準，寫成 config 可調）

- 一般股期 1 口 = 2,000 股；小型股期 1 口 = 100 股
- 目標級距：股價 > 1000 元的小型股期 → tick = 5 元 → **1 tick = 500 元/口**
- 期交稅：契約價值 × 0.00002／邊；手續費 v0 假設 25 元／邊（依實際費率改 config）
- 來回成本 ≈ 50–65 元 → 抓到 1 tick 淨賺約 435–450 元

## §2. 架構總覽與部署邊界

```
┌─ 老闆本地機器（macOS）──────────────┐      ┌─ Fly.io（現有，不動）─────────┐
│ scalper/runner.py（盤中常駐）        │      │ src/（S1/S2/S3、dashboard）   │
│  ├─ feed.py     Shioaji 報價        │      │ Supabase ←──────┐            │
│  ├─ recorder.py 本地 SQLite 落地    │      └─────────────────┼────────────┘
│  ├─ grid.py     掛單決策            │─── Phase 3 起寫交易紀錄 ┘
│  ├─ risk_guard.py 熔斷              │─── 讀 GET /api/v1/black-swan/latest（A6）
│  └─ notify.py   Discord webhook     │
└─────────────────────────────────────┘
```

**硬性邊界（違反 = 立即停手）**：
1. `scalper/` **禁止 `import src.`**（避免把生產設定與重依賴拖進本地；Discord 用獨立輕量 webhook client）
2. `shioaji` 禁止出現在 `requirements.txt`、`Dockerfile`、`fly.toml` 任何一處
3. tick 原始資料只落本地 SQLite（`scalper/data/*.db`，gitignore），**禁止塞進 Supabase**
4. Phase 0–2 全程不下任何真實單；Phase 3 只用 simulation=True；Phase 4 開關見 A7

**macOS 相容性**：Phase 0 第一步實測 `pip install shioaji`；若該機型無可用 wheel，改用 Docker Linux 容器（shioaji Linux 支援最成熟），兩路擇一通過即可。

## §3. 目錄結構與模組職責

```
scalper/
├── __init__.py
├── config.py        # ScalperSettings（pydantic BaseSettings，讀 .env.scalper）
├── feed.py          # ShioajiFeed：登入、訂閱 tick+五檔、斷線重連、回呼分發
├── contracts.py     # 標的掃描：列股期合約、近30日量/價差/五檔厚度排行（§5）
├── recorder.py      # TickRecorder：SQLite 批次寫入、日檔輪替、收盤壓縮
├── range_engine.py  # RangeEngine：60分K聚合、參考區間狀態機
├── grid.py          # GridStrategy：§1 規則表的掛單決策狀態機（純函式核心，可回測復用）
├── risk_guard.py    # RiskGuard：庫存/停損/熔斷/日曆過濾，唯一有權下「停機」指令的模組
├── broker.py        # BrokerAdapter：place/cancel/list_positions 統一介面，sim 與 real 同介面
├── replay.py        # Replayer：讀錄製 SQLite 重放，悲觀成交模型（§7）
├── notify.py        # Discord webhook（httpx.post，5 秒 timeout，失敗只 log 不 raise）
├── runner.py        # 入口：開盤自檢 → 訂閱 → 事件迴圈 → 收盤收檔（launchd 排程啟動）
└── data/            # 本地 SQLite（gitignore）
```

**設計鐵則**：`grid.py` 與 `range_engine.py` 的核心必須是**純函式**（輸入 tick/五檔事件 → 輸出動作列表），不直接呼叫 broker——這樣 Phase 2 回測與 Phase 3 實跑跑的是同一份決策代碼，回測才有效。

## §4. Shioaji 介接注意事項

- 官方文件 https://sinotrade.github.io/ 。**方法名與參數以實測為準**，實作前先在 Python REPL 驗證登入與訂閱流程，把實測可跑的最小片段記進本節（允許更新本檔此節）。
- 模擬模式：`shioaji.Shioaji(simulation=True)` + API Key/Secret 登入；真實下單需 CA 憑證（Phase 4）。
- 訂閱數有上限（約 200 檔），本策略最多同時訂 3 檔，無壓力。
- 歷史資料：`api.ticks()`（逐筆）與 `api.kbars()`（K 棒）可拉近期資料，供 §5 標的掃描與 60 分 K 初始化。
- **LESSONS 繼承**：所有 API 呼叫包 timeout；所有數值過 `math.isnan()`；回呼函式內禁止阻塞操作（寫檔交給 queue + 背景執行緒）。

## §5. Phase 0 — 骨架與標的掃描

| 任務 | 產出 | 驗收（貼輸出）|
|------|------|---------------|
| 0-1 | 本地 venv 裝 `shioaji`（或 Docker 備援）| `python -c "import shioaji; print(shioaji.__version__)"` |
| 0-2 | `config.py` + `.env.scalper.example`（只有 key 名，無值）| `python -m py_compile scalper/config.py` |
| 0-3 | `feed.py` 模擬登入 + 訂閱 1 檔股期 tick | 盤中執行 60 秒，stdout 印出 ≥ 10 筆 tick |
| 0-4 | `contracts.py` 標的掃描：全部股期近 30 日日均量、平均價差、五檔厚度，輸出排行 CSV | CSV 存在且 ≥ 50 檔；股價>1000 的小型股期子表另列 |
| 0-5 | 把 0-4 排行前 3 檔呈給老闆選定錄製名單 | 老闆回覆選定 | 

**過關條件**：0-3 報價流穩定 + 老闆選定 2–3 檔錄製標的。

## §6. Phase 1 — Tick 錄製器（跑 2–4 週）

- 錄製內容：選定標的的逐筆成交（時間、價、量、內外盤）+ 五檔（買賣各五檔價量），本地 SQLite，一天一檔 `data/ticks_YYYYMMDD.db`。
- 排程：launchd 於 08:40 啟動 `runner.py --mode record`，13:50 自動收檔退出。
- 韌性：斷線自動重連（指數退避，上限 5 次後 Discord 告警）；每日收盤推 Discord 摘要（各標的筆數、最大資料空窗秒數）。
- **驗收**：連續 5 個交易日，每日摘要筆數 > 0 且最大空窗 < 60 秒；SQLite 可用 `replay.py --validate` 通過完整性檢查（時間戳單調、無 NaN 價格）。

**過關條件**：≥ 10 個交易日的乾淨資料。

## §7. Phase 2 — 悲觀回測

成交模型（**悲觀假設，禁止放寬**）：
1. 掛單進隊：掛出當下，記 `Q_ahead` = 該價位當時五檔顯示量（我排最後）。
2. 成交判定（二擇一達成）：(a) 掛單後該價位累積成交量 > `Q_ahead`；(b) 成交價**穿過**掛單價（嚴格優於，觸價不算）。
3. 延遲：下單與撤單各加 300ms 模擬延遲，期間的行情變化照吃。
4. 成本：§1 稅費常數，每筆計入。

輸出報表（`scalper/reports/backtest_YYYYMMDD.md`）：總筆數、勝率、平均賺/虧 ticks、淨損益、最大單日虧損、破區間日的損益分佈、參數敏感度表（庫存上限×停損檔數×五檔量門檻的網格掃描）。

**過關條件（全達才進 Phase 3）**：
1. 悲觀模型下淨期望值 > 0
2. 最大單日虧損 ≤ 熔斷線（3,000 元）——即熔斷規則真的擋得住尾部
3. 移除任一單日最賺的日子後仍為正（不能靠一天吃飯）

## §8. Phase 3 — 模擬盤實跑（2–4 週）

- `runner.py --mode sim`：simulation=True 真下單模擬撮合，`grid.py` 同一份決策代碼。
- 上線前置（需 A5、A6 核准後實作）：交易紀錄寫 Supabase `scalper_trades`；每日收盤寫 `scalper_daily_stats`；開盤自檢呼叫 `GET /api/v1/black-swan/latest`，severity ≥ ALERT → 今日不出勤並推 Discord。
- 熔斷實測：人為觸發（調低熔斷線跑一天）驗證停機與 Discord 告警真的發生。
- **過關條件**：模擬盤勝率/成交率與 Phase 2 回測差距 < 15%（差距大 = 成交模型失真，回 Phase 2 校正）；熔斷實測通過。

## §9. Phase 4 — 真金（A7 鎖定，屆時另案核准）

前置：CA 憑證啟用、老闆書面（對話明示）核准、只做 1 口、只做老闆指定 1 檔。
本階段規格屆時另補，本檔先鎖定不展開。

## §10. Supabase 資料表設計草案（A5 待核准，Phase 3 前實施）

```sql
CREATE TABLE scalper_trades (
  id BIGSERIAL PRIMARY KEY,
  trade_date DATE NOT NULL,
  symbol TEXT NOT NULL,              -- 股期合約代碼
  direction TEXT NOT NULL,           -- LONG / SHORT
  qty INT NOT NULL,                  -- 口數
  entry_ts TIMESTAMPTZ NOT NULL,
  entry_price NUMERIC(10,2) NOT NULL,
  exit_ts TIMESTAMPTZ,
  exit_price NUMERIC(10,2),
  ticks_pnl INT,                     -- 賺賠幾檔
  fees NUMERIC(10,2) DEFAULT 0,      -- 手續費雙邊
  tax NUMERIC(10,2) DEFAULT 0,       -- 期交稅雙邊
  net_pnl NUMERIC(12,2),
  exit_reason TEXT,                  -- TP / SL / RANGE_BREAK / EOD / FUSE / MANUAL
  mode TEXT NOT NULL DEFAULT 'sim',  -- sim / real
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE scalper_daily_stats (
  trade_date DATE NOT NULL,
  symbol TEXT NOT NULL,
  n_trades INT DEFAULT 0,
  win_rate NUMERIC(5,4),
  net_pnl NUMERIC(12,2),
  max_intraday_drawdown NUMERIC(12,2),
  fuse_triggered BOOLEAN DEFAULT FALSE,
  mode TEXT NOT NULL DEFAULT 'sim',
  notes TEXT,
  PRIMARY KEY (trade_date, symbol, mode)
);
```

## §11. 錯誤處理準則（從 docs/harness/LESSONS.md 繼承 + 本模組特有）

1. 所有外部 IO（Shioaji、Discord、生產 API）包 timeout；逾時不得卡死事件迴圈
2. 所有價格量值先過 `math.isnan()` / None 檢查再運算
3. **斷線時的安全姿勢**：偵測到連線中斷 → 立即嘗試撤銷所有未成交掛單；重連成功後先對帳（查詢實際持倉與掛單）再恢復報價決策；對不上帳 → 停機 + Discord 告警，等人工處理
4. 回呼執行緒內只做入隊，重活（寫檔、HTTP）在背景執行緒
5. 任何未捕捉例外 → 停機（撤單+告警），**禁止 catch 後繼續跑**——刷單程式帶傷上陣比停機危險

## §12. 測試要求

- `tests/unit/scalper/` 內至少覆蓋：`range_engine`（區間計算、跨日、缺 K）、`grid`（規則表每一列至少一個 case，含區間失效與逆選擇過濾）、`risk_guard`（熔斷觸發、連虧計數、日曆過濾）、`replay` 成交模型（Q_ahead 消化、穿價成交、觸價不成交）
- 純函式設計使上述測試不需要 mock Shioaji
- push 前照 CLAUDE.md：`python -m py_compile` 改動檔 + `python -m pytest tests/unit -x -q`

## §13. 禁止事項總表（派工單必附）

1. 禁止動 `src/`（除 A6 核准後的唯讀 endpoint 一處）
2. 禁止 `shioaji` 進生產依賴檔
3. 禁止 `import src.` 於 scalper/ 內
4. 禁止讀寫 `.env*` 內容（含 `.env.scalper`）
5. 禁止任何真實下單代碼路徑在 Phase 0–3 被啟用（`mode real` 必須硬編碼 raise，直到 A7 核准）
6. 禁止 `git add -A` / `git add .`
7. tick 資料禁止進 git（`scalper/data/` 入 .gitignore）
