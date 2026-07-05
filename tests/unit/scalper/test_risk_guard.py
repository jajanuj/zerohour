from datetime import date, datetime, timedelta

from scalper.risk_guard import RiskGuard, is_settlement_day


class TestSettlementDay:
    def test_third_wednesday_is_settlement_day(self):
        # 2026-07：週三為 1,8,15,22,29 → 第三個週三是 7/15
        assert is_settlement_day(date(2026, 7, 15)) is True

    def test_other_wednesdays_are_not_settlement_day(self):
        assert is_settlement_day(date(2026, 7, 8)) is False
        assert is_settlement_day(date(2026, 7, 22)) is False

    def test_non_wednesday_is_never_settlement_day(self):
        assert is_settlement_day(date(2026, 7, 16)) is False


def make_guard(**overrides):
    params = dict(
        daily_loss_limit=3000.0,
        consecutive_loss_pause=3,
        consecutive_loss_pause_minutes=30,
        max_inventory_lots=1,
        session_start="09:05",
        session_end="13:15",
    )
    params.update(overrides)
    return RiskGuard(**params)


class TestCanEnter:
    def test_allowed_within_session_no_blocks(self):
        guard = make_guard()
        allowed, reason = guard.can_enter(datetime(2026, 7, 6, 10, 0))  # 週一
        assert allowed is True

    def test_blocked_outside_session(self):
        guard = make_guard()
        allowed, reason = guard.can_enter(datetime(2026, 7, 6, 8, 30))
        assert allowed is False
        assert "時段" in reason

    def test_blocked_on_settlement_day(self):
        guard = make_guard()
        allowed, reason = guard.can_enter(datetime(2026, 7, 15, 10, 0))
        assert allowed is False
        assert "結算" in reason

    def test_blocked_on_blackout_date(self):
        guard = make_guard(blackout_dates={date(2026, 7, 6)})
        allowed, reason = guard.can_enter(datetime(2026, 7, 6, 10, 0))
        assert allowed is False

    def test_blocked_when_inventory_at_cap(self):
        guard = make_guard(max_inventory_lots=1)
        guard.record_entry(datetime(2026, 7, 6, 10, 0))
        allowed, reason = guard.can_enter(datetime(2026, 7, 6, 10, 1))
        assert allowed is False
        assert "庫存" in reason

    def test_entry_and_exit_frees_inventory_slot(self):
        guard = make_guard(max_inventory_lots=1)
        guard.record_entry(datetime(2026, 7, 6, 10, 0))
        guard.record_exit_pnl(datetime(2026, 7, 6, 10, 5), net_pnl=200.0)
        allowed, _ = guard.can_enter(datetime(2026, 7, 6, 10, 6))
        assert allowed is True


class TestDailyFuse:
    def test_daily_loss_limit_halts_for_rest_of_day(self):
        guard = make_guard(daily_loss_limit=3000.0, max_inventory_lots=5)
        ts = datetime(2026, 7, 6, 10, 0)
        guard.record_exit_pnl(ts, net_pnl=-1500.0)
        guard.record_exit_pnl(ts, net_pnl=-1600.0)

        allowed, reason = guard.can_enter(datetime(2026, 7, 6, 10, 30))
        assert allowed is False
        assert "熔斷" in reason

    def test_below_daily_loss_limit_still_allowed(self):
        guard = make_guard(daily_loss_limit=3000.0, max_inventory_lots=5)
        guard.record_exit_pnl(datetime(2026, 7, 6, 10, 0), net_pnl=-1000.0)
        allowed, _ = guard.can_enter(datetime(2026, 7, 6, 10, 1))
        assert allowed is True

    def test_new_trading_day_resets_fuse(self):
        guard = make_guard(daily_loss_limit=3000.0, max_inventory_lots=5)
        guard.record_exit_pnl(datetime(2026, 7, 6, 10, 0), net_pnl=-3500.0)
        assert guard.can_enter(datetime(2026, 7, 6, 10, 30))[0] is False

        allowed, _ = guard.can_enter(datetime(2026, 7, 7, 9, 30))
        assert allowed is True


class TestConsecutiveLossPause:
    def test_three_consecutive_losses_pause_30_minutes(self):
        guard = make_guard(consecutive_loss_pause=3, consecutive_loss_pause_minutes=30, max_inventory_lots=5)
        ts = datetime(2026, 7, 6, 10, 0)
        guard.record_exit_pnl(ts, net_pnl=-100.0)
        guard.record_exit_pnl(ts, net_pnl=-100.0)
        guard.record_exit_pnl(ts, net_pnl=-100.0)

        allowed, reason = guard.can_enter(ts + timedelta(minutes=5))
        assert allowed is False
        assert "冷卻" in reason

        allowed2, _ = guard.can_enter(ts + timedelta(minutes=31))
        assert allowed2 is True

    def test_win_resets_consecutive_loss_counter(self):
        guard = make_guard(consecutive_loss_pause=3, max_inventory_lots=5)
        ts = datetime(2026, 7, 6, 10, 0)
        guard.record_exit_pnl(ts, net_pnl=-100.0)
        guard.record_exit_pnl(ts, net_pnl=-100.0)
        guard.record_exit_pnl(ts, net_pnl=50.0)  # 勝場重置計數
        guard.record_exit_pnl(ts, net_pnl=-100.0)

        allowed, _ = guard.can_enter(ts + timedelta(minutes=1))
        assert allowed is True
