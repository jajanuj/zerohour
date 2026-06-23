import logging
from typing import Optional

logger = logging.getLogger(__name__)

DECAY_THRESHOLDS = {
    "win_rate_rolling_30d": 0.45,
    "sharpe_rolling_60d": 0.50,
    "profit_factor_rolling": 1.10,
    "consecutive_loss_days": 3,
}


class EdgeDecayDetector:
    """優勢衰減偵測器。"""

    def __init__(self, alerter=None):
        self.alerter = alerter

    async def check(self, rolling_stats: dict) -> list[str]:
        alerts = []

        win_rate = rolling_stats.get("win_rate_30d", 1.0)
        if win_rate < DECAY_THRESHOLDS["win_rate_rolling_30d"]:
            alerts.append(
                f"30日勝率 {win_rate:.1%} 低於門檻 {DECAY_THRESHOLDS['win_rate_rolling_30d']:.0%}"
            )

        sharpe = rolling_stats.get("sharpe_60d", 1.0)
        if sharpe < DECAY_THRESHOLDS["sharpe_rolling_60d"]:
            alerts.append(
                f"60日 Sharpe {sharpe:.2f} 低於門檻 {DECAY_THRESHOLDS['sharpe_rolling_60d']}"
            )

        pf = rolling_stats.get("profit_factor", 2.0)
        if pf < DECAY_THRESHOLDS["profit_factor_rolling"]:
            alerts.append(
                f"獲利因子 {pf:.2f} 低於門檻 {DECAY_THRESHOLDS['profit_factor_rolling']}"
            )

        consec_loss = rolling_stats.get("consecutive_loss_days", 0)
        if consec_loss >= DECAY_THRESHOLDS["consecutive_loss_days"]:
            alerts.append(f"連續 {consec_loss} 天虧損，觸發自動暫停")
            await self._trigger_auto_pause(reason=f"連續 {consec_loss} 天虧損")

        return alerts

    async def _trigger_auto_pause(self, reason: str) -> None:
        logger.critical(f"系統自動切換至觀察模式：{reason}")
        if self.alerter:
            await self.alerter.send(
                f"系統已自動切換至觀察模式\n原因：{reason}\n"
                f"請人工複核後設定 TRADING_MODE=paper 恢復",
            )
