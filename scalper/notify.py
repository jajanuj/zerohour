"""Discord webhook 推播（策略三專用，獨立於 src/alerts/discord.py，不 import src.）。"""

import logging

import httpx

logger = logging.getLogger(__name__)


class ScalperNotifier:
    def __init__(self, webhook_url: str, timeout: float = 5.0):
        self.webhook_url = webhook_url
        self.timeout = timeout

    def send(self, content: str) -> bool:
        if not self.webhook_url:
            logger.warning("SCALPER_DISCORD_WEBHOOK 未設定，略過推播: %s", content[:80])
            return False
        try:
            resp = httpx.post(self.webhook_url, json={"content": content}, timeout=self.timeout)
            return resp.status_code < 300
        except Exception as e:
            logger.error("Discord 推播失敗: %s", e)
            return False

    def trade_filled(self, symbol: str, direction: str, price: float, qty: int) -> bool:
        return self.send(f"[策略三] 成交 {direction} {symbol} {qty}口 @ {price}")

    def fuse_triggered(self, reason: str) -> bool:
        return self.send(f"[策略三] 熔斷觸發：{reason}")

    def disconnected(self, detail: str) -> bool:
        return self.send(f"[策略三] 斷線：{detail}")

    def daily_summary(self, trading_date, n_trades: int, win_rate: float, net_pnl: float) -> bool:
        return self.send(
            f"[策略三] {trading_date} 收盤摘要：{n_trades} 筆，勝率 {win_rate:.0%}，淨損益 {net_pnl:+.0f} 元"
        )
