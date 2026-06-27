"""技術面選股 Agent — 純量化，不呼叫 LLM。"""
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TechnicalResult:
    symbol: str
    technical_score: float  # 0-100
    rsi: float
    macd_bullish: bool
    above_ma50: bool
    above_ma200: bool
    momentum_20d: float  # 20 日報酬率 %
    signal: str  # "STRONG_BUY" | "BUY" | "NEUTRAL" | "SELL"
    reason: str


def _calc_rsi(prices, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _calc_ema(prices: list[float], period: int) -> list[float]:
    if len(prices) < period:
        return []
    k = 2 / (period + 1)
    ema = [sum(prices[:period]) / period]
    for p in prices[period:]:
        ema.append(p * k + ema[-1] * (1 - k))
    return ema


def analyze_technical(symbol: str) -> TechnicalResult:
    """
    對指定股票進行技術面分析。
    使用 yfinance 取得 6 個月日線資料，計算 RSI / MACD / MA50 / MA200。
    """
    import yfinance as yf

    _default = TechnicalResult(
        symbol=symbol,
        technical_score=50.0,
        rsi=50.0,
        macd_bullish=False,
        above_ma50=False,
        above_ma200=False,
        momentum_20d=0.0,
        signal="NEUTRAL",
        reason="資料不足，使用預設值",
    )

    try:
        df = yf.Ticker(symbol).history(period="1y")
        if df is None or len(df) < 60:
            logger.warning(f"{symbol}: insufficient data ({len(df) if df is not None else 0} rows)")
            return _default

        closes = [float(x) for x in df["Close"].tolist()]
        current = closes[-1]

        # RSI
        rsi = _calc_rsi(closes[-30:])  # 用最近 30 日計算 14 日 RSI

        # MACD
        ema12 = _calc_ema(closes, 12)
        ema26 = _calc_ema(closes, 26)
        if len(ema12) >= 26 and len(ema26) >= 9:
            macd_line = [ema12[i + (len(ema12) - len(ema26))] - ema26[i] for i in range(len(ema26))]
            signal_line = _calc_ema(macd_line, 9)
            macd_bullish = (
                len(macd_line) > 0 and len(signal_line) > 0 and
                macd_line[-1] > signal_line[-1]
            )
        else:
            macd_bullish = False

        # MA50 / MA200
        ma50 = sum(closes[-50:]) / min(50, len(closes)) if len(closes) >= 20 else current
        ma200 = sum(closes[-200:]) / min(200, len(closes)) if len(closes) >= 50 else current
        above_ma50 = current > ma50
        above_ma200 = current > ma200

        # 20-day momentum
        momentum_20d = (current - closes[-21]) / closes[-21] * 100 if len(closes) >= 21 else 0.0

        # 評分計算
        score = 0.0

        # RSI 評分 (30 pts)
        if 40 <= rsi <= 60:
            score += 30
        elif 30 <= rsi < 40 or 60 < rsi <= 70:
            score += 20
        elif rsi > 70 or rsi < 30:
            score += 10

        # MACD 評分 (20 pts)
        if macd_bullish:
            score += 20

        # 趨勢評分 (30 pts)
        if above_ma50 and above_ma200 and ma50 > ma200:
            score += 30  # 完美多頭排列
        elif above_ma200 and above_ma50:
            score += 22
        elif above_ma200:
            score += 15
        elif above_ma50:
            score += 8

        # 動能評分 (20 pts)
        if momentum_20d > 5:
            score += 20
        elif momentum_20d > 0:
            score += 15
        elif momentum_20d > -5:
            score += 8
        else:
            score += 3

        score = max(0.0, min(100.0, score))

        # 訊號分類
        if score >= 75 and rsi < 70:
            signal = "STRONG_BUY"
        elif score >= 55:
            signal = "BUY"
        elif score >= 35:
            signal = "NEUTRAL"
        else:
            signal = "SELL"

        reasons = []
        if above_ma200:
            reasons.append("價格站上 MA200")
        if macd_bullish:
            reasons.append("MACD 多頭")
        if 40 <= rsi <= 60:
            reasons.append(f"RSI {rsi:.0f} 健康")
        elif rsi > 70:
            reasons.append(f"RSI {rsi:.0f} 過熱")
        elif rsi < 30:
            reasons.append(f"RSI {rsi:.0f} 超賣")
        if not reasons:
            reasons.append("無明顯技術信號")

        return TechnicalResult(
            symbol=symbol,
            technical_score=round(score, 1),
            rsi=round(rsi, 1),
            macd_bullish=macd_bullish,
            above_ma50=above_ma50,
            above_ma200=above_ma200,
            momentum_20d=round(momentum_20d, 2),
            signal=signal,
            reason="；".join(reasons),
        )

    except Exception as e:
        logger.error(f"analyze_technical {symbol} error: {e}")
        return _default
