from fastapi import APIRouter, HTTPException, Depends, UploadFile
from typing import Optional
import logging

from .schemas import (
    CurrentSignalsResponse,
    TrendSignalSchema,
    TimeDiffSignalSchema,
    CombinedSignalSchema,
    PositionSchema,
    OrderRequest,
    OrderResponse,
    PerformanceResponse,
    ReviewReportSchema,
    MarketContextSchema,
    BlackSwanSchema,
    WatchlistItemSchema,
    BacktestRequest,
    BacktestResponse,
    PerformanceHistoryItem,
    SignalHistoryItem,
    BacktestCompareRequest,
    BacktestCompareResponse,
    StrategyResult,
    TaskTriggerResponse,
)
from ..config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")
settings = get_settings()


@router.get("/health")
async def health_check():
    return {"status": "ok", "mode": settings.trading_mode}


@router.get("/signals/current", response_model=CurrentSignalsResponse)
async def get_current_signals():
    """即時抓取市場資料並生成 S1/S2/S3 訊號。"""
    import asyncio
    from datetime import datetime
    from ..data.fetcher import USMarketFetcher, TWMarketFetcher
    from ..data.normalizer import DataNormalizer
    from ..signals.time_diff import TimeDiffSignalGenerator
    from ..signals.ma200_filter import MA200Filter
    from ..signals.aggregator import SignalAggregator

    try:
        loop = asyncio.get_running_loop()

        fetcher = USMarketFetcher()
        norm = DataNormalizer()

        # S2：時間差訊號（用美股最新收盤漲跌）
        import math as _math

        def _safe_chg(d: dict | None) -> float:
            """從 get_all_signals_data 結果安全取 change_pct，防止 None / NaN。"""
            if not d:
                return 0.0
            v = d.get("change_pct", 0.0)
            try:
                f = float(v)
                return f if _math.isfinite(f) else 0.0
            except (TypeError, ValueError):
                return 0.0

        us_data = await loop.run_in_executor(None, fetcher.get_all_signals_data)
        nasdaq_chg = _safe_chg(us_data.get("nasdaq"))
        sp500_chg  = _safe_chg(us_data.get("sp500"))
        sox_chg    = _safe_chg(us_data.get("sox"))

        gen = TimeDiffSignalGenerator(
            nasdaq_threshold=settings.us_signal_threshold,
            min_confidence=settings.min_confidence,
        )
        time_diff = gen.generate(nasdaq_chg, sp500_chg, sox_chg)

        # S1：MA200 趨勢（QQQ 2年資料）
        qqq_raw = await loop.run_in_executor(
            None, lambda: fetcher.get_historical("qqq", period="2y")
        )
        qqq_df = norm.normalize_ohlcv(qqq_raw)
        ma_filter = MA200Filter(period=settings.ma_period)
        trend = ma_filter.calculate(qqq_df, "QQQ")

        # S3：組合決策
        agg = SignalAggregator()
        combined = agg.aggregate(trend, time_diff)

        return CurrentSignalsResponse(
            trend=TrendSignalSchema(
                symbol=trend.symbol,
                state=trend.state.value,
                current_price=float(trend.current_price),
                ma200=float(trend.ma200),
                distance_pct=float(trend.distance_pct),
                signal_date=datetime.combine(trend.date, datetime.min.time()),
                is_newly_crossed=trend.is_newly_crossed,
            ),
            time_diff=TimeDiffSignalSchema(
                direction=time_diff.direction.value,
                confidence=float(time_diff.confidence),
                nasdaq_change_pct=nasdaq_chg,
                sp500_change_pct=sp500_chg,
                sox_change_pct=sox_chg,
                trigger_reason=time_diff.trigger_reason,
                generated_at=time_diff.generated_at,
            ),
            combined=CombinedSignalSchema(
                final_action=combined.final_action.value,
                symbol=combined.symbol or "0050",
                suggested_position_pct=float(combined.suggested_position_pct),
                stop_loss_pct=float(combined.stop_loss_pct),
                reason=combined.reason,
            ),
        )

    except Exception as e:
        logger.error(f"get_current_signals error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/positions", response_model=list[PositionSchema])
async def get_positions():
    """取得目前所有持倉（從 DB 讀取最新快照）。"""
    try:
        from ..database.helpers import get_open_positions
        positions = await get_open_positions()
        return [
            PositionSchema(
                symbol=p["symbol"],
                quantity=p["quantity"],
                avg_entry_price=p["avg_entry_price"],
                current_price=p["current_price"] or p["avg_entry_price"],
                unrealized_pnl=p["unrealized_pnl"] or 0.0,
                unrealized_pnl_pct=p["unrealized_pnl_pct"] or 0.0,
            )
            for p in positions
        ]
    except Exception as e:
        logger.error(f"get_positions error: {e}")
        return []


