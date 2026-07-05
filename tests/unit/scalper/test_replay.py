from datetime import datetime, timedelta

from scalper.grid import DepthSnapshot, GridStrategy, TradePrint
from scalper.replay import PessimisticFillSimulator, compute_cost, run_backtest
from scalper.risk_guard import RiskGuard


class TestPessimisticFillSimulator:
    def test_no_fill_within_ack_delay(self):
        sim = PessimisticFillSimulator(order_ack_delay_ms=300)
        t0 = datetime(2026, 7, 6, 10, 0, 0)
        sim.submit("BUY", price=100.0, qty=1, placed_ts=t0, queue_ahead=0)

        filled = sim.on_trade_print(t0 + timedelta(milliseconds=100), price=99.0, qty=5)
        assert filled == []

    def test_price_through_fills_after_delay(self):
        sim = PessimisticFillSimulator(order_ack_delay_ms=300)
        t0 = datetime(2026, 7, 6, 10, 0, 0)
        order_id = sim.submit("BUY", price=100.0, qty=1, placed_ts=t0, queue_ahead=999)

        filled = sim.on_trade_print(t0 + timedelta(milliseconds=400), price=99.5, qty=1)
        assert len(filled) == 1
        assert filled[0][0] == order_id
        assert filled[0][1] == 100.0

    def test_touch_only_does_not_fill(self):
        """只是「碰到」掛單價，不算穿價——若排隊量夠大，不該成交。"""
        sim = PessimisticFillSimulator(order_ack_delay_ms=300)
        t0 = datetime(2026, 7, 6, 10, 0, 0)
        sim.submit("BUY", price=100.0, qty=1, placed_ts=t0, queue_ahead=1000)

        filled = sim.on_trade_print(t0 + timedelta(milliseconds=400), price=100.0, qty=5)
        assert filled == []

    def test_queue_ahead_consumption_then_fill(self):
        sim = PessimisticFillSimulator(order_ack_delay_ms=300)
        t0 = datetime(2026, 7, 6, 10, 0, 0)
        order_id = sim.submit("SELL", price=100.0, qty=1, placed_ts=t0, queue_ahead=10)

        after = t0 + timedelta(milliseconds=400)
        filled1 = sim.on_trade_print(after, price=100.0, qty=6)
        assert filled1 == []  # 10-6=4 剩餘，還沒輪到我

        filled2 = sim.on_trade_print(after + timedelta(seconds=1), price=100.0, qty=4)
        assert len(filled2) == 1
        assert filled2[0][0] == order_id

    def test_cancel_removes_resting_order(self):
        sim = PessimisticFillSimulator(order_ack_delay_ms=300)
        t0 = datetime(2026, 7, 6, 10, 0, 0)
        order_id = sim.submit("BUY", price=100.0, qty=1, placed_ts=t0, queue_ahead=0)
        sim.cancel(order_id)

        filled = sim.on_trade_print(t0 + timedelta(seconds=1), price=99.0, qty=5)
        assert filled == []

    def test_cancel_by_direction_removes_all_matching(self):
        sim = PessimisticFillSimulator(order_ack_delay_ms=300)
        t0 = datetime(2026, 7, 6, 10, 0, 0)
        sim.submit("SELL", price=100.0, qty=1, placed_ts=t0, queue_ahead=0)
        sim.cancel_by_direction("SELL")

        filled = sim.on_trade_print(t0 + timedelta(seconds=1), price=101.0, qty=5)
        assert filled == []


class TestComputeCost:
    def test_cost_scales_with_contract_value(self):
        cost = compute_cost(price=1000.0, qty=1, fee_per_side=25.0, tax_rate=0.00002, contract_multiplier=100.0)
        # 契約價值 = 1000*1*100 = 100,000；稅 = 100,000*0.00002 = 2
        assert abs(cost - 27.0) < 1e-9


def make_grid_and_guard(tick_size=5.0, stop_loss_ticks=2):
    grid = GridStrategy(
        tick_size=tick_size,
        depth_qty_threshold=0,  # 測試不驗逆選擇過濾，門檻設0一律放行
        aggressive_volume_threshold=999999,
        aggressive_window_seconds=30,
        stop_loss_ticks=stop_loss_ticks,
        aggressive_cooldown_seconds=60,
    )
    guard = RiskGuard(
        daily_loss_limit=999999.0,
        consecutive_loss_pause=999,
        consecutive_loss_pause_minutes=30,
        max_inventory_lots=1,
        session_start="00:00",
        session_end="23:59",
    )
    return grid, guard


