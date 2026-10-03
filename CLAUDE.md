# CLAUDE.md — ZeroHour 專案路由中心

> 本檔只放核心規則與檔案路由。細則在 `docs/harness/`，**按需跳轉，不要一次全讀**。
> ZeroHour 是**真金交易系統**（FastAPI + Supabase + Upstash Redis + Celery）。
> **2026-10-03 起已下線**：Fly.io app 已刪除（持續計費），目前無生產環境、push 不會部署。
> 你寫的每一行代碼都可能影響真實金錢，不確定就停下來問。

## 溝通規則

- 每次回覆開頭稱呼「老闆」
- 回覆結構：1. 本次做了什麼 2. 遇到什麼問題（若有）3. 下一步
- 規格不清楚 → 先問，**不得自行假設後修改**

## Session 啟動（總成本 < 5k tokens，禁止超讀）

1. 讀 `docs/PROGRESS.md` **前 40 行**（`Read` 帶 `limit=40`；最新狀態在頂部）
2. `git status` 確認 repo 狀態
3. 掃一眼 `docs/harness/LESSONS.md` 的教訓欄
4. 向老闆確認本次任務後才動工

## 規格書查閱鐵則（啟動與開發全程適用）

查 `docs/trading-system-impl.md` 一律先讀 `docs/harness/IMPL-MAP.md`
取得章節行號，用 offset/limit 讀單章。**該檔禁止整讀**（3,678 行 ≈ 40k tokens）。

## 開發循環（每個功能走完一輪）

1. **單一功能**：一次只做一件事，不動無關代碼
2. **實作前**：涉及規格 → IMPL-MAP 查對應章節；涉及已知坑 → LESSONS.md
3. **Push 前強制驗證**（缺一不可，貼輸出證明）：
   ```
   python -m py_compile <每一個改過的 .py>
   python -m pytest tests/unit -x -q
   ```
4. **完成判定**：對照 `docs/harness/D-judgment-rubric.md` §2 的量化清單
5. **Commit**：`git add <明確檔名>`（**禁止 `git add -A` 和 `git add .`**）→ commit → push
6. **更新 `docs/PROGRESS.md`**：新條目寫在「最新狀態」區頂部，格式見該檔開頭說明

## Commit 格式

`feat:` 新功能 `fix:` 修錯 `docs:` 文件 `test:` 測試 `refactor:` 重構 `chore:` 雜項

## 紅線（違反任何一條 = 立即停手回報老闆）

| 紅線 | 原因 |
|------|------|
| `git add -A` / `git add .` / `git add -f` | 曾有活密鑰檔在 untracked 邊緣（A 診斷書痛點二）|
| 未跑 pytest 就 push | master 是唯一可信版本；重新上線時 push 將再度等於部署（A 診斷書痛點三）|
| 動 `src/risk/`、`src/signals/` 的公式或參數而未先問老闆 | 直接影響真實金錢 |
| 資料庫 schema 異動、API 介面變更、新增依賴 | 需老闆明示同意 |
| 動 `.env*` 檔內容或任何部署平台的 secrets | 生產憑證，只有老闆能動 |
| 重新部署到任何雲端平台（含恢復 `deploy.yml` 的 push 觸發）| 會產生費用，需老闆明示同意 |
| 同一問題連續失敗 2 次還繼續原地重試 | 走 D 檔 §1 換路徑判準或 C 檔升級路徑（此為主對話門檻；Subagent 的升降級門檻更嚴，見 C 檔 §4）|

## 檔案路由（需要時才讀）

| 情境 | 讀這個 |
|------|--------|
| 查系統規格 | `docs/harness/IMPL-MAP.md` → 定位後讀單章 |
| 要派 Subagent / 連續失敗要升降級 | `docs/harness/C-model-dispatch.md` |
| 判斷「該停嗎/完成了嗎/該問老闆嗎」 | `docs/harness/D-judgment-rubric.md` |
| 派工 prompt 怎麼寫 | `docs/harness/E-delegation-templates.md` |
| 想修改 harness 規則檔 | `docs/harness/F-knowledge-protocol.md`（先讀再動）|
| 接手大任務前 | `docs/harness/G-handover.md` |
| 老闆說「準備交接檔案」/「開始新對話」| `docs/harness/H-handover-procedure.md`（照 SOP 自動完成，不用逐項交代）|
| 踩坑了 | 追加到 `docs/harness/LESSONS.md`（唯一可自由追加的檔）|
| 想知道規則為什麼長這樣 | `docs/harness/A-diagnosis.md`（唯讀）|
| 動 `scalper/`（策略三股期刷單）| `docs/scalper-spec.md`（獨立模組，只跑老闆本地機器，不進 Fly.io）|
| 動 S4 台股趨勢確認因子（策略一補強）| `docs/strategy-s4-spec.md`（只調整 S3 的 BUY 倉位係數，不改進出邏輯）|
| 做報表可觀測性優化（條件明細/品質註記/下一步等）| `docs/report-optimization-plan.md`（純觀測層，禁改訊號公式與決策）|

## 環境速查

- 生產：**無**（2026-10-03 起下線；原 Fly.io 東京 web 256MB×2 / worker 512MB，app 已刪除）
- 部署：`deploy.yml` 已改為僅手動觸發（`workflow_dispatch`），且 Fly.io app 不存在，**不要手動觸發**；push 只會跑 `test.yml`。重新上線需另選平台並經老闆同意
- 本地跑 API：`uvicorn src.main:app --port 8080`
- E2E：`python -m pytest tests/e2e -x -q`（Playwright dashboard 測試在 `tests/e2e/test_dashboard_playwright.py`）
- DB：生產 Supabase PostgreSQL；本地 SQLite `zerohour_dev.db`（已 gitignore）
