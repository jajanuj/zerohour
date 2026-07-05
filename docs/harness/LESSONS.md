# LESSONS — 踩坑紀錄

> 這是 harness 中**唯一允許模型自由追加**的檔案（格式見下，其他規則見 F 協議）。
> 開工前掃一眼「教訓」欄，避免重付學費。超過 150 行觸發精簡（F 協議 §4）。

## 寫入格式（固定五欄，一坑一列）

| 日期 | 症狀 | 根因 | 教訓（一句話，可執行）| 相關 commit |
|------|------|------|----------------------|-------------|

## 紀錄

| 日期 | 症狀 | 根因 | 教訓（一句話，可執行）| 相關 commit |
|------|------|------|----------------------|-------------|
| 2026-06 | CI/CD 部署失敗 | 憑記憶寫依賴套件名，PyPI 上不存在 | 加任何依賴前先 `pip index versions <pkg>` 或查 PyPI 確認名稱與版本，且加依賴前必先問老闆 | — |
| 2026-06 | GET /portfolio 回 500 | yfinance `fast_info.last_price` 回 NaN；`float(NaN or 0)` 仍是 NaN（NaN 是 truthy）；`json.dumps(NaN)` 直接炸 | 任何 yfinance 數值在使用前必須過 `math.isnan()` 檢查，`or 0` 擋不住 NaN | 927165b |
| 2026-06 | watchlist 回 500 | `history()` 的 Volume 欄沒 dropna，`volumes[-1]` 是 NaN，除法後 NaN 進 JSON | DataFrame 取值前先 dropna 該欄，或取值後 isnan 過濾 | 927165b |
| 2026-06 | 前端顯示「載入失敗：」冒號後空白 | Fly.io HTTP/2 對錯誤回應的 `statusText` 一律是空字串 | 前端錯誤訊息用 `HTTP ${r.status}`，永遠不要用 `r.statusText` | fd9dc06 |
| 2026-06 | 整站 HTTP 502 | 12+8=20 條 yfinance 執行緒在 256MB Fly.io 機器上 OOM，進程被殺 | web 進程只有 256MB：ThreadPoolExecutor 總並發 ≤ 6，新增任何並發前先算記憶體 | d178cae |
| 2026-06 | 頁面卡「載入中」5 分鐘 | yfinance 無 timeout 保護，單一慢請求拖死整個 endpoint | 所有外部 IO 必包 `asyncio.wait_for`，timeout 後 `pool.shutdown(wait=False)` 否則 event loop 卡死 | de23a68 |
| 2026-06 | 後端逾時回空 `{}`，前端所有格子永遠「計算中...」 | 前端只迭代回應內容，回應為空時迴圈不執行，loading 文字沒人清 | 前端渲染 loading 佔位後，回呼裡必須有「清除所有未更新佔位」的收尾步驟（成功與 catch 都要）| d178cae |
| 2026-07 | 債券 ETF 股價顯示 N/A | 00679B 等低流動性 ETF 好幾天沒成交，`history("3d")` 抓不到資料 | 抓價 fallback 要逐步放寬回看期 5d→1mo→3mo | e0fa40e |
| 2026-07 | scalper 回測測試失敗（少了預期的成交記錄） | 合成測試事件的時間戳用各自獨立的 `base + timedelta(...)` 拼湊，其中一筆算出來反而早於前一筆，事件順序顛倒 | 建構 replay/backtest 用的合成事件序列，一律用單一遞增游標變數疊加 timedelta，禁止從同一個 base 各自獨立算相對偏移 | 59786a8 |
| 2026-07 | `or 0.0` 擋不住 NaN 的坑 2026-06 已修過，但只修了 routes.py；tasks.py 三個任務（含黑天鵝偵測）同模式殘留一個月 | 修坑時只改了報錯的那一處，沒有全域搜同一寫法 | 修任何 bug 時先 `grep` 全 codebase 找同一模式（本例 `or 0.0`），一次修完所有出現點，並在 LESSONS 註明搜過 | b7e3d6a |
