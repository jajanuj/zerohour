# S4-SPEC — 策略一：台股趨勢確認因子（補強 S3）實作規格書

> **讀者**：負責實作的模型（Sonnet/Haiku）。派工時引用本檔章節號。
> **狀態**：規劃完成，**待核准項見 §0，未核准前禁止動工**。
> **定位（老闆已拍板方案 A）**：S4 不是獨立策略，是 S3 的倉位調整係數。
> **S3 的進出時點、決策矩陣、停損停利一律不變**——S4 只在 S3 決定 BUY 時縮放買入倉位。

---

## §0. 待核准清單

| # | 項目 | 紅線類別 | 狀態 |
|---|------|----------|------|
| B1 | 新增 `src/signals/taiex_confirm.py`；修改 `src/tasks.py` 的 `generate_signal` 接上係數 | 動 src/signals/ | ⬜ 待核准 |
| B2 | 係數表 v0（見 §3）與 fail-open 行為（資料抓不到 → ×1.0 + Discord 警告）| 策略參數 | ⬜ 待核准 |
| B3 | 新外部資料源：TWSE OpenAPI（純 HTTP JSON，用現有 httpx，**不加任何套件**）| 外部依賴 | ⬜ 待核准 |
| B4 | S4 訊號入庫方式：復用現有 `save_trend_signal(symbol="TAIEX")`，**無 schema 變更** | 確認即可 | ⬜ 待核准 |
| B5 | CLAUDE.md 路由表加一行指向本檔 | 規則檔 | ⬜ 待核准 |

## §1. 要補的洞

現在 S1 趨勢判斷只看 QQQ（美股）。台美背離時（美股多頭、台股自己走空），S3 仍會全額買 0050。
S4 用台股本土數據做第二意見：**台股自身趨勢不健康時，買一樣的訊號、但買少一點。**

## §2. 訊號定義

兩個子指標，皆為每日一次、在 `generate_signal`（04:05）內計算：

1. **TAIEX 趨勢**：台灣加權指數（yfinance `^TWII`）收盤 vs 其 200 日均線。
   計算直接復用現有 `MA200Filter`（src/signals/ma200_filter.py），不另寫公式。
2. **法人動向**：三大法人近 5 個交易日**合計買賣超金額**正負。
   資料源：TWSE OpenAPI 三大法人買賣金額統計（BFI82U 系列端點）。
   **端點路徑與欄位名以實測為準**：實作第一步先 `curl` 驗證回傳 JSON 結構，把實測結果記入本節（允許更新本檔此節）。抓近 5 個交易日 = 逐日呼叫，包 timeout，任何一天抓失敗 → 該子指標視為「無資料」。

## §3. 係數表 v0（B2 待核准）

| TAIEX vs 200MA | 法人 5 日淨額 | 係數（乘在 S3 的 suggested_position_pct 上）|
|----------------|---------------|----------|
| 站上 | 買超 | ×1.00（雙確認，全額）|
| 站上 | 賣超 | ×0.75 |
| 跌破 | 買超 | ×0.50（台美背離，減半）|
| 跌破 | 賣超 | ×0.50 |
| 任一子指標無資料 | — | ×1.00 + Discord 警告（fail-open）|

**fail-open 理由**：S4 是補強不是守門員；TWSE API 掛掉不該讓主策略停擺或縮水。老闆若偏好保守可改 fail-safe ×0.75，核准 B2 時一併裁決。

**邊界**：係數只作用於 `FinalAction.BUY` 的新倉買入量。SELL / EXIT_ALL / HOLD 與停損停利完全不受 S4 影響。

## §4. 模組設計

新檔 `src/signals/taiex_confirm.py`：

```python
@dataclass
class TaiexConfirmSignal:
    taiex_state: str          # "BULL" / "BEAR" / "UNDEFINED"（沿用 TrendState 值）
    inst_net_5d: float | None # 三大法人5日淨額（億元）；None = 無資料
    modifier: float           # §3 係數
    reason: str               # 人話說明，進 Discord 與 log

class TaiexConfirmFilter:
    def calculate(self) -> TaiexConfirmSignal:
        # 1) TWMarketFetcher 抓 ^TWII 2y → DataNormalizer → MA200Filter.calculate()
        # 2) httpx 抓 TWSE 法人數據（5 次呼叫，各 10s timeout，失敗→None）
        # 3) 查 §3 表 → 回傳
```

`src/tasks.py::generate_signal` 接點（唯一修改處，B1 核准後）：

```python
combined = agg.aggregate(trend, time_diff)      # 現有行為，一字不動
s4 = TaiexConfirmFilter().calculate()           # 新增
effective_position_pct = combined.suggested_position_pct * s4.modifier  # 新增
# 之後 PositionSizer.calculate(...) 的 suggested_pct 改用 effective_position_pct
# S4 訊號入庫：save_trend_signal(symbol="TAIEX", state=s4.taiex_state, ...)
# Discord signal_alert 的 reason 追加 s4.reason
```

**明確禁止**：不改 `aggregator.py`、不改 `ma200_filter.py`、不改 `time_diff.py`、不改 `src/risk/` 任何檔。

## §5. 失效保護（繼承 LESSONS）

1. `^TWII` 抓價全過 NaN 檢查；資料 < 200 根 → TrendState.UNDEFINED → 無資料路徑
2. TWSE 呼叫逐次包 `timeout=10`，總預算 ≤ 30 秒（超過 → 無資料路徑），不得拖慢 04:05 任務
3. 係數輸出強制夾在 [0.5, 1.0]，防止未來改表時手滑寫出放大槓桿的值

## §6. 測試要求

`tests/unit/test_taiex_confirm.py` 至少覆蓋：§3 表格全部 5 列、TWSE 部分天數失敗、^TWII 資料不足、係數夾限。TWSE HTTP 一律 mock，不打真網路。
push 前照 CLAUDE.md 驗證流程。

## §7. 上線步驟（B 群全核准後）

1. 實作 + 單元測試（一次派工，引用本檔 §2–§6）
2. 隔離驗收（E 檔模板 4，驗收官確認「S3 原行為不變」：HOLD/SELL/EXIT_ALL 路徑 diff 為零）
3. push → 煙霧測試 → 觀察 3 個交易日的 Discord 訊號中 S4 reason 是否合理
4. PROGRESS.md 記錄
