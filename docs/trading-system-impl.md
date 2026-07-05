# ZeroHour — 台美時間差量化交易系統 · 實作文件

> **專案名稱：** ZeroHour  
> **版本：** v1.4.0  
> **狀態：** 草稿  
> **最後更新：** 2026-06-21  
> **命名緣由：** 凌晨 04:00，美股收盤的那一刻，訊號從這裡生成，一切從這裡開始。

---

## 目錄

### 🟢 第一階段：量化執行系統（優先建置）
1. [文件簡介](#1-文件簡介)
2. [系統架構與技術棧](#2-系統架構與技術棧)
3. [開發環境設置](#3-開發環境設置)
4. [核心模組與實作細節](#4-核心模組與實作細節)
5. [資料庫設計](#5-資料庫設計)
6. [API 規格說明](#6-api-規格說明)
7. [回測框架](#7-回測框架)
8. [測試策略](#8-測試策略)
9. [風險管理框架](#9-風險管理框架)
10. [監控與警報](#10-監控與警報)
11. [部署與 CI/CD](#11-部署與-cicd)
12. [覆盤與策略優化機制](#12-覆盤與策略優化機制)

### 🔵 第二階段：Multi-Agent 選股系統（第一階段穩定後建置）
13. [Multi-Agent 選股系統](#13-multi-agent-選股系統)

### 📋 附錄
14. [文件異動紀錄](#14-文件異動紀錄)

---

## 1. 文件簡介

### 1.1 專案背景

**ZeroHour** 是一套利用台美市場 13 小時時差的自動化量化交易系統。系統名稱來自凌晨 04:00——美股收盤的那一刻，訊號生成、決策完成，等待台股 9 點開盤執行。

本系統整合以下三項策略，建立一套可自動執行的量化交易系統：

| 策略編號 | 策略名稱 | 邏輯摘要 |
|----------|----------|----------|
| S1 | **200MA 趨勢過濾系統** | 每日收盤判斷，收盤 > 200MA 持有；跌破緩衝帶（2%）出場，站上緩衝帶（2%）再進場 |
| S2 | **台美時間差訊號** | 美股收盤漲跌 > 1.5% 時，台灣市場開盤方向性操作 |
| S3 | **組合策略（S1 × S2）** | S1 判斷大環境，S2 判斷短線訊號，兩者同向才執行 |

### 1.2 核心目標

- **自動化執行**：消除人為情緒干擾，嚴格依據規則進出場
- **風險優先**：停損優先於獲利，保護本金為第一要務
- **可驗證性**：每個訊號、每筆交易皆可追蹤與回測
- **可擴展性**：新策略可作為模組插入，不影響既有系統

### 1.3 交易標的範圍

```
美股 ETF：QQQ（NASDAQ 100）、TQQQ（3倍 QQQ）
台股 ETF：0050（台灣50）
台灣期貨：小台指（MTX）
參考指標：費城半導體指數（SOX）、NASDAQ、S&P 500
```

### 1.4 名詞定義

| 術語 | 定義 |
|------|------|
| 趨勢過濾器 | 200 日移動平均線，判斷當前是否為多頭環境 |
| 時間差訊號 | 美股收盤方向性變動（> ±1.5%）對台股的領先指標 |
| 停損線 | 進場價 × 0.88（指數）或 0.92（個股） |
| 移動停利 | 從持倉最高點回落 15% 時觸發出場 |
| 空倉期 | 系統判斷無明確訊號，不持有任何部位 |

---

## 2. 系統架構與技術棧

### 2.1 整體架構圖

```
┌─────────────────────────────────────────────────────────────┐
│                        外部資料來源                          │
│  Yahoo Finance │ Alpha Vantage │ TWSE API │ 券商即時報價     │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│                    資料收集層 (Data Layer)                    │
│         DataFetcher  ──  DataNormalizer  ──  DataStore      │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    訊號生成層 (Signal Layer)                  │
│   MA200Filter  ──  TimeDiffSignal  ──  SignalAggregator     │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                   風險管理層 (Risk Layer)                     │
│    PositionSizer  ──  StopLossManager  ──  ExposureCheck    │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                   執行層 (Execution Layer)                    │
│        OrderManager  ──  BrokerAdapter  ──  FillTracker     │
└────────────────────────────┬────────────────────────────────┘
                             │
                    ┌────────┴────────┐
                    ▼                 ▼
         ┌──────────────┐   ┌──────────────────┐
         │  PostgreSQL  │   │  Alert System    │
         │  (主資料庫)   │   │  Telegram / Line │
         └──────────────┘   └──────────────────┘
                    │
                    ▼
         ┌──────────────────┐
         │   FastAPI        │
         │   Dashboard API  │
         └──────────────────┘
```

### 2.2 技術棧

#### 核心語言與資料處理
| 層級 | 技術選擇 | 理由 |
|------|----------|------|
| **語言** | Python 3.11+ | 金融資料生態最完整 |
| **資料處理** | pandas 2.x、numpy | 時間序列標準工具 |
| **美股資料** | yfinance（主）、Alpha Vantage（備） | 免費可靠，支援歷史數據 |
| **台股資料** | TWSE 開放 API、fugle-marketdata | 官方來源 |
| **排程** | Celery Beat | cron 式定時任務 |
| **ORM** | SQLAlchemy 2.0 + Alembic | 型別安全的資料庫操作 |
| **測試** | pytest + pytest-asyncio | 完整測試覆蓋 |
| **回測** | vectorbt（主）、backtrader（備） | 向量化回測，速度快 |
| **警報** | Telegram Bot API | 即時交易通知 |

#### 雲端服務（免費方案起步）
| 用途 | 服務 | 方案 | 月費 |
|------|------|------|------|
| **Trading Engine** | Fly.io（東京節點）| free tier（3 VM） | $0 |
| **資料庫** | Supabase（managed PostgreSQL）| free tier（500MB）| $0 |
| **訊息佇列** | Upstash Redis（serverless）| free tier（10k cmd/日）| $0 |
| **Dashboard** | Vercel（Next.js 14）| Hobby | $0 |
| **Keep-Alive / CI/CD** | GitHub Actions | free tier（2000分/月）| $0 |
| **合計** | | | **$0/月** |

> 💡 **升級路徑**：策略驗證完成、產生穩定收入後，優先升級 Supabase → Pro（$25/月）消除閒置風險，再視需求評估 Fly.io 付費方案或遷移至 VPS。

### 2.3 排程時間表

```
台灣時間（UTC+8）

04:00 ── 美股收盤資料抓取
04:05 ── 執行 S2 時間差訊號計算
04:10 ── 若訊號觸發，生成預訂單（Pre-order）
04:30 ── 風險審查（Position Size、Exposure Check）
08:55 ── 最終確認，送出集合競價委託
09:00 ── 台股開盤，等待成交回報
13:35 ── 台股收盤，更新部位與損益
23:00 ── 每日資料備份
```

---

## 3. 開發環境設置

### 3.1 系統需求

```
OS：Ubuntu 22.04 LTS / macOS 13+（開發）
Python：3.11.x
Docker：24.x（本地測試用）
Git：2.40+
RAM：最低 4GB（建議 8GB）
flyctl：latest（Fly.io CLI，部署用）
```

安裝 Fly.io CLI：
```bash
# macOS
brew install flyctl

# Linux
curl -L https://fly.io/install.sh | sh

# 登入
fly auth login
```

### 3.2 專案目錄結構

```
trading-system/
├── src/
│   ├── data/
│   │   ├── __init__.py
│   │   ├── fetcher.py          # 資料抓取模組
│   │   ├── normalizer.py       # 資料標準化
│   │   └── store.py            # 資料存取介面
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── ma200_filter.py     # 200MA 趨勢過濾器
│   │   ├── time_diff.py        # 台美時間差訊號
│   │   └── aggregator.py       # 訊號整合器
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── position_sizer.py   # 倉位計算
│   │   ├── stop_loss.py        # 停損管理
│   │   └── exposure.py         # 曝險控制
│   ├── execution/
│   │   ├── __init__.py
│   │   ├── order_manager.py    # 訂單管理
│   │   ├── brokers/
│   │   │   ├── base.py         # Broker 抽象介面
│   │   │   ├── ibkr.py         # Interactive Brokers
│   │   │   ├── yuanta.py       # 元大期貨
│   │   │   └── paper.py        # 模擬帳戶
│   │   └── fill_tracker.py     # 成交追蹤
│   ├── backtest/
│   │   ├── __init__.py
│   │   ├── engine.py           # 回測引擎
│   │   └── metrics.py          # 績效指標計算
│   ├── alerts/
│   │   ├── __init__.py
│   │   └── telegram.py         # Telegram 警報
│   ├── database/
│   │   ├── __init__.py
│   │   ├── models.py           # SQLAlchemy 模型
│   │   └── migrations/         # Alembic 遷移檔
│   └── config.py               # 全域設定
├── dashboard/                  # Next.js 14 Dashboard（部署至 Vercel）
│   ├── app/
│   │   ├── page.tsx            # 總覽頁
│   │   ├── positions/
│   │   ├── signals/
│   │   └── performance/
│   ├── lib/
│   │   └── supabase.ts         # Supabase client
│   └── package.json
├── tests/
│   ├── unit/
│   ├── integration/
│   └── backtest/
├── scripts/
│   ├── setup_db.py
│   └── run_backtest.py
├── docker/
│   └── Dockerfile              # Trading Engine 映像檔
├── fly.toml                    # Fly.io 部署設定
├── .github/
│   └── workflows/
│       ├── test.yml            # CI：測試與 Lint
│       ├── deploy.yml          # CD：推送 main 自動部署至 Fly.io
│       └── supabase-keepalive.yml  # 每 3 天 ping Supabase 防止閒置暫停
├── .env.example
├── pyproject.toml
└── README.md
```

### 3.3 快速啟動

```bash
# 1. Clone 專案
git clone https://github.com/your-org/trading-system.git
cd trading-system

# 2. 建立虛擬環境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. 安裝依賴
pip install -e ".[dev]"

# 4. 複製環境設定
cp .env.example .env
# 編輯 .env 填入 Supabase URL、Upstash Redis URL、Telegram Token 等

# 5. 執行資料庫遷移（連到 Supabase）
alembic upgrade head

# 6. 本地開發模式（只啟動 Trading Engine，不需要本地 DB/Redis）
TRADING_MODE=paper python -m src.main

# 7. 部署至 Fly.io
fly launch          # 首次：自動讀取 fly.toml，建立 App
fly secrets set DATABASE_URL="你的 Supabase URL"
fly secrets set REDIS_URL="你的 Upstash Redis URL"
fly secrets set TELEGRAM_BOT_TOKEN="你的 Token"
fly deploy          # 後續更新
```

### 3.4 環境變數（.env.example）

```env
# ── Supabase（資料庫）──────────────────────────────────────
# 從 Supabase Dashboard → Settings → Database → Connection string
DATABASE_URL=postgresql+asyncpg://postgres:[YOUR-PASSWORD]@db.[YOUR-PROJECT-REF].supabase.co:5432/postgres
SUPABASE_URL=https://[YOUR-PROJECT-REF].supabase.co
SUPABASE_ANON_KEY=your_anon_key_here

# ── Upstash Redis（Celery Broker）──────────────────────────
# 從 Upstash Console → Redis → REST API
REDIS_URL=rediss://default:[YOUR-PASSWORD]@[YOUR-ENDPOINT].upstash.io:6380

# ── 美股資料 ────────────────────────────────────────────────
ALPHA_VANTAGE_API_KEY=your_key_here   # 備用，yfinance 預設免費

# ── 台股資料 ────────────────────────────────────────────────
FUGLE_API_KEY=your_key_here

# ── 券商 API（至少設定一個）──────────────────────────────────
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=1

YUANTA_API_KEY=your_key_here
YUANTA_SECRET=your_secret_here

# ── 警報 ─────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# ── 系統設定 ─────────────────────────────────────────────────
TRADING_MODE=paper                    # paper（模擬）| live（真實）
MAX_POSITION_PCT=0.30
MAX_TOTAL_EXPOSURE_PCT=0.80
US_SIGNAL_THRESHOLD=1.5
MA_PERIOD=200
```

> ⚠️ `.env` 永遠不要 commit 到 Git。Fly.io 上使用 `fly secrets set` 管理所有機密，本地開發才用 `.env` 檔。

---

## 4. 核心模組與實作細節

### 4.1 策略 S1：200MA 趨勢過濾器

**邏輯（2026-07-05 起，第二批風控修復定案）：** 每日收盤判斷。收盤 > 200MA →
多頭環境，允許做多；跌破 200MA×(1-出場緩衝) → 出場持現金；重新進場需站上
200MA×(1+進場緩衝)。緩衝帶預設各 2%（`MA200_EXIT_BUFFER_PCT` /
`MA200_ENTER_BUFFER_PCT`），用於避免價格貼線時天天翻多翻空（Whipsaw）。
帶內維持前一日狀態，前一日狀態讀自 `trend_signals` 表最新一筆記錄。
此前規格書寫的是「月底收盤判斷」，但生產環境從未真的接上月底邏輯
（`check_monthly_trend` 任務只寫入 DB、不參與交易決策），實際跑的一直是
每日判斷；本次是把「每日」正式定案並補上緩衝帶，`check_monthly_trend`
任務已移除。決策依據見 `docs/PROGRESS.md` 2026-07-05 條目的回測對照數據。

```python
# src/signals/ma200_filter.py

import pandas as pd
import numpy as np
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class TrendState(str, Enum):
    BULL = "BULL"       # 多頭環境：收盤 > 200MA
    BEAR = "BEAR"       # 空頭環境：收盤 < 200MA
    UNDEFINED = "UNDEFINED"  # 資料不足


@dataclass
class MA200Signal:
    symbol: str
    date: pd.Timestamp
    state: TrendState
    current_price: float
    ma200: float
    distance_pct: float          # (price - ma200) / ma200 * 100
    is_newly_crossed: bool       # 本月是否剛越過均線


class MA200Filter:
    """
    200 日移動平均線趨勢過濾系統。
    
    規則：
    - 每日收盤時判斷
    - 收盤價 > 200MA → BULL（允許進場）
    - 收盤價 < 200MA → BEAR（強制出場，持現金）
    - 加緩衝帶（hysteresis）：帶入前一日狀態時，出場需跌破
      200MA×(1-exit_buffer_pct)、重新進場需站上 200MA×(1+enter_buffer_pct)，
      帶內維持前一日狀態

    防止雜訊：緩衝帶取代原本設想的「改用月底收盤判斷」，
    同時保留每日反應速度與防雜訊效果，避免在均線附近反覆進出（Whipsaw）
    """

    def __init__(self, period: int = 200):
        self.period = period

    def calculate(
        self,
        price_data: pd.DataFrame,
        symbol: str,
        check_date: Optional[pd.Timestamp] = None
    ) -> MA200Signal:
        """
        計算指定日期的 200MA 狀態。
        
        Args:
            price_data: 包含 'date'、'close' 欄位的 DataFrame
            symbol: 股票代碼
            check_date: 檢查日期（預設為最後一筆）
            
        Returns:
            MA200Signal 物件
        """
        if len(price_data) < self.period:
            logger.warning(
                f"{symbol}: 資料不足 {len(price_data)} 筆，需要至少 {self.period} 筆"
            )
            return MA200Signal(
                symbol=symbol,
                date=price_data['date'].iloc[-1],
                state=TrendState.UNDEFINED,
                current_price=0,
                ma200=0,
                distance_pct=0,
                is_newly_crossed=False
            )

        df = price_data.copy().sort_values('date')
        df['ma200'] = df['close'].rolling(self.period).mean()

        if check_date:
            row = df[df['date'] == check_date]
            if row.empty:
                raise ValueError(f"找不到日期 {check_date} 的資料")
            idx = row.index[0]
        else:
            idx = df.index[-1]

        current_price = df.loc[idx, 'close']
        ma200 = df.loc[idx, 'ma200']
        date = df.loc[idx, 'date']

        if pd.isna(ma200):
            state = TrendState.UNDEFINED
        elif current_price > ma200:
            state = TrendState.BULL
        else:
            state = TrendState.BEAR

        distance_pct = ((current_price - ma200) / ma200 * 100) if ma200 else 0

        # 判斷是否為本月新突破
        is_newly_crossed = self._check_newly_crossed(df, idx, state)

        return MA200Signal(
            symbol=symbol,
            date=date,
            state=state,
            current_price=float(current_price),
            ma200=float(ma200) if not pd.isna(ma200) else 0,
            distance_pct=float(distance_pct),
            is_newly_crossed=is_newly_crossed
        )

    def _check_newly_crossed(
        self,
        df: pd.DataFrame,
        current_idx: int,
        current_state: TrendState
    ) -> bool:
        """判斷是否在本月首次越過 200MA。"""
        if current_idx == 0 or current_state == TrendState.UNDEFINED:
            return False

        prev_idx = df.index[df.index.get_loc(current_idx) - 1]
        prev_price = df.loc[prev_idx, 'close']
        prev_ma200 = df.loc[prev_idx, 'ma200']

        if pd.isna(prev_ma200):
            return False

        prev_was_bull = prev_price > prev_ma200
        current_is_bull = current_state == TrendState.BULL

        return prev_was_bull != current_is_bull  # 狀態改變
```

### 4.2 策略 S2：台美時間差訊號生成器

**邏輯：** 美股收盤漲跌幅 > ±1.5% 且費半 SOX 同向 → 台股隔日開盤同向操作。

```python
# src/signals/time_diff.py

import pandas as pd
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime, time
import logging

logger = logging.getLogger(__name__)


class SignalDirection(str, Enum):
    LONG = "LONG"       # 做多
    SHORT = "SHORT"     # 做空（僅適用於期貨）
    NEUTRAL = "NEUTRAL" # 無訊號，不操作


@dataclass
class TimeDiffSignal:
    generated_at: datetime
    direction: SignalDirection
    confidence: float              # 0.0 ~ 1.0，訊號信心度
    
    # 美股指標
    nasdaq_change_pct: float
    sp500_change_pct: float
    sox_change_pct: float          # 費城半導體指數
    
    # 訊號觸發原因
    trigger_reason: str
    
    # 建議操作
    suggested_symbol: str          # 建議標的（0050、MTX 等）
    suggested_action: str          # BUY / SELL / HOLD
    
    # 交易參數
    entry_window_start: time = time(9, 0)   # 台股開盤
    entry_window_end: time = time(9, 30)    # 開盤後 30 分鐘
    exit_time: time = time(13, 25)          # 台股收盤前 5 分鐘


class TimeDiffSignalGenerator:
    """
    台美時間差訊號生成器。
    
    觸發條件（全部需符合）：
    1. NASDAQ 漲跌幅 > ±1.5%
    2. S&P 500 方向與 NASDAQ 一致（避免板塊分化）
    3. 費半（SOX）同向（與台股半導體高度相關）
    
    信心度加權：
    - NASDAQ 每超過 0.5%（超過門檻），信心度 +0.1
    - SOX 同向：信心度 +0.2
    - 三指數全部同向：額外 +0.1
    """

    def __init__(
        self,
        nasdaq_threshold: float = 1.5,
        require_sox_confirmation: bool = True,
        min_confidence: float = 0.6
    ):
        self.nasdaq_threshold = nasdaq_threshold
        self.require_sox_confirmation = require_sox_confirmation
        self.min_confidence = min_confidence

    def generate(
        self,
        nasdaq_change_pct: float,
        sp500_change_pct: float,
        sox_change_pct: float,
        generated_at: Optional[datetime] = None
    ) -> TimeDiffSignal:
        """
        根據美股收盤資料生成台股訊號。
        
        Args:
            nasdaq_change_pct: NASDAQ 當日漲跌幅（%）
            sp500_change_pct:  S&P 500 當日漲跌幅（%）
            sox_change_pct:    費城半導體指數漲跌幅（%）
            generated_at:      訊號生成時間
            
        Returns:
            TimeDiffSignal
        """
        generated_at = generated_at or datetime.now()
        
        # Step 1：判斷 NASDAQ 是否達到門檻
        nasdaq_abs = abs(nasdaq_change_pct)
        if nasdaq_abs < self.nasdaq_threshold:
            return self._neutral_signal(
                generated_at, nasdaq_change_pct, sp500_change_pct, sox_change_pct,
                reason=f"NASDAQ 漲跌幅 {nasdaq_change_pct:.2f}% 未達門檻 ±{self.nasdaq_threshold}%"
            )

        # Step 2：判斷方向
        direction = SignalDirection.LONG if nasdaq_change_pct > 0 else SignalDirection.SHORT

        # Step 3：確認 S&P 500 方向一致
        sp500_aligned = (sp500_change_pct > 0) == (nasdaq_change_pct > 0)
        if not sp500_aligned:
            return self._neutral_signal(
                generated_at, nasdaq_change_pct, sp500_change_pct, sox_change_pct,
                reason="NASDAQ 與 S&P 500 方向不一致（板塊分化）"
            )

        # Step 4：費半確認（若啟用）
        sox_aligned = (sox_change_pct > 0) == (nasdaq_change_pct > 0)
        if self.require_sox_confirmation and not sox_aligned:
            return self._neutral_signal(
                generated_at, nasdaq_change_pct, sp500_change_pct, sox_change_pct,
                reason="費半（SOX）方向與 NASDAQ 不一致，台灣半導體股可能不跟進"
            )

        # Step 5：計算信心度
        confidence = self._calculate_confidence(
            nasdaq_change_pct, sp500_change_pct, sox_change_pct, sox_aligned
        )

        if confidence < self.min_confidence:
            return self._neutral_signal(
                generated_at, nasdaq_change_pct, sp500_change_pct, sox_change_pct,
                reason=f"信心度 {confidence:.2f} 低於最低門檻 {self.min_confidence}"
            )

        # Step 6：決定建議標的
        suggested_symbol, suggested_action = self._suggest_trade(direction)

        trigger_reason = (
            f"NASDAQ {nasdaq_change_pct:+.2f}% | "
            f"S&P500 {sp500_change_pct:+.2f}% | "
            f"SOX {sox_change_pct:+.2f}% | "
            f"信心度 {confidence:.0%}"
        )

        return TimeDiffSignal(
            generated_at=generated_at,
            direction=direction,
            confidence=confidence,
            nasdaq_change_pct=nasdaq_change_pct,
            sp500_change_pct=sp500_change_pct,
            sox_change_pct=sox_change_pct,
            trigger_reason=trigger_reason,
            suggested_symbol=suggested_symbol,
            suggested_action=suggested_action
        )

    def _calculate_confidence(
        self,
        nasdaq_pct: float,
        sp500_pct: float,
        sox_pct: float,
        sox_aligned: bool
    ) -> float:
        base = 0.5
        
        # NASDAQ 超過門檻越多，信心度越高
        excess = abs(nasdaq_pct) - self.nasdaq_threshold
        base += min(excess * 0.1, 0.2)

        # SOX 同向加分
        if sox_aligned:
            base += 0.2

        # 三指數全部同向且大漲
        if (abs(sp500_pct) > 1.0 and abs(sox_pct) > 2.0 and sox_aligned):
            base += 0.1

        return min(base, 1.0)

    def _suggest_trade(self, direction: SignalDirection) -> tuple[str, str]:
        """根據訊號方向建議標的與動作。"""
        if direction == SignalDirection.LONG:
            return "0050", "BUY"
        else:
            # 台股 ETF 不能直接做空，建議轉倉至期貨或空手
            return "MTX", "SELL"  # 小台指放空

    def _neutral_signal(
        self,
        generated_at: datetime,
        nasdaq: float, sp500: float, sox: float,
        reason: str
    ) -> TimeDiffSignal:
        return TimeDiffSignal(
            generated_at=generated_at,
            direction=SignalDirection.NEUTRAL,
            confidence=0.0,
            nasdaq_change_pct=nasdaq,
            sp500_change_pct=sp500,
            sox_change_pct=sox,
            trigger_reason=reason,
            suggested_symbol="",
            suggested_action="HOLD"
        )
```

### 4.3 策略 S3：組合訊號整合器

```python
# src/signals/aggregator.py

from dataclasses import dataclass
from enum import Enum
from typing import Optional
import logging

from .ma200_filter import MA200Filter, TrendState, MA200Signal
from .time_diff import TimeDiffSignalGenerator, TimeDiffSignal, SignalDirection

logger = logging.getLogger(__name__)


class FinalAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    EXIT_ALL = "EXIT_ALL"   # 趨勢翻空，強制清倉


@dataclass
class CombinedSignal:
    final_action: FinalAction
    symbol: str
    
    trend_signal: MA200Signal
    time_diff_signal: TimeDiffSignal
    
    reason: str
    
    # 倉位建議
    suggested_position_pct: float   # 建議倉位佔帳戶比例
    stop_loss_pct: float            # 建議停損幅度
    trailing_stop_pct: float        # 移動停利幅度


class SignalAggregator:
    """
    組合訊號整合器（S1 × S2）。
    
    決策矩陣：
    ┌──────────┬──────────┬─────────────┐
    │ S1 趨勢  │ S2 方向  │  最終動作   │
    ├──────────┼──────────┼─────────────┤
    │ BULL     │ LONG     │ BUY         │  ← 雙重確認，執行
    │ BULL     │ SHORT    │ HOLD        │  ← 趨勢多但短線空，不動
    │ BULL     │ NEUTRAL  │ HOLD        │  ← 無短線訊號，不動
    │ BEAR     │ 任何     │ EXIT_ALL    │  ← 趨勢轉空，立即清倉
    │ UNDEFINED│ 任何     │ HOLD        │  ← 資料不足，不動
    └──────────┴──────────┴─────────────┘
    
    注意：系統偏向保守，寧願錯過機會也不在趨勢不明時進場。
    """

    def __init__(
        self,
        base_position_pct: float = 0.25,   # 基本倉位 25%
        max_position_pct: float = 0.40,    # 最高倉位 40%
        index_stop_loss_pct: float = 0.12, # 指數停損 12%
        trailing_stop_pct: float = 0.15    # 移動停利 15%
    ):
        self.base_position_pct = base_position_pct
        self.max_position_pct = max_position_pct
        self.index_stop_loss_pct = index_stop_loss_pct
        self.trailing_stop_pct = trailing_stop_pct

    def aggregate(
        self,
        trend: MA200Signal,
        time_diff: TimeDiffSignal,
        current_positions: Optional[dict] = None
    ) -> CombinedSignal:
        """整合兩個策略訊號，輸出最終交易決策。"""

        # 情境 1：趨勢空頭 → 不管短線訊號，強制清倉
        if trend.state == TrendState.BEAR:
            return CombinedSignal(
                final_action=FinalAction.EXIT_ALL,
                symbol="ALL",
                trend_signal=trend,
                time_diff_signal=time_diff,
                reason=f"200MA 趨勢轉空（目前距離 {trend.distance_pct:.1f}%），強制清倉",
                suggested_position_pct=0.0,
                stop_loss_pct=0.0,
                trailing_stop_pct=0.0
            )

        # 情境 2：趨勢未定義
        if trend.state == TrendState.UNDEFINED:
            return CombinedSignal(
                final_action=FinalAction.HOLD,
                symbol="",
                trend_signal=trend,
                time_diff_signal=time_diff,
                reason="200MA 資料不足，維持觀望",
                suggested_position_pct=0.0,
                stop_loss_pct=0.0,
                trailing_stop_pct=0.0
            )

        # 情境 3：趨勢多頭 + 時間差 LONG → 執行買進
        if (trend.state == TrendState.BULL
                and time_diff.direction == SignalDirection.LONG):

            # 根據信心度調整倉位
            position_pct = self.base_position_pct + (
                time_diff.confidence * (self.max_position_pct - self.base_position_pct)
            )
            position_pct = min(position_pct, self.max_position_pct)

            return CombinedSignal(
                final_action=FinalAction.BUY,
                symbol=time_diff.suggested_symbol,
                trend_signal=trend,
                time_diff_signal=time_diff,
                reason=(
                    f"雙重確認：200MA 多頭（{trend.distance_pct:+.1f}%）× "
                    f"時間差 LONG（信心 {time_diff.confidence:.0%}）"
                ),
                suggested_position_pct=round(position_pct, 3),
                stop_loss_pct=self.index_stop_loss_pct,
                trailing_stop_pct=self.trailing_stop_pct
            )

        # 情境 4：趨勢多頭但短線訊號不確定 → 維持現狀
        return CombinedSignal(
            final_action=FinalAction.HOLD,
            symbol="",
            trend_signal=trend,
            time_diff_signal=time_diff,
            reason=(
                f"趨勢多頭但短線訊號為 {time_diff.direction.value}，"
                f"維持觀望（{time_diff.trigger_reason}）"
            ),
            suggested_position_pct=0.0,
            stop_loss_pct=0.0,
            trailing_stop_pct=0.0
        )
```

### 4.4 風險管理：停損管理器

```python
# src/risk/stop_loss.py

from dataclasses import dataclass
from typing import Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class StopLossConfig:
    stop_loss_pct: float = 0.12        # 固定停損（距進場價）
    trailing_stop_pct: float = 0.15    # 移動停利（距高點）
    time_stop_days: int = 5            # 時間停損：N 天內若無盈利則出場


@dataclass
class Position:
    symbol: str
    entry_price: float
    entry_date: datetime
    quantity: float
    peak_price: float                   # 持倉最高點（移動停利用）
    stop_loss_price: float
    trailing_stop_price: float


class StopLossManager:
    """
    停損管理器。
    
    三種出場觸發：
    1. 固定停損：現價跌破進場價 × (1 - stop_loss_pct)
    2. 移動停利：現價跌破歷史最高點 × (1 - trailing_stop_pct)
    3. 時間停損：持倉 N 天仍無獲利，自動出場
    """

    def __init__(self, config: StopLossConfig):
        self.config = config

    def initialize_position(
        self,
        symbol: str,
        entry_price: float,
        entry_date: datetime,
        quantity: float
    ) -> Position:
        """建立新倉位並計算初始停損線。"""
        stop_price = entry_price * (1 - self.config.stop_loss_pct)
        
        return Position(
            symbol=symbol,
            entry_price=entry_price,
            entry_date=entry_date,
            quantity=quantity,
            peak_price=entry_price,
            stop_loss_price=round(stop_price, 2),
            trailing_stop_price=round(stop_price, 2)
        )

    def update_trailing_stop(
        self,
        position: Position,
        current_price: float
    ) -> Position:
        """根據最新價格更新移動停利線（只升不降）。"""
        if current_price > position.peak_price:
            position.peak_price = current_price
            new_trailing = current_price * (1 - self.config.trailing_stop_pct)
            # 移動停利只能往上調，不能往下
            position.trailing_stop_price = max(
                position.trailing_stop_price,
                round(new_trailing, 2)
            )
            logger.debug(
                f"{position.symbol}: 新高 {current_price:.2f}，"
                f"移動停利更新至 {position.trailing_stop_price:.2f}"
            )
        return position

    def should_exit(
        self,
        position: Position,
        current_price: float,
        current_date: datetime
    ) -> tuple[bool, str]:
        """
        判斷是否應該出場。
        
        Returns:
            (should_exit: bool, reason: str)
        """
        # 固定停損
        if current_price <= position.stop_loss_price:
            loss_pct = (current_price - position.entry_price) / position.entry_price * 100
            return True, f"觸發固定停損 {loss_pct:.1f}%（停損線 {position.stop_loss_price:.2f}）"

        # 移動停利
        if current_price <= position.trailing_stop_price:
            gain_pct = (position.peak_price - position.entry_price) / position.entry_price * 100
            return True, (
                f"觸發移動停利（高點 {position.peak_price:.2f}，"
                f"曾獲利 {gain_pct:.1f}%，停利線 {position.trailing_stop_price:.2f}）"
            )

        # 時間停損
        days_held = (current_date - position.entry_date).days
        if days_held >= self.config.time_stop_days:
            pnl_pct = (current_price - position.entry_price) / position.entry_price * 100
            if pnl_pct <= 0:
                return True, f"時間停損：持倉 {days_held} 天仍虧損 {pnl_pct:.1f}%"

        return False, ""
```

### 4.5 資料抓取模組

```python
# src/data/fetcher.py

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional
import asyncio
import httpx
import logging

logger = logging.getLogger(__name__)

# 美股指數代碼對照
US_SYMBOLS = {
    "nasdaq": "^IXIC",
    "sp500": "^GSPC",
    "sox": "^SOX",      # 費城半導體指數
    "qqq": "QQQ",
    "tqqq": "TQQQ",
}

# 台股代碼對照
TW_SYMBOLS = {
    "0050": "0050.TW",
    "taiex": "^TWII",
}


class USMarketFetcher:
    """美股市場資料抓取器。"""

    def get_latest_close(self, symbol_key: str) -> dict:
        """
        抓取最新收盤資料。
        
        Returns:
            {
                'symbol': str,
                'date': datetime,
                'close': float,
                'change_pct': float,
                'volume': int
            }
        """
        ticker_code = US_SYMBOLS.get(symbol_key, symbol_key)
        ticker = yf.Ticker(ticker_code)

        # 抓最近 5 天資料（確保拿到最新收盤）
        hist = ticker.history(period="5d")
        if hist.empty:
            raise ValueError(f"無法取得 {ticker_code} 的資料")

        latest = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) > 1 else None

        change_pct = 0.0
        if prev is not None:
            change_pct = (latest['Close'] - prev['Close']) / prev['Close'] * 100

        return {
            "symbol": ticker_code,
            "date": hist.index[-1].to_pydatetime(),
            "close": float(latest['Close']),
            "change_pct": round(float(change_pct), 4),
            "volume": int(latest['Volume'])
        }

    def get_historical(
        self,
        symbol_key: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        period: str = "2y"
    ) -> pd.DataFrame:
        """
        抓取歷史 OHLCV 資料（供回測與 MA 計算）。
        
        Returns:
            DataFrame with columns: date, open, high, low, close, volume
        """
        ticker_code = US_SYMBOLS.get(symbol_key, symbol_key)
        ticker = yf.Ticker(ticker_code)

        if start_date and end_date:
            hist = ticker.history(start=start_date, end=end_date)
        else:
            hist = ticker.history(period=period)

        df = hist.reset_index()
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"datetime": "date"})[
            ["date", "open", "high", "low", "close", "volume"]
        ]
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)

        return df

    def get_all_signals_data(self) -> dict:
        """同時抓取所有需要的美股指標。"""
        results = {}
        for key in ["nasdaq", "sp500", "sox"]:
            try:
                results[key] = self.get_latest_close(key)
            except Exception as e:
                logger.error(f"抓取 {key} 失敗: {e}")
                results[key] = None
        return results


class TWMarketFetcher:
    """台股市場資料抓取器。"""

    def get_historical(
        self,
        symbol: str,
        start_date: Optional[datetime] = None,
        period: str = "2y"
    ) -> pd.DataFrame:
        """抓取台股歷史資料（透過 Yahoo Finance .TW 後綴）。"""
        ticker_code = TW_SYMBOLS.get(symbol, f"{symbol}.TW")
        ticker = yf.Ticker(ticker_code)

        hist = ticker.history(period=period)
        df = hist.reset_index()
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"datetime": "date"})[
            ["date", "open", "high", "low", "close", "volume"]
        ]
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)

        return df
```

### 4.6 券商介面（抽象層）

```python
# src/execution/brokers/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from datetime import datetime


class OrderType(str, Enum):
    MARKET = "MARKET"           # 市價單
    LIMIT = "LIMIT"             # 限價單
    STOP = "STOP"               # 停損單
    STOP_LIMIT = "STOP_LIMIT"  # 停損限價單


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class Order:
    order_id: str
    symbol: str
    quantity: float
    order_type: OrderType
    direction: str              # BUY / SELL
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_price: Optional[float] = None
    filled_at: Optional[datetime] = None


class BaseBroker(ABC):
    """
    券商介面抽象基類。
    
    新增券商只需繼承此類並實作以下方法，
    不需修改上層交易邏輯。
    """

    @abstractmethod
    def submit_order(self, order: Order) -> Order:
        """送出訂單，回傳含 order_id 的更新訂單。"""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """取消訂單。"""
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> Order:
        """查詢訂單狀態。"""
        pass

    @abstractmethod
    def get_positions(self) -> list[dict]:
        """取得目前所有持倉。"""
        pass

    @abstractmethod
    def get_account_balance(self) -> dict:
        """取得帳戶資金狀況。"""
        pass


# src/execution/brokers/paper.py

import uuid
from datetime import datetime
from .base import BaseBroker, Order, OrderStatus
import logging

logger = logging.getLogger(__name__)


class PaperBroker(BaseBroker):
    """
    模擬帳戶（Paper Trading）。
    
    用於開發測試與策略驗證，
    不連接真實券商，模擬成交邏輯。
    """

    def __init__(self, initial_capital: float = 1_000_000):
        self.capital = initial_capital
        self.positions: dict[str, dict] = {}
        self.orders: dict[str, Order] = {}
        self.trade_history: list[dict] = []

    def submit_order(self, order: Order) -> Order:
        order.order_id = str(uuid.uuid4())
        order.status = OrderStatus.SUBMITTED

        # 模擬市價單即時成交
        if order.order_type == OrderType.MARKET:
            order.status = OrderStatus.FILLED
            order.filled_price = order.limit_price  # 模擬以限價成交
            order.filled_at = datetime.now()
            self._update_position(order)

        self.orders[order.order_id] = order
        logger.info(
            f"[PAPER] 訂單 {order.order_id[:8]}: "
            f"{order.direction} {order.quantity} {order.symbol} "
            f"@ {order.filled_price} → {order.status.value}"
        )
        return order

    def _update_position(self, order: Order):
        """更新模擬持倉。"""
        if order.direction == "BUY":
            cost = order.quantity * order.filled_price
            self.capital -= cost
            if order.symbol in self.positions:
                pos = self.positions[order.symbol]
                total_qty = pos["quantity"] + order.quantity
                pos["avg_price"] = (
                    (pos["avg_price"] * pos["quantity"] + cost) / total_qty
                )
                pos["quantity"] = total_qty
            else:
                self.positions[order.symbol] = {
                    "quantity": order.quantity,
                    "avg_price": order.filled_price
                }
        elif order.direction == "SELL":
            if order.symbol in self.positions:
                proceeds = order.quantity * order.filled_price
                self.capital += proceeds
                pos = self.positions[order.symbol]
                pos["quantity"] -= order.quantity
                if pos["quantity"] <= 0:
                    del self.positions[order.symbol]

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self.orders:
            self.orders[order_id].status = OrderStatus.CANCELLED
            return True
        return False

    def get_order_status(self, order_id: str) -> Order:
        return self.orders.get(order_id)

    def get_positions(self) -> list[dict]:
        return [
            {"symbol": k, **v}
            for k, v in self.positions.items()
        ]

    def get_account_balance(self) -> dict:
        return {
            "cash": self.capital,
            "positions_value": sum(
                p["quantity"] * p["avg_price"]
                for p in self.positions.values()
            ),
            "total": self.capital + sum(
                p["quantity"] * p["avg_price"]
                for p in self.positions.values()
            )
        }
```

---

## 5. 資料庫設計

### 5.1 ER 圖概覽

```
market_prices ──< signals >── combined_signals
                                    │
                                    ▼
                               orders ──< fills
                                    │
                                    ▼
                              positions ──── trade_journal
                                    │
                                    ▼
                         performance_snapshots
```

> **Supabase 連線設定注意事項**
>
> Supabase 免費版最多 60 個並發連線（透過 PgBouncer）。多個 Celery Worker 同時運行時需限制連線池上限：
>
> ```python
> # src/database/__init__.py
> engine = create_async_engine(
>     DATABASE_URL,
>     pool_size=5,      # 每個 Worker 最多 5 條連線
>     max_overflow=2,
>     pool_timeout=30,
>     pool_pre_ping=True   # 自動重連斷線的連線
> )
> ```

### 5.2 資料表定義（SQLAlchemy）

```python
# src/database/models.py

from sqlalchemy import (
    Column, String, Float, Integer, Boolean,
    DateTime, JSON, ForeignKey, Index, Numeric
)
from sqlalchemy.orm import DeclarativeBase, relationship
from datetime import datetime


class Base(DeclarativeBase):
    pass


class MarketPrice(Base):
    """美股/台股歷史收盤資料。"""
    __tablename__ = "market_prices"
    __table_args__ = (
        Index("ix_market_prices_symbol_date", "symbol", "date", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    date = Column(DateTime, nullable=False)
    open = Column(Numeric(12, 4))
    high = Column(Numeric(12, 4))
    low = Column(Numeric(12, 4))
    close = Column(Numeric(12, 4), nullable=False)
    volume = Column(Integer)
    change_pct = Column(Numeric(8, 4))       # 當日漲跌幅（%）
    source = Column(String(50))               # yfinance / twse / etc
    created_at = Column(DateTime, default=datetime.utcnow)


class TrendSignal(Base):
    """200MA 趨勢過濾訊號記錄。"""
    __tablename__ = "trend_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    signal_date = Column(DateTime, nullable=False)
    state = Column(String(10), nullable=False)      # BULL / BEAR / UNDEFINED
    current_price = Column(Numeric(12, 4))
    ma200 = Column(Numeric(12, 4))
    distance_pct = Column(Numeric(8, 4))
    is_newly_crossed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class TimeDiffSignalRecord(Base):
    """台美時間差訊號記錄。"""
    __tablename__ = "time_diff_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    generated_at = Column(DateTime, nullable=False)
    direction = Column(String(10), nullable=False)  # LONG / SHORT / NEUTRAL
    confidence = Column(Numeric(4, 3))

    nasdaq_change_pct = Column(Numeric(8, 4))
    sp500_change_pct = Column(Numeric(8, 4))
    sox_change_pct = Column(Numeric(8, 4))

    trigger_reason = Column(String(500))
    suggested_symbol = Column(String(20))
    suggested_action = Column(String(10))
    created_at = Column(DateTime, default=datetime.utcnow)


class Order(Base):
    """訂單記錄。"""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(100), unique=True, nullable=False)
    symbol = Column(String(20), nullable=False)
    direction = Column(String(5), nullable=False)     # BUY / SELL
    order_type = Column(String(20), nullable=False)
    quantity = Column(Numeric(12, 4), nullable=False)
    limit_price = Column(Numeric(12, 4))
    stop_price = Column(Numeric(12, 4))
    status = Column(String(20), nullable=False)
    filled_price = Column(Numeric(12, 4))
    filled_at = Column(DateTime)

    # 觸發來源
    signal_id = Column(Integer, ForeignKey("time_diff_signals.id"))
    strategy = Column(String(10))                     # S1 / S2 / S3
    broker = Column(String(20))                       # paper / ibkr / yuanta

    created_at = Column(DateTime, default=datetime.utcnow)
    fills = relationship("Fill", back_populates="order")


class Fill(Base):
    """成交紀錄（一個訂單可能分批成交）。"""
    __tablename__ = "fills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    fill_price = Column(Numeric(12, 4), nullable=False)
    fill_quantity = Column(Numeric(12, 4), nullable=False)
    commission = Column(Numeric(10, 4), default=0)
    filled_at = Column(DateTime, nullable=False)
    order = relationship("Order", back_populates="fills")


class Position(Base):
    """目前持倉快照。"""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    quantity = Column(Numeric(12, 4), nullable=False)
    avg_entry_price = Column(Numeric(12, 4), nullable=False)
    current_price = Column(Numeric(12, 4))
    stop_loss_price = Column(Numeric(12, 4))
    trailing_stop_price = Column(Numeric(12, 4))
    peak_price = Column(Numeric(12, 4))
    unrealized_pnl = Column(Numeric(12, 4))
    unrealized_pnl_pct = Column(Numeric(8, 4))
    opened_at = Column(DateTime)
    last_updated = Column(DateTime, default=datetime.utcnow)


class PerformanceSnapshot(Base):
    """每日績效快照。"""
    __tablename__ = "performance_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_date = Column(DateTime, nullable=False, unique=True)
    total_equity = Column(Numeric(15, 4))
    cash = Column(Numeric(15, 4))
    positions_value = Column(Numeric(15, 4))
    daily_pnl = Column(Numeric(12, 4))
    daily_return_pct = Column(Numeric(8, 4))
    total_return_pct = Column(Numeric(8, 4))
    max_drawdown_pct = Column(Numeric(8, 4))
    win_rate = Column(Numeric(5, 4))
    sharpe_ratio = Column(Numeric(8, 4))
    metadata = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
```

---

## 6. API 規格說明

### 6.1 基本資訊

```
Base URL：http://localhost:8000/api/v1
認證方式：Bearer Token（JWT）
格式：application/json
```

### 6.2 端點清單

#### GET `/signals/current`
取得目前最新訊號狀態。

**Response：**
```json
{
  "trend": {
    "symbol": "QQQ",
    "state": "BULL",
    "current_price": 485.23,
    "ma200": 451.87,
    "distance_pct": 7.39,
    "signal_date": "2026-06-21T00:00:00Z"
  },
  "time_diff": {
    "direction": "LONG",
    "confidence": 0.82,
    "nasdaq_change_pct": 2.31,
    "sp500_change_pct": 1.87,
    "sox_change_pct": 3.12,
    "trigger_reason": "NASDAQ +2.31% | S&P500 +1.87% | SOX +3.12% | 信心度 82%",
    "generated_at": "2026-06-21T04:05:00+08:00"
  },
  "combined": {
    "final_action": "BUY",
    "symbol": "0050",
    "suggested_position_pct": 0.35,
    "stop_loss_pct": 0.12,
    "reason": "雙重確認：200MA 多頭（+7.4%）× 時間差 LONG（信心 82%）"
  }
}
```

#### GET `/positions`
取得目前所有持倉。

#### POST `/orders`
手動建立訂單（需 Admin 權限）。

**Request：**
```json
{
  "symbol": "0050",
  "direction": "BUY",
  "order_type": "MARKET",
  "quantity": 100,
  "strategy": "S3"
}
```

#### GET `/performance`
取得績效摘要。

**Response：**
```json
{
  "period": "ytd",
  "total_return_pct": 18.43,
  "max_drawdown_pct": -8.21,
  "win_rate": 0.68,
  "total_trades": 47,
  "sharpe_ratio": 1.84,
  "profit_factor": 2.31
}
```

#### POST `/backtest/run`
觸發回測任務。

**Request：**
```json
{
  "strategy": "S3",
  "symbol": "QQQ",
  "start_date": "2015-01-01",
  "end_date": "2025-12-31",
  "initial_capital": 1000000
}
```

---

## 7. 回測框架

### 7.1 回測引擎

```python
# src/backtest/engine.py

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

from ..signals.ma200_filter import MA200Filter, TrendState
from ..signals.time_diff import TimeDiffSignalGenerator
from ..signals.aggregator import SignalAggregator, FinalAction
from .metrics import PerformanceMetrics


@dataclass
class BacktestConfig:
    symbol: str = "QQQ"
    start_date: str = "2015-01-01"
    end_date: str = "2025-12-31"
    initial_capital: float = 1_000_000
    commission_pct: float = 0.001           # 手續費 0.1%
    slippage_pct: float = 0.001            # 滑價 0.1%
    nasdaq_threshold: float = 1.5
    stop_loss_pct: float = 0.12
    trailing_stop_pct: float = 0.15


@dataclass
class BacktestResult:
    config: BacktestConfig
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate: float
    total_trades: int
    profit_factor: float
    equity_curve: pd.Series
    trade_log: list[dict] = field(default_factory=list)


class BacktestEngine:
    """向量化回測引擎。"""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.ma200 = MA200Filter()
        self.time_diff_gen = TimeDiffSignalGenerator(
            nasdaq_threshold=config.nasdaq_threshold
        )
        self.aggregator = SignalAggregator(
            index_stop_loss_pct=config.stop_loss_pct,
            trailing_stop_pct=config.trailing_stop_pct
        )

    def run(
        self,
        price_data: pd.DataFrame,       # 台股/標的資料
        us_signal_data: pd.DataFrame    # 美股指數資料（含 nasdaq/sp500/sox 欄位）
    ) -> BacktestResult:
        """
        執行回測。
        
        Args:
            price_data: 含 date/close 欄位的目標標的資料
            us_signal_data: 含 date/nasdaq_chg/sp500_chg/sox_chg 欄位的美股資料
        """
        capital = self.config.initial_capital
        position = 0.0          # 持有股數
        entry_price = 0.0
        peak_price = 0.0
        equity_curve = []
        trade_log = []

        merged = pd.merge(price_data, us_signal_data, on="date", how="inner")
        merged = merged.sort_values("date").reset_index(drop=True)

        for i, row in merged.iterrows():
            current_price = row["close"]
            current_date = row["date"]

            # 計算當前均值（需要前面的資料）
            if i < 200:
                equity_curve.append(capital + position * current_price)
                continue

            hist_slice = merged.iloc[max(0, i-250):i+1]

            # S1: 趨勢訊號
            trend_sig = self.ma200.calculate(
                price_data=hist_slice[["date", "close"]],
                symbol=self.config.symbol
            )

            # S2: 時間差訊號
            time_sig = self.time_diff_gen.generate(
                nasdaq_change_pct=row.get("nasdaq_chg", 0),
                sp500_change_pct=row.get("sp500_chg", 0),
                sox_change_pct=row.get("sox_chg", 0)
            )

            # S3: 組合訊號
            combined = self.aggregator.aggregate(trend_sig, time_sig)

            # 停損檢查
            if position > 0:
                # 更新移動停利
                if current_price > peak_price:
                    peak_price = current_price

                trailing_stop = peak_price * (1 - self.config.trailing_stop_pct)
                fixed_stop = entry_price * (1 - self.config.stop_loss_pct)
                effective_stop = max(trailing_stop, fixed_stop)

                if current_price <= effective_stop or combined.final_action == FinalAction.EXIT_ALL:
                    # 出場
                    proceeds = position * current_price * (1 - self.config.commission_pct)
                    pnl = proceeds - (position * entry_price)
                    trade_log.append({
                        "date": current_date,
                        "action": "SELL",
                        "price": current_price,
                        "pnl": pnl,
                        "pnl_pct": pnl / (position * entry_price) * 100,
                        "reason": "STOP_LOSS" if current_price <= effective_stop else "TREND_EXIT"
                    })
                    capital += proceeds
                    position = 0
                    entry_price = 0
                    peak_price = 0

            # 進場
            if position == 0 and combined.final_action == FinalAction.BUY:
                invest_amount = capital * combined.suggested_position_pct
                shares = invest_amount / (current_price * (1 + self.config.commission_pct + self.config.slippage_pct))
                cost = shares * current_price * (1 + self.config.commission_pct + self.config.slippage_pct)

                if cost <= capital:
                    capital -= cost
                    position = shares
                    entry_price = current_price
                    peak_price = current_price
                    trade_log.append({
                        "date": current_date,
                        "action": "BUY",
                        "price": current_price,
                        "shares": shares,
                        "reason": combined.reason
                    })

            equity_curve.append(capital + position * current_price)

        equity_series = pd.Series(equity_curve, index=merged["date"].iloc[len(equity_curve)*-1:])
        metrics = PerformanceMetrics(equity_series, self.config.initial_capital)

        return BacktestResult(
            config=self.config,
            total_return_pct=metrics.total_return_pct,
            annualized_return_pct=metrics.annualized_return_pct,
            max_drawdown_pct=metrics.max_drawdown_pct,
            sharpe_ratio=metrics.sharpe_ratio,
            win_rate=metrics.win_rate(trade_log),
            total_trades=len([t for t in trade_log if t["action"] == "SELL"]),
            profit_factor=metrics.profit_factor(trade_log),
            equity_curve=equity_series,
            trade_log=trade_log
        )
```

---

## 8. 測試策略

### 8.1 測試分層

```
tests/
├── unit/                   # 單元測試（不依賴外部服務）
│   ├── test_ma200_filter.py
│   ├── test_time_diff.py
│   ├── test_aggregator.py
│   ├── test_stop_loss.py
│   └── test_position_sizer.py
├── integration/            # 整合測試（需要 DB、Redis）
│   ├── test_data_pipeline.py
│   ├── test_order_flow.py
│   └── test_api_endpoints.py
└── backtest/               # 策略回測驗證
    ├── test_s1_strategy.py
    ├── test_s2_strategy.py
    └── test_s3_combined.py
```

### 8.2 單元測試範例

```python
# tests/unit/test_ma200_filter.py

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from src.signals.ma200_filter import MA200Filter, TrendState


def make_price_data(n_days: int, start_price: float = 100.0, trend: float = 0.0) -> pd.DataFrame:
    """生成測試用價格資料。"""
    dates = [datetime(2020, 1, 1) + timedelta(days=i) for i in range(n_days)]
    prices = [start_price * (1 + trend) ** i for i in range(n_days)]
    return pd.DataFrame({"date": dates, "close": prices})


class TestMA200Filter:

    def setup_method(self):
        self.filter = MA200Filter(period=200)

    def test_bull_state_when_price_above_ma200(self):
        """價格在 200MA 上方應回傳 BULL。"""
        data = make_price_data(300, start_price=100, trend=0.001)  # 持續上漲
        signal = self.filter.calculate(data, "TEST")
        assert signal.state == TrendState.BULL
        assert signal.distance_pct > 0

    def test_bear_state_when_price_below_ma200(self):
        """價格在 200MA 下方應回傳 BEAR。"""
        data = make_price_data(300, start_price=100, trend=-0.001)  # 持續下跌
        signal = self.filter.calculate(data, "TEST")
        assert signal.state == TrendState.BEAR
        assert signal.distance_pct < 0

    def test_undefined_when_insufficient_data(self):
        """資料不足 200 筆應回傳 UNDEFINED。"""
        data = make_price_data(150)
        signal = self.filter.calculate(data, "TEST")
        assert signal.state == TrendState.UNDEFINED

    def test_newly_crossed_detection(self):
        """應正確偵測本期新突破。"""
        # 先下跌200天，再急拉1天
        down = make_price_data(200, start_price=100, trend=-0.002)
        up = pd.DataFrame({
            "date": [down["date"].iloc[-1] + timedelta(days=1)],
            "close": [120.0]  # 大幅拉高至均線以上
        })
        data = pd.concat([down, up], ignore_index=True)
        signal = self.filter.calculate(data, "TEST")
        # 驗證邏輯而非結果（因為簡單測試資料）
        assert isinstance(signal.is_newly_crossed, bool)
```

### 8.3 回測驗證標準

| 指標 | 最低要求 | 目標 |
|------|----------|------|
| 夏普比率（Sharpe Ratio）| > 0.8 | > 1.5 |
| 最大回撤（Max Drawdown）| < -30% | < -15% |
| 勝率（Win Rate）| > 50% | > 60% |
| 獲利因子（Profit Factor）| > 1.2 | > 1.8 |
| 年化報酬（相對大盤） | > 0%（超越大盤） | > +3% |

---

## 9. 風險管理框架

### 9.1 多層風控機制

```
第一層：單筆交易停損（-8% 個股 / -12% 指數）
第二層：移動停利（高點回落 -15%）
第三層：時間停損（N 天無獲利強制出場）
第四層：總倉位限制（單一標的 ≤ 30%，總倉 ≤ 80%）
第五層：趨勢過濾（BEAR 環境禁止新開倉）
第六層：每日虧損熔斷（單日虧損 > 5% 帳戶，停止當日所有操作）
```

### 9.2 每日虧損熔斷

```python
# src/risk/exposure.py

class DailyCircuitBreaker:
    """每日虧損熔斷機制。"""

    def __init__(self, max_daily_loss_pct: float = 0.05):
        self.max_daily_loss_pct = max_daily_loss_pct
        self._triggered = False

    def check(self, daily_pnl_pct: float) -> bool:
        """若單日虧損超過門檻，觸發熔斷。"""
        if daily_pnl_pct <= -self.max_daily_loss_pct:
            self._triggered = True
            logger.critical(
                f"🚨 每日熔斷觸發：單日虧損 {daily_pnl_pct:.1%}，"
                f"停止今日所有交易操作"
            )
        return self._triggered

    def reset(self):
        """每個交易日開始時重置。"""
        self._triggered = False
```

---

## 10. 監控與警報

### 10.1 Telegram 警報

```python
# src/alerts/telegram.py

import httpx
import asyncio
from enum import Enum


class AlertLevel(str, Enum):
    INFO = "ℹ️"
    SUCCESS = "✅"
    WARNING = "⚠️"
    CRITICAL = "🚨"


class TelegramAlerter:

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    async def send(self, message: str, level: AlertLevel = AlertLevel.INFO):
        text = f"{level.value} *交易系統通知*\n\n{message}"
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "Markdown"
                }
            )

    async def signal_alert(self, signal: dict):
        msg = (
            f"*新訊號觸發*\n"
            f"方向：{signal['final_action']}\n"
            f"標的：{signal['symbol']}\n"
            f"建議倉位：{signal['suggested_position_pct']:.0%}\n"
            f"原因：{signal['reason']}"
        )
        await self.send(msg, AlertLevel.SUCCESS if signal['final_action'] == "BUY" else AlertLevel.WARNING)

    async def trade_executed(self, order: dict):
        msg = (
            f"*訂單成交*\n"
            f"{order['direction']} {order['quantity']} {order['symbol']}\n"
            f"成交價：{order['filled_price']}\n"
            f"策略：{order['strategy']}"
        )
        await self.send(msg, AlertLevel.SUCCESS)

    async def stop_loss_triggered(self, position: dict, loss_pct: float):
        msg = (
            f"*停損觸發*\n"
            f"標的：{position['symbol']}\n"
            f"虧損：{loss_pct:.1f}%\n"
            f"已自動出場"
        )
        await self.send(msg, AlertLevel.CRITICAL)
```

---

## 11. 部署與 CI/CD

## 11. 部署與 CI/CD

### 11.1 Fly.io 設定（Trading Engine）

```toml
# fly.toml

app = "trading-system-engine"
primary_region = "nrt"          # 東京節點，離台灣最近

[build]
  dockerfile = "docker/Dockerfile"

# Worker：停損監控（長期運行）
[[services]]
  internal_port = 8080
  protocol = "tcp"

  [services.concurrency]
    hard_limit = 25
    soft_limit = 20

# 兩個持久 Process：Worker + Scheduler
[processes]
  worker    = "celery -A src.tasks worker --loglevel=info -Q signals,orders,alerts -c 2"
  scheduler = "celery -A src.tasks beat   --loglevel=info"

[env]
  TRADING_MODE = "paper"
  TZ = "Asia/Taipei"

# 資源設定（free tier 範圍內）
[[vm]]
  cpu_kind  = "shared"
  cpus      = 1
  memory_mb = 256
```

**首次部署：**
```bash
fly launch --no-deploy          # 建立 App，不立即部署
fly secrets set \
  DATABASE_URL="postgresql+asyncpg://..." \
  REDIS_URL="rediss://..." \
  TELEGRAM_BOT_TOKEN="..." \
  TRADING_MODE="paper"
fly deploy                      # 正式部署
fly logs                        # 即時查看日誌
```

### 11.2 Supabase Keep-Alive（GitHub Actions）

每 3 天獨立 ping 一次，與 Fly.io 完全解耦，Fly.io 即使故障也不影響 ping：

```yaml
# .github/workflows/supabase-keepalive.yml

name: Supabase Keep-Alive

on:
  schedule:
    - cron: '0 12 */3 * *'     # 每 3 天中午 12:00 UTC 執行
  workflow_dispatch:            # 支援手動觸發

jobs:
  ping:
    runs-on: ubuntu-latest
    steps:
      - name: Ping Supabase Database
        run: |
          STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
            "${{ secrets.SUPABASE_URL }}/rest/v1/market_prices?limit=1" \
            -H "apikey: ${{ secrets.SUPABASE_ANON_KEY }}" \
            -H "Authorization: Bearer ${{ secrets.SUPABASE_ANON_KEY }}")

          echo "Supabase ping status: $STATUS"

          if [ "$STATUS" != "200" ]; then
            echo "❌ Supabase ping failed with status $STATUS"
            exit 1
          fi

          echo "✅ Supabase is alive"
```

> **為什麼不在 Fly.io 裡面 ping？** 如果 Fly.io 本身故障導致任務停跑，同時 Supabase 也閒置超過 7 天，就會兩個服務同時掛掉。GitHub Actions 是完全獨立的第三方，確保 ping 永遠能觸發。

### 11.3 CI/CD（GitHub Actions）

```yaml
# .github/workflows/test.yml

name: Test & Lint

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: trading_test
          POSTGRES_USER: test_user
          POSTGRES_PASSWORD: test_pass
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s

    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Lint
        run: |
          ruff check src/ tests/
          mypy src/

      - name: Run unit tests
        env:
          DATABASE_URL: postgresql+asyncpg://test_user:test_pass@localhost:5432/trading_test
          REDIS_URL: redis://localhost:6379/0
          TRADING_MODE: paper
        run: |
          pytest tests/unit/ -v --cov=src --cov-report=xml
          pytest tests/integration/ -v

      - name: Upload coverage
        uses: codecov/codecov-action@v4
```

```yaml
# .github/workflows/deploy.yml

name: Deploy to Fly.io

on:
  push:
    branches: [main]          # 只有 main 分支合併才觸發部署

jobs:
  deploy:
    runs-on: ubuntu-latest
    needs: [test]             # 測試通過才部署
    steps:
      - uses: actions/checkout@v4

      - uses: superfly/flyctl-actions/setup-flyctl@master

      - name: Deploy to Fly.io
        run: fly deploy --remote-only
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

### 11.4 部署流程

```
本地開發（TRADING_MODE=paper）
    │
    ├── feature/xxx branch
    │       ↓ PR
    ├── develop branch  →  自動跑 CI（test.yml）
    │       ↓ 手動合併（通過所有測試後）
    └── main branch  →  自動部署至 Fly.io（deploy.yml）
                              ↓
                     模擬帳戶穩定 4 週
                              ↓
                    fly secrets set TRADING_MODE=live
                              ↓
                        真實資金啟動
```

### 11.5 上線前 Checklist

- [ ] 模擬帳戶（TRADING_MODE=paper）穩定運行 4 週
- [ ] 回測通過驗收標準（Section 8.3）
- [ ] Supabase Keep-Alive workflow 確認正常觸發
- [ ] Fly.io 日誌確認 Worker + Scheduler 均正常運行
- [ ] Telegram 警報所有事件類型測試通過
- [ ] 停損機制手動觸發測試通過
- [ ] 每日熔斷機制測試通過
- [ ] 緊急手動停止指令確認：`fly scale count worker=0`
- [ ] 初始資金設定（建議第一個月不超過總投機資金的 50%）

### 11.6 升級路徑（有獲利後評估）

| 觸發條件 | 建議升級項目 | 費用變化 |
|----------|-------------|---------|
| 策略驗證完成，開始真實交易 | Supabase Free → Pro | +$25/月（消除閒置風險）|
| 月獲利穩定 > NT$3,000 | Fly.io 升級至 performance VM | +$5–10/月 |
| 需要更低延遲或更高可靠性 | 評估遷移至 GCP 台灣 VPS | 重新評估整體架構 |
| 資料量超過 400MB | Supabase Pro 已包含，或考慮資料歸檔策略 | 不額外收費 |

---

## 12. 覆盤與策略優化機制

> **顧問說明**：覆盤機制是這套系統的「學習迴路」。沒有它，系統只能執行，無法進化；有了它，每一天的交易都在累積可操作的知識。本章設計原則：**量化優先、人為干預最小化、防止過度擬合**。

### 12.1 系統全貌

```
每個交易日 13:35 台股收盤後
        │
        ▼
┌───────────────────────────────────────────┐
│           覆盤引擎 (ReviewEngine)          │
│                                           │
│  Layer 1: 規則遵守度檢查（自動）           │
│  Layer 2: 訊號品質分析（自動）             │
│  Layer 3: AI 質化分析（Claude API）        │
│  Layer 4: 稅後損益計算（自動）             │
└──────────────────┬────────────────────────┘
                   │
        ┌──────────┼────────────┐
        ▼          ▼            ▼
  Supabase    Telegram      Dashboard
 (儲存報告)  (推送摘要)   (視覺化呈現)
        │
        ▼
┌──────────────────────────────────────────┐
│        週期性分析模組                     │
│                                          │
│  市場環境分類器  ←→  邊緣衰減偵測器       │
│  人為干預追蹤器  ←→  基準比較器           │
│  策略版本管理器  ←→  穩定度評分器         │
│  過度擬合防護    ←→  自動暫停邏輯         │
└──────────────────────────────────────────┘
```

---

### 12.2 三層覆盤架構

#### Layer 1：規則遵守度（每日自動）

**目的**：確認系統有沒有按照策略規則執行，與交易員行為無關。

```python
# src/review/layer1_compliance.py

from dataclasses import dataclass, field
from typing import Optional
from datetime import date


@dataclass
class ComplianceViolation:
    rule: str
    expected: str
    actual: str
    severity: str          # "CRITICAL" | "WARNING" | "INFO"


@dataclass
class ComplianceReport:
    trade_date: date
    passed: bool
    violations: list[ComplianceViolation] = field(default_factory=list)
    score: float = 100.0   # 100 = 完全符合，每個 CRITICAL -30，WARNING -10


class RuleComplianceChecker:
    """
    Layer 1：規則遵守度自動檢查。

    檢查項目：
    1. 訊號觸發條件是否符合參數設定
    2. 進場時間是否在允許窗口內（09:00–09:30）
    3. 停損線是否按進場價正確設定
    4. 倉位大小是否在允許範圍內
    5. BEAR 環境是否有不應該有的進場
    6. 任何人為干預是否有記錄
    """

    def check(self, trade: dict, signal: dict, config: dict) -> ComplianceReport:
        violations = []

        # 規則 1：訊號門檻
        nasdaq_chg = abs(signal.get("nasdaq_change_pct", 0))
        threshold = config.get("US_SIGNAL_THRESHOLD", 1.5)
        if nasdaq_chg < threshold:
            violations.append(ComplianceViolation(
                rule="訊號門檻",
                expected=f"NASDAQ 變動 ≥ {threshold}%",
                actual=f"NASDAQ 變動 = {nasdaq_chg:.2f}%",
                severity="CRITICAL"
            ))

        # 規則 2：進場時間窗口
        entry_time = trade.get("entry_time")
        if entry_time and not (
            entry_time.hour == 9 and entry_time.minute <= 30
        ):
            violations.append(ComplianceViolation(
                rule="進場時間窗口",
                expected="09:00–09:30",
                actual=entry_time.strftime("%H:%M"),
                severity="WARNING"
            ))

        # 規則 3：停損設定
        entry_price = trade.get("entry_price", 0)
        stop_loss = trade.get("stop_loss_price", 0)
        expected_stop = entry_price * (1 - config.get("INDEX_STOP_LOSS_PCT", 0.12))
        if stop_loss and abs(stop_loss - expected_stop) > entry_price * 0.005:
            violations.append(ComplianceViolation(
                rule="停損設定",
                expected=f"{expected_stop:.2f}",
                actual=f"{stop_loss:.2f}",
                severity="CRITICAL"
            ))

        # 規則 4：趨勢環境
        trend_state = signal.get("trend_state")
        if trend_state == "BEAR" and trade.get("direction") == "BUY":
            violations.append(ComplianceViolation(
                rule="趨勢過濾",
                expected="BEAR 環境不得做多",
                actual="BEAR 環境執行 BUY",
                severity="CRITICAL"
            ))

        score = 100.0
        for v in violations:
            score -= 30 if v.severity == "CRITICAL" else 10
        score = max(0.0, score)

        return ComplianceReport(
            trade_date=date.today(),
            passed=score >= 70,
            violations=violations,
            score=score
        )
```

#### Layer 2：訊號品質分析（每日自動）

**目的**：事後評估訊號的「預測力」，找出訊號強但結果差的系統性原因。

```python
# src/review/layer2_signal_quality.py

from dataclasses import dataclass
from datetime import date


@dataclass
class SignalQualityReport:
    trade_date: date

    # 訊號強度
    signal_confidence: float
    nasdaq_change_pct: float
    sox_change_pct: float

    # 市場實際反應
    taiwan_open_change_pct: float      # 台股開盤漲跌
    taiwan_close_change_pct: float     # 台股收盤漲跌
    tracking_error_pct: float          # 台股 vs 美股方向偏差

    # 結果
    trade_pnl_pct: float
    signal_was_correct: bool           # 方向預測對了嗎
    tracking_failure_reason: Optional[str]  # 若方向錯誤，可能原因

    # 品質分數（0–100）
    quality_score: float


def analyze_signal_quality(
    signal: dict,
    market_data: dict,
    trade: dict
) -> SignalQualityReport:
    """
    分析今日訊號品質。

    tracking_failure_reason 的常見原因：
    - "外資大量賣超"：外資動向蓋過美股訊號
    - "匯率大幅波動"：台幣升值抵消出口股獲利預期
    - "本土利空事件"：地緣政治、個別公司事件
    - "過度反應後回撤"：開盤跳漲後反轉，訊號本身正確但時機問題
    """
    nasdaq_dir = 1 if signal["nasdaq_change_pct"] > 0 else -1
    taiwan_dir = 1 if market_data["taiwan_open_change_pct"] > 0 else -1

    signal_was_correct = nasdaq_dir == taiwan_dir
    tracking_error = abs(
        signal["nasdaq_change_pct"] - market_data["taiwan_open_change_pct"]
    )

    # 品質分數邏輯：方向正確 +60，tracking error 越小越高分
    quality_score = 60.0 if signal_was_correct else 20.0
    quality_score += max(0, 40 - tracking_error * 10)

    return SignalQualityReport(
        trade_date=date.today(),
        signal_confidence=signal["confidence"],
        nasdaq_change_pct=signal["nasdaq_change_pct"],
        sox_change_pct=signal["sox_change_pct"],
        taiwan_open_change_pct=market_data["taiwan_open_change_pct"],
        taiwan_close_change_pct=market_data["taiwan_close_change_pct"],
        tracking_error_pct=tracking_error,
        trade_pnl_pct=trade["pnl_pct"],
        signal_was_correct=signal_was_correct,
        tracking_failure_reason=None if signal_was_correct else "待人工標記或 AI 分析",
        quality_score=quality_score
    )
```

#### Layer 3：AI 質化分析（每日，Claude API）

**目的**：產生有脈絡的自然語言分析，讓人看一眼就理解今天發生了什麼。

```python
# src/review/layer3_ai_analysis.py

import httpx
import json
from datetime import date


AI_REVIEW_SYSTEM_PROMPT = """
你是一位量化交易系統的覆盤分析師。
你的工作是分析每日交易數據，提供有建設性的覆盤報告。

分析原則：
1. 只根據提供的數據，不要假設額外資訊
2. 區分「策略問題」和「市場環境問題」
3. 改進建議必須有數據支撐，不接受「感覺」
4. 如果樣本數不足（< 30 筆），明確說明無法下結論
5. 輸出使用繁體中文，語氣專業但不誇張
"""


async def run_ai_review(
    compliance: dict,
    signal_quality: dict,
    trade: dict,
    rolling_stats: dict,
    market_context: dict
) -> str:
    """
    呼叫 Claude API 進行 AI 覆盤分析。
    """
    prompt = f"""
請分析以下今日（{date.today()}）交易覆盤數據：

【Layer 1 規則遵守度】
合規分數：{compliance['score']}/100
違規項目：{json.dumps(compliance['violations'], ensure_ascii=False, indent=2)}

【Layer 2 訊號品質】
美股訊號：NASDAQ {signal_quality['nasdaq_change_pct']:+.2f}%、SOX {signal_quality['sox_change_pct']:+.2f}%
台股反應：開盤 {signal_quality['taiwan_open_change_pct']:+.2f}%、收盤 {signal_quality['taiwan_close_change_pct']:+.2f}%
訊號方向正確：{signal_quality['signal_was_correct']}
今日損益：{trade['pnl_pct']:+.2f}%
訊號品質分數：{signal_quality['quality_score']:.0f}/100

【滾動統計（近 30 天）】
勝率：{rolling_stats['win_rate_30d']:.1%}
Sharpe Ratio：{rolling_stats['sharpe_30d']:.2f}
平均滑價：{rolling_stats['avg_slippage_pct']:.3f}%
vs 基準（0050 買入持有）：{rolling_stats['vs_benchmark_pct']:+.2f}%

【市場背景】
{market_context.get('summary', '無額外市場背景資訊')}

請提供：
1. **今日交易總結**（2–3 句，說明今天發生了什麼）
2. **訊號評估**（這個訊號在事後看起來是好訊號嗎？為什麼？）
3. **需要關注的問題**（如有，否則說明無問題）
4. **改進建議**（若有數據支撐，否則說明樣本不足）
5. **明日注意事項**（基於今日數據）

格式：使用 Markdown，每個區塊清楚標示。
"""

    response = await httpx.AsyncClient().post(
        "https://api.anthropic.com/v1/messages",
        headers={"Content-Type": "application/json"},
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 1000,
            "system": AI_REVIEW_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}]
        },
        timeout=30.0
    )
    data = response.json()
    return data["content"][0]["text"]
```

---

### 12.3 策略版本管理

#### 版本生命週期

```
策略修改前
    │
    ▼
建立新版本記錄（含修改原因、支持數據）
    │
    ▼
啟動 A/B 影子測試（新版本 Paper Mode 並行跑）
    │ 最少 2 週 / 最少 20 個訊號機會
    ▼
影子測試通過評估標準？
    ├── YES → 切換至新版本（舊版本歸檔）
    └── NO  → 放棄修改，恢復原版本記錄原因
```

#### 版本資料庫設計

```python
# 新增至 src/database/models.py

class StrategyVersion(Base):
    """策略版本記錄。"""
    __tablename__ = "strategy_versions"

    id = Column(Integer, primary_key=True)
    version   = Column(String(20), nullable=False)       # e.g. "v1.0.0"
    status    = Column(String(20), nullable=False)
    # "active"（運行中）| "shadow"（影子測試）|
    # "archived"（已歸檔）| "rollback"（回滾目標）

    # 策略參數快照
    parameters = Column(JSON, nullable=False)
    # {
    #   "us_signal_threshold": 1.5,
    #   "ma_period": 200,
    #   "stop_loss_pct": 0.12,
    #   "trailing_stop_pct": 0.15,
    #   "min_confidence": 0.6
    # }

    # 變更記錄（強制填寫）
    change_reason          = Column(String(500), nullable=False)
    supporting_data        = Column(JSON)     # 支持此次變更的統計數據
    expected_improvement   = Column(String(200))
    actual_improvement     = Column(String(200))  # 事後填寫

    activated_at    = Column(DateTime)
    deactivated_at  = Column(DateTime)
    created_by      = Column(String(50), default="system")
    created_at      = Column(DateTime, default=datetime.utcnow)


class ShadowTestResult(Base):
    """A/B 影子測試結果。"""
    __tablename__ = "shadow_test_results"

    id              = Column(Integer, primary_key=True)
    new_version_id  = Column(Integer, ForeignKey("strategy_versions.id"))
    base_version_id = Column(Integer, ForeignKey("strategy_versions.id"))
    test_date       = Column(DateTime, nullable=False)

    # 當日模擬結果對比
    new_version_signal  = Column(String(10))   # BUY/SELL/HOLD
    base_version_signal = Column(String(10))
    new_version_pnl_pct = Column(Numeric(8, 4))
    base_version_pnl_pct = Column(Numeric(8, 4))

    # 影子測試結論（測試期結束後填寫）
    decision = Column(String(20))  # "SWITCH" | "ABORT" | "EXTEND"
    decision_reason = Column(String(500))
```

#### 回滾指令

```python
# src/review/version_manager.py

class StrategyVersionManager:

    async def rollback(self, target_version: str, reason: str):
        """
        緊急回滾至指定版本。

        注意：回滾不是「刪除現版本」，而是：
        1. 將現版本標記為 "archived"
        2. 將目標版本重新啟動
        3. 記錄回滾原因和時間

        這樣未來可以分析「為什麼當時的修改是錯的」。
        """
        async with get_session() as session:
            # 停用現版本
            current = await session.execute(
                select(StrategyVersion)
                .where(StrategyVersion.status == "active")
            )
            current_ver = current.scalar_one()
            current_ver.status = "archived"
            current_ver.deactivated_at = datetime.utcnow()
            current_ver.actual_improvement = f"回滾：{reason}"

            # 啟用目標版本
            target = await session.execute(
                select(StrategyVersion)
                .where(StrategyVersion.version == target_version)
            )
            target_ver = target.scalar_one()
            target_ver.status = "active"
            target_ver.activated_at = datetime.utcnow()

            await session.commit()

        await self.alerter.send(
            f"⚠️ 策略已回滾至 {target_version}\n原因：{reason}",
            level=AlertLevel.WARNING
        )
```

---

### 12.4 市場環境分類器

**目的**：標記每筆交易發生時的市場環境，讓你知道策略在哪種環境下有效。

```python
# src/review/market_regime.py

from enum import Enum


class MarketRegime(str, Enum):
    BULL_LOW_VOL   = "多頭低波動"    # 穩定上漲，最理想
    BULL_HIGH_VOL  = "多頭高波動"    # 上漲但震盪，需謹慎
    CHOPPY         = "震盪整理"      # 無趨勢，策略最不適合
    BEAR_EARLY     = "初期空頭"      # 開始下跌，200MA 剛跌破
    BEAR_DEEP      = "深度空頭"      # 持續下跌，全面迴避


def classify_regime(
    nasdaq_ma50: float, nasdaq_ma200: float,
    vix: float, nasdaq_30d_range_pct: float
) -> MarketRegime:
    """
    根據技術指標分類當前市場環境。

    VIX 低（< 18）= 低波動
    VIX 高（> 25）= 高波動
    30 日波幅 > 20% = 震盪
    """
    is_bull = nasdaq_ma50 > nasdaq_ma200
    is_low_vol = vix < 18
    is_choppy = nasdaq_30d_range_pct > 20

    if not is_bull:
        return MarketRegime.BEAR_DEEP if vix > 30 else MarketRegime.BEAR_EARLY
    if is_choppy:
        return MarketRegime.CHOPPY
    return MarketRegime.BULL_LOW_VOL if is_low_vol else MarketRegime.BULL_HIGH_VOL
```

**回顧分析**（每月自動）：

```
市場環境         | 訊號次數 | 勝率  | 平均損益
─────────────────|---------|------|─────────
多頭低波動        |   18    | 72%  | +0.8%   ← 最適合
多頭高波動        |    9    | 56%  | +0.2%   ← 可操作
震盪整理          |    5    | 40%  | -0.6%   ← 考慮迴避
```

---

### 12.5 人為干預追蹤器

**核心原則**：人的干預必須被記錄並量化評估，不能「憑感覺覺得自己做對了」。

```python
# src/review/override_tracker.py

class OverrideType(str, Enum):
    SKIP_SIGNAL     = "跳過系統訊號"      # 系統說買，人工不買
    EARLY_EXIT      = "提前出場"           # 停利/停損前手動出場
    DELAYED_EXIT    = "延遲出場"           # 系統說賣，人工繼續持有
    SIZE_CHANGE     = "更改倉位大小"
    MANUAL_ENTRY    = "手動進場（無訊號）"


class OverrideTracker:

    async def log_override(
        self,
        override_type: OverrideType,
        reason: str,
        system_recommendation: dict,
        actual_action: dict
    ) -> int:
        """記錄每次人為干預，事後系統自動填寫反事實結果。"""
        async with get_session() as session:
            override = ManualOverride(
                override_type=override_type.value,
                reason=reason,
                system_recommendation=system_recommendation,
                actual_action=actual_action,
                override_at=datetime.utcnow()
            )
            session.add(override)
            await session.commit()
            return override.id

    async def evaluate_override(self, override_id: int):
        """
        事後評估：如果沒有干預，結果會是什麼？
        填寫 counterfactual_pnl_pct。
        """
        # 對比 actual_pnl vs 若遵循系統建議的 theoretical_pnl
        pass

    async def monthly_override_report(self) -> dict:
        """
        月度干預報告：
        - 干預總次數
        - 干預幫助了多少次 vs 傷害了多少次
        - 累積干預損益 vs 若完全遵循系統的損益差
        """
        pass
```

---

### 12.6 基準比較器

```python
# src/review/benchmark.py

class BenchmarkComparator:
    """
    每月比較策略 vs 買入持有 0050 的表現。

    重要：比較必須在相同的資金、時間段、且扣除所有成本後進行。
    """

    async def monthly_comparison(
        self,
        strategy_equity_curve: pd.Series,
        benchmark_symbol: str = "0050.TW",
        initial_capital: float = 1_000_000
    ) -> dict:

        benchmark_data = await fetch_price(benchmark_symbol)
        bm_return = (
            benchmark_data["close"].iloc[-1] / benchmark_data["close"].iloc[0] - 1
        ) * 100

        strategy_return = (
            strategy_equity_curve.iloc[-1] / initial_capital - 1
        ) * 100

        excess_return = strategy_return - bm_return

        return {
            "strategy_return_pct":  round(strategy_return, 2),
            "benchmark_return_pct": round(bm_return, 2),
            "excess_return_pct":    round(excess_return, 2),
            "verdict": (
                "✅ 策略跑贏基準" if excess_return > 3
                else "⚠️ 策略接近基準，考量成本與時間後需評估是否值得"
                if excess_return > 0
                else "❌ 策略跑輸基準，須重新檢視策略根本邏輯"
            )
        }
```

---

### 12.7 優勢衰減偵測器

```python
# src/review/edge_decay.py

DECAY_THRESHOLDS = {
    "win_rate_rolling_30d":   0.45,   # 30 日勝率低於 45% → 警告
    "sharpe_rolling_60d":     0.50,   # 60 日 Sharpe 低於 0.5 → 警告
    "profit_factor_rolling":  1.10,   # 獲利因子低於 1.1 → 警告
    "consecutive_loss_days":  3,      # 連續 3 天虧損 → 自動暫停
}


class EdgeDecayDetector:

    async def check(self, rolling_stats: dict) -> list[str]:
        alerts = []

        if rolling_stats["win_rate_30d"] < DECAY_THRESHOLDS["win_rate_rolling_30d"]:
            alerts.append(
                f"⚠️ 30日勝率 {rolling_stats['win_rate_30d']:.1%} 低於門檻 45%"
            )

        if rolling_stats["sharpe_60d"] < DECAY_THRESHOLDS["sharpe_rolling_60d"]:
            alerts.append(
                f"⚠️ 60日 Sharpe {rolling_stats['sharpe_60d']:.2f} 低於門檻 0.5"
            )

        if rolling_stats["consecutive_loss_days"] >= DECAY_THRESHOLDS["consecutive_loss_days"]:
            alerts.append(
                f"🚨 連續 {rolling_stats['consecutive_loss_days']} 天虧損，觸發自動暫停"
            )
            await self._trigger_auto_pause(
                reason=f"連續 {rolling_stats['consecutive_loss_days']} 天虧損"
            )

        return alerts

    async def _trigger_auto_pause(self, reason: str):
        """切換至觀察模式：系統繼續生成訊號但不執行下單。"""
        await update_config("TRADING_MODE", "observe")
        await self.alerter.send(
            f"🚨 系統已自動切換至觀察模式\n原因：{reason}\n"
            f"請人工複核後執行 `fly secrets set TRADING_MODE=paper` 恢復",
            level=AlertLevel.CRITICAL
        )
```

---

### 12.8 過度擬合防護

**核心規則**：修改策略參數前必須通過以下三個檢查。

```python
# src/review/overfit_guard.py

class OverfitGuard:
    """
    防止根據近期表現過度調整策略參數。

    三道防線：
    1. 樣本數門檻：變更前須有至少 30 筆交易數據
    2. 時間窗口驗證：新參數必須在「問題期之前」的數據上也表現良好
    3. 外樣本測試：新參數在「未曾見過的時間段」上測試
    """

    MIN_TRADES_BEFORE_CHANGE = 30

    def validate_parameter_change(
        self,
        param_name: str,
        old_value: float,
        new_value: float,
        trade_history: pd.DataFrame,
        change_reason: str
    ) -> dict:

        result = {
            "approved": False,
            "warnings": [],
            "required_actions": []
        }

        # 防線 1：樣本數
        n_trades = len(trade_history)
        if n_trades < self.MIN_TRADES_BEFORE_CHANGE:
            result["warnings"].append(
                f"⛔ 樣本數不足：現有 {n_trades} 筆，需至少 {self.MIN_TRADES_BEFORE_CHANGE} 筆才能調整參數"
            )
            return result

        # 防線 2：問題期前後分析
        # 找出「問題期」（近 N 筆虧損集中的時段）
        # 驗證新參數在問題期之前的表現
        result["required_actions"].append(
            "執行時間窗口驗證：用新參數回測「問題期之前」的數據"
        )

        # 防線 3：外樣本測試
        result["required_actions"].append(
            "執行外樣本測試：使用 2015–2019 數據（策略設計期未使用的樣本）"
        )

        result["approved"] = len(result["warnings"]) == 0
        return result
```

---

### 12.9 穩定度評分與自動解鎖

**「穩定」的量化定義**（三條件同時達成才算穩定）：

```python
# src/review/stability_scorer.py

STABILITY_CRITERIA = {
    "sharpe_3m":          {"threshold": 1.0,  "description": "3個月 Sharpe Ratio > 1.0"},
    "win_rate_20trades":  {"threshold": 0.55, "description": "近 20 筆勝率 > 55%"},
    "max_drawdown_3m":    {"threshold": -0.10,"description": "3個月最大回撤 < -10%"},
    "vs_benchmark_3m":    {"threshold": 0.03, "description": "3個月超越基準 > +3%"},
}

# AI 分析頻率根據穩定度自動調整
AI_REVIEW_FREQUENCY = {
    "unstable":  "daily",     # 每日：初期 / 策略剛修改後 / 連續虧損後
    "stable":    "weekly",    # 每週：三個條件全部達成後
    "excellent": "biweekly",  # 雙週：Sharpe > 1.5 且連續 6 個月穩定
}
```

---

### 12.10 稅後損益計算

```python
# src/review/tax_calculator.py

# 台灣稅率（2026）
TAX_RATES = {
    "stock_transaction_tax":  0.003,   # 證券交易稅 0.3%（賣方）
    "futures_transaction_tax": 0.00002, # 期貨交易稅 0.002%（每口）
    "broker_commission_rate":  0.001425,# 手續費上限 0.1425%（可折扣）
    "capital_gains_tax":       0.0,    # 台灣目前股票資本利得免稅
}


def calculate_after_tax_pnl(
    gross_pnl: float,
    instrument: str,       # "stock" | "futures"
    transaction_value: float,
    commission_discount: float = 0.6   # 通常可折扣 6 折
) -> dict:
    """
    計算稅後淨損益。

    覆盤必須使用稅後數字，否則盈利能力被高估。
    """
    if instrument == "stock":
        tax = transaction_value * TAX_RATES["stock_transaction_tax"]
        commission = transaction_value * TAX_RATES["broker_commission_rate"] * commission_discount * 2  # 買賣各一次
    else:
        tax = TAX_RATES["futures_transaction_tax"] * transaction_value
        commission = 80 * 2    # 期貨手續費約 NT$80/口（買賣）

    total_cost = tax + commission
    net_pnl = gross_pnl - total_cost

    return {
        "gross_pnl":    round(gross_pnl, 2),
        "tax":          round(tax, 2),
        "commission":   round(commission, 2),
        "total_cost":   round(total_cost, 2),
        "net_pnl":      round(net_pnl, 2),
        "cost_drag_pct": round(total_cost / transaction_value * 100, 4)
    }
```

---

### 12.11 覆盤排程整合

```python
# src/tasks.py（新增覆盤相關 Celery 任務）

@celery_app.task
def run_daily_review():
    """每日 13:40 台股收盤後執行。"""
    # 1. 收集今日所有交易
    # 2. Layer 1 合規檢查
    # 3. Layer 2 訊號品質分析
    # 4. Layer 3 AI 分析（呼叫 Claude API）
    # 5. 計算稅後損益
    # 6. 更新滾動統計
    # 7. 執行優勢衰減偵測
    # 8. 儲存報告至 Supabase
    # 9. 推送 Telegram 摘要


@celery_app.task
def run_weekly_review():
    """每週五 14:00 執行。"""
    # 週度績效統計
    # 市場環境分類回顧
    # 人為干預追蹤彙整
    # 基準比較更新


@celery_app.task
def run_monthly_review():
    """每月最後一個交易日 22:00 執行。"""
    # 重跑當月回測，比對實際 vs 理論差距
    # 穩定度評分計算
    # AI 分析頻率自動調整
    # 策略優化建議彙整報告
```

### 12.12 新增資料表

```sql
-- 覆盤報告
CREATE TABLE review_reports (
    id              SERIAL PRIMARY KEY,
    review_date     DATE NOT NULL UNIQUE,
    review_type     VARCHAR(20) NOT NULL,  -- daily / weekly / monthly
    compliance_score    NUMERIC(5,2),
    signal_quality_score NUMERIC(5,2),
    ai_analysis     TEXT,
    net_pnl         NUMERIC(12,4),
    tax_cost        NUMERIC(10,4),
    stability_score NUMERIC(5,2),
    market_regime   VARCHAR(30),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 人為干預追蹤
CREATE TABLE manual_overrides (
    id                  SERIAL PRIMARY KEY,
    override_type       VARCHAR(50) NOT NULL,
    reason              TEXT NOT NULL,
    system_recommendation JSONB,
    actual_action       JSONB,
    actual_pnl_pct      NUMERIC(8,4),
    counterfactual_pnl_pct NUMERIC(8,4),  -- 若未干預的理論損益
    helped              BOOLEAN,           -- 干預有沒有幫助
    override_at         TIMESTAMPTZ NOT NULL
);

-- 優勢衰減紀錄
CREATE TABLE edge_decay_alerts (
    id          SERIAL PRIMARY KEY,
    alert_date  DATE NOT NULL,
    metric      VARCHAR(50) NOT NULL,
    value       NUMERIC(8,4),
    threshold   NUMERIC(8,4),
    action_taken VARCHAR(100),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 13. Multi-Agent 選股系統

> **開發時機：** 第一階段量化執行系統穩定運行（達到穩定度評分標準，§12.9）後開始建置。
> 第一階段已累積真實交易紀錄，才能有效驗證選股 Agent 的品質。

### 13.1 系統定位與分工

```
┌─────────────────────────────────────────────────────┐
│         第二階段：Multi-Agent 選股系統               │
│    「買什麼」— 每週產出候選名單                      │
│                                                     │
│  基本面 → 催化劑 → 供應鏈 → 技術面 → 整合           │
└─────────────────────┬───────────────────────────────┘
                      │ 候選名單 (JSON Watchlist)
                      ▼
┌─────────────────────────────────────────────────────┐
│         第一階段：量化執行系統                       │
│    「何時買賣」— 每日監控 Watchlist 進出場訊號        │
│                                                     │
│  S1×S2×S3 → 風控 → 下單 → 覆盤                     │
└─────────────────────────────────────────────────────┘
```

**兩個系統的關係**：選股系統決定「監控哪些股票」，執行系統決定「什麼時候動手」。選股 Agent 不產生下單訊號，只產生 Watchlist；下單決策完全由第一階段的量化規則負責。

---

### 13.2 第一階段末期可提前加入的兩個 Agent

這兩個 Agent 輔助現有執行系統，不影響交易邏輯，**建議在第一階段後期（策略穩定但尚未進入第二階段）加入**。

#### 13.2.1 Market Context Agent

**觸發時間**：每日凌晨 04:05（美股收盤後）  
**目的**：解讀美股「為什麼漲跌」，補充訊號背景，提升覆盤報告的脈絡深度。

```python
# src/agents/market_context_agent.py

import httpx
import json
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

MARKET_CONTEXT_SYSTEM = """
你是一位台灣股市的市場分析師，專精於解讀美股動向對台灣科技股的影響。
請根據提供的數據，分析今日市場背景。
只根據提供的數據，不要推測額外資訊。
回覆必須是合法的 JSON，不包含任何其他文字。
"""


async def run_market_context_agent(
    nasdaq_change_pct: float,
    sp500_change_pct: float,
    sox_change_pct: float,
    news_headlines: list[str]
) -> dict:
    """
    解讀美股收盤的背景脈絡。

    Returns:
        {
            "market_driver": "主要驅動力說明",
            "taiwan_relevance": "HIGH" | "MEDIUM" | "LOW",
            "relevance_reason": "與台灣市場的關聯說明",
            "confidence_modifier": float,   # -0.20 ~ +0.20，調整 S2 訊號信心度
            "key_risks": ["風險1", "風險2"],
            "context_summary": "一句話總結"
        }
    """
    prompt = f"""
今日美股收盤數據（台灣時間 {datetime.now().strftime('%Y-%m-%d')} 凌晨）：
- NASDAQ: {nasdaq_change_pct:+.2f}%
- S&P 500: {sp500_change_pct:+.2f}%
- 費城半導體指數 SOX: {sox_change_pct:+.2f}%

今日重大新聞（前 10 則）：
{chr(10).join([f'{i+1}. {h}' for i, h in enumerate(news_headlines[:10])])}

請分析：
1. 今日市場的主要驅動力（技術面、基本面、宏觀事件）
2. 這個驅動力與台灣半導體 / 科技股的關聯度
3. 信心度修正值（正值代表台股跟進機率更高，負值代表更低）
4. 主要風險因素

JSON 回覆格式：
{{
    "market_driver": "string",
    "taiwan_relevance": "HIGH|MEDIUM|LOW",
    "relevance_reason": "string",
    "confidence_modifier": float,
    "key_risks": ["string"],
    "context_summary": "string"
}}
"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 600,
                "system": MARKET_CONTEXT_SYSTEM,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30.0
        )
    data = resp.json()
    raw = data["content"][0]["text"].strip()

    try:
        result = json.loads(raw)
        # 限制 confidence_modifier 範圍
        result["confidence_modifier"] = max(-0.20, min(0.20, result.get("confidence_modifier", 0)))
        return result
    except json.JSONDecodeError:
        logger.error(f"Market Context Agent 回傳非 JSON 格式：{raw}")
        return {
            "market_driver": "解析失敗",
            "taiwan_relevance": "MEDIUM",
            "relevance_reason": "Agent 輸出格式錯誤，使用預設值",
            "confidence_modifier": 0.0,
            "key_risks": [],
            "context_summary": "無法解析"
        }
```

#### 13.2.2 黑天鵝偵測 Agent

**觸發時間**：台股交易時段每 5 分鐘（09:00–13:30），以及每日凌晨 04:05  
**目的**：偵測策略假設失效的極端市場情境，觸發強制人工複核。

```python
# src/agents/black_swan_agent.py

from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class BlackSwanSeverity(str, Enum):
    NONE     = "NONE"      # 正常，繼續執行
    WATCH    = "WATCH"     # 觀察，記錄但不干預
    ALERT    = "ALERT"     # 警告，推送 Telegram 通知
    CRITICAL = "CRITICAL"  # 嚴重，系統切換至觀察模式，要求人工確認


@dataclass
class BlackSwanSignal:
    severity: BlackSwanSeverity
    triggers: list[str]         # 觸發哪些指標
    recommended_action: str


# 量化觸發條件（不依賴 LLM，快速且確定性）
QUANTITATIVE_TRIGGERS = {
    "vix_critical":          ("VIX > 40", lambda vix: vix > 40),
    "vix_alert":             ("VIX > 30", lambda vix: vix > 30),
    "nasdaq_crash":          ("NASDAQ 單日跌幅 > -5%", lambda chg: chg < -5.0),
    "nasdaq_surge_abnormal": ("NASDAQ 單日漲幅 > +5%", lambda chg: chg > 5.0),
    "sox_diverge":           ("SOX 與 NASDAQ 背離 > 3%", lambda diff: abs(diff) > 3.0),
}

# 新聞關鍵字觸發（LLM 輔助判斷）
CRITICAL_KEYWORDS = [
    "war", "invasion", "nuclear", "戰爭", "入侵", "核武",
    "trading halt", "circuit breaker", "熔斷", "交易暫停",
    "bank run", "financial crisis", "台海", "封鎖"
]


def detect_black_swan(
    vix: float,
    nasdaq_change_pct: float,
    sox_change_pct: float,
    news_headlines: list[str]
) -> BlackSwanSignal:
    """
    黑天鵝偵測（量化層，不呼叫 LLM，確保即時性）。
    嚴重情況再由覆盤 AI 進行後續分析。
    """
    triggers = []
    max_severity = BlackSwanSeverity.NONE

    # 量化指標檢查
    if vix > 40:
        triggers.append(f"VIX = {vix:.1f}（超過 40，極度恐慌）")
        max_severity = BlackSwanSeverity.CRITICAL
    elif vix > 30:
        triggers.append(f"VIX = {vix:.1f}（超過 30，高度恐慌）")
        max_severity = BlackSwanSeverity.ALERT

    if nasdaq_change_pct < -5.0:
        triggers.append(f"NASDAQ 單日暴跌 {nasdaq_change_pct:.1f}%")
        max_severity = BlackSwanSeverity.CRITICAL

    sox_diff = sox_change_pct - nasdaq_change_pct
    if abs(sox_diff) > 3.0:
        triggers.append(f"SOX 與 NASDAQ 出現 {sox_diff:+.1f}% 異常背離")
        if max_severity == BlackSwanSeverity.NONE:
            max_severity = BlackSwanSeverity.WATCH

    # 新聞關鍵字掃描（輕量級字串比對）
    all_news = " ".join(news_headlines).lower()
    hit_keywords = [kw for kw in CRITICAL_KEYWORDS if kw.lower() in all_news]
    if hit_keywords:
        triggers.append(f"新聞出現高風險關鍵字：{', '.join(hit_keywords)}")
        if max_severity.value < BlackSwanSeverity.ALERT.value:
            max_severity = BlackSwanSeverity.ALERT

    # 建議動作
    action_map = {
        BlackSwanSeverity.NONE:     "系統正常運作",
        BlackSwanSeverity.WATCH:    "記錄異常，持續監控",
        BlackSwanSeverity.ALERT:    "推送 Telegram 警告，人工確認後繼續",
        BlackSwanSeverity.CRITICAL: "系統自動切換至觀察模式，停止新開倉，等待人工確認",
    }

    return BlackSwanSignal(
        severity=max_severity,
        triggers=triggers,
        recommended_action=action_map[max_severity]
    )
```

---

### 13.3 選股 Agent 鏈

#### 13.3.1 觸發條件與運行頻率

```
觸發條件（任一滿足即運行）：
  ① 每週日 20:00 定期掃描（固定排程）
  ② 財報季期間，重點追蹤公司財報發布後 2 小時內
  ③ 重大市場事件後（如 Fed 聲明、重大供應鏈新聞）

掃描範圍（可設定）：
  - 台股：台灣50成分股 + 自選清單
  - 美股：NASDAQ 100 中與台灣供應鏈高度相關標的
  - 每次最多掃描 20 支，每支約呼叫 4–5 次 Claude API

預估費用：每週 $1–3（claude-sonnet-4-6 定價）
```

#### 13.3.2 基本面 Agent

```python
# src/agents/stock_selection/fundamental_agent.py

async def run_fundamental_agent(
    symbol: str,
    financial_data: dict     # 從 TIKR / Supabase 拉取的財務數據
) -> dict:
    """
    回答選股三問的前兩問：護城河 + 成長性。

    financial_data 結構：
    {
        "revenue_growth_yoy": [Q1, Q2, Q3, Q4],   # 近四季 YoY 成長率
        "gross_margin_trend": [Q1, Q2, Q3, Q4],
        "free_cash_flow":     [Q1, Q2, Q3, Q4],
        "guidance_vs_consensus": float,             # 正值 = 超過市場預期
        "debt_to_equity": float,
        "pe_ratio": float,
        "peg_ratio": float
    }
    """
    prompt = f"""
分析 {symbol} 的基本面，回答以下三個問題：

財務數據：
{json.dumps(financial_data, ensure_ascii=False, indent=2)}

問題：
1. 護城河：這家公司有什麼難以被複製的競爭優勢？（根據數據推斷）
2. 成長性：營收和獲利成長趨勢是加速、穩定還是放緩？
3. 估值：目前 PE/PEG 相對歷史和同業是貴還是便宜？

JSON 回覆：
{{
    "moat_score": 0-100,
    "moat_description": "string",
    "growth_score": 0-100,
    "growth_trend": "accelerating|stable|decelerating",
    "valuation_score": 0-100,
    "valuation_comment": "string",
    "fundamental_score": 0-100,
    "key_strengths": ["string"],
    "key_concerns": ["string"],
    "pass": true|false
}}
"""
    return await _call_claude(prompt, max_tokens=600)
```

#### 13.3.3 催化劑 Agent

```python
# src/agents/stock_selection/catalyst_agent.py

async def run_catalyst_agent(
    symbol: str,
    earnings_transcript: str,      # 最近一次法說會逐字稿
    upcoming_events: list[dict]    # 未來 60 天重大事件
) -> dict:
    """
    分析近期催化劑：法說會語氣 + 未來 60 天觸發事件。

    核心價值：
    - 比較本次 vs 上次法說會的管理層用詞
    - 識別「悄悄降溫」或「意外樂觀」的微妙訊號
    - 量化未來催化劑的強度和時間
    """
    prompt = f"""
分析 {symbol} 的近期催化劑：

法說會重點摘要（最近一次）：
{earnings_transcript[:3000]}  # 控制 token 數

未來 60 天重大事件：
{json.dumps(upcoming_events, ensure_ascii=False)}

請分析：
1. 管理層對未來的展望是樂觀、中性還是謹慎？
2. 是否有具體的超預期 Guidance？
3. 未來 60 天最重要的催化劑事件是什麼？時間點？

JSON 回覆：
{{
    "management_tone": "bullish|neutral|cautious",
    "tone_vs_last_quarter": "improved|same|deteriorated",
    "guidance_beat": true|false,
    "guidance_detail": "string",
    "top_catalyst": {{"event": "string", "date": "YYYY-MM-DD", "impact": "high|medium|low"}},
    "catalyst_score": 0-100,
    "pass": true|false
}}
"""
    return await _call_claude(prompt, max_tokens=500)
```

#### 13.3.4 供應鏈 Agent

```python
# src/agents/stock_selection/supply_chain_agent.py

async def run_supply_chain_agent(
    symbol: str,
    tw_related_news: list[str],     # 台灣相關產業新聞（多語言翻譯後）
    customer_earnings_summaries: list[dict]  # 主要客戶的最新財報摘要
) -> dict:
    """
    台灣市場最獨特的 Agent：利用供應鏈關係找領先訊號。

    邏輯：
    客戶財報（NVDA/Apple/AMD）→ 推斷台灣供應商訂單 →
    在供應商財報公布之前，已經有參考依據

    同時處理跨語言訊號（日文/韓文/中文產業媒體）
    """
    prompt = f"""
分析 {symbol} 在全球供應鏈中的位置與近期訊號：

近期台灣相關供應鏈新聞：
{chr(10).join([f'- {n}' for n in tw_related_news[:8]])}

主要客戶近期財報摘要：
{json.dumps(customer_earnings_summaries, ensure_ascii=False, indent=2)}

請分析：
1. 這家公司在供應鏈中的角色（上游/中游/下游）
2. 客戶財報中是否有直接或間接對此公司有利/不利的訊號？
3. 目前是庫存去化階段還是補庫存階段？
4. 供應鏈訊號整體對此公司是正面還是負面？

JSON 回覆：
{{
    "supply_chain_role": "string",
    "customer_signal": "positive|neutral|negative",
    "customer_signal_reason": "string",
    "inventory_cycle": "destocking|neutral|restocking",
    "supply_chain_score": 0-100,
    "key_insight": "string",
    "pass": true|false
}}
"""
    return await _call_claude(prompt, max_tokens=500)
```

#### 13.3.5 技術面 Agent

```python
# src/agents/stock_selection/technical_agent.py

async def run_technical_agent(
    symbol: str,
    price_data: dict    # 含 MA、成交量、RS 等技術指標
) -> dict:
    """
    套用 Weinstein 四階段 + Minervini 趨勢模板，
    確認基本面好的股票同時有技術面支撐。

    純量化計算為主，LLM 只做最終解讀。
    """
    # 量化計算（不依賴 LLM）
    weinstein_stage = _calculate_weinstein_stage(price_data)
    minervini_pass  = _check_minervini_template(price_data)
    rs_rating       = _calculate_rs_rating(price_data)
    volume_pattern  = _check_volume_pattern(price_data)

    # 若量化已明確不通過，直接回傳，不呼叫 LLM
    if weinstein_stage in [1, 3, 4] or not minervini_pass:
        return {
            "weinstein_stage": weinstein_stage,
            "minervini_pass": minervini_pass,
            "rs_rating": rs_rating,
            "technical_score": 20,
            "entry_readiness": "NOT_READY",
            "reason": f"Weinstein Stage {weinstein_stage}，不符合進場條件",
            "pass": False
        }

    # Stage 2 且 Minervini 通過，才進 LLM 做細部判斷
    prompt = f"""
{symbol} 技術指標：
- Weinstein Stage: {weinstein_stage}（Stage 2 = 上升趨勢）
- Minervini 趨勢模板：通過
- RS Rating: {rs_rating}（高於 {rs_rating} 百分比的股票）
- 成交量形態：{volume_pattern}
- 距離 52 週高點：{price_data['distance_from_52w_high_pct']:.1f}%
- 距離 50 日均線：{price_data['distance_from_ma50_pct']:.1f}%

請評估：
1. 目前是突破前整理還是已突破延伸？
2. 進場風險報酬比是否合理（距離最近支撐 vs 預期目標）？
3. 技術面整體評分與進場時機建議

JSON 回覆：
{{
    "weinstein_stage": {weinstein_stage},
    "minervini_pass": true,
    "rs_rating": {rs_rating},
    "chart_pattern": "consolidating|breakout|extended",
    "technical_score": 0-100,
    "entry_readiness": "READY|WAIT|NOT_READY",
    "entry_condition": "string",
    "pass": true|false
}}
"""
    result = await _call_claude(prompt, max_tokens=400)
    result["weinstein_stage"] = weinstein_stage
    result["minervini_pass"]  = minervini_pass
    return result
```

#### 13.3.6 整合 Agent 與 Pipeline

```python
# src/agents/stock_selection/pipeline.py

import asyncio
from dataclasses import dataclass


@dataclass
class StockCandidate:
    symbol: str
    overall_score: float
    recommendation: str           # "ADD" | "WATCH" | "REJECT"
    fundamental:  dict
    catalyst:     dict
    supply_chain: dict
    technical:    dict
    thesis:       str             # 核心投資邏輯（AI 生成）
    risks:        list[str]
    entry_condition: str


async def run_stock_selection_pipeline(
    symbols: list[str],
    data_provider
) -> list[StockCandidate]:
    """
    對每支股票依序跑四個 Agent，整合後輸出排名候選名單。

    設計原則：任一 Agent pass=False 即提前終止（不浪費後續 API 呼叫）。
    """
    candidates = []

    for symbol in symbols:
        try:
            data = await data_provider.fetch_all(symbol)

            # Agent 1：基本面（必過才繼續）
            fundamental = await run_fundamental_agent(symbol, data["financial"])
            if not fundamental.get("pass"):
                continue

            # Agent 2：催化劑
            catalyst = await run_catalyst_agent(
                symbol, data["transcript"], data["events"]
            )
            if not catalyst.get("pass"):
                continue

            # Agent 3：供應鏈
            supply_chain = await run_supply_chain_agent(
                symbol, data["tw_news"], data["customer_earnings"]
            )
            if not supply_chain.get("pass"):
                continue

            # Agent 4：技術面（最後過濾）
            technical = await run_technical_agent(symbol, data["price"])
            if not technical.get("pass"):
                continue

            # 整合分數
            overall_score = (
                fundamental["fundamental_score"] * 0.35 +
                catalyst["catalyst_score"]        * 0.25 +
                supply_chain["supply_chain_score"] * 0.20 +
                technical["technical_score"]       * 0.20
            )

            # 整合 Agent：生成投資論點
            thesis_data = {
                "fundamental": fundamental,
                "catalyst": catalyst,
                "supply_chain": supply_chain,
                "technical": technical
            }
            thesis, risks, entry_condition = await _run_synthesis_agent(
                symbol, overall_score, thesis_data
            )

            candidates.append(StockCandidate(
                symbol=symbol,
                overall_score=overall_score,
                recommendation="ADD" if overall_score >= 75 else "WATCH",
                fundamental=fundamental,
                catalyst=catalyst,
                supply_chain=supply_chain,
                technical=technical,
                thesis=thesis,
                risks=risks,
                entry_condition=entry_condition
            ))

        except Exception as e:
            logger.error(f"{symbol} 分析失敗：{e}")
            continue

    # 依總分排序
    return sorted(candidates, key=lambda x: x.overall_score, reverse=True)


async def _run_synthesis_agent(
    symbol: str, score: float, agent_results: dict
) -> tuple[str, list[str], str]:
    """整合四個 Agent 的結果，生成核心投資論點。"""
    prompt = f"""
{symbol} 分析完成，整體分數 {score:.0f}/100：

{json.dumps(agent_results, ensure_ascii=False, indent=2)}

請生成：
1. 核心投資論點（2–3 句，說明為什麼值得關注）
2. 主要風險（2–3 點）
3. 進場條件（何時適合進場）

JSON：
{{
    "thesis": "string",
    "risks": ["string"],
    "entry_condition": "string"
}}
"""
    result = await _call_claude(prompt, max_tokens=400)
    return result["thesis"], result["risks"], result["entry_condition"]
```

---

### 13.4 輸出格式與執行系統整合

選股 Agent 鏈最終輸出存入 `watchlist` 表，執行系統每日訊號生成時同時監控 Watchlist 中的個股：

```json
[
  {
    "symbol": "2330.TW",
    "overall_score": 88,
    "recommendation": "ADD",
    "thesis": "台積電 CoWoS 先進封裝產能全線滿載，AI 晶片需求持續超越供給",
    "risks": ["美中出口管制升級", "客戶庫存調整"],
    "entry_condition": "等待量能突破 580 元壓力區",
    "fundamental_score": 91,
    "catalyst_score": 85,
    "supply_chain_score": 90,
    "technical_score": 82,
    "generated_at": "2026-06-22T20:05:00+08:00",
    "expires_at": "2026-06-29T20:00:00+08:00"
  }
]
```

---

### 13.5 新增資料表

```sql
-- 市場背景 Agent 結果（每日）
CREATE TABLE agent_market_contexts (
    id                  SERIAL PRIMARY KEY,
    context_date        DATE NOT NULL UNIQUE,
    market_driver       TEXT,
    taiwan_relevance    VARCHAR(10),
    relevance_reason    TEXT,
    confidence_modifier NUMERIC(4,3),
    key_risks           JSONB,
    context_summary     TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 黑天鵝偵測紀錄
CREATE TABLE black_swan_alerts (
    id              SERIAL PRIMARY KEY,
    detected_at     TIMESTAMPTZ NOT NULL,
    severity        VARCHAR(20) NOT NULL,
    triggers        JSONB,
    action_taken    VARCHAR(100),
    resolved_at     TIMESTAMPTZ,
    resolved_by     VARCHAR(50)
);

-- 選股候選名單
CREATE TABLE watchlist (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(20) NOT NULL,
    overall_score   NUMERIC(5,2),
    recommendation  VARCHAR(10),
    thesis          TEXT,
    risks           JSONB,
    entry_condition TEXT,
    agent_results   JSONB,        -- 四個 Agent 的完整輸出
    status          VARCHAR(20) DEFAULT 'active',  -- active / expired / executed
    generated_at    TIMESTAMPTZ NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Agent 執行紀錄（費用追蹤）
CREATE TABLE agent_run_logs (
    id              SERIAL PRIMARY KEY,
    run_type        VARCHAR(50) NOT NULL,  -- market_context / black_swan / stock_selection
    symbol          VARCHAR(20),
    tokens_used     INTEGER,
    cost_usd        NUMERIC(8,6),
    duration_ms     INTEGER,
    success         BOOLEAN,
    error_message   TEXT,
    run_at          TIMESTAMPTZ DEFAULT NOW()
);
```

---

### 13.6 第二階段驗證方式

**如何評估選股 Agent 的品質？**

第一階段結束後，你已有真實交易紀錄。第二階段開始時，先讓 Agent 跑 4 週的「紙上選股」（只選股不執行），再對比：

```
Agent 選出的候選名單 vs 同期大盤表現
├── 若候選名單平均跑贏大盤 > 3%  → Agent 有選股 Alpha，可信
├── 若候選名單表現與大盤相近      → Agent 選股無附加價值，重新評估
└── 若候選名單跑輸大盤             → Agent 邏輯有根本問題，暫緩使用
```

通過驗證後，才將 Watchlist 正式整合進執行系統的個股監控。

---

## 14. 文件異動紀錄

| 版本 | 日期 | 異動說明 | 異動者 |
|------|------|----------|--------|
| v1.0.0 | 2026-06-21 | 初始版本建立，涵蓋三大策略架構與核心模組 | — |
| v1.1.0 | 2026-06-21 | 架構決策：採用 Supabase + Vercel + Fly.io（東京）+ Upstash Redis 零成本起步方案 | — |
| v1.2.0 | 2026-06-21 | 新增 §12 覆盤與策略優化機制：三層覆盤、策略版本管理、市場環境分類、人為干預追蹤、優勢衰減偵測、過度擬合防護、穩定度評分、自動暫停邏輯 | — |
| v1.3.0 | 2026-06-21 | 新增 §13 Multi-Agent 選股系統（第二階段）：Market Context Agent、黑天鵝偵測 Agent、五層選股 Agent 鏈（基本面→催化劑→供應鏈→技術面→整合）、新增資料表、第二階段驗證方式；目錄重構為兩階段分期標示 | — |
| v1.4.0 | 2026-06-21 | 專案正式命名為 **ZeroHour**；更新文件標題、§1.1 專案背景說明 | — |
| v1.5.0 | 2026-07-05 | S1 判斷週期定案：由規格書原訂「月底收盤」改為「每日收盤 + 2%/2% 緩衝帶」，與生產環境實際行為對齊；移除從未真正接上決策流程的 `check_monthly_trend` 任務。決策依據為回測對照數據（見 §1 表格、§4.1、`docs/PROGRESS.md`） | Claude Sonnet 5 |

---

*本文件為系統開發規格，所有策略邏輯皆基於歷史資料分析，不構成投資建議。實際交易前請務必完整執行回測與模擬交易驗證。*
