import httpx
import asyncio
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    INFO = "ℹ️"
    SUCCESS = "✅"
    WARNING = "⚠️"
    CRITICAL = "🚨"


class TelegramAlerter:
    """Telegram 警報發送器。"""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self._enabled = bool(bot_token and chat_id)

    async def send(self, message: str, level: AlertLevel = AlertLevel.INFO) -> bool:
        if not self._enabled:
            logger.debug(f"[Telegram disabled] {level.value} {message[:80]}")
            return False

        text = f"{level.value} *ZeroHour 通知*\n\n{message}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                    },
                )
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"Telegram 發送失敗: {e}")
            return False

    async def signal_alert(self, signal: dict) -> bool:
        action = signal.get("final_action", "UNKNOWN")
        msg = (
            f"*新訊號觸發*\n"
            f"方向：{action}\n"
            f"標的：{signal.get('symbol', '-')}\n"
            f"建議倉位：{signal.get('suggested_position_pct', 0):.0%}\n"
            f"原因：{signal.get('reason', '-')}"
        )
        level = AlertLevel.SUCCESS if action == "BUY" else AlertLevel.WARNING
        return await self.send(msg, level)

    async def trade_executed(self, order: dict) -> bool:
        msg = (
            f"*訂單成交*\n"
            f"{order.get('direction')} {order.get('quantity')} {order.get('symbol')}\n"
            f"成交價：{order.get('filled_price')}\n"
            f"策略：{order.get('strategy', '-')}"
        )
        return await self.send(msg, AlertLevel.SUCCESS)

    async def stop_loss_triggered(self, symbol: str, loss_pct: float) -> bool:
        msg = (
            f"*停損觸發*\n"
            f"標的：{symbol}\n"
            f"虧損：{loss_pct:.1f}%\n"
            f"已自動出場"
        )
        return await self.send(msg, AlertLevel.CRITICAL)

    async def system_error(self, error_msg: str) -> bool:
        return await self.send(f"系統錯誤：{error_msg}", AlertLevel.CRITICAL)

    def send_sync(self, message: str, level: AlertLevel = AlertLevel.INFO) -> bool:
        return asyncio.run(self.send(message, level))