@router.post("/orders", response_model=OrderResponse)
async def create_order(request: OrderRequest):
    """手動建立訂單（需確認 trading_mode）。"""
    if settings.trading_mode == "observe":
        raise HTTPException(status_code=403, detail="系統處於觀察模式，不允許下單")
    raise HTTPException(status_code=501, detail="手動下單請透過 Celery 訊號任務執行")


@router.get("/performance", response_model=PerformanceResponse)
async def get_performance():
    """取得績效摘要（從 DB 最新快照）。"""
    try:
        from ..database.helpers import get_latest_performance
        perf = await get_latest_performance()
        if not perf:
            return PerformanceResponse(
                period="ytd",
                total_return_pct=0.0,
                max_drawdown_pct=0.0,
                win_rate=0.0,
                total_trades=0,
                sharpe_ratio=0.0,
                profit_factor=0.0,
            )
        extra = perf.get("extra_data", {}) or {}
        return PerformanceResponse(
            period="ytd",
            total_return_pct=perf["total_return_pct"],
            max_drawdown_pct=perf["max_drawdown_pct"],
            win_rate=perf["win_rate"],
            total_trades=extra.get("total_trades", 0),
            sharpe_ratio=perf["sharpe_ratio"],
            profit_factor=0.0,
        )
    except Exception as e:
        logger.error(f"get_performance error: {e}")
        return PerformanceResponse(
            period="ytd",
            total_return_pct=0.0,
            max_drawdown_pct=0.0,
            win_rate=0.0,
            total_trades=0,
            sharpe_ratio=0.0,
            profit_factor=0.0,
        )


@router.get("/review/daily/latest", response_model=Optional[ReviewReportSchema])
async def get_daily_review():
    """取得最新每日覆盤報告。"""
    try:
        from ..database.helpers import get_latest_review
        return await get_latest_review("daily")
    except Exception as e:
        logger.error(f"get_daily_review error: {e}")
        return None


@router.get("/review/weekly/latest", response_model=Optional[ReviewReportSchema])
async def get_weekly_review():
    """取得最新週覆盤報告。"""
    try:
        from ..database.helpers import get_latest_review
        return await get_latest_review("weekly")
    except Exception as e:
        logger.error(f"get_weekly_review error: {e}")
        return None


@router.get("/agents/market-context/latest", response_model=Optional[MarketContextSchema])
async def get_market_context():
    """取得最新市場背景 Agent 分析結果。"""
    try:
        from ..database.helpers import get_latest_market_context
        return await get_latest_market_context()
    except Exception as e:
        logger.error(f"get_market_context error: {e}")
        return None


@router.get("/agents/black-swan/status", response_model=Optional[BlackSwanSchema])
async def get_black_swan_status():
    """取得最近 7 天黑天鵝偵測狀態（無警報回傳 null）。"""
    try:
        from ..database.helpers import get_latest_black_swan
        return await get_latest_black_swan()
    except Exception as e:
        logger.error(f"get_black_swan_status error: {e}")
        return None


@router.get("/watchlist", response_model=list[WatchlistItemSchema])
async def get_watchlist():
    """取得目前 Watchlist（選股 Pipeline 輸出）。"""
    try:
        from ..database.helpers import get_watchlist
        return await get_watchlist()
    except Exception as e:
        logger.error(f"get_watchlist error: {e}")
        return []


