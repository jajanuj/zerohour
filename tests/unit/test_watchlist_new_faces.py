"""Watchlist 新面孔判定測試 — docs/report-optimization-plan.md Phase E。

只測純函數 compute_new_faces（save_watchlist 的 DB 讀寫沿用既有流程，
diff 邏輯全部集中在此純函數）。
"""
from src.database.helpers import compute_new_faces


class TestComputeNewFaces:

    def test_first_generation_all_false(self):
        # 首期無前期可比 → 全 False，避免全場標 NEW 的噪音
        result = compute_new_faces(["2330.TW", "2454.TW"], set())
        assert result == {"2330.TW": False, "2454.TW": False}

    def test_second_generation_marks_only_new(self):
        prev = {"2330.TW", "2317.TW"}
        result = compute_new_faces(["2330.TW", "2454.TW", "3711.TW"], prev)
        assert result["2330.TW"] is False   # 續留
        assert result["2454.TW"] is True    # 新進榜
        assert result["3711.TW"] is True    # 新進榜

    def test_all_carryover(self):
        prev = {"2330.TW", "2454.TW"}
        result = compute_new_faces(["2330.TW", "2454.TW"], prev)
        assert not any(result.values())

    def test_dropped_symbols_ignored(self):
        # 前期有但本期沒有的 symbol 不出現在結果中
        prev = {"2330.TW", "9999.TW"}
        result = compute_new_faces(["2330.TW"], prev)
        assert set(result.keys()) == {"2330.TW"}

    def test_empty_new_list(self):
        assert compute_new_faces([], {"2330.TW"}) == {}
        assert compute_new_faces([], set()) == {}
