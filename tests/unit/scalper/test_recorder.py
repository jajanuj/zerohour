from datetime import date, datetime, timedelta

from scalper.recorder import TickRecorder


class TestTickRecorder:
    def test_creates_db_file_per_trading_date(self, tmp_path):
        recorder = TickRecorder(trading_date=date(2026, 7, 6), data_dir=tmp_path)
        assert recorder.db_path.name == "ticks_20260706.db"
        assert recorder.db_path.exists()
        recorder.close()

    def test_record_and_validate_clean_data(self, tmp_path):
        recorder = TickRecorder(trading_date=date(2026, 7, 6), data_dir=tmp_path)
        base = datetime(2026, 7, 6, 9, 5, 0)
        recorder.record_tick(base, "MXFR1", 100.0, 1, "buy_initiated")
        recorder.record_tick(base + timedelta(seconds=1), "MXFR1", 100.5, 2, "sell_initiated")
        recorder.commit()

        report = recorder.validate()
        assert report["n_ticks"] == 2
        assert report["monotonic"] is True
        assert report["nan_price_count"] == 0
        assert report["max_gap_seconds"] == 1.0
        recorder.close()

    def test_validate_detects_large_gap(self, tmp_path):
        recorder = TickRecorder(trading_date=date(2026, 7, 6), data_dir=tmp_path)
        base = datetime(2026, 7, 6, 9, 5, 0)
        recorder.record_tick(base, "MXFR1", 100.0, 1, "buy_initiated")
        recorder.record_tick(base + timedelta(seconds=90), "MXFR1", 100.5, 2, "sell_initiated")
        recorder.commit()

        report = recorder.validate()
        assert report["max_gap_seconds"] == 90.0
        recorder.close()

    def test_record_depth(self, tmp_path):
        recorder = TickRecorder(trading_date=date(2026, 7, 6), data_dir=tmp_path)
        recorder.record_depth(datetime(2026, 7, 6, 9, 5), "MXFR1", 50, 40, 10, 8)
        recorder.commit()

        cur = recorder._conn.execute("SELECT COUNT(*) FROM depth")
        assert cur.fetchone()[0] == 1
        recorder.close()
