from datetime import datetime

from scalper.range_engine import BarAggregator, RangeEngine


class TestBarAggregator:
    def test_first_tick_starts_bar_no_completion(self):
        agg = BarAggregator(bar_minutes=60)
        completed = agg.on_tick(datetime(2026, 7, 6, 9, 5), 100.0)
        assert completed is None
        assert agg.current_bar.open == 100.0

    def test_same_bucket_updates_high_low(self):
        agg = BarAggregator(bar_minutes=60)
        agg.on_tick(datetime(2026, 7, 6, 9, 5), 100.0)
        agg.on_tick(datetime(2026, 7, 6, 9, 30), 105.0)
        agg.on_tick(datetime(2026, 7, 6, 9, 45), 95.0)
        bar = agg.current_bar
        assert bar.high == 105.0
        assert bar.low == 95.0
        assert bar.close == 95.0

    def test_new_bucket_emits_completed_bar(self):
        agg = BarAggregator(bar_minutes=60)
        agg.on_tick(datetime(2026, 7, 6, 9, 5), 100.0)
        agg.on_tick(datetime(2026, 7, 6, 9, 50), 110.0)
        completed = agg.on_tick(datetime(2026, 7, 6, 10, 5), 108.0)
        assert completed is not None
        assert completed.high == 110.0
        assert completed.low == 100.0
        assert agg.current_bar.open == 108.0


class TestRangeEngine:
    def test_no_reference_before_first_bar_completes(self):
        engine = RangeEngine()
        engine.on_tick(datetime(2026, 7, 6, 9, 5), 100.0)
        assert engine.reference is None

    def test_reference_set_after_bar_completes(self):
        engine = RangeEngine()
        engine.on_tick(datetime(2026, 7, 6, 9, 5), 100.0)
        engine.on_tick(datetime(2026, 7, 6, 9, 50), 110.0)
        engine.on_tick(datetime(2026, 7, 6, 9, 55), 95.0)
        engine.on_tick(datetime(2026, 7, 6, 10, 5), 105.0)
        assert engine.reference is not None
        assert engine.reference.low == 95.0
        assert engine.reference.high == 110.0
        assert engine.reference.mid == 102.5

    def test_breakout_detection(self):
        engine = RangeEngine()
        engine.on_tick(datetime(2026, 7, 6, 9, 5), 100.0)
        engine.on_tick(datetime(2026, 7, 6, 9, 50), 110.0)
        engine.on_tick(datetime(2026, 7, 6, 10, 5), 105.0)
        assert engine.reference.is_breakout(111.0) is True
        assert engine.reference.is_breakout(105.0) is False
        assert engine.reference.is_breakout(99.0) is True

    def test_cross_day_discards_reference_until_first_bar_of_new_day(self):
        engine = RangeEngine()
        engine.on_tick(datetime(2026, 7, 6, 9, 5), 100.0)
        engine.on_tick(datetime(2026, 7, 6, 9, 50), 110.0)
        engine.on_tick(datetime(2026, 7, 6, 10, 5), 105.0)
        assert engine.reference is not None

        # 隔天第一筆 tick：舊區間應被捨棄
        engine.on_tick(datetime(2026, 7, 7, 9, 5), 200.0)
        assert engine.reference is None

    def test_missing_bucket_does_not_fabricate_empty_bar(self):
        """跳過一整個小時沒有 tick，聚合器不應該為那個空窗 bucket 憑空生出K棒——
        只有真正出現過 tick 的 bucket 才會完成/生效（即使只有一筆，也是真實資料）。"""
        engine = RangeEngine()
        engine.on_tick(datetime(2026, 7, 6, 9, 5), 100.0)
        engine.on_tick(datetime(2026, 7, 6, 9, 50), 110.0)
        # 這筆完成 09:00 bucket，同時開始 10:00 bucket（目前只有這 1 筆）
        engine.on_tick(datetime(2026, 7, 6, 10, 5), 105.0)
        assert engine.reference.low == 100.0
        assert engine.reference.high == 110.0

        # 跳過 11:00 整根，直接送 12:10 的 tick：
        # 完成的應是「10:00」bucket（僅 10:05 這 1 筆，low=high=105），
        # 而不是憑空生出「11:00」的K棒，也不是維持舊值不變
        engine.on_tick(datetime(2026, 7, 6, 12, 10), 106.0)
        assert engine.reference.low == 105.0
        assert engine.reference.high == 105.0
        assert engine.reference.source_bar_start == datetime(2026, 7, 6, 10, 0)
