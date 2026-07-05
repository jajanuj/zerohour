from datetime import datetime, timedelta

from scalper.grid import ActionType, DepthSnapshot, GridStrategy, Position, TradePrint


def make_grid(**overrides):
    params = dict(
        tick_size=5.0,
        depth_qty_threshold=20,
        aggressive_volume_threshold=30,
        aggressive_window_seconds=30,
        stop_loss_ticks=2,
        aggressive_cooldown_seconds=60,
    )
    params.update(overrides)
    return GridStrategy(**params)


def bootstrap_reference(grid, low=95.0, high=110.0, base_ts=datetime(2026, 7, 6, 9, 5)):
    """灌入一根完整的 09:00 bucket bar，跨到 10:05 觸發完成，reference 從此生效。
    完成後清空可能殘留的 pending_order 狀態，讓後續測試從乾淨狀態開始。"""
    grid.on_trade(TradePrint(ts=base_ts, price=(low + high) / 2, qty=1, side="buy_initiated"))
    grid.on_trade(TradePrint(ts=base_ts + timedelta(minutes=45), price=high, qty=1, side="buy_initiated"))
    grid.on_trade(TradePrint(ts=base_ts + timedelta(minutes=50), price=low, qty=1, side="sell_initiated"))
    grid.on_trade(TradePrint(
        ts=base_ts + timedelta(hours=1, minutes=0), price=(low + high) / 2, qty=1, side="buy_initiated",
    ))
    grid.state.pending_order_price = None
    grid.state.pending_order_direction = None


class TestEntryDecision:
    def test_no_action_before_reference_exists(self):
        grid = make_grid()
        actions = grid.on_trade(TradePrint(ts=datetime(2026, 7, 6, 9, 5), price=100.0, qty=1, side="buy_initiated"))
        assert actions == []

    def test_buy_when_price_below_mid(self):
        grid = make_grid()
        bootstrap_reference(grid, low=95.0, high=110.0)  # mid = 102.5

        actions = grid.on_trade(TradePrint(ts=datetime(2026, 7, 6, 10, 10), price=98.0, qty=1, side="buy_initiated"))
        assert len(actions) == 1
        assert actions[0].type == ActionType.PLACE_LIMIT
        assert actions[0].direction == "BUY"
        assert actions[0].price == 98.0

    def test_sell_when_price_above_mid(self):
        grid = make_grid()
        bootstrap_reference(grid, low=95.0, high=110.0)

        actions = grid.on_trade(TradePrint(ts=datetime(2026, 7, 6, 10, 10), price=106.0, qty=1, side="sell_initiated"))
        assert len(actions) == 1
        assert actions[0].type == ActionType.PLACE_LIMIT
        assert actions[0].direction == "SELL"
        assert actions[0].price == 106.0


class TestAdverseSelectionFilter:
    def test_depth_filter_blocks_thin_opposite_side(self):
        grid = make_grid(depth_qty_threshold=20)
        bootstrap_reference(grid, low=95.0, high=110.0)

        grid.on_depth(DepthSnapshot(
            ts=datetime(2026, 7, 6, 10, 9), bid_qty_total=50, ask_qty_total=5, best_bid_qty=10, best_ask_qty=3,
        ))
        actions = grid.on_trade(TradePrint(ts=datetime(2026, 7, 6, 10, 10), price=98.0, qty=1, side="buy_initiated"))
        assert actions == []

    def test_depth_filter_allows_thick_opposite_side(self):
        grid = make_grid(depth_qty_threshold=20)
        bootstrap_reference(grid, low=95.0, high=110.0)

        grid.on_depth(DepthSnapshot(
            ts=datetime(2026, 7, 6, 10, 9), bid_qty_total=50, ask_qty_total=25, best_bid_qty=10, best_ask_qty=8,
        ))
        actions = grid.on_trade(TradePrint(ts=datetime(2026, 7, 6, 10, 10), price=98.0, qty=1, side="buy_initiated"))
        assert len(actions) == 1
        assert actions[0].type == ActionType.PLACE_LIMIT

    def test_aggressive_flow_halts_and_resumes_after_cooldown(self):
        grid = make_grid(aggressive_volume_threshold=30, aggressive_window_seconds=30, aggressive_cooldown_seconds=60)
        bootstrap_reference(grid, low=95.0, high=110.0)

        base = datetime(2026, 7, 6, 10, 10)
        grid.on_trade(TradePrint(ts=base, price=100.0, qty=10, side="buy_initiated"))
        grid.on_trade(TradePrint(ts=base + timedelta(seconds=5), price=100.0, qty=10, side="buy_initiated"))
        grid.on_trade(TradePrint(ts=base + timedelta(seconds=10), price=100.0, qty=15, side="buy_initiated"))
        assert grid.state.halted is True
        assert grid.state.halt_reason == "AGGRESSIVE_FLOW"

        grid.on_trade(TradePrint(ts=base + timedelta(seconds=30), price=100.0, qty=1, side="buy_initiated"))
        assert grid.state.halted is True  # 冷卻中

        grid.on_trade(TradePrint(ts=base + timedelta(seconds=71), price=100.0, qty=1, side="buy_initiated"))
        assert grid.state.halted is False  # 60 秒冷卻已過


