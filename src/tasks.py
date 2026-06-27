import ssl
import logging
from datetime import datetime, date
import calendar

from celery import Celery
from celery.schedules import crontab

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

INITIAL_CAPITAL = settings.initial_capital
SYMBOL = "0050"


def _make_redis_url(url: str) -> str:
    """Upstash rediss:// needs ssl_cert_reqs in URL for Celery validation."""
    if url.startswith("rediss://") and "ssl_cert_reqs" not in url:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}ssl_cert_reqs=CERT_NONE"
    return url


_redis_url = _make_redis_url(settings.redis_url)

celery_app = Celery(
    "zerohour",
    broker=_redis_url,
    backend=_redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Taipei",
    enable_utc=True,
    task_track_started=True,
)

if settings.redis_url.startswith("rediss://"):
    celery_app.conf.broker_use_ssl = {"ssl_cert_reqs": ssl.CERT_NONE}
    celery_app.conf.redis_backend_use_ssl = {"ssl_cert_reqs": ssl.CERT_NONE}

celery_app.conf.beat_schedule = {
    # 04:00 美股收盤資料抓取
    "fetch-us-close": {
        "task": "src.tasks.fetch_us_market_data",
        "schedule": crontab(hour=4, minute=0),
    },
    # 04:05 S1+S2+S3 訊號計算 + Paper 下單
    "generate-time-diff-signal": {
        "task": "src.tasks.generate_signal",
        "schedule": crontab(hour=4, minute=5),
    },
    # 13:35 台股收盤後更新持倉損益 + 績效快照
    "update-positions": {
        "task": "src.tasks.update_positions",
        "schedule": crontab(hour=13, minute=35),
    },
    # 13:40 每日覆盤
    "daily-review": {
        "task": "src.tasks.run_daily_review",
        "schedule": crontab(hour=13, minute=40),
    },
    # 週五 14:00 週覆盤
    "weekly-review": {
        "task": "src.tasks.run_weekly_review",
        "schedule": crontab(hour=14, minute=0, day_of_week=5),
    },
    # 22:00 月底 200MA 趨勢檢查
    "monthly-trend-check": {
        "task": "src.tasks.check_monthly_trend",
        "schedule": crontab(hour=22, minute=0),
    },
    # 23:00 每日資料備份
    "daily-backup": {
        "task": "src.tasks.daily_backup",
        "schedule": crontab(hour=23, minute=0),
    },
}


# ── 任務：抓取美股資料 ────────────────────────────────────────────────

@celery_app.task(name="src.tasks.fetch_us_market_data")
def fetch_us_market_data():
    """04:00 抓取美股收盤資料並存入 DB。"""
    from .data.fetcher import USMarketFetcher
    from .database import sync_run
    from .database.helpers import save_market_prices

    fetcher = USMarketFetcher()
    data = fetcher.get_all_signals_data()

    try:
        sync_run(save_market_prices(data))
    except Exception as e:
        logger.error(f"save_market_prices failed: {e}")

    logger.info(f"US market data fetched: {[k for k, v in data.items() if v]}")
    return {"status": "ok", "symbols": list(data.keys())}


# ── 任務：生成訊號 + Paper 下單 ───────────────────────────────────────

