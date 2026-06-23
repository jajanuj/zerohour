from enum import Enum


class MarketRegime(str, Enum):
    BULL_LOW_VOL = "多頭低波動"
    BULL_HIGH_VOL = "多頭高波動"
    CHOPPY = "震盪整理"
    BEAR_EARLY = "初期空頭"
    BEAR_DEEP = "深度空頭"


def classify_regime(
    nasdaq_ma50: float,
    nasdaq_ma200: float,
    vix: float,
    nasdaq_30d_range_pct: float,
) -> MarketRegime:
    """
    根據技術指標分類市場環境。

    VIX < 18 = 低波動；> 25 = 高波動；> 40 = 極度恐慌
    30日波幅 > 20% = 震盪
    """
    is_bull = nasdaq_ma50 > nasdaq_ma200
    is_low_vol = vix < 18
    is_choppy = nasdaq_30d_range_pct > 20

    if not is_bull:
        return MarketRegime.BEAR_DEEP if vix > 30 else MarketRegime.BEAR_EARLY
    if is_choppy:
        return MarketRegime.CHOPPY
    return MarketRegime.BULL_LOW_VOL if is_low_vol else MarketRegime.BULL_HIGH_VOL
