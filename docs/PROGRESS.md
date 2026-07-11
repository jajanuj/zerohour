# ZeroHour — 開發進度追蹤

> 結構規則：新條目寫在下方「📍 最新狀態」區**頂部**（一個 session 一個小節）。
> Session 啟動只讀本檔前 40 行。歷史細節在檔案下半部，按需查閱。
> 超過 250 行觸發壓縮（見 docs/harness/F-knowledge-protocol.md §4）。

---

## 📍 最新狀態（新的寫最上面）

### 2026-07-11 — 生產事故：Upstash Redis 免費額度耗盡修復

**觸發**：老闆轉來 Upstash 通知——ZeroHour 資料庫已達免費方案 500,000 命令/月
上限。老闆表示先前評估過用量不應該這麼高。

**根因**：Celery 用 Kombu redis transport 當 broker，`src/tasks.py` 建立
`Celery(...)` 時沒設定 `broker_transport_options`，Kombu 對應的
`brpop_timeout` 因此吃預設值 **1 秒**。Worker（`--pool=solo -B`，fly.toml）
閒置等任務時，每秒發一次 `BRPOP` 輪詢 4 個佇列——`24h × 3600 = 86,400`
次/天，換算約 **259 萬次/月**，是免費額度的 5 倍以上。這個系統每天只有
04:00/04:05/04:07/04:10/13:35/13:40 等少數幾次排程任務真的在執行，絕大多數
命令都是「閒置空轉輪詢」，跟實際任務執行量完全不成比例——這正是老闆先前
評估時容易漏算的一塊（只算了「跑幾次任務」，沒算「等任務的輪詢成本」）。

**修復**（commit `c1c5c47`）：`celery_app.conf.broker_transport_options =
{'polling_interval': 10}`。BRPOP 是阻塞式指令，訊息一到就立即喚醒，此設定
**完全不影響任務被撿起的即時性**，只降低「真的閒置時」重新發問的頻率
（1 次/秒 → 1 次/10 秒）。預期輪詢命令量降至約 1/10（259 萬/月 → 約 26
萬/月），額度內有充足餘裕。新增 2 個回歸測試防止未來被移除，全套 203
passed（201→203）。

**其他次要貢獻源（本次未動，供未來需要更多餘裕時參考）**：
1. RedBeat 排程器的 tick/lock 續租，估計每 5 分鐘一次、每次數個命令，
   約 3–4.5 萬次/月（比 BRPOP 輪詢小 60–80 倍，非優先項）
2. `Celery(..., backend=_redis_url)` 的 result backend 全程無人讀取
   （`grep AsyncResult` 全 codebase 零結果），每次任務完成的寫入是純浪費，
   但任務量小（每天約 10 次），影響可忽略

**下一步**：觀察下個月 Upstash 用量報表，確認命令數大幅下降；若仍偏高，
可考慮上述兩個次要項目或把 `polling_interval` 再拉大。

### 2026-07-11 — 生產事故：Gemini API 金鑰外洩到 Discord 修復

**觸發**：老闆轉來 Discord 週覆盤截圖——「AI 週報」欄顯示 Gemini 呼叫失敗訊息
`Server error '503 Service Unavailable' for url '...generateContent?key=<真實金鑰>'`，
完整金鑰直接暴露在頻道訊息中。

**根因**：5 個 Gemini 呼叫點（market_context_agent、catalyst_agent、
fundamental_agent、layer3 日/週 AI 覆盤）都把金鑰放在 URL query string
（`?key=...`）。Gemini 服務端 503 時，httpx 拋出的例外字串內含完整請求 URL；
`layer3_ai_analysis.py` 的 `except Exception as e: return f"...{e}"` 把這段
含金鑰的例外文字直接回傳，一路流進 Discord 週報訊息。

**修復**（commit `3ed39fb`、`86937c0`）：
1. 全部 5 個呼叫點改用 `x-goog-api-key` header 傳金鑰，金鑰不再出現在 URL
2. 新增 `redact_secrets()`（`src/agents/gemini_usage.py`）作第二道防線：
   log、DB（`agent_run_logs.error_message`，即上次 Gemini 用量查看功能存的
   欄位）、回傳給呼叫方的文字，一律先過濾金鑰
3. 新增 8 個測試（`tests/unit/test_gemini_usage.py`），用
   `httpx.MockTransport` 重現 503 情境驗證金鑰不進 URL、不外洩
