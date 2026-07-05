import logging

logger = logging.getLogger(__name__)


class PositionSizer:
    """
    倉位計算器。

    根據帳戶資金、訊號信心度與風控參數，計算每次交易的合理下單金額與股數。
    """

    def __init__(
        self,
        max_position_pct: float = 0.30,
        max_total_exposure_pct: float = 0.80,
    ):
        self.max_position_pct = max_position_pct
        self.max_total_exposure_pct = max_total_exposure_pct

    def calculate(
        self,
        account_equity: float,
        current_exposure: float,
        suggested_pct: float,
        current_price: float,
        lot_size: int = 1,
    ) -> dict:
        """
        計算下單數量。

        Args:
            account_equity:    帳戶總資產（含持倉）
            current_exposure:  目前已投入金額
            suggested_pct:     訊號建議倉位比例（0~1）
            current_price:     目標標的現價
            lot_size:          最小交易單位（台股 1000 股 = 1 張）

        Returns:
            {
                'invest_amount': float,   可投入金額
                'shares': float,          建議股數
                'lots': int,              建議張數
                'blocked': bool,          是否因風控封鎖
                'reason': str
            }
        """
        available_room = (
            account_equity * self.max_total_exposure_pct - current_exposure
        )

        if available_room <= 0:
            return {
                "invest_amount": 0.0,
                "shares": 0.0,
                "lots": 0,
                "blocked": True,
                "reason": f"總曝險已達上限 {self.max_total_exposure_pct:.0%}",
            }

        target_pct = min(suggested_pct, self.max_position_pct)
        target_amount = account_equity * target_pct
        invest_amount = min(target_amount, available_room)

        if current_price <= 0:
            return {
                "invest_amount": 0.0,
                "shares": 0.0,
                "lots": 0,
                "blocked": True,
                "reason": "無效價格",
            }

        shares = invest_amount / current_price
        if lot_size > 1:
            # 整張交易：無條件捨去到整張；不足一張 → 封鎖（禁止超買，2026-07-06 老闆核准修復）
            lots = int(shares // lot_size)
            if lots < 1:
                return {
                    "invest_amount": 0.0,
                    "shares": 0.0,
                    "lots": 0,
                    "blocked": True,
                    "reason": (
                        f"資金不足最小交易單位（一張需 {current_price * lot_size:,.0f}，"
                        f"可投入僅 {invest_amount:,.0f}）"
                    ),
                }
            shares = float(lots * lot_size)
            invest_amount = shares * current_price
        else:
            lots = shares

        logger.info(
            f"PositionSizer: 建議投入 {invest_amount:,.0f}，"
            f"{shares:.1f} 股（{lots} 張）@ {current_price:.2f}"
        )

        return {
            "invest_amount": round(invest_amount, 2),
            "shares": round(shares, 4),
            "lots": int(lots),
            "blocked": False,
            "reason": f"倉位 {target_pct:.0%}",
        }
