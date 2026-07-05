# ZeroHour 開發 Harness — 制度總索引

> 建立日期：2026-07-04（Fable 5 一次性制度建設 session）
> 目的：讓後續模型（Sonnet / Opus 4.8 / Haiku）在此框架下穩定自主產出。
> 入口：專案根目錄 `CLAUDE.md` 是唯一路由中心，按需跳轉到本目錄各檔。

## 檔案地圖（規劃結構，若某檔缺失代表 session 中斷，見 G 交接信）

| 檔案 | 內容 | 誰在什麼時候讀 |
|------|------|----------------|
| `A-diagnosis.md` | 漏水診斷書：三大痛點與物理阻斷方案 | 想了解「為什麼規則長這樣」時 |
| （B = 根目錄 `CLAUDE.md`）| 路由中心，每 session 自動載入 | 所有模型，自動 |
| `C-model-dispatch.md` | 模型調度與升降級守則 | 要派 Subagent 或連續失敗時 |
| `D-judgment-rubric.md` | 判斷力外化矩陣：停損/完成/熔斷判準 | 每次任務收尾前；卡關時 |
| `E-delegation-templates.md` | 派工 Prompt 模板 ×4 | 呼叫 Agent tool 前複製套用 |
| `F-knowledge-protocol.md` | 知識迭代協議：誰能改什麼、踩坑格式 | 想修改 harness 檔案前 |
| `G-handover.md` | Fable 5 交接信：三件關鍵事 + 退化預警（凍結）| 新 session 接手大任務前 |
| `H-handover-procedure.md` | 「準備交接檔案」觸發詞的 SOP：更新 PROGRESS/LESSONS/驗證/commit | 老闆說「準備交接檔案」或「開始新對話」時 |
| `LESSONS.md` | 踩坑紀錄（唯一可自由追加的檔案） | 踩坑後寫；開工前掃一眼 |
| `IMPL-MAP.md` | trading-system-impl.md 章節行號地圖 | 需要查規格時，代替整讀 |

## 一句話原則

**規則只有在「弱模型不用思考就能照做」時才有效。** 所有判準必須可肉眼比對，
所有指令必須可直接複製執行，所有驗收必須有貼得出來的輸出。
