"""
策略三入口：盤中常駐主迴圈（scalper-spec.md §6/§8）。
launchd 於 08:40 啟動 --mode record；Phase 3 起支援 --mode sim。
--mode real 在 A7 核准前一律硬性拒絕啟動（見 §13 禁止事項 5）。

⚠️ --mode sim 目前只提供元件初始化骨架，完整事件迴圈（feed→grid→risk_guard→
broker→notifier 的即時串接）待 Phase 3 依 scalper-spec.md §8 補完並在模擬環境驗證。
"""

import argparse
import logging
import sys
import time
from datetime import datetime

from .config import get_scalper_settings
from .notify import ScalperNotifier

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ZeroHour 策略三：股期影線區間刷單")
    parser.add_argument("--mode", choices=["record", "sim", "real"], default="record")
    parser.add_argument("--symbol", required=True, help="股期合約代碼")
    args = parser.parse_args(argv)

    if args.mode == "real":
        print(
            "錯誤：真金模式（--mode real）需 scalper-spec.md A7 核准後才會開放，目前硬性拒絕。",
            file=sys.stderr,
        )
        return 1

    settings = get_scalper_settings()
    notifier = ScalperNotifier(settings.scalper_discord_webhook)

    logger.info("策略三啟動：mode=%s symbol=%s", args.mode, args.symbol)

    if args.mode == "record":
        return _run_record_mode(args.symbol, settings, notifier)
    return _run_sim_mode(args.symbol, settings, notifier)


def _run_record_mode(symbol: str, settings, notifier: ScalperNotifier) -> int:
    from .feed import ShioajiFeed
    from .recorder import TickRecorder

    recorder = TickRecorder()
    feed = ShioajiFeed(settings.shioaji_api_key, settings.shioaji_secret_key, simulation=True)

    def on_tick(exchange, tick):
        side = "buy_initiated" if getattr(tick, "tick_type", None) == 1 else "sell_initiated"
        recorder.record_tick(datetime.now(), symbol, float(tick.close), int(tick.volume), side)

    def on_depth(exchange, bidask):
        bid_total = sum(bidask.bid_volume) if bidask.bid_volume else 0
        ask_total = sum(bidask.ask_volume) if bidask.ask_volume else 0
        best_bid = bidask.bid_volume[0] if bidask.bid_volume else 0
        best_ask = bidask.ask_volume[0] if bidask.ask_volume else 0
        recorder.record_depth(datetime.now(), symbol, bid_total, ask_total, best_bid, best_ask)

    try:
        feed.login()
        contract = feed.resolve_futures_contract(symbol)
        feed.subscribe(contract, on_tick, on_depth)
        _run_until_session_end(settings)
    except Exception as e:
        logger.error("record 模式異常終止：%s", e, exc_info=True)
        notifier.disconnected(str(e))
        return 1
    finally:
        recorder.close()
        feed.logout()

    return 0


def _run_sim_mode(symbol: str, settings, notifier: ScalperNotifier) -> int:
    logger.warning(
        "sim 模式的完整事件迴圈待 Phase 3 依 scalper-spec.md §8 補完；"
        "目前僅提供元件初始化骨架，不會真的下模擬單。"
    )
    return 0


def _run_until_session_end(settings) -> None:
    end_hh, end_mm = map(int, settings.session_end.split(":"))
    while True:
        now = datetime.now()
        if now.hour > end_hh or (now.hour == end_hh and now.minute >= end_mm):
            break
        time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())