4. **診斷過程中順帶發現另一個問題**：`test_api_key_guard.py` 有兩個測試會讓
   請求真的打到查 DB 的 handler；本機 `.env` 目前指向生產 Supabase（同
   07-07 EMAXCONNSESSION 事故那顆），這兩個測試因此會真的連線且連線沒關乾淨
   （`PYTHONTRACEMALLOC=25` 追出 ResourceWarning 堆疊確認）。已 mock 掉
   `get_agent_runs` 修復（`86937c0`），全套 201 passed（193→201，新增 8 個）

**金鑰輪替**：老闆已確認該 Discord 頻道僅自己可見，風險低，**決定不換金鑰**
（2026-07-11 對話中明示）。代碼修復（header 傳遞 + redact_secrets）已上線，
不論金鑰換不換，往後同類錯誤都不會再外洩任何密鑰到 Discord。此項視為結案，
非待辦。

**下一步**：觀察下次 Gemini 呼叫（04:10 市場背景/13:40 日覆盤/週五 14:00
週覆盤）即使再次逾時/出錯，Discord 訊息中不會再出現任何金鑰片段。

### 2026-07-07 — 生產事故：Supabase 連線池耗盡修復（EMAXCONNSESSION）

**觸發**：老闆轉來 Discord 系統錯誤截圖——`run_daily_review` 於 2026-07-06 下午
13:40 報錯 `(EMAXCONNSESSION) max clients reached in session mode - max clients
are limited to pool_size: 15`。

**根因**：`src/database/__init__.py` 的 `sync_run()`（Celery 任務橋接 sync→async
的唯一入口，`tasks.py` 內 41 處呼叫點）每次呼叫都用 `asyncio.run()` 建一顆新
event loop、跑完就關閉；且跑之前 `dispose(close=False)`——這個 `close=False`
是 6/28 兩次 commit（`758d301`、`9329a1d`）為了修「Future attached to a
different loop」錯誤而選擇的做法：不真的關閉舊 loop 綁定的底層連線（關閉會拋
錯），而是直接棄置。Celery worker 用 `--pool=solo`（fly.toml，單行程單執行緒
長駐），這些沒真正關閉的 asyncpg 連線在 worker 生命週期內逐日堆積、從未釋放，
9 天後打穿 Supabase session pooler 的 `pool_size=15` 上限。

**診斷過程中的意外驗證**：本機跑診斷測試時，其中一版測試意外連上生產 Supabase
（本機 `.env` 設定的是生產 DATABASE_URL）並**當場重現同一個 EMAXCONNSESSION
錯誤**——證實事故是持續性的（連線持續處於耗盡邊緣），不是單次事件。已改寫測試
改用獨立記憶體 SQLite engine，避免測試碰觸本機環境變數指向的生產資料庫。

**修復**（commit `66e3e02`）：`sync_run()` 改為復用單一常駐 event loop（模組級
全域變數，`--pool=solo` 單執行緒序列跑任務、天生安全），移除 `dispose` 呼叫，
連線池交回 SQLAlchemy 正常管理與回收，不再逐次建了又棄。新增 4 個回歸測試
（含模擬多任務週期的 DB session 往返），全套 193 passed（189→193）。

**與過去修復的關係**：`758d301`／`9329a1d` 的原始問題（different loop 錯誤）
本次修復依然解決——因為現在全程只有一顆 loop，跟本不會有「連線綁在別的 loop」
的情況；等於是把當初的繞道 workaround 換成真正的根治。

**下一步**：push 後除了 CI 綠燈 + 煙霧測試，**還需額外確認部署後的
worker 有正常重啟**（deploy.yml 既有的 scale 0→1 步驟會強制重啟 worker VM，
副作用是清掉舊 process 遺留的、已卡住的 TCP 連線——這對於解除當下已經耗盡的
連線額度是必要的，不只是防未來再犯）。建議明天（下一個交易日）觀察
04:05/13:40 等排程任務是否恢復正常，Discord 若無新的 EMAXCONNSESSION 錯誤即
代表修復生效。

### 2026-07-06 — 安全與維運補強五連發（老闆逐項核准）

**任務目標**：老闆核准五項：API 認證 + Gemini 呼叫記錄與查看、deploy.yml 測試閘門、
每日任務非交易日過濾、PositionSizer 超買修復、PROGRESS 精簡。

**已完成**（commit 順序 `b94bf53`→`42910bb`→`9c103fe`→`67b49ed`→`6113c77`→`84086a0`）：
- ✅ **PROGRESS 精簡**：依 F 協議 §4，最新狀態留 5 個 session，其餘壓為單行摘要移歷史區
  （440→380 行；備份於本機 scratchpad，完整版在 git 歷史）
