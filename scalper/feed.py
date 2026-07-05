"""
Shioaji 報價/連線管理（scalper-spec.md §4）。

⚠️ 方法名與參數以 Shioaji 官方文件（https://sinotrade.github.io/）為準，
尚未在真實環境驗證——Phase 0 §5 任務 0-1~0-3 的第一要務就是實測校正本檔。
全部 shioaji import 延後到方法內部，未安裝 shioaji 套件時仍可 import 本模組（供單元測試用）。

斷線安全姿勢（§11.3）：斷線先撤所有掛單，重連後先對帳（查詢實際持倉/掛單）才恢復決策，
對不上帳就停機等人工處理——這部分邏輯由 runner.py 呼叫 broker.cancel_all() /
list_positions() 對帳完成，本檔只負責連線本身。
"""

import logging
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class ShioajiFeed:
    def __init__(self, api_key: str, secret_key: str, simulation: bool = True):
        self.api_key = api_key
        self.secret_key = secret_key
        self.simulation = simulation
        self._api = None
        self._connected = False
        self._on_tick_callback: Optional[Callable] = None
        self._on_depth_callback: Optional[Callable] = None

    def login(self):
        import shioaji as sj  # 延後 import：未裝 shioaji 時仍可 import 本模組做單元測試

        self._api = sj.Shioaji(simulation=self.simulation)
        self._api.login(api_key=self.api_key, secret_key=self.secret_key)
        self._connected = True
        logger.info("Shioaji 登入成功（simulation=%s）", self.simulation)
        return self._api

    def resolve_futures_contract(self, symbol: str):
        if self._api is None:
            raise RuntimeError("尚未登入，請先呼叫 login()")
        return self._api.Contracts.Futures[symbol]

    def subscribe(self, contract, on_tick: Callable, on_depth: Callable) -> None:
        """訂閱逐筆成交與五檔。回呼簽名（exchange, tick/bidask）以 shioaji 實測為準。"""
        import shioaji as sj

        if self._api is None:
            raise RuntimeError("尚未登入，請先呼叫 login()")

        self._on_tick_callback = on_tick
        self._on_depth_callback = on_depth

        self._api.quote.subscribe(contract, quote_type=sj.constant.QuoteType.Tick, version=sj.constant.QuoteVersion.v1)
        self._api.quote.subscribe(contract, quote_type=sj.constant.QuoteType.BidAsk, version=sj.constant.QuoteVersion.v1)

        @self._api.on_tick_fop_v1()
        def _tick_handler(exchange, tick):
            if self._on_tick_callback:
                self._on_tick_callback(exchange, tick)

        @self._api.on_bidask_fop_v1()
        def _bidask_handler(exchange, bidask):
            if self._on_depth_callback:
                self._on_depth_callback(exchange, bidask)

    def reconnect_with_backoff(self, max_attempts: int = 5) -> bool:
        """斷線重連，指數退避；超過上限回傳 False（呼叫端須觸發 Discord 告警並停機對帳）。"""
        for attempt in range(1, max_attempts + 1):
            try:
                self.login()
                return True
            except Exception as e:
                wait = min(2 ** attempt, 60)
                logger.warning("重連失敗（第 %d 次）：%s，%d 秒後重試", attempt, e, wait)
                time.sleep(wait)
        self._connected = False
        return False

    def is_connected(self) -> bool:
        return self._connected

    def logout(self) -> None:
        if self._api is not None:
            try:
                self._api.logout()
            except Exception as e:
                logger.warning("登出失敗（忽略）：%s", e)
        self._connected = False
