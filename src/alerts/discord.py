"""Discord Webhook 推播模組。"""
import asyncio
import logging
from datetime import datetime
from enum import Enum

import httpx

logger = logging.getLogger(__name__)

# Discord embed colors
_COLOR = {
    "BUY":       0x57F287,  # green
    "SELL":      0xED4245,  # red
    "HOLD":      0x5865F2,  # blue
    "EXIT_ALL":  0xED4245,  # red
    "WARNING":   0xFEE75C,  # yellow
    "CRITICAL":  0xED4245,  # red
    "INFO":      0x5865F2,  # blue
}


class DiscordAlerter:
    """Discord Webhook 推播器。"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self._enabled = bool(webhook_url)

    async def _post(self, payload: dict) -> bool:
        if not self._enabled:
            logger.debug(f"[Discord disabled] payload={payload.get('embeds', [{}])[0].get('title', '')}")
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.webhook_url, json=payload)
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"Discord webhook failed: {e}")
            return False

    async def signal_alert(
        self,
        action: str,
        symbol: str,
        confidence: float,
        s1_state: str,
        s2_direction: str,
        position_pct: float,
        stop_loss_pct: float,
        reason: str,
    ) -> bool:
        color = _COLOR.get(action, _COLOR["INFO"])
        action_label = {"BUY": "做多", "SELL": "出場", "HOLD": "觀望", "EXIT_ALL": "強制清倉"}.get(action, action)

        embed = {
            "title": f"ZeroHour 訊號 — {action_label} {symbol}",
            "color": color,
            "fields": [
                {"name": "S3 決策", "value": action_label, "inline": True},
                {"name": "S1 趨勢", "value": s1_state, "inline": True},
                {"name": "S2 方向", "value": s2_direction, "inline": True},
                {"name": "信心度", "value": f"{confidence:.0%}", "inline": True},
                {"name": "建議倉位", "value": f"{position_pct:.0%}", "inline": True},
                {"name": "停損", "value": f"{stop_loss_pct:.1%}" if stop_loss_pct else "—", "inline": True},
                {"name": "原因", "value": reason or "—", "inline": False},
            ],
            "footer": {"text": "ZeroHour Trading System"},
            "timestamp": datetime.utcnow().isoformat(),
        }
        return await self._post({"embeds": [embed]})

    async def trade_executed(
        self,
        direction: str,
        symbol: str,
        quantity: float,
        fill_price: float,
        stop_loss_price: float = 0,
    ) -> bool:
        color = _COLOR.get(direction, _COLOR["INFO"])
        label = "買進" if direction == "BUY" else "賣出"
        embed = {
            "title": f"ZeroHour Paper 成交 — {label} {symbol}",
            "color": color,
            "fields": [
                {"name": "方向", "value": label, "inline": True},
                {"name": "數量", "value": f"{quantity:,.0f} 股", "inline": True},
                {"name": "成交價", "value": f"NT$ {fill_price:,.2f}", "inline": True},
            ],
            "footer": {"text": "Paper Trading"},
            "timestamp": datetime.utcnow().isoformat(),
        }
        if stop_loss_price:
            embed["fields"].append(
                {"name": "停損價", "value": f"NT$ {stop_loss_price:,.2f}", "inline": True}
            )
        return await self._post({"embeds": [embed]})

    async def stop_loss_triggered(
        self,
        symbol: str,
        current_price: float,
        stop_price: float,
        pnl: float = 0,
    ) -> bool:
        embed = {
            "title": f"ZeroHour 停損觸發 — {symbol}",
            "color": _COLOR["CRITICAL"],
            "fields": [
                {"name": "標的", "value": symbol, "inline": True},
                {"name": "現價", "value": f"NT$ {current_price:,.2f}", "inline": True},
                {"name": "停損價", "value": f"NT$ {stop_price:,.2f}", "inline": True},
                {"name": "損益", "value": f"NT$ {pnl:+,.0f}", "inline": True},
            ],
            "footer": {"text": "ZeroHour Trading System"},
            "timestamp": datetime.utcnow().isoformat(),
        }
        return await self._post({"embeds": [embed]})

    async def daily_summary(
        self,
        total_equity: float,
        daily_pnl: float,
        total_return_pct: float,
        positions: list[dict],
    ) -> bool:
        pos_text = "\n".join(
            f"{p['symbol']}: {p['quantity']:,.0f} 股 @ {p['avg_entry_price']:,.2f}"
            f" (損益: {(p.get('unrealized_pnl') or 0):+,.0f})"
            for p in positions
        ) or "無持倉"

        color = _COLOR["BUY"] if daily_pnl >= 0 else _COLOR["SELL"]
        embed = {
            "title": "ZeroHour 每日收盤摘要",
            "color": color,
            "fields": [
                {"name": "總資產", "value": f"NT$ {total_equity:,.0f}", "inline": True},
                {"name": "今日損益", "value": f"NT$ {daily_pnl:+,.0f}", "inline": True},
                {"name": "總報酬率", "value": f"{total_return_pct:+.2%}", "inline": True},
                {"name": "目前持倉", "value": pos_text, "inline": False},
            ],
            "footer": {"text": "ZeroHour Trading System"},
            "timestamp": datetime.utcnow().isoformat(),
        }
        return await self._post({"embeds": [embed]})

    async def daily_review(
        self,
        compliance_score: float,
        quality_score: float,
        signal_correct: bool,
        regime: str,
        ai_summary: str,
    ) -> bool:
        avg = (compliance_score + quality_score) / 2
        color = _COLOR["BUY"] if avg >= 75 else _COLOR["WARNING"] if avg >= 50 else _COLOR["SELL"]
        embed = {
            "title": "ZeroHour 每日覆盤完成",
            "color": color,
            "fields": [
                {"name": "合規分數", "value": f"{compliance_score:.0f}/100", "inline": True},
                {"name": "訊號品質", "value": f"{quality_score:.0f}/100", "inline": True},
                {"name": "訊號方向", "value": "正確" if signal_correct else "錯誤", "inline": True},
                {"name": "市場環境", "value": regime or "—", "inline": True},
                {"name": "AI 分析摘要", "value": ai_summary[:800] if ai_summary else "—", "inline": False},
            ],
            "footer": {"text": "ZeroHour Daily Review"},
            "timestamp": datetime.utcnow().isoformat(),
        }
        return await self._post({"embeds": [embed]})

    async def weekly_review(
        self,
        week_label: str,
        signal_count: int,
        signal_accuracy: float,
        trade_count: int,
        weekly_return_pct: float,
        market_regime: str,
        ai_summary: str,
    ) -> bool:
        color = _COLOR["BUY"] if weekly_return_pct >= 0 else _COLOR["SELL"]
        embed = {
            "title": f"ZeroHour 週覆盤 — {week_label}",
            "color": color,
            "fields": [
                {"name": "本週訊號數", "value": str(signal_count), "inline": True},
                {"name": "方向準確率", "value": f"{signal_accuracy:.0%}", "inline": True},
                {"name": "本週交易", "value": f"{trade_count} 筆", "inline": True},
                {"name": "週報酬率", "value": f"{weekly_return_pct:+.2%}", "inline": True},
                {"name": "市場環境", "value": market_regime or "—", "inline": True},
                {"name": "AI 週報", "value": ai_summary[:800] if ai_summary else "—", "inline": False},
            ],
            "footer": {"text": "ZeroHour Weekly Review"},
            "timestamp": datetime.utcnow().isoformat(),
        }
        return await self._post({"embeds": [embed]})

    async def watchlist_update(self, count: int, top_symbols: str) -> bool:
        embed = {
            "title": f"ZeroHour 選股完成 — Watchlist 更新 {count} 支",
            "color": _COLOR["INFO"],
            "fields": [
                {"name": "入選股數", "value": str(count), "inline": True},
                {"name": "前五名", "value": top_symbols or "—", "inline": False},
            ],
            "footer": {"text": "ZeroHour Stock Selection"},
            "timestamp": datetime.utcnow().isoformat(),
        }
        return await self._post({"embeds": [embed]})

    async def black_swan_alert(self, severity: str, triggers: list[str]) -> bool:
        color = _COLOR["CRITICAL"] if severity == "CRITICAL" else _COLOR["WARNING"]
        embed = {
            "title": f"ZeroHour 黑天鵝警報 — [{severity}]",
            "color": color,
            "description": "\n".join(f"• {t}" for t in triggers),
            "footer": {"text": "ZeroHour Black Swan Detector"},
            "timestamp": datetime.utcnow().isoformat(),
        }
        return await self._post({"embeds": [embed]})

    async def system_error(self, task_name: str, error: str) -> bool:
        embed = {
            "title": f"ZeroHour 系統錯誤 — {task_name}",
            "color": _COLOR["CRITICAL"],
            "description": f"```{error[:1000]}```",
            "timestamp": datetime.utcnow().isoformat(),
        }
        return await self._post({"embeds": [embed]})

    def send_sync(self, coro) -> bool:
        return asyncio.run(coro)


def get_alerter() -> DiscordAlerter:
    from ..config import get_settings
    return DiscordAlerter(get_settings().discord_webhook_url)
