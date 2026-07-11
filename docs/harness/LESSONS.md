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
| 2026-07 | Test & Lint 連紅 4 次無人發現（aiosqlite 未宣告在依賴，CI 裝不到），煙霧測試卻照樣 200 | deploy 無測試閘門時壞測試照樣部署；驗收習慣只看煙霧測試不看 CI 結論 | push 後驗收必跑 `gh run list` 確認兩個 workflow conclusion 皆 success，煙霧測試 200 不能代替 CI 綠燈 | 42910bb |
| 2026-07-07 | 生產 Discord 報 run_daily_review 錯誤 `(EMAXCONNSESSION) max clients reached in session mode - pool_size 15` | `sync_run()` 每次呼叫都 `asyncio.run()` 建新 loop 又關閉，且 `dispose(close=False)`（6/28 為修另一個 bug 引入）不真的關底層連線，Celery worker 長駐生命週期內連線逐日堆積，9 天後打穿 Supabase session pooler 上限 | 橋接 sync/async 的一次性 event loop 函式若在**長駐 process**（Celery worker、非 request-per-process）內被重複呼叫，必須復用同一顆常駐 loop，不可每次建了又關——否則連線資源無法被池化回收，會隨時間累積直到打穿資料庫連線上限；且該類修復不能只跑本機 pytest 驗證，要留意本機 `.env` 可能指向生產 DB，測試應用獨立臨時 engine 避免誤連 | 66e3e02 |
| 2026-07-11 | Discord 週覆盤「AI 週報」欄直接顯示完整 Gemini API 金鑰（Gemini 503 時例外訊息含 `?key=<真實金鑰>` 的請求 URL，被原樣回傳並推播） | 5 個 Gemini 呼叫點都把金鑰放在 URL query string（`?key=...`），`except Exception as e: return f"...{e}"` 讓例外字串（含 URL）直接變成使用者可見文字 | 呼叫任何帶金鑰的外部 API，金鑰一律走 header（如 `x-goog-api-key`）不要放 query string；例外訊息在寫進 log／DB／回傳給呼叫方前，一律過一層「移除已知密鑰」的 redact 函式，不能假設例外字串不含敏感資訊；本次順便發現：測試若讓請求真的打到會查 DB 的 handler，必須 mock 掉 DB 呼叫，否則本機 `.env` 指向生產庫時測試會真連生產、且連線未關閉——PYTHONTRACEMALLOC=25 可用來追出 ResourceWarning 的實際配置點 | 3ed39fb、86937c0 |
| 2026-07-11 | Upstash 通知 Redis 免費額度 500,000 命令/月耗盡（老闆評估過「不該這麼多」）| Celery 用 Kombu redis transport，`brpop_timeout` 預設 1 秒，worker 閒置時每秒發一次 BRPOP：86,400 次/天 ≈ 259 萬次/月，遠超額度且與系統每天僅數次排程任務的實際流量不成比例（此系統每天真正的任務執行量微不足道，幾乎全部命令都是空轉輪詢） | Celery + Redis broker（尤其 Upstash 這類按命令計費/計額的 serverless Redis）務必設定 `broker_transport_options={'polling_interval': N}`（BRPOP 阻塞式，訊息一到就立即喚醒，此設定不影響任務即時性，只降低閒置時重新發問的頻率）；評估「這個排程系統應該用多少額度」時要拆成「輪詢空轉成本」與「實際任務執行成本」兩塊分別估算，不能只算後者 | c1c5c47 |
| 2026-07-11 | 老闆問「還有其他會超額度的嗎」複查時，發現 07-07 修 Gemini 金鑰外洩「全部 5 個呼叫點」的宣稱是錯的，`supply_chain_agent.py` 漏了第 6 個同樣漏洞 | 上次修復前雖然有查過，但查詢範圍/耐心不夠廣，沒有對整個 codebase 跑最直接的字串搜尋（`grep generativelanguage.googleapis.com`），憑記憶列出的呼叫點清單本身就不完整 | 宣稱「已修復全部 N 個呼叫點」前，必須用最不會漏的搜尋方式（服務網域名稱、SDK 特徵字串等）對整個 codebase 掃一次，把掃到的數量和宣稱的數量對上，而不是憑先前列的清單去逐一修；同一類 bug 的修復收尾前，`grep` 一次當作驗收步驟，不是可省略的動作 | 0a3c829 |
| 2026-07-11 | Gemini 用量儀表板寫死「RPD 上限 20」，實際免費方案落在 250~1500（低估 12 倍以上），差點誤導老闆以為額度緊繃 | 寫這個數字時沒有查證來源，憑印象/隨手估了一個保守到不合理的數字放進程式碼當常數 | 任何寫進程式碼、會被使用者看到並據以判斷風險的「第三方服務額度/限制」數字，下筆前必須查證來源（官方文件或至少多方交叉確認），不能憑印象填一個數字；查不到官方保證值時，要在註解寫明「這是保守估計非官方保證」而非讓數字看起來像權威事實 | 0a3c829 |