- ✅ **deploy.yml 測試閘門**：test job + `needs:[test]`（A 診斷書痛點三 patch），
  單元測試不過不部署——生產直通車正式關閉
- ✅ **非交易日過濾**：新增 `src/data/market_calendar.py`（UTC+8 週末 +
  `TW_MARKET_HOLIDAYS` 假日清單），guard 掛在 generate_signal / update_positions /
  run_daily_review / run_market_context；週報（五）/選股（日）/黑天鵝（安全監控）不過濾
- ✅ **PositionSizer 超買修復**（老闆核准動 src/risk/）：lot_size>1 資金不足一張 →
  blocked（原 `max(1,...)` 會強制買滿）；足夠時無條件捨去到整張並對齊金額；
  lot_size=1 零股路徑行為不變
- ✅ **Gemini 呼叫記錄**：`agent_run_logs` 表/`log_agent_run()` 一直存在但**從未接線**——
  新增 `src/agents/gemini_usage.py`，接上全部 5 個呼叫點（market_context、daily/weekly
  review、catalyst、fundamental）；新端點 `GET /api/v1/agents/gemini-usage`；
  dashboard 新增「Gemini 用量」卡（今日次數 vs RPD 20、tokens、近 8 筆）
- ✅ **API 認證**：X-API-Key middleware 保護全部 /api/v1/*（豁免 health/OPTIONS/首頁）；
  `api_key` 為空 = 停用；前端 fetch wrapper 自動帶 key、401 prompt 一次
- ✅ 測試 171 → 189（新增 18 個：日曆 7 + 倉位 4 + 認證 7），既有測試零改動

**遇到的問題**：
1. 本地 venv 缺 `python-multipart`（pyproject 既有宣告依賴，非新增），補裝後測試全過
2. **閘門首航就擋下隱形 CI 失敗**：`aiosqlite` 從未宣告在依賴（config.py 預設
   sqlite+aiosqlite，本地能跑是手動裝過），Phase E 起 Test & Lint 連紅 4 次被
   無閘門部署掩蓋。老闆核准後補進 dev extras（`c4b8660`），兩個 workflow 轉綠、
   部署成功；教訓已入 LESSONS（push 後必查 `gh run list`，煙霧 200 ≠ CI 綠）

**⚠️ 待老闆一件事**：API 認證代碼已部署但**金鑰未設定前驗證是停用的**（fail-open）。
請執行 `fly secrets set API_KEY=<自訂長隨機字串>` 啟用；設定後開 dashboard 會跳出
輸入框，貼同一組 key 即可。另 `TW_MARKET_HOLIDAYS` 假日清單可視需要用
`fly secrets set` 補（格式 `2026-10-09,2026-10-10`，未填只過濾週末）。

**下一步**：S4 觀察期進行中（3 個交易日）；剩餘未完成項見歷史區
「計劃中但未實作」（月度覆盤、熔斷落地 Redis、ShadowTestResult 等）。

### 2026-07-06 — S4 台股趨勢確認因子實作上線（規格：docs/strategy-s4-spec.md）

**任務目標**：S4 = S3 的 BUY 倉位調整係數（方案 A）。台股自身趨勢不健康時買一樣的訊號、
買少一點。S3 進出時點/決策矩陣/停損停利零變更。

**已完成**：
- ✅ TWSE BFI82U 端點實測並記入規格 §2（rwd 端點可用、openapi 302 棄用、
  假日 stat 非 OK 跳過、金額單位元）
- ✅ 新增 `src/signals/taiex_confirm.py`：^TWII 200MA（復用 MA200Filter）+ 法人 5 日淨額，
  §3 係數表 v0，fail-open ×1.0，係數夾限 [0.5,1.0]，逐次 timeout 10s / 總預算 30s /
  回看上限 10 天
- ✅ `tasks.py::generate_signal` 接點：`effective_position_pct = suggested × s4.modifier`
  只餵給 BUY 的 PositionSizer；S4 入庫 `save_trend_signal(symbol="TAIEX")`（B4 無 schema
  變更，帶 conditions 明細）；無資料時 Discord system_error 警告；signal_alert reason
  追加 s4.reason
- ✅ 連帶修正：`get_signal_history` 的 TrendSignal 查詢加 `symbol=="QQQ"` 過濾
  （TAIEX 列入庫後會污染 dashboard S1 欄位，原查詢無 symbol 條件）
- ✅ `tests/unit/test_taiex_confirm.py` 18 個測試（§3 表 5 列/假日跳過/部分失敗/
  資料不足/夾限/預算耗盡/結構異常/conditions），全套 171 passed
- ✅ 隔離驗收 PASS（E 檔模板 4，獨立 Sonnet 驗收官，14 項判準全過、差異清單「無」；
  確認 HOLD/SELL/EXIT_ALL 路徑 diff 為零、禁改檔零異動）

**踩坑**：Windows `time.monotonic()` 解析度粗，預算歸零測試用 `>` 判不出來 → 改 `>=`

**下一步**（規格 §7.3）：觀察 3 個交易日的 04:05 Discord 訊號中 S4 reason 是否合理；
首個交易日後查 `trend_signals` 表 TAIEX 列確認入庫正常。

### 2026-07-05 — 報表可觀測性優化 6 項全部完成（計畫：docs/report-optimization-plan.md）

**任務目標**：老闆核准借鑑外部 AI 交易報表的 6 項設計（逐條件明細/品質註記/決策下一步/
Run 資訊/新面孔標記/關鍵價位），全部為觀測層工作，訊號公式與決策矩陣零變更。

**已完成**（6 個 feature commit，每個都煙霧測試 200；`2729b00`→`5097cd3`→`b7e3d6a`→
`f4791db`→`d5979e4`→Phase F）：
- ✅ **A** schema：trend_signals/time_diff_signals 加 `conditions`(JSON)、time_diff_signals 加
  `next_step`、watchlist 加 `is_new`；走 `database/__init__.py` 啟動時 idempotent ALTER 慣例
- ✅ **B** S1/S2/S3 逐條件明細（name/label/passed/actual/threshold）：訊號 dataclass → 落庫 →
  API → dashboard chips；快取 key 換版 v2
- ✅ **D** 資料品質註記：共用 `safe_change_pct`，`/signals/current` 與 `/portfolio` 回
  `quality_notes`（指數缺值/抓價 fallback/逾時不再靜默）；**順帶修復 tasks.py 三處
  `or 0.0` 擋不住 NaN 舊坑**（generate_signal / check_black_swan / run_market_context，
  LESSONS 2026-06 同型坑，routes 當時修了 tasks 全漏——黑天鵝偵測拿 NaN 比較會靜默不觸發）
- ✅ **C** `CombinedSignal.next_step`（四分支具體文案）+ `key_levels`（MA200 緩衝上下緣、
  BUY 時 0050 進場/停損價，timeout 10s + isfinite 防護）；快取 key 換版 v3；
  aggregator 新增兩個僅供文案的 buffer 參數（有測試守護不影響決策）
- ✅ **E** watchlist 新面孔：`compute_new_faces` 純函數（首期全 False），NEW 徽章 +
  Discord ★ 前綴
- ✅ **F** `from_cache` 快取徽章、訊號歷史 #id、頁尾免責聲明
- ✅ 測試 115 → 153（新增 38 個，既有測試零改動）；本地 `zerohour_dev.db` 已刪除重建

**與計畫的偏差**（均已在對應 commit 註明）：
1. portfolio 品質註記用獨立 `portfolio-quality` div（計畫寫 portfolio-msg，但該元素被
   CSV 匯入訊息佔用，共用會互相覆蓋）
2. NaN 修復範圍從計畫的 generate_signal 一處擴大到三處（同 bug 同修法，黑天鵝那處最危險）
3. Phase E 測試改測抽出的純函數（repo 沒有現成的 DB 測試模式，不為此新建）

**下一步**：等下次訊號生成（04:05）與週日選股後，檢查 dashboard 條件 chips、
next_step、新面孔徽章的實際顯示；S4（策略一台股趨勢確認）仍待動工。

### 2026-07-05 — 策略三（scalper）Phase 0 核心模組實作完成【交接用完整版】

**任務目標**：老闆核准 scalper-spec.md 全部 A 項與 strategy-s4-spec.md 全部 B 項（A7 真金下單
除外，設計上本就排除在外），指示「先完成策略三」。本輪建立完整 `scalper/` 模組（Phase 0 骨架 +
Phase 1 錄製器 + Phase 2 悲觀回測引擎），S4（策略一）尚未動工，留待下一輪。

**已完成到哪**（commit `59786a8`，已 push，CI + Deploy 皆綠燈，煙霧測試 200）：
- ✅ 新增 `scalper/` 獨立模組（不 import src/，不進 Fly.io 部署）：
  `config.py`、`range_engine.py`（60分K/參考區間）、`grid.py`（v0規則表決策核心：進場/
  逆選擇過濾/停損/區間失效/暫停恢復）、`risk_guard.py`（熔斷/庫存上限/連虧冷卻/結算日過濾）、
  `broker.py`（SimBrokerAdapter 可測 + ShioajiBrokerAdapter 全數 raise，A7 鎖定未實作）、
  `replay.py`（悲觀成交模型 + 回測編排）、`recorder.py`（SQLite tick落地）、`notify.py`
  （Discord webhook）、`feed.py`/`contracts.py`/`runner.py`（Shioaji 連線骨架，**未經實測**，
  方法名以官方文件為準，Phase 0 §5 待老闆本地實測校正）
- ✅ `pyproject.toml` 新增 `[project.optional-dependencies] scalper`（`shioaji>=1.5.0,<2.0.0`，
  已用 `pip index versions shioaji` 驗證存在與版本）——**與規格書原訂的
  `requirements-scalper.txt` 不同**，改用本專案既有的 pyproject extras 慣例，功能等價
- ✅ 新增 `.dockerignore`（排除 `scalper/`、`tests/`、`docs/` 等，確保生產 image 不含這些）
- ✅ `tests/unit/scalper/`：64 個新測試，覆蓋 §12 要求全部核心邏輯（含跨日/缺K、逆選擇過濾、
  停利/停損/區間失效/暫停恢復、風控熔斷、悲觀成交模型的三種成交/不成交情境）
- ✅ `docs/scalper-spec.md` §0 更新核准狀態與 A2 修正說明；CLAUDE.md 路由表加 scalper 與 S4 兩行

**遇到的問題**：
- 規格書假設用 `requirements-scalper.txt`，實測發現專案已用 `pyproject.toml` optional-dependencies
  慣例（`dev`/`backtest` 已是此模式），改用同一慣例新增 `scalper` extra group，功能等價且更一致
- 設計時發現「區間失效」邏輯若只在 FLAT 狀態檢查會有漏洞（持倉中價格突破區間不會被攔截，
  只靠 2-tick 停損但停損距離可能大於區間邊界距離）→ 修正為持倉中也檢查突破，突破優先於停損
- 寫 `test_replay.py` 時因為用各自獨立的 `timedelta` 偏移量拼事件時間戳，導致事件順序顛倒
  （已追加進 LESSONS.md，見下方踩坑檢查）

**下一步 — 已核准可做**：
1. 老闆本地：永豐申請模擬 API Key → 填 `scalper/.env`（複製自 `scalper/.env.example`）
2. 老闆本地：`pip install ".[scalper]"` 驗證 shioaji 安裝（macOS 失敗則走 Docker 備援，見
  scalper-spec.md §2）
3. 老闆本地：盤中實測 `feed.py` 登入/訂閱，校正官方 API 呼叫方式，回饋給模型修正
4. 老闆本地：跑 `contracts.py` 標的流動性排行，選定 2-3 檔進 Phase 1 錄製名單
5. S4（策略一補強）：B1-B5 已核准，規格見 strategy-s4-spec.md，可隨時開工（下一輪處理）

**下一步 — 待老闆決策**：
- `docs/PROGRESS.md` 現已超過 250 行精簡觸發線（F協議§4），精簡前依規則須先問老闆同意，
  上一輪已提出、老闆尚未回覆是否要精簡
- A7（真金下單）：Phase 4 前才需要決策，目前不急

**User 已核准 vs 尚未核准**：
- ✅ 已核准：scalper-spec.md A1-A6、A8（A7 明確排除，鎖定）；strategy-s4-spec.md B1-B5 全部
- ⬜ 尚未核准：A7 真金下單（規格設計上就排除在外，需屆時另案取得明示同意）；
  `scalper/` 內任何真金下單代碼路徑（目前 `ShioajiBrokerAdapter` 全數硬編碼 raise，
  移除這道 raise 需要 A7 核准後才可進行）

**涉及檔案**：新增 `scalper/`（12 個 .py + `.env.example`）、`tests/unit/scalper/`（8 個測試檔）、
`.dockerignore`；修改 `pyproject.toml`、`CLAUDE.md`、`docs/scalper-spec.md`、本檔

**驗證**（交接時重跑確認狀態未變）：`python -m pytest tests/unit -x -q` → 115 passed；
`git status --short` → clean（本輪純交接文件整理，無新增/修改 .py 檔）

### 2026-07-05 — 新策略規格書落地（S4 台股趨勢確認 + 策略三股期刷單），待老闆核准

**任務目標**：老闆要加兩個新策略，且實作將派給較弱模型照文件執行，因此先把討論結論
落成規格書，並把所有紅線核准項集中列出待裁決。**本輪零代碼改動，僅文件。**

**已完成到哪**：
- ✅ [docs/strategy-s4-spec.md](strategy-s4-spec.md)：策略一定案為「S4 台股趨勢確認因子」（方案 A）——
  TAIEX 200MA + 三大法人 5 日淨額 → 倉位係數 ×0.5–1.0，只縮放 S3 的 BUY 倉位，
  進出時點/停損停利不變。待核准項 B1–B5 在該檔 §0。
- ✅ [docs/scalper-spec.md](scalper-spec.md)：策略三「股期影線區間刷單」完整規格——
  獨立 `scalper/` 模組跑老闆本地 macOS（不部署 Fly.io、禁 import src/）、券商永豐 Shioaji、
  Phase 0 骨架→1 錄 tick→2 悲觀回測→3 模擬盤→4 真金（鎖定另案核准），
  v0 規則表與熔斷參數在 §1，待核准項 A1–A8 在 §0。
- 討論結論存檔：三策略信心排序 = 原 S3 > 策略一(補強) > 策略二(權值股，需 paper 實跑贏得資金，暫緩)

**下一步**：等老闆逐項核准 A1–A8、B1–B5 → 動工順序建議：S4（小、快）→ scalper Phase 0
（需老闆先申請永豐模擬 API Key）。策略二暫緩不動工。

**涉及檔案**：`docs/scalper-spec.md`（新增）、`docs/strategy-s4-spec.md`（新增）、本檔

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
`git status` 乾淨。**Commit**：ffa3506，已 push。**部署驗證**：`curl /api/v1/positions` → 200

---

## 📚 歷史紀錄（僅供查閱）

### 壓縮摘要（2026-06-29 ~ 07-05 各 session，2026-07-06 依 F 協議 §4 精簡，完整版見 git 歷史）

- 2026-07-05 — 交接 SOP 制度化：新增 `docs/harness/H-handover-procedure.md`（觸發詞「準備交接檔案」→ 4 步驟自動完成），CLAUDE.md/README 路由同步
- 2026-07-05 — 第一批風控修復：EXIT_ALL 接上執行+推播（過去 200MA 轉空完全靜默）、倉位改帳戶現況+信心加權（過去固定用初始資金）、Aggregator 參數統一走 settings、SELL 推播抓錯部位修正（65dfb55）
- 2026-07-04 — Harness 制度建設：`docs/harness/` A–G+LESSONS+IMPL-MAP 落地，CLAUDE.md 重寫為路由中心；.gitignore 補 `.env*`/`*.db`、settings.json deny 高危 git 指令（8715192）
- 2026-07-04 — 持倉顯示修正：N/A 股價 fallback 5d→1mo→3mo、具體出售建議、損益四欄重構（e0fa40e）
- 2026-06-29~07-03 — 效能穩定：Redis 價格快取+timeout 防掛死（de23a68）、NaN 500 修正（927165b）、OOM 502 修正+訊號快取 30 分（d178cae）

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

**1. ✅ API 認證（已實作 2026-07-06）** — X-API-Key middleware 保護全部 /api/v1/*，
金鑰待老闆 `fly secrets set API_KEY=...` 啟用。

### 高優先：效能

**2. ✅ Redis 快取（已實作 2026-06-29）** — `_fetch_price`、`_fetch_usd_twd`、`_fetch_one` 均加入 Upstash Redis 快取（TTL = 300s）。快取命中時直接從 Redis 回傳，跳過 yfinance 請求。另加 `asyncio.wait_for` 逾時（portfolio 25s、watchlist 30s），使用 `pool.shutdown(wait=False)` 防止伺服器掛死。
- **快取 Key 格式**：`zrh:price:{sym}`、`zrh:rate:usdtwd`、`zrh:wl:{sym}`
- **效果**：第一次載入仍需等 yfinance（一次性），後續 5 分鐘內幾乎秒開

### 中優先：功能完整性

**3. ✅ 非交易日過濾（已實作 2026-07-06）** — `src/data/market_calendar.py`，
四個每日任務週末/假日跳過。

**4. ✅ deploy.yml 測試閘門（已實作 2026-07-06）** — test job + `needs: [test]`。

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