class TestRequote:
    def test_requote_cancels_old_order_on_price_change(self):
        grid = make_grid()
        bootstrap_reference(grid, low=95.0, high=110.0)

        actions1 = grid.on_trade(TradePrint(ts=datetime(2026, 7, 6, 10, 10), price=98.0, qty=1, side="buy_initiated"))
        assert actions1[0].type == ActionType.PLACE_LIMIT
        assert grid.state.pending_order_price == 98.0

        actions2 = grid.on_trade(TradePrint(ts=datetime(2026, 7, 6, 10, 11), price=99.0, qty=1, side="buy_initiated"))
        assert [a.type for a in actions2] == [ActionType.CANCEL, ActionType.PLACE_LIMIT]
        assert actions2[0].price == 98.0
        assert actions2[1].price == 99.0

    def test_same_price_and_direction_no_duplicate_order(self):
        grid = make_grid()
        bootstrap_reference(grid, low=95.0, high=110.0)

        grid.on_trade(TradePrint(ts=datetime(2026, 7, 6, 10, 10), price=98.0, qty=1, side="buy_initiated"))
        actions2 = grid.on_trade(TradePrint(ts=datetime(2026, 7, 6, 10, 11), price=98.0, qty=1, side="buy_initiated"))
        assert actions2 == []


class TestFillAndExit:
    def test_on_order_filled_opens_position_and_places_take_profit(self):
        grid = make_grid(tick_size=5.0)
        actions = grid.on_order_filled(ts=datetime(2026, 7, 6, 10, 10), price=98.0, direction="BUY")

        assert grid.state.position == Position.LONG
        assert grid.state.entry_price == 98.0
        assert len(actions) == 1
        assert actions[0].type == ActionType.PLACE_LIMIT
        assert actions[0].direction == "SELL"
        assert actions[0].price == 103.0

    def test_on_order_filled_short_take_profit_below_entry(self):
        grid = make_grid(tick_size=5.0)
        actions = grid.on_order_filled(ts=datetime(2026, 7, 6, 10, 10), price=98.0, direction="SELL")

        assert grid.state.position == Position.SHORT
        assert actions[0].direction == "BUY"
        assert actions[0].price == 93.0

    def test_stop_loss_triggers_after_two_ticks_adverse(self):
        grid = make_grid(tick_size=5.0, stop_loss_ticks=2)
        grid.on_order_filled(ts=datetime(2026, 7, 6, 10, 10), price=100.0, direction="BUY")

        actions = grid.on_trade(TradePrint(ts=datetime(2026, 7, 6, 10, 11), price=89.0, qty=1, side="sell_initiated"))
        assert len(actions) == 1
        assert actions[0].type == ActionType.MARKET_EXIT
        assert actions[0].direction == "SELL"

    def test_no_stop_loss_below_threshold(self):
        grid = make_grid(tick_size=5.0, stop_loss_ticks=2)
        grid.on_order_filled(ts=datetime(2026, 7, 6, 10, 10), price=100.0, direction="BUY")

        actions = grid.on_trade(TradePrint(ts=datetime(2026, 7, 6, 10, 11), price=91.0, qty=1, side="sell_initiated"))
        assert actions == []

    def test_on_position_closed_resets_state(self):
        grid = make_grid()
        grid.on_order_filled(ts=datetime(2026, 7, 6, 10, 10), price=100.0, direction="BUY")
        grid.on_position_closed()

        assert grid.state.position == Position.FLAT
        assert grid.state.entry_price is None
        assert grid.state.entry_ts is None


class TestRangeInvalidation:
    def test_breakout_while_flat_halts_and_cancels_pending(self):
        grid = make_grid()
        bootstrap_reference(grid, low=95.0, high=110.0)
        grid.on_trade(TradePrint(ts=datetime(2026, 7, 6, 10, 10), price=98.0, qty=1, side="buy_initiated"))
        assert grid.state.pending_order_price == 98.0

        actions = grid.on_trade(TradePrint(ts=datetime(2026, 7, 6, 10, 15), price=111.0, qty=1, side="buy_initiated"))
        types = [a.type for a in actions]
        assert ActionType.CANCEL in types
        assert ActionType.HALT in types
        assert grid.state.halted is True
        assert grid.state.halt_reason == "RANGE_BREAKOUT"
        assert grid.state.pending_order_price is None

    def test_breakout_while_in_position_forces_immediate_exit(self):
        grid = make_grid(stop_loss_ticks=10)  # 停損設很寬，確認是 breakout 造成出場而非停損
        bootstrap_reference(grid, low=95.0, high=110.0)
        grid.on_order_filled(ts=datetime(2026, 7, 6, 10, 10), price=98.0, direction="BUY")

        actions = grid.on_trade(TradePrint(ts=datetime(2026, 7, 6, 10, 15), price=111.0, qty=1, side="buy_initiated"))
        assert len(actions) == 1
        assert actions[0].type == ActionType.MARKET_EXIT
        assert actions[0].direction == "SELL"
        assert grid.state.halted is True
        assert grid.state.halt_reason == "RANGE_BREAKOUT"

    def test_resumes_when_next_bar_completes(self):
        grid = make_grid()
        bootstrap_reference(grid, low=95.0, high=110.0)

        grid.on_trade(TradePrint(ts=datetime(2026, 7, 6, 10, 20), price=111.0, qty=1, side="buy_initiated"))
        assert grid.state.halted is True

        grid.on_trade(TradePrint(ts=datetime(2026, 7, 6, 10, 40), price=105.0, qty=1, side="buy_initiated"))
        assert grid.state.halted is True  # 仍在同一根 K 內

        grid.on_trade(TradePrint(ts=datetime(2026, 7, 6, 11, 5), price=105.0, qty=1, side="buy_initiated"))
        assert grid.state.halted is False  # 跨到新的一根 K，恢復