@celery_app.task(name="src.tasks.generate_signal")
def generate_signal():
    """04:05 生成 S1+S2+S3 訊號，若需要則執行 paper 下單。"""
    from .data.fetcher import USMarketFetcher, TWMarketFetcher
    from .data.normalizer import DataNormalizer
    from .signals.time_diff import TimeDiffSignalGenerator
    from .signals.ma200_filter import MA200Filter
    from .signals.aggregator import SignalAggregator
    from .risk.position_sizer import PositionSizer
    from .risk.stop_loss import StopLossManager
    from .database import sync_run
    from .database.helpers import (
        save_time_diff_signal,
        save_trend_signal,
        get_open_positions,
        open_position,
        close_position,
    )

    try:
        fetcher = USMarketFetcher()
        tw_fetcher = TWMarketFetcher()
        norm = DataNormalizer()

        # S2
        us_data = fetcher.get_all_signals_data()
        nasdaq_chg = us_data.get("nasdaq", {}).get("change_pct", 0.0) or 0.0
        sp500_chg  = us_data.get("sp500",  {}).get("change_pct", 0.0) or 0.0
        sox_chg    = us_data.get("sox",    {}).get("change_pct", 0.0) or 0.0

        gen = TimeDiffSignalGenerator(
            nasdaq_threshold=settings.us_signal_threshold,
            min_confidence=settings.min_confidence,
        )
        time_diff = gen.generate(nasdaq_chg, sp500_chg, sox_chg)

        # S1
        qqq_raw = fetcher.get_historical("qqq", period="2y")
        qqq_df  = norm.normalize_ohlcv(qqq_raw)
        ma_filter = MA200Filter(period=settings.ma_period)
        trend = ma_filter.calculate(qqq_df, "QQQ")

        # S3
        agg = SignalAggregator()
        combined = agg.aggregate(trend, time_diff)
        action = combined.final_action.value  # BUY / SELL / HOLD

        # Save signals to DB
        signal_id = sync_run(save_time_diff_signal(
            direction=time_diff.direction.value,
            confidence=float(time_diff.confidence),
            nasdaq_chg=nasdaq_chg,
            sp500_chg=sp500_chg,
            sox_chg=sox_chg,
            trigger_reason=time_diff.trigger_reason,
            suggested_action=action,
            suggested_symbol=SYMBOL,
        ))
        sync_run(save_trend_signal(
            symbol="QQQ",
            state=trend.state.value,
            current_price=float(trend.current_price),
            ma200=float(trend.ma200),
            distance_pct=float(trend.distance_pct),
            signal_date=datetime.utcnow(),
            is_newly_crossed=trend.is_newly_crossed,
        ))

        logger.info(f"Signal: {action} | S2={time_diff.direction.value} "
                    f"conf={time_diff.confidence:.2f} | S1={trend.state.value}")

        # Paper 下單
        open_positions = sync_run(get_open_positions())
        has_position = any(p["symbol"] == SYMBOL for p in open_positions)

        if action == "BUY" and not has_position:
            tw_df = tw_fetcher.get_historical(SYMBOL, period="5d")
            if not tw_df.empty:
                fill_price = float(tw_df.iloc[-1]["close"])
                quantity = INITIAL_CAPITAL * settings.max_position_pct / fill_price
                stop_loss = fill_price * (1 - settings.index_stop_loss_pct)

                sync_run(open_position(
                    signal_id=signal_id,
                    symbol=SYMBOL,
                    quantity=round(quantity, 0),
                    fill_price=fill_price,
                    stop_loss_price=round(stop_loss, 2),
                ))
                logger.info(f"Paper BUY: {quantity:.0f} {SYMBOL} @ {fill_price}")

        elif action == "SELL" and has_position:
            tw_df = tw_fetcher.get_historical(SYMBOL, period="5d")
            if not tw_df.empty:
                fill_price = float(tw_df.iloc[-1]["close"])
                sync_run(close_position(
                    signal_id=signal_id,
                    symbol=SYMBOL,
                    fill_price=fill_price,
                ))
                logger.info(f"Paper SELL: {SYMBOL} @ {fill_price}")

        return {
            "action": action,
            "direction": time_diff.direction.value,
            "confidence": float(time_diff.confidence),
            "s1_state": trend.state.value,
            "signal_id": signal_id,
        }

    except Exception as e:
        logger.error(f"generate_signal failed: {e}", exc_info=True)
        return {"status": "error", "reason": str(e)}


# ── 任務：更新持倉 + 績效快照 ─────────────────────────────────────────

