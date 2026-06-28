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
    task_default_queue="celery",
)

if settings.redis_url.startswith("rediss://"):
    celery_app.conf.broker_use_ssl = {"ssl_cert_reqs": ssl.CERT_NONE}
    celery_app.conf.redis_backend_use_ssl = {"ssl_cert_reqs": ssl.CERT_NONE}

# RedBeat: 排程狀態存 Redis，容器重啟後不遺失（避免 Beat 補跑所有過期任務）
celery_app.conf.beat_scheduler = "redbeat.RedBeatScheduler"
celery_app.conf.redbeat_redis_url = settings.redis_url  # 原始 URL，無 ssl_cert_reqs 字串
if settings.redis_url.startswith("rediss://"):
    celery_app.conf.redbeat_redis_options = {"ssl_cert_reqs": ssl.CERT_NONE}

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
    # 04:07 黑天鵝偵測（美股收盤後立即檢查）
    "check-black-swan": {
        "task": "src.tasks.check_black_swan",
        "schedule": crontab(hour=4, minute=7),
    },
    # 04:10 市場背景 Agent
    "run-market-context": {
        "task": "src.tasks.run_market_context",
        "schedule": crontab(hour=4, minute=10),
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
    # 週日 20:00 選股掃描
    "stock-selection": {
        "task": "src.tasks.run_stock_selection",
        "schedule": crontab(hour=20, minute=0, day_of_week=0),
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

        from .alerts.discord import get_alerter
        alerter = get_alerter()

        # 推播訊號（BUY/SELL 才發）
        if action in ("BUY", "SELL"):
            sync_run(alerter.signal_alert(
                action=action,
                symbol=SYMBOL,
                confidence=float(time_diff.confidence),
                s1_state=trend.state.value,
                s2_direction=time_diff.direction.value,
                position_pct=float(combined.suggested_position_pct),
                stop_loss_pct=float(combined.stop_loss_pct),
                reason=combined.reason,
            ))

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
                sync_run(alerter.trade_executed(
                    direction="BUY",
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
                sync_run(alerter.trade_executed(
                    direction="SELL",
                    symbol=SYMBOL,
                    quantity=has_position and open_positions[0]["quantity"] or 0,
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

        # 每日收盤摘要推播
        try:
            from .alerts.discord import get_alerter
            alerter = get_alerter()
            fresh_positions = sync_run(get_open_positions())
            total_return_pct = (total_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL
            sync_run(alerter.daily_summary(
                total_equity=total_equity,
                daily_pnl=daily_pnl,
                total_return_pct=total_return_pct,
                positions=fresh_positions,
            ))
        except Exception as e:
            logger.warning(f"Discord daily_summary failed: {e}")

        logger.info(f"Positions updated. equity={total_equity:.0f} cash={cash:.0f}")
        return {"status": "ok", "total_equity": total_equity, "positions": len(positions)}

    except Exception as e:
        logger.error(f"update_positions failed: {e}", exc_info=True)
        return {"status": "error", "reason": str(e)}


# ── 任務：每日覆盤 ────────────────────────────────────────────────────

@celery_app.task(name="src.tasks.run_daily_review")
def run_daily_review():
    """13:40 每日覆盤：Layer1 合規 → Layer2 品質 → Layer3 AI → DB → Discord。"""
    from datetime import date
    from .database import sync_run
    from .database.helpers import (
        get_today_signal, get_today_orders, get_open_positions,
        get_latest_performance, save_review_report,
    )
    from .review.layer1_compliance import RuleComplianceChecker
    from .review.layer2_signal_quality import analyze_signal_quality
    from .review.layer3_ai_analysis import run_ai_review
    from .review.market_regime import classify_regime
    from .data.fetcher import USMarketFetcher, TWMarketFetcher
    from .data.normalizer import DataNormalizer
    from .alerts.discord import get_alerter

    try:
        today_signal = sync_run(get_today_signal())
        if not today_signal:
            logger.info("No signal today — skip daily review")
            return {"status": "skipped", "reason": "no signal"}

        today_orders = sync_run(get_today_orders())
        trade_dict = {}
        if today_orders:
            o = today_orders[0]
            trade_dict = {
                "direction": o["direction"],
                "entry_price": o["filled_price"],
                "stop_loss_price": o["filled_price"] * (1 - settings.index_stop_loss_pct),
                "entry_time": o["filled_at"],
                "pnl_pct": 0.0,
            }

        # Taiwan market data for Layer 2
        tw_open_chg = tw_close_chg = 0.0
        try:
            tw_fetcher = TWMarketFetcher()
            norm = DataNormalizer()
            tw_raw = tw_fetcher.get_historical(SYMBOL, period="10d")
            tw_df = norm.normalize_ohlcv(tw_raw)
            if len(tw_df) >= 2:
                prev_close = float(tw_df.iloc[-2]["close"])
                today_open = float(tw_df.iloc[-1]["open"] or tw_df.iloc[-1]["close"])
                today_close = float(tw_df.iloc[-1]["close"])
                tw_open_chg = (today_open - prev_close) / prev_close * 100
                tw_close_chg = (today_close - prev_close) / prev_close * 100
        except Exception as e:
            logger.warning(f"TW market data fetch failed: {e}")

        # Market regime
        regime_val = "未知"
        try:
            us_fetcher = USMarketFetcher()
            norm = DataNormalizer()
            qqq_raw = us_fetcher.get_historical("qqq", period="1y")
            qqq_df = norm.normalize_ohlcv(qqq_raw)
            vix_data = us_fetcher.get_latest_close("vix")
            vix = float(vix_data.get("close", 20.0))
            if len(qqq_df) >= 200:
                import pandas as pd
                closes = qqq_df["close"].astype(float)
                ma50 = float(closes.rolling(50).mean().iloc[-1])
                ma200 = float(closes.rolling(200).mean().iloc[-1])
                high30 = float(closes.tail(30).max())
                low30 = float(closes.tail(30).min())
                range30 = (high30 - low30) / low30 * 100
                regime_val = classify_regime(ma50, ma200, vix, range30).value
        except Exception as e:
            logger.warning(f"Market regime calc failed: {e}")

        # Layer 1
        config = {
            "us_signal_threshold": settings.us_signal_threshold,
            "index_stop_loss_pct": settings.index_stop_loss_pct,
        }
        checker = RuleComplianceChecker()
        compliance = checker.check(trade_dict, today_signal, config)
        compliance_dict = {
            "score": compliance.score,
            "violations": [
                {"rule": v.rule, "expected": v.expected, "actual": v.actual, "severity": v.severity}
                for v in compliance.violations
            ],
        }

        # Layer 2
        quality = analyze_signal_quality(
            today_signal,
            {"taiwan_open_change_pct": tw_open_chg, "taiwan_close_change_pct": tw_close_chg},
            trade_dict,
        )
        quality_dict = {
            "quality_score": quality.quality_score,
            "signal_was_correct": quality.signal_was_correct,
            "nasdaq_change_pct": quality.nasdaq_change_pct,
            "sox_change_pct": quality.sox_change_pct,
            "taiwan_open_change_pct": quality.taiwan_open_change_pct,
            "taiwan_close_change_pct": quality.taiwan_close_change_pct,
        }

        perf = sync_run(get_latest_performance()) or {}
        rolling_stats = {
            "win_rate_30d": perf.get("win_rate", 0),
            "sharpe_30d": perf.get("sharpe_ratio", 0),
            "vs_benchmark_pct": 0.0,
        }

        # Layer 3 AI (Gemini)
        ai_text = sync_run(run_ai_review(
            compliance=compliance_dict,
            signal_quality=quality_dict,
            trade=trade_dict,
            rolling_stats=rolling_stats,
        ))

        # Save to DB
        sync_run(save_review_report(
            review_date=date.today(),
            review_type="daily",
            compliance_score=compliance.score,
            signal_quality_score=quality.quality_score,
            ai_analysis=ai_text,
            net_pnl=0.0,
            stability_score=0.0,
            market_regime=regime_val,
        ))

        # Discord
        alerter = get_alerter()
        sync_run(alerter.daily_review(
            compliance_score=compliance.score,
            quality_score=quality.quality_score,
            signal_correct=quality.signal_was_correct,
            regime=regime_val,
            ai_summary=ai_text[:600],
        ))

        logger.info(f"Daily review done: L1={compliance.score:.0f} L2={quality.quality_score:.0f} regime={regime_val}")
        return {
            "status": "ok",
            "compliance_score": compliance.score,
            "signal_quality_score": quality.quality_score,
            "market_regime": regime_val,
        }

    except Exception as e:
        logger.error(f"run_daily_review failed: {e}", exc_info=True)
        try:
            from .alerts.discord import get_alerter
            sync_run(get_alerter().system_error("run_daily_review", str(e)))
        except Exception:
            pass
        return {"status": "error", "reason": str(e)}


# ── 任務：週覆盤 ──────────────────────────────────────────────────────

@celery_app.task(name="src.tasks.run_weekly_review")
def run_weekly_review():
    """週五 14:00 週覆盤：本週訊號統計 → Gemini 彙整 → DB → Discord。"""
    from datetime import date, timedelta
    from .database import sync_run
    from .database.helpers import (
        get_week_signals, get_week_orders, get_latest_performance, save_review_report,
    )
    from .review.layer3_ai_analysis import run_weekly_ai_review
    from .review.market_regime import classify_regime
    from .data.fetcher import USMarketFetcher
    from .data.normalizer import DataNormalizer
    from .alerts.discord import get_alerter

    try:
        week_signals = sync_run(get_week_signals())
        week_orders = sync_run(get_week_orders())

        # Signal accuracy
        correct = sum(
            1 for s in week_signals
            if (s["direction"] == "UP" and s["suggested_action"] == "BUY")
            or (s["direction"] == "DOWN" and s["suggested_action"] == "SELL")
            or s["suggested_action"] == "HOLD"
        )
        signal_accuracy = correct / len(week_signals) if week_signals else 0.0

        # Weekly return from performance
        perf = sync_run(get_latest_performance()) or {}
        weekly_return_pct = float(perf.get("total_return_pct", 0))

        # Market regime
        regime_val = "未知"
        try:
            us_fetcher = USMarketFetcher()
            norm = DataNormalizer()
            qqq_raw = us_fetcher.get_historical("qqq", period="1y")
            qqq_df = norm.normalize_ohlcv(qqq_raw)
            vix_data = us_fetcher.get_latest_close("vix")
            vix = float(vix_data.get("close", 20.0))
            if len(qqq_df) >= 200:
                closes = qqq_df["close"].astype(float)
                ma50 = float(closes.rolling(50).mean().iloc[-1])
                ma200 = float(closes.rolling(200).mean().iloc[-1])
                high30 = float(closes.tail(30).max())
                low30 = float(closes.tail(30).min())
                range30 = (high30 - low30) / low30 * 100
                regime_val = classify_regime(ma50, ma200, vix, range30).value
        except Exception as e:
            logger.warning(f"Market regime calc failed: {e}")

        today = date.today()
        monday = today - timedelta(days=today.weekday())
        week_label = f"{monday.strftime('%m/%d')}–{today.strftime('%m/%d')}"

        ai_text = sync_run(run_weekly_ai_review(
            week_label=week_label,
            signals=week_signals,
            orders=week_orders,
            weekly_return_pct=weekly_return_pct,
            signal_accuracy=signal_accuracy,
            market_regime=regime_val,
        ))

        # Save — use Monday's date to avoid unique collision with daily review on Friday
        sync_run(save_review_report(
            review_date=monday,
            review_type="weekly",
            compliance_score=0,
            signal_quality_score=signal_accuracy * 100,
            ai_analysis=ai_text,
            net_pnl=0.0,
            stability_score=0.0,
            market_regime=regime_val,
        ))

        # Discord
        alerter = get_alerter()
        sync_run(alerter.weekly_review(
            week_label=week_label,
            signal_count=len(week_signals),
            signal_accuracy=signal_accuracy,
            trade_count=len(week_orders),
            weekly_return_pct=weekly_return_pct,
            market_regime=regime_val,
            ai_summary=ai_text[:600],
        ))

        logger.info(f"Weekly review done: signals={len(week_signals)} trades={len(week_orders)}")
        return {
            "status": "ok",
            "week": week_label,
            "signal_count": len(week_signals),
            "trade_count": len(week_orders),
        }

    except Exception as e:
        logger.error(f"run_weekly_review failed: {e}", exc_info=True)
        try:
            from .alerts.discord import get_alerter
            sync_run(get_alerter().system_error("run_weekly_review", str(e)))
        except Exception:
            pass
        return {"status": "error", "reason": str(e)}


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


# ── 任務：黑天鵝偵測 ─────────────────────────────────────────────────

@celery_app.task(name="src.tasks.check_black_swan")
def check_black_swan():
    """04:07 黑天鵝偵測 — 純量化，不呼叫 LLM。"""
    from .agents.black_swan_agent import detect_black_swan, fetch_vix, BlackSwanSeverity
    from .database import sync_run
    from .database.helpers import save_black_swan_alert
    from .data.fetcher import USMarketFetcher

    try:
        fetcher = USMarketFetcher()
        us_data = fetcher.get_all_signals_data()
        nasdaq_chg = us_data.get("nasdaq", {}).get("change_pct", 0.0) or 0.0
        sox_chg = us_data.get("sox", {}).get("change_pct", 0.0) or 0.0
        vix = fetch_vix()

        signal = detect_black_swan(
            vix=vix,
            nasdaq_change_pct=nasdaq_chg,
            sox_change_pct=sox_chg,
        )

        if signal.severity != BlackSwanSeverity.NONE:
            sync_run(save_black_swan_alert(
                severity=signal.severity.value,
                triggers=signal.triggers,
                action_taken=signal.recommended_action,
            ))
            logger.warning(f"Black Swan detected: {signal.severity.value} | {signal.triggers}")

            # Discord 警告
            if signal.severity in (BlackSwanSeverity.ALERT, BlackSwanSeverity.CRITICAL):
                try:
                    from .alerts.discord import get_alerter
                    sync_run(get_alerter().black_swan_alert(
                        severity=signal.severity.value,
                        triggers=signal.triggers,
                    ))
                except Exception as e:
                    logger.warning(f"Discord black swan alert failed: {e}")

        logger.info(f"Black swan check: {signal.severity.value} | VIX={vix:.1f} NASDAQ={nasdaq_chg:+.1f}%")
        return {
            "severity": signal.severity.value,
            "vix": vix,
            "triggers": signal.triggers,
        }

    except Exception as e:
        logger.error(f"check_black_swan failed: {e}", exc_info=True)
        return {"status": "error", "reason": str(e)}


# ── 任務：市場背景 Agent ───────────────────────────────────────────────

@celery_app.task(name="src.tasks.run_market_context")
def run_market_context():
    """04:10 市場背景 Agent — 解讀美股收盤背景對台股的影響。"""
    from .agents.market_context_agent import run_market_context_agent
    from .database import sync_run
    from .database.helpers import save_market_context
    from .data.fetcher import USMarketFetcher

    try:
        fetcher = USMarketFetcher()
        us_data = fetcher.get_all_signals_data()
        nasdaq_chg = us_data.get("nasdaq", {}).get("change_pct", 0.0) or 0.0
        sp500_chg  = us_data.get("sp500",  {}).get("change_pct", 0.0) or 0.0
        sox_chg    = us_data.get("sox",    {}).get("change_pct", 0.0) or 0.0

        result = sync_run(run_market_context_agent(
            nasdaq_change_pct=nasdaq_chg,
            sp500_change_pct=sp500_chg,
            sox_change_pct=sox_chg,
        ))

        today = date.today()
        sync_run(save_market_context(today, result))

        logger.info(
            f"Market context: {result.get('taiwan_relevance')} | "
            f"modifier={result.get('confidence_modifier', 0):+.2f} | "
            f"{result.get('context_summary', '')[:60]}"
        )
        return {
            "status": "ok",
            "taiwan_relevance": result.get("taiwan_relevance"),
            "confidence_modifier": result.get("confidence_modifier", 0),
        }

    except Exception as e:
        logger.error(f"run_market_context failed: {e}", exc_info=True)
        return {"status": "error", "reason": str(e)}


# ── 任務：選股 Pipeline（週日 20:00）──────────────────────────────────

@celery_app.task(name="src.tasks.run_stock_selection")
def run_stock_selection():
    """週日 20:00 執行選股 Pipeline，產出 Watchlist。"""
    from .agents.stock_selection.pipeline import run_stock_selection_pipeline
    from .database import sync_run
    from .database.helpers import save_watchlist

    try:
        entries = sync_run(run_stock_selection_pipeline())

        if not entries:
            logger.info("Stock selection: no stocks passed threshold")
            return {"status": "ok", "count": 0}

        items = [
            {
                "symbol": e.symbol,
                "overall_score": e.overall_score,
                "recommendation": e.recommendation,
                "thesis": e.thesis,
                "risks": e.risks,
                "entry_condition": e.entry_condition,
                "agent_results": e.agent_results,
            }
            for e in entries
        ]
        sync_run(save_watchlist(items))

        # Discord 通知
        try:
            from .alerts.discord import get_alerter
            top_symbols = ", ".join(e.symbol for e in entries[:5])
            sync_run(get_alerter().watchlist_update(
                count=len(entries),
                top_symbols=top_symbols,
            ))
        except Exception as e:
            logger.warning(f"Discord watchlist notify failed: {e}")

        logger.info(f"Stock selection done: {len(entries)} stocks added to watchlist")
        return {
            "status": "ok",
            "count": len(entries),
            "symbols": [e.symbol for e in entries],
        }

    except Exception as e:
        logger.error(f"run_stock_selection failed: {e}", exc_info=True)
        return {"status": "error", "reason": str(e)}


# ── 任務：每日備份 ────────────────────────────────────────────────────

@celery_app.task(name="src.tasks.daily_backup")
def daily_backup():
    """23:00 每日資料備份（目前 Supabase 自動備份，此任務記錄備份狀態）。"""
    logger.info("Daily backup checkpoint — Supabase handles persistence.")
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
