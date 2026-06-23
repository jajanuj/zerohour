from celery import Celery
from celery.schedules import crontab
import logging

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

celery_app = Celery(
    "zerohour",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Taipei",
    enable_utc=True,
    task_track_started=True,
)

celery_app.conf.beat_schedule = {
    # 04:00 美股收盤資料抓取
    "fetch-us-close": {
        "task": "src.tasks.fetch_us_market_data",
        "schedule": crontab(hour=4, minute=0),
    },
    # 04:05 S2 時間差訊號計算
    "generate-time-diff-signal": {
        "task": "src.tasks.generate_signal",
        "schedule": crontab(hour=4, minute=5),
    },
    # 13:35 台股收盤後更新部位
    "update-positions": {
        "task": "src.tasks.update_positions",
        "schedule": crontab(hour=13, minute=35),
    },
    # 13:40 每日覆盤
    "daily-review": {
        "task": "src.tasks.run_daily_review",
        "schedule": crontab(hour=13, minute=40),
    },
    # 22:00 月底 200MA 趨勢檢查（每日執行，但邏輯內部判斷是否月底）
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


@celery_app.task(name="src.tasks.fetch_us_market_data")
def fetch_us_market_data():
    """04:00 抓取美股收盤資料並存入 DB。"""
    from .data.fetcher import USMarketFetcher
    fetcher = USMarketFetcher()
    data = fetcher.get_all_signals_data()
    logger.info(f"US market data fetched: {list(data.keys())}")
    return {"status": "ok", "symbols": list(data.keys())}


@celery_app.task(name="src.tasks.generate_signal")
def generate_signal():
    """04:05 生成台美時間差訊號。"""
    from .data.fetcher import USMarketFetcher
    from .signals.time_diff import TimeDiffSignalGenerator

    fetcher = USMarketFetcher()
    data = fetcher.get_all_signals_data()

    if not all(data.get(k) for k in ["nasdaq", "sp500", "sox"]):
        logger.warning("缺少市場資料，跳過訊號生成")
        return {"status": "skipped", "reason": "missing data"}

    generator = TimeDiffSignalGenerator(
        nasdaq_threshold=settings.us_signal_threshold,
        min_confidence=settings.min_confidence,
    )
    signal = generator.generate(
        nasdaq_change_pct=data["nasdaq"]["change_pct"],
        sp500_change_pct=data["sp500"]["change_pct"],
        sox_change_pct=data["sox"]["change_pct"],
    )

    logger.info(f"Signal: {signal.direction.value} | confidence: {signal.confidence:.2f}")
    return {
        "direction": signal.direction.value,
        "confidence": signal.confidence,
        "reason": signal.trigger_reason,
    }


@celery_app.task(name="src.tasks.update_positions")
def update_positions():
    """13:35 更新持倉損益快照。"""
    logger.info("Updating position snapshots...")
    return {"status": "ok"}


@celery_app.task(name="src.tasks.run_daily_review")
def run_daily_review():
    """13:40 每日覆盤（Layer 1~3 + 優勢衰減偵測）。"""
    logger.info("Running daily review...")
    return {"status": "ok"}


@celery_app.task(name="src.tasks.check_monthly_trend")
def check_monthly_trend():
    """22:00 月底 200MA 趨勢檢查。"""
    import pandas as pd
    from datetime import date

    today = date.today()
    import calendar
    last_day = calendar.monthrange(today.year, today.month)[1]
    if today.day != last_day:
        return {"status": "skipped", "reason": "非月底"}

    from .data.fetcher import USMarketFetcher
    from .signals.ma200_filter import MA200Filter

    fetcher = USMarketFetcher()
    qqq_df = fetcher.get_historical("qqq", period="2y")
    ma_filter = MA200Filter(period=settings.ma_period)
    signal = ma_filter.calculate(qqq_df, "QQQ")

    logger.info(f"Monthly MA200 check: QQQ → {signal.state.value}")
    return {"state": signal.state.value, "distance_pct": signal.distance_pct}


@celery_app.task(name="src.tasks.daily_backup")
def daily_backup():
    """23:00 每日資料備份。"""
    logger.info("Daily backup started...")
    return {"status": "ok"}