@celery_app.task(name="src.tasks.update_positions")
def update_positions():
    """13:35 台股收盤後：更新持倉現價 + 存績效快照 + 觸發停損。"""
    from .data.fetcher import TWMarketFetcher
    from .database import sync_run
    from .database.helpers import (
        get_open_positions,
        update_position_price,
        close_position,
        get_cash_balance,
        save_performance_snapshot,
    )

    try:
        tw_fetcher = TWMarketFetcher()
        positions = sync_run(get_open_positions())

        positions_value = 0.0
        for pos in positions:
            symbol = pos["symbol"]
            try:
                tw_df = tw_fetcher.get_historical(symbol, period="5d")
                if tw_df.empty:
                    continue
                current_price = float(tw_df.iloc[-1]["close"])
                sync_run(update_position_price(
                    symbol=symbol,
                    current_price=current_price,
                    trailing_stop_pct=settings.trailing_stop_pct,
                ))
                positions_value += current_price * pos["quantity"]

                # Stop loss check
                stop = pos.get("stop_loss_price") or 0
                if stop and current_price <= stop:
                    logger.warning(f"Stop loss triggered: {symbol} {current_price} <= {stop}")
                    sync_run(close_position(
                        signal_id=0,
                        symbol=symbol,
                        fill_price=current_price,
                    ))
                    positions_value -= current_price * pos["quantity"]

            except Exception as e:
                logger.error(f"update_position_price {symbol} failed: {e}")

        cash = sync_run(get_cash_balance(INITIAL_CAPITAL))
        total_equity = cash + positions_value
        daily_pnl = total_equity - INITIAL_CAPITAL  # rough daily proxy

        sync_run(save_performance_snapshot(
            initial_capital=INITIAL_CAPITAL,
            positions_value=positions_value,
            cash=cash,
            daily_pnl=daily_pnl,
        ))

        logger.info(f"Positions updated. equity={total_equity:.0f} cash={cash:.0f}")
        return {"status": "ok", "total_equity": total_equity, "positions": len(positions)}

    except Exception as e:
        logger.error(f"update_positions failed: {e}", exc_info=True)
        return {"status": "error", "reason": str(e)}


# ── 任務：每日覆盤 ────────────────────────────────────────────────────

@celery_app.task(name="src.tasks.run_daily_review")
def run_daily_review():
    """13:40 每日覆盤（Layer 1~3 + 優勢衰減偵測）。"""
    logger.info("Running daily review...")
    # TODO (P2): Layer1 → Layer2 → Layer3(Gemini) → save ReviewReport → Discord notify
    return {"status": "ok", "note": "stub — P2 will implement full review pipeline"}


# ── 任務：週覆盤 ──────────────────────────────────────────────────────

@celery_app.task(name="src.tasks.run_weekly_review")
def run_weekly_review():
    """週五 14:00 週覆盤。"""
    logger.info("Running weekly review...")
    # TODO (P3): Analyze week's signals → Gemini summary → save ReviewReport → Discord notify
    return {"status": "ok", "note": "stub — P3 will implement weekly review"}


# ── 任務：月底 MA200 趨勢檢查 ─────────────────────────────────────────

@celery_app.task(name="src.tasks.check_monthly_trend")
def check_monthly_trend():
    """22:00 月底 200MA 趨勢檢查。"""
    today = date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    if today.day != last_day:
        return {"status": "skipped", "reason": "非月底"}

    from .data.fetcher import USMarketFetcher
    from .data.normalizer import DataNormalizer
    from .signals.ma200_filter import MA200Filter
    from .database import sync_run
    from .database.helpers import save_trend_signal

    try:
        fetcher = USMarketFetcher()
        norm = DataNormalizer()
        qqq_raw = fetcher.get_historical("qqq", period="2y")
        qqq_df = norm.normalize_ohlcv(qqq_raw)
        ma_filter = MA200Filter(period=settings.ma_period)
        signal = ma_filter.calculate(qqq_df, "QQQ")

        sync_run(save_trend_signal(
            symbol="QQQ",
            state=signal.state.value,
            current_price=float(signal.current_price),
            ma200=float(signal.ma200),
            distance_pct=float(signal.distance_pct),
            signal_date=datetime.utcnow(),
            is_newly_crossed=signal.is_newly_crossed,
        ))

        logger.info(f"Monthly MA200: QQQ → {signal.state.value}")
        return {"state": signal.state.value, "distance_pct": signal.distance_pct}

    except Exception as e:
        logger.error(f"check_monthly_trend failed: {e}")
        return {"status": "error", "reason": str(e)}


# ── 任務：每日備份 ────────────────────────────────────────────────────

@celery_app.task(name="src.tasks.daily_backup")
def daily_backup():
    """23:00 每日資料備份（目前 Supabase 自動備份，此任務記錄備份狀態）。"""
    logger.info("Daily backup checkpoint — Supabase handles persistence.")
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