class TestRunBacktestEndToEnd:
    def test_take_profit_round_trip_produces_positive_net_pnl(self):
        grid, guard = make_grid_and_guard(tick_size=5.0)
        t0 = datetime(2026, 7, 6, 9, 5, 0)

        events = [
            # 建立參考區間 [95, 110]（09:00 bucket）
            TradePrint(ts=t0, price=102.5, qty=1, side="buy_initiated"),
            TradePrint(ts=t0 + timedelta(minutes=45), price=110.0, qty=1, side="buy_initiated"),
            TradePrint(ts=t0 + timedelta(minutes=50), price=95.0, qty=1, side="sell_initiated"),
            # 五檔量設 1，方便單筆 qty=1 就吃完排隊、不需要用穿價
            DepthSnapshot(
                ts=t0 + timedelta(hours=1), bid_qty_total=50, ask_qty_total=50,
                best_bid_qty=1, best_ask_qty=1,
            ),
            # 跨到 10:00 bucket → 09:00 bar 完成、reference=[95,110]生效，98<mid(102.5)→掛BUY@98
            TradePrint(ts=t0 + timedelta(hours=1, seconds=1), price=98.0, qty=1, side="sell_initiated"),
            # 400ms後、同價位（不觸發撤舊掛新），qty吃完queue_ahead(1)→進場成交@98
            TradePrint(ts=t0 + timedelta(hours=1, seconds=1, milliseconds=400), price=98.0, qty=1, side="sell_initiated"),
            # 再400ms後（滿足停利單300ms下單延遲），價格穿過103(98+1tick)→停利成交
            TradePrint(ts=t0 + timedelta(hours=1, seconds=1, milliseconds=800), price=104.0, qty=1, side="buy_initiated"),
        ]

        result = run_backtest(
            events, grid, guard,
            tick_size=5.0, tick_value=500.0, fee_per_side=25.0, tax_rate=0.00002,
            contract_multiplier=100.0, order_ack_delay_ms=300,
        )

        assert result.n_trades == 1
        assert result.trades[0].exit_reason == "TP"
        assert result.trades[0].ticks_pnl == 1.0
        assert result.net_pnl > 0  # 1 tick(500) 扣掉費稅仍為正

    def test_stop_loss_round_trip_produces_negative_net_pnl(self):
        # 用寬區間 [50,150] 讓 entry 附近有足夠空間，2 ticks(10點) 停損不會同時撞到區間邊界
        grid, guard = make_grid_and_guard(tick_size=5.0, stop_loss_ticks=2)
        t0 = datetime(2026, 7, 6, 9, 5, 0)

        events = [
            TradePrint(ts=t0, price=100.0, qty=1, side="buy_initiated"),
            TradePrint(ts=t0 + timedelta(minutes=45), price=150.0, qty=1, side="buy_initiated"),
            TradePrint(ts=t0 + timedelta(minutes=50), price=50.0, qty=1, side="sell_initiated"),
            DepthSnapshot(
                ts=t0 + timedelta(hours=1), bid_qty_total=50, ask_qty_total=50,
                best_bid_qty=1, best_ask_qty=1,
            ),
            # mid=100，90<100→掛BUY@90
            TradePrint(ts=t0 + timedelta(hours=1, seconds=1), price=90.0, qty=1, side="sell_initiated"),
            # 同價成交@90
            TradePrint(ts=t0 + timedelta(hours=1, seconds=1, milliseconds=400), price=90.0, qty=1, side="sell_initiated"),
            # 反向 2 ticks（90-10=80，仍 >50 不算突破區間）觸發停損市價出場
            TradePrint(ts=t0 + timedelta(hours=1, seconds=1, milliseconds=800), price=80.0, qty=1, side="sell_initiated"),
        ]

        result = run_backtest(
            events, grid, guard,
            tick_size=5.0, tick_value=500.0, fee_per_side=25.0, tax_rate=0.00002,
            contract_multiplier=100.0, order_ack_delay_ms=300,
        )

        assert result.n_trades == 1
        assert result.trades[0].exit_reason == "SL"
        assert result.net_pnl < 0

    def test_risk_guard_blocks_new_entry_when_inventory_full(self):
        grid, guard = make_grid_and_guard(tick_size=5.0)
        guard.record_entry(datetime(2026, 7, 6, 9, 0))  # 手動塞滿庫存上限(1口)
        t0 = datetime(2026, 7, 6, 9, 5, 0)

        events = [
            TradePrint(ts=t0, price=102.5, qty=1, side="buy_initiated"),
            TradePrint(ts=t0 + timedelta(minutes=45), price=110.0, qty=1, side="buy_initiated"),
            TradePrint(ts=t0 + timedelta(minutes=50), price=95.0, qty=1, side="sell_initiated"),
            DepthSnapshot(
                ts=t0 + timedelta(hours=1), bid_qty_total=50, ask_qty_total=50,
                best_bid_qty=1, best_ask_qty=1,
            ),
            TradePrint(ts=t0 + timedelta(hours=1, seconds=1), price=98.0, qty=1, side="sell_initiated"),
            TradePrint(ts=t0 + timedelta(hours=1, seconds=1, milliseconds=400), price=98.0, qty=1, side="sell_initiated"),
        ]

        result = run_backtest(
            events, grid, guard,
            tick_size=5.0, tick_value=500.0, fee_per_side=25.0, tax_rate=0.00002,
            contract_multiplier=100.0, order_ack_delay_ms=300,
        )

        assert result.n_trades == 0  # RiskGuard 擋下進場，不該有任何成交