@router.get("/watchlist/prices")
async def get_watchlist_prices():
    """即時抓取 Watchlist 各股技術指標：股價、止損、MA200、RSI、MACD。"""
    import asyncio as _aio
    from concurrent.futures import ThreadPoolExecutor
    from ..database.helpers import get_watchlist

    items = await get_watchlist()
    symbols = [i["symbol"] for i in items]
    if not symbols:
        return {}

    # index_stop_loss_pct = 0.12 (decimal form = 12%)
    sl_ratio = 1 - settings.index_stop_loss_pct          # 0.88 = 12% stop loss
    tp_ratio = 1 + 2 * settings.index_stop_loss_pct      # 1.24 = 24% profit (2:1 R/R)

    def _calc_rsi(closes: list, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        avg_g = sum(gains) / period
        avg_l = sum(losses) / period
        return 100.0 if avg_l == 0 else round(100 - (100 / (1 + avg_g / avg_l)), 1)

    def _calc_ema(prices: list, period: int) -> list:
        if len(prices) < period:
            return []
        k = 2 / (period + 1)
        ema = [sum(prices[:period]) / period]
        for p in prices[period:]:
            ema.append(p * k + ema[-1] * (1 - k))
        return ema

    def _fetch_one(sym: str):
        try:
            import yfinance as _yf
            tkr = _yf.Ticker(sym)
            hist = tkr.history(period="1y").dropna(subset=["Close"])
            if len(hist) < 30:
                return sym, None
            closes = [float(x) for x in hist["Close"].tolist()]
            volumes = [float(x) for x in hist["Volume"].tolist()]
            prev_close = closes[-2] if len(closes) >= 2 else closes[-1]

            # 嘗試取即時盤中價（開市中）
            try:
                live = float(tkr.fast_info.last_price or 0)
                # 合理性驗證：不超過歷史收盤 ±30%
                if live > 0 and abs(live - closes[-1]) / max(closes[-1], 1) < 0.30:
                    price = live
                    is_live = True
                else:
                    price = closes[-1]
                    is_live = False
            except Exception:
                price = closes[-1]
                is_live = False

            day_change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0.0

            # MA
            ma50 = round(sum(closes[-50:]) / min(50, len(closes)), 1)
            ma200 = round(sum(closes[-200:]) / min(200, len(closes)), 1)

            # RSI (14-day)
            rsi = _calc_rsi(closes[-30:])

            # MACD
            ema12 = _calc_ema(closes, 12)
            ema26 = _calc_ema(closes, 26)
            macd_bullish = False
            macd_diff = 0.0
            if len(ema12) >= len(ema26) >= 9:
                offset = len(ema12) - len(ema26)
                macd_line = [ema12[i + offset] - ema26[i] for i in range(len(ema26))]
                sig_line = _calc_ema(macd_line, 9)
                if sig_line:
                    macd_diff = round(macd_line[-1] - sig_line[-1], 2)
                    macd_bullish = macd_diff > 0

            # 20-day momentum
            mom20 = round((price - closes[-21]) / closes[-21] * 100, 1) if len(closes) >= 21 else 0.0

            # 量能比
            avg_vol20 = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else volumes[-1]
            vol_ratio = round(volumes[-1] / avg_vol20, 2) if avg_vol20 > 0 else 1.0

            # 52週位置
            n = min(252, len(closes))
            high52 = round(max(closes[-n:]), 1)
            low52 = round(min(closes[-n:]), 1)
            range52 = high52 - low52
            pos52 = int(round((price - low52) / range52 * 100, 0)) if range52 > 0 else 50

            # ── 進場觸發條件 ─────────────────────────────────────
            trigger_score = 0
            trigger_signals = []

            # 今日突破 MA50（前日收盤 ≤ 前日MA50，今日站上）
            if len(closes) >= 52:
                prev_ma50 = sum(closes[-51:-1]) / 50
                if closes[-2] <= prev_ma50 and closes[-1] > ma50:
                    trigger_score += 2
                    trigger_signals.append("🚀 今日突破 MA50（強力進場信號）")

            # 均線多頭排列
            if price > ma200 and price > ma50 and ma50 > ma200:
                trigger_score += 2
                trigger_signals.append("✅ 完美多頭排列（MA50>MA200 均站上）")
            elif price > ma200 and price > ma50:
                trigger_score += 1
                trigger_signals.append("✅ 站上 MA200 & MA50")
            elif price > ma200:
                trigger_score += 1
                trigger_signals.append("⚡ 站上 MA200，待突破 MA50")
            else:
                trigger_signals.append("❌ 跌破 MA200（空頭趨勢，禁止追買）")

            # RSI
            if 40 <= rsi <= 65:
                trigger_score += 1
                trigger_signals.append(f"✅ RSI {rsi} 最佳買入區（40-65）")
            elif rsi > 70:
                trigger_score -= 1
                trigger_signals.append(f"⚠ RSI {rsi} 過熱，避免追高")
            elif rsi < 30:
                trigger_score += 1
                trigger_signals.append(f"✅ RSI {rsi} 超賣，潛在反彈")
            else:
                trigger_signals.append(f"🔶 RSI {rsi} 偏弱，等待回升至 40")

            # MACD
            if macd_bullish:
                trigger_score += 1
                trigger_signals.append(f"✅ MACD 多頭（差值 +{macd_diff}）")
            else:
                trigger_signals.append(f"❌ MACD 空頭（差值 {macd_diff}）")

            # 量能確認
            if vol_ratio >= 1.5:
                trigger_score += 1
                trigger_signals.append(f"✅ 量增確認（{vol_ratio}x 均量）")
            elif vol_ratio < 0.7:
                trigger_signals.append(f"⚠ 成交縮量（{vol_ratio}x），等待放量")
            else:
                trigger_signals.append(f"🔶 量能不足（{vol_ratio}x），等待放量確認")

            if trigger_score >= 5:
                trigger_action, trigger_color = "立即進場", "#00cc66"
            elif trigger_score >= 3:
                trigger_action, trigger_color = "等待確認", "#ffcc00"
            elif trigger_score >= 1:
                trigger_action, trigger_color = "繼續觀察", "#ff8800"
            else:
                trigger_action, trigger_color = "暫勿進場", "#ff4444"

            return sym, {
                "price": round(price, 1),
                "is_live": is_live,
                "day_change_pct": day_change_pct,
                "prev_close": round(prev_close, 1),
                "stop_loss": round(price * sl_ratio, 1),
                "profit_target": round(price * tp_ratio, 1),
                "ma50": ma50,
                "ma200": ma200,
                "above_ma200": price > ma200,
                "above_ma50": price > ma50,
                "rsi": rsi,
                "macd_bullish": macd_bullish,
                "macd_diff": macd_diff,
                "momentum_20d": mom20,
                "vol_ratio": vol_ratio,
                "high52": high52,
                "low52": low52,
                "pos52": pos52,
                "trigger": {
                    "action": trigger_action,
                    "color": trigger_color,
                    "score": trigger_score,
                    "signals": trigger_signals,
                },
            }
        except Exception as e:
            logger.error(f"watchlist prices {sym}: {e}")
            return sym, None

    loop = _aio.get_running_loop()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [loop.run_in_executor(pool, _fetch_one, s) for s in symbols]
        results = await _aio.gather(*futures, return_exceptions=True)

    out = {}
    for r in results:
        if isinstance(r, Exception):
            continue
        sym, data = r
        if data is not None:
            out[sym] = data
    return out


# ── 持倉 CSV 匯入 ────────────────────────────────────────────────────

# 國泰世華股票中文名稱 → yfinance 代號對照表
_TW_NAME_TO_SYMBOL: dict[str, str] = {
    # 個股
    "台積電": "2330.TW", "鴻海": "2317.TW", "聯發科": "2454.TW",
    "中華電": "2412.TW", "聯電": "2303.TW", "大立光": "3008.TW",
    "廣達": "2382.TW", "台達電": "2308.TW", "華碩": "2357.TW",
    "瑞昱": "2379.TW", "日月光投控": "3711.TW", "研華": "2395.TW",
    "旺宏": "2337.TW", "華邦電": "2344.TW", "聯詠": "3034.TW",
    "國巨": "2327.TW", "南亞科": "2408.TW", "和碩": "4938.TW",
    "泰銘": "8928.TW", "中美晶": "5483.TW", "宏碁": "2353.TW",
    "富邦媒": "8454.TW", "統一": "1216.TW", "台塑": "1301.TW",
    "南亞": "1303.TW", "台化": "1326.TW", "台灣大": "3045.TW",
    "遠傳": "4904.TW", "富邦金": "2881.TW", "國泰金": "2882.TW",
    "中信金": "2891.TW", "兆豐金": "2886.TW",
    # ETF（台股代號以 0 開頭 → is_etf=True）
    "元大台灣50": "0050.TW", "元大高股息": "0056.TW",
    "富邦台50": "006208.TW", "元大美債20年": "00679B.TW",
    "復華富時不動產": "00712.TW", "元大台灣高息低波": "00713.TW",
    "元大AAA至A公司債": "00751B.TW", "國泰永續高股息": "00878.TW",
    "凱基優選高股息30": "00915.TW", "群益台灣精選高息": "00919.TW",
    "主動統一台股增長": "00932.TW", "國泰台灣5G+": "00881.TW",
    "富邦高股息": "00900.TW", "中信關鍵半導體": "00891.TW",
    "永豐台灣ESG": "00888.TW", "台新臺灣永續指數": "00850.TW",
    "元大台灣ESG永續": "00850.TW", "統一FANG+": "00757.TW",
    "國泰美國道瓊": "00668.TW", "富邦NASDAQ": "00662.TW",
    "元大S&P500": "00646.TW", "富邦美國科技": "00712.TW",
}


_US_ETF_SYMBOLS = {
    "VOO","VTI","VT","SPY","QQQ","TQQQ","IWM","GLD","TLT","AGG",
    "SCHD","JEPI","JEPQ","QQQM","SQQQ","ARKK","XLK","XLF","XLE",
    "VNQ","VEA","VWO","BNDX","BND","IAU","GLDM",
}


@router.post("/portfolio/import")
async def import_portfolio_csv(file: UploadFile):
    """解析國泰世華 CSV（台股或複委託），自動偵測格式，按市場分開覆蓋。"""
    import io, csv
    from datetime import datetime as _dt
    from ..database.helpers import save_portfolio_positions

    content = await file.read()
    try:
        raw_text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raw_text = content.decode("big5", errors="replace")

    reader = csv.DictReader(io.StringIO(raw_text))
    fieldnames = reader.fieldnames or []

    # ── 自動偵測格式 ──────────────────────────────────────────────────
    is_us_format = "代號" in fieldnames  # 複委託 CSV 有「代號」欄
    market = "US" if is_us_format else "TW"
    positions = []
    unmapped = []
    now = _dt.utcnow()

    for row in reader:
        if is_us_format:
            # ── 複委託（美股）格式 ───────────────────────────────────
            symbol = (row.get("代號") or "").strip().upper()
            name = (row.get("股票名稱") or symbol).strip()
            if not symbol or symbol.startswith("總"):
                continue
            try:
                shares = float((row.get("目前庫存") or "0").replace(",", ""))
                avg_cost = float((row.get("均價") or "0").replace(",", ""))
            except (ValueError, AttributeError):
                continue
            is_etf = symbol in _US_ETF_SYMBOLS
            currency = "USD"
        else:
            # ── 台股格式 ────────────────────────────────────────────
            name = (row.get("股票名稱") or "").strip()
            if not name or name.startswith("總"):
                continue
            try:
                shares = float((row.get("股數") or "0").replace(",", ""))
                avg_cost = float((row.get("成交均價") or "0").replace(",", ""))
            except (ValueError, AttributeError):
                continue
            symbol = _TW_NAME_TO_SYMBOL.get(name)
            if not symbol:
                unmapped.append(name)
            is_etf = bool(symbol and symbol.startswith("0"))
            currency = "TWD"

        if shares <= 0 or avg_cost <= 0:
            continue

        positions.append({
            "symbol": symbol,
            "name": name,
            "shares": shares,
            "avg_cost": avg_cost,
            "is_etf": is_etf,
            "currency": currency,
            "market": market,
            "imported_at": now,
        })

    count = await save_portfolio_positions(positions, market)
    market_label = "美股複委託" if is_us_format else "台股"
    return {
        "imported": count,
        "market": market,
        "unmapped": unmapped,
        "message": (
            f"【{market_label}】成功匯入 {count} 筆"
            + (f"，未識別代號（仍匯入）：{', '.join(unmapped)}" if unmapped else "")
        ),
    }


@router.get("/portfolio")
async def get_portfolio():
    """取得持倉列表，附帶即時股價、損益、止損狀態；含 USD/TWD 匯率換算。"""
    import asyncio as _aio
    from concurrent.futures import ThreadPoolExecutor
    from ..database.helpers import get_portfolio_positions

    positions = await get_portfolio_positions()
    if not positions:
        return {"items": [], "usd_twd_rate": None}

    sl_pct = settings.index_stop_loss_pct  # 0.12

    def _fetch_price(sym: str):
        try:
            import yfinance as _yf
            tkr = _yf.Ticker(sym)
            try:
                live = float(tkr.fast_info.last_price or 0)
            except Exception:
                live = 0.0
            if live <= 0:
                hist = tkr.history(period="3d").dropna(subset=["Close"])
                live = float(hist.iloc[-1]["Close"]) if not hist.empty else 0.0
            return sym, round(live, 4)
        except Exception as e:
            logger.warning(f"portfolio price {sym}: {e}")
            return sym, None

    def _fetch_usd_twd():
        try:
            import yfinance as _yf
            hist = _yf.Ticker("USDTWD=X").history(period="3d").dropna(subset=["Close"])
            return round(float(hist.iloc[-1]["Close"]), 2) if not hist.empty else None
        except Exception:
            return None

    valid_syms = list({p["symbol"] for p in positions if p["symbol"]})
    loop = _aio.get_running_loop()
    with ThreadPoolExecutor(max_workers=12) as pool:
        futs = [loop.run_in_executor(pool, _fetch_price, s) for s in valid_syms]
        rate_fut = loop.run_in_executor(pool, _fetch_usd_twd)
        price_results = await _aio.gather(*futs, return_exceptions=True)
        usd_twd = await rate_fut

    price_map: dict[str, float] = {}
    for r in price_results:
        if isinstance(r, Exception):
            continue
        sym, px = r
        if px is not None:
            price_map[sym] = px

    result = []
    for p in positions:
        sym = p["symbol"]
        currency = p.get("currency", "TWD")
        current = price_map.get(sym) if sym else None
        cost = p["avg_cost"]
        shares = p["shares"]

        cost_total = round(cost * shares, 2)
        current_total = round(current * shares, 2) if current is not None else None
        pnl = round(current_total - cost_total, 2) if current_total is not None else None
        pnl_pct = round((current - cost) / cost * 100, 2) if current else None
        stop_price = round(cost * (1 - sl_pct), 2) if not p["is_etf"] else None
        near_stop = bool(
            current is not None and stop_price is not None and current <= stop_price * 1.03
        )
        below_stop = bool(
            current is not None and stop_price is not None and current < stop_price
        )
        # TWD 等值（USD 持倉用於彙總計算）
        twd_equiv = None
        if currency == "USD" and usd_twd and current_total is not None:
            twd_equiv = round(current_total * usd_twd, 0)

        result.append({
            **p,
            "current_price": current,
            "cost_total": round(cost_total, 2),
            "current_total": round(current_total, 2) if current_total is not None else None,
            "pnl": round(pnl, 2) if pnl is not None else None,
            "pnl_pct": pnl_pct,
            "stop_price": stop_price,
            "near_stop": near_stop,
            "below_stop": below_stop,
            "twd_equiv": twd_equiv,
        })

    return {"items": result, "usd_twd_rate": usd_twd}


_ALLOWED_TASKS = {
    "run_daily_review",
    "run_weekly_review",
    "run_market_context",
    "check_black_swan",
    "run_stock_selection",
    "fetch_us_market_data",
    "generate_signal",
    "update_positions",
}


@router.post("/tasks/{task_name}", response_model=TaskTriggerResponse)
async def trigger_task(task_name: str):
    """手動觸發指定 Celery 任務；send_task 在 executor 執行，8 秒 timeout 防止阻塞。"""
    import asyncio as _aio
    if task_name not in _ALLOWED_TASKS:
        raise HTTPException(status_code=400, detail=f"不允許的任務名稱：{task_name}。允許清單：{sorted(_ALLOWED_TASKS)}")
    try:
        from ..tasks import celery_app

        def _send():
            result = celery_app.send_task(f"src.tasks.{task_name}")
            return result.id

        loop = _aio.get_running_loop()
        task_id = await _aio.wait_for(
            loop.run_in_executor(None, _send),
            timeout=8.0,
        )
        return TaskTriggerResponse(
            status="queued",
            task=task_name,
            message=f"已送出 Celery 佇列，Task ID: {task_id[:12]}",
        )
    except _aio.TimeoutError:
        # Celery/Redis 連不上時，改為直接在背景執行緒跑任務
        logger.warning(f"Celery timeout for {task_name}, falling back to direct thread execution")
        try:
            import threading
            import importlib as _il

            def _direct():
                try:
                    mod = _il.import_module("src.tasks")
                    getattr(mod, task_name)()
                    logger.info(f"Direct execution of {task_name} completed")
                except Exception as ex:
                    logger.error(f"Direct execution of {task_name} failed: {ex}", exc_info=True)

            t = threading.Thread(target=_direct, daemon=True, name=f"manual-{task_name}")
            t.start()
            return TaskTriggerResponse(
                status="queued",
                task=task_name,
                message="Celery 連線超時，任務已改為直接在背景執行緒啟動",
            )
        except Exception as e2:
            return TaskTriggerResponse(status="error", task=task_name, message=str(e2))
    except Exception as e:
        logger.error(f"trigger_task {task_name} error: {e}", exc_info=True)
        return TaskTriggerResponse(status="error", task=task_name, message=str(e))


@router.get("/debug/celery")
async def debug_celery():
    """診斷 Celery Worker 是否在線，並回報 pending task 數量。"""
    import asyncio as _aio
    from ..tasks import celery_app

    # Upstash Redis 不支援 persistent pub/sub，Celery ping/inspect 永遠 timeout。
    # 改用 Redis List 操作（llen）直接確認佇列狀態，這與 Upstash 完全相容。
    def _check_redis():
        import redis as _redis
        import ssl as _ssl
        # 直接用原始 URL（不加 ssl_cert_reqs=CERT_NONE 字串）
        # redis-py 只接受 ssl.CERT_NONE integer，不接受字串 "CERT_NONE"
        url = settings.redis_url
        kwargs: dict = {}
        if url.startswith("rediss://"):
            kwargs["ssl_cert_reqs"] = _ssl.CERT_NONE
        r = _redis.from_url(url, decode_responses=True, **kwargs)
        r.ping()
        queues = {q: r.llen(q) for q in ["celery", "signals", "orders", "alerts"]}
        return {
            "redis_ok": True,
            "queue_pending": queues,
            "total_pending": sum(queues.values()),
        }

    try:
        loop = _aio.get_running_loop()
        result = await _aio.wait_for(
            loop.run_in_executor(None, _check_redis),
            timeout=5.0,
        )
        pending = result["total_pending"]
        result["diagnosis"] = (
            f"✅ Redis 正常，佇列無積壓（Worker 應已處理完畢）" if pending == 0
            else f"⚠️ Redis 正常，佇列尚有 {pending} 個任務待處理"
        )
        result["note"] = "Upstash 不支援 pub/sub，Worker 線上狀態請以 flyctl status 確認"
        return result
    except _aio.TimeoutError:
        return {"error": "timeout", "diagnosis": "⚠️ Redis 連線超時（5s）"}
    except Exception as e:
        return {"error": str(e), "diagnosis": "⚠️ Redis 連線失敗"}


@router.get("/debug/queue")
async def debug_queue():
    """查看 Celery 佇列中所有待執行任務的名稱。"""
    import asyncio as _aio
    import json as _json

    def _list_tasks():
        import redis as _redis
        import ssl as _ssl
        url = settings.redis_url
        kwargs: dict = {}
        if url.startswith("rediss://"):
            kwargs["ssl_cert_reqs"] = _ssl.CERT_NONE
        r = _redis.from_url(url, decode_responses=True, **kwargs)
        raw_list = r.lrange("celery", 0, -1)
        tasks = []
        for raw in raw_list:
            try:
                msg = _json.loads(raw)
                name = msg.get("headers", {}).get("task", "unknown")
                task_id = msg.get("headers", {}).get("id", "")
                tasks.append({"task": name, "id": task_id[:8]})
            except Exception:
                tasks.append({"task": "parse_error", "id": ""})
        return tasks

    try:
        loop = _aio.get_running_loop()
        tasks = await _aio.wait_for(loop.run_in_executor(None, _list_tasks), timeout=5.0)
        from collections import Counter
        summary = dict(Counter(t["task"] for t in tasks))
        return {"total": len(tasks), "summary": summary, "tasks": tasks}
    except Exception as e:
        return {"error": str(e)}


@router.post("/debug/queue/clear")
async def clear_queue():
    """清除 Celery 佇列中所有待執行任務（不影響正在執行的任務）。"""
    import asyncio as _aio

    def _clear():
        import redis as _redis
        import ssl as _ssl
        url = settings.redis_url
        kwargs: dict = {}
        if url.startswith("rediss://"):
            kwargs["ssl_cert_reqs"] = _ssl.CERT_NONE
        r = _redis.from_url(url, decode_responses=True, **kwargs)
        count = r.llen("celery")
        r.delete("celery")
        return count

    try:
        loop = _aio.get_running_loop()
        cleared = await _aio.wait_for(loop.run_in_executor(None, _clear), timeout=5.0)
        return {"status": "ok", "cleared": cleared, "message": f"已清除 {cleared} 個待執行任務（正在執行的任務不受影響）"}
    except Exception as e:
        return {"error": str(e)}


@router.get("/performance/history", response_model=list[PerformanceHistoryItem])
async def get_performance_history(days: int = 60):
    """取得最近 N 天的每日資金快照（資金曲線用）。"""
    try:
        from ..database.helpers import get_performance_history
        return await get_performance_history(days)
    except Exception as e:
        logger.error(f"get_performance_history error: {e}")
        return []


@router.get("/signals/history", response_model=list[SignalHistoryItem])
async def get_signal_history(days: int = 30):
    """取得最近 N 天的訊號紀錄。"""
    try:
        from ..database.helpers import get_signal_history
        return await get_signal_history(days)
    except Exception as e:
        logger.error(f"get_signal_history error: {e}")
        return []


@router.post("/backtest/compare", response_model=BacktestCompareResponse)
async def run_backtest_compare(request: BacktestCompareRequest):
    """S1 / S2 / S3 三策略並排回測比較（blocking IO 移至 executor）。"""
    import asyncio
    from ..backtest.engine import BacktestEngine, BacktestConfig
    from ..data.fetcher import USMarketFetcher, TWMarketFetcher
    from ..data.normalizer import DataNormalizer

    def _run_compare():
        fetcher = USMarketFetcher()
        tw_fetcher = TWMarketFetcher()
        normalizer = DataNormalizer()

        nasdaq_df = normalizer.normalize_ohlcv(fetcher.get_historical("nasdaq", period="10y"))
        nasdaq_df = normalizer.calculate_change_pct(nasdaq_df)
        sp500_df = normalizer.normalize_ohlcv(fetcher.get_historical("sp500", period="10y"))
        sp500_df = normalizer.calculate_change_pct(sp500_df)
        sox_df = normalizer.normalize_ohlcv(fetcher.get_historical("sox", period="10y"))
        sox_df = normalizer.calculate_change_pct(sox_df)
        us_signals = normalizer.merge_us_signals(nasdaq_df, sp500_df, sox_df)

        price_raw = tw_fetcher.get_historical(request.symbol, period="10y")
        price_df = normalizer.normalize_ohlcv(price_raw)

        out = []
        for strat in ["S1", "S2", "S3"]:
            cfg = BacktestConfig(
                symbol=request.symbol,
                start_date=request.start_date,
                end_date=request.end_date,
                initial_capital=request.initial_capital,
                nasdaq_threshold=request.nasdaq_threshold,
                strategy=strat,
            )
            res = BacktestEngine(cfg).run(price_df, us_signals)
            pf = res.profit_factor
            out.append(StrategyResult(
                strategy=strat,
                total_return_pct=res.total_return_pct,
                annualized_return_pct=res.annualized_return_pct,
                max_drawdown_pct=res.max_drawdown_pct,
                sharpe_ratio=res.sharpe_ratio,
                win_rate=round(res.win_rate * 100, 2),   # 0-1 → 0-100 %
                total_trades=res.total_trades,
                profit_factor=round(min(pf, 99.99), 2) if pf == pf else 0.0,  # cap inf/nan
            ))
        return out

    try:
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, _run_compare)
        return BacktestCompareResponse(
            symbol=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date,
            results=results,
        )
    except Exception as e:
        logger.error(f"backtest compare 失敗: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/backtest/run", response_model=BacktestResponse)
