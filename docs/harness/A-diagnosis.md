# A. Harness 漏水診斷書

> 診斷者：Fable 5（2026-07-04）。本文件是唯讀的歷史紀錄，後續模型**不得修改**（見 F 協議）。
> 各痛點的阻斷方案已在同 session 內實施，實施狀態標記於各節末尾。

---

## 痛點一：Session 啟動即整讀 3,678 行規格書（最浪費 Token）

### 症狀
舊版 CLAUDE.md 啟動流程第 4 步要求「讀取 docs/trading-system-impl.md，選出下一個待處理項目」。
該檔 3,678 行 ≈ 40k tokens。每個 session 開工前先燒掉約 1/4 context window，
而其中 95% 內容（已完成的 Phase A–G 規格）與當次任務無關。

### 連鎖傷害
- Context 提早耗盡 → 對話中途 compact → 模型忘記先前修過什麼 → 重複勞動或互相打架。
- 弱模型讀完長文後注意力稀釋，反而更容易忽略 PROGRESS.md 裡的真實近況。

### 物理阻斷
1. `CLAUDE.md` 重寫為路由中心：啟動只讀 `PROGRESS.md` 前 40 行 + `git status`。
2. 新增 `docs/harness/IMPL-MAP.md`：規格書的章節→行號地圖。
   需要查規格時用 `Read` 帶 `offset/limit` 只讀該章節，**禁止無 offset 整讀該檔**。
3. PROGRESS.md 改為「最新狀態置頂」結構（規則寫在 CLAUDE.md），
   舊 session 記錄移到檔案下方的歷史區，讀前 40 行即得全貌。

**狀態：✅ 已實施（CLAUDE.md 重寫 + IMPL-MAP.md 建立）**

---

## 痛點二：活密鑰裸奔在 git 暫存邊緣（最危險）

### 症狀
`git status` 顯示兩個 untracked 檔案：
- `.env.tmp` — 內含 **DATABASE_URL、SUPABASE_ANON_KEY、REDIS_URL 等生產環境活密鑰**
- `zerohour_dev.db` — 本地資料庫

`.gitignore` 只擋 `.env` / `.env.local` / `.env.*.local`，**擋不住 `.env.tmp` 和 `*.db`**。
任何一次 `git add -A` 或 `git add .` + commit + push（push 已在 allow 清單內免確認），
密鑰就永久進入 GitHub 歷史。這是真金交易系統的資料庫與 Redis 憑證。

### 物理阻斷
1. `.gitignore` 補上 `.env.*`、`.env*.tmp`（保留 `!.env.example`）、`*.db`、`*.db-journal`、`*.sqlite3`、`*.bak`。
2. `.claude/settings.json`（專案級，入 repo）deny 清單擋掉高危 git 操作
   （force push、reset --hard 等，完整清單見該檔）。
3. 行為規則（CLAUDE.md 紅線）：**永遠用 `git add <明確檔名>`，禁止 `-A` 與 `.`**。
   規則可能被忽略，所以 1、2 才是主防線 — 就算模型犯規，gitignore 也會把密鑰擋下。

**狀態：✅ 已實施（.gitignore 已補、settings.json 已建）**
**殘留風險：若未來有人手動 `git add -f .env.tmp` 仍會洩漏 — 沒有工具能擋 -f，只能靠紅線規則。**

---

## 痛點三：無測試閘門的生產直通車（最容易釀災）

### 症狀
`deploy.yml` 觸發條件是 push 到 **main 或 master 任一分支**，**沒有 `needs: [test]`，甚至沒有 test job**。
舊 CLAUDE.md 工作流程第 6 步指示「自查通過後 commit + push origin master」——
「自查」對弱模型而言常常退化成「我看了一眼覺得沒問題」。
結果：語法能過但邏輯錯誤的代碼 → 直接部署 → 交易系統帶病運行 →
最壞情況是**風控參數算錯導致真實金錢損失**，而不只是網頁壞掉。

本 session 之前的歷史已經證明這條路徑會出事：OOM 502、NaN 500、
watchlist 永遠「計算中」——全部都是 push 後才在生產環境發現的。

### 物理阻斷
1. Push 前強制驗證（CLAUDE.md 硬規則，附可複製指令）：
   ```
   python -m py_compile <改過的每一個 .py 檔>
   python -m pytest tests/unit -x -q
   ```
   兩者任一失敗 → 禁止 push，回報老闆。
2. Push 後強制煙霧測試（等部署 ~3 分鐘後執行）：
   ```
   curl -s -o /dev/null -w "%{http_code}" https://zerohour-trading-engine.fly.dev/api/v1/positions
   ```
   非 200 → 立即回報並停止宣告完成。
3. **待老闆同意的 CI patch**（deploy.yml 屬破壞性變更，未經同意不動）：
   ```yaml
   # deploy.yml 在 jobs: 下新增 test job，deploy job 加 needs
   jobs:
     test:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with: { python-version: "3.11" }
         - run: pip install -e ".[dev]" || pip install -r requirements.txt
         - run: python -m pytest tests/unit -x -q
     deploy:
       needs: [test]        # ← 關鍵新增
       runs-on: ubuntu-latest
       # ...其餘不變
   ```

**狀態：⚠️ 1、2 已寫入 CLAUDE.md；3 待老闆說「同意 CI patch」後由任何模型套用。**

---

## 誠實條款：這套 Harness 的能力極限

| 極限 | 說明 | 弱模型遇到時的標準動作 |
|------|------|------------------------|
| 品味與美感決策 | UI 配色、文案語氣、圖表美觀度——拆解與驗證救不了品味 | 做出 2–3 個方案截圖，**讓老闆挑**，不要自己選了就 push |
| 交易策略正確性 | 測試只能驗證「代碼照規格跑」，不能驗證「規格會賺錢」 | 涉及策略邏輯/參數變更一律先問老闆，引用 IMPL-MAP 對應章節 |
| 未知的未知 | deny 清單只能擋已知危險指令；新型危險操作擋不住 | 對任何「感覺威力很大」的指令（批量刪除、改雲端資源、動錢）套用 D 檔熔斷判準 |
| 規則腐化 | 規則越多，弱模型越可能只讀一半 | F 協議設了長度上限與精簡機制；CLAUDE.md 永遠 ≤ 120 行 |
| 本診斷的時效性 | 行號、檔案路徑會隨開發漂移 | IMPL-MAP 的行號允許模型自行更新（見 F）；本檔其餘內容凍結 |
