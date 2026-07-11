"""Celery broker 輪詢頻率設定測試 — 2026-07-11 Upstash 免費額度耗盡事故。

事故：Kombu redis transport 預設 brpop_timeout=1 秒，worker 閒置時每秒發一次
BRPOP，24h 累積 86,400 次/天 ≈ 259 萬次/月，遠超 Upstash 免費 500,000 次/月
額度。修法：broker_transport_options.polling_interval 降低閒置輪詢頻率
（BRPOP 阻塞式，訊息到達立即喚醒，不影響任務即時性，只降低空轉重問頻率）。

本測試只檢查設定值存在且合理，不需要真的連線 Redis。
"""
from src.tasks import celery_app


class TestCeleryBrokerPollingConfig:

    def test_polling_interval_is_configured(self):
        opts = celery_app.conf.broker_transport_options
        assert opts.get("polling_interval") is not None

    def test_polling_interval_reduces_default_1s_poll_rate(self):
        # 預設 1 秒一次（86,400 次/天）；設定值必須明顯拉長，
        # 否則等於沒修（且要低於 60s，避免真斷線重連時等太久）
        interval = celery_app.conf.broker_transport_options["polling_interval"]
        assert 5 <= interval <= 60


class TestRedBeatMaxLoopInterval:
    """RedBeat tick 頻率上限（次要貢獻源，見 tasks.py 內註解的原始碼分析）。

    所有排程都是靜態 crontab，拉大 max_interval 只影響閒置多久 check-in
    一次，不影響任務觸發精確度（RedBeatScheduler.tick 每次都用
    crontab.is_due() 算精確剩餘秒數）。
    """

    def test_beat_max_loop_interval_is_configured(self):
        assert celery_app.conf.beat_max_loop_interval > 300  # 高於 Celery 預設

    def test_beat_max_loop_interval_within_sane_bounds(self):
        # 上限不能設到荒謬大：RedBeatScheduler.lock_timeout = max_interval * 5，
        # 太大會讓其他 worker 接手 lock 前等太久；1 小時（3600s）封頂
        assert 300 < celery_app.conf.beat_max_loop_interval <= 3600