async def run_backtest(request: BacktestRequest):
    """觸發回測任務（blocking IO 移至 executor）。"""
    import asyncio
    from ..backtest.engine import BacktestEngine, BacktestConfig
    from ..data.fetcher import USMarketFetcher, TWMarketFetcher
    from ..data.normalizer import DataNormalizer

    def _run():
        config = BacktestConfig(
            symbol=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            nasdaq_threshold=request.nasdaq_threshold,
        )
        fetcher = USMarketFetcher()
        tw_fetcher = TWMarketFetcher()
        normalizer = DataNormalizer()

        nasdaq_df = normalizer.normalize_ohlcv(fetcher.get_historical("nasdaq", period="10y"))
        nasdaq_df = normalizer.calculate_change_pct(nasdaq_df)
        sp500_df = normalizer.normalize_ohlcv(fetcher.get_historical("sp500", period="10y"))
        sp500_df = normalizer.calculate_change_pct(sp500_df)
        sox_df = normalizer.normalize_ohlcv(fetcher.get_historical("sox", period="10y"))
        sox_df = normalizer.calculate_change_pct(sox_df)
        us_signals = normalizer.merge_us_signals(nasdaq_df, sp500_df, sox_df)

        price_raw = tw_fetcher.get_historical(request.symbol, period="10y")
        price_df = normalizer.normalize_ohlcv(price_raw)

        return BacktestEngine(config).run(price_df, us_signals)

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run)
        return BacktestResponse(
            symbol=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date,
            total_return_pct=result.total_return_pct,
            annualized_return_pct=result.annualized_return_pct,
            max_drawdown_pct=result.max_drawdown_pct,
            sharpe_ratio=result.sharpe_ratio,
            win_rate=result.win_rate,
            total_trades=result.total_trades,
            profit_factor=result.profit_factor,
        )
    except Exception as e:
        logger.error(f"回測執行失敗: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
