"""黑天鵝偵測 Agent — 純量化規則，不依賴 LLM，確保即時性與確定性。"""
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class BlackSwanSeverity(str, Enum):
    NONE     = "NONE"      # 正常，繼續執行
    WATCH    = "WATCH"     # 觀察，記錄但不干預
    ALERT    = "ALERT"     # 警告，發送 Discord 通知
    CRITICAL = "CRITICAL"  # 嚴重，系統切換觀察模式，要求人工確認


@dataclass
class BlackSwanSignal:
    severity: BlackSwanSeverity
    triggers: list[str] = field(default_factory=list)
    recommended_action: str = "系統正常運作"
    vix: float = 0.0
    nasdaq_change_pct: float = 0.0
    sox_change_pct: float = 0.0


_CRITICAL_KEYWORDS = [
    "war", "invasion", "nuclear", "戰爭", "入侵", "核武",
    "trading halt", "circuit breaker", "熔斷", "交易暫停",
    "bank run", "financial crisis", "台海", "封鎖", "blockade",
    "pandemic", "earthquake", "台灣", "invasion",
]

_ACTION_MAP = {
    BlackSwanSeverity.NONE:     "系統正常運作",
    BlackSwanSeverity.WATCH:    "記錄異常，持續監控",
    BlackSwanSeverity.ALERT:    "發送 Discord 警告，人工確認後繼續",
    BlackSwanSeverity.CRITICAL: "系統自動切換至觀察模式，停止新開倉，等待人工確認",
}


def detect_black_swan(
    vix: float,
    nasdaq_change_pct: float,
    sox_change_pct: float,
    news_headlines: list[str] | None = None,
) -> BlackSwanSignal:
    """
    黑天鵝偵測（量化層，不呼叫 LLM，確保即時性）。
    嚴重情況再由覆盤 AI 進行後續分析。
    """
    triggers: list[str] = []
    severity = BlackSwanSeverity.NONE

    def _elevate(new_sev: BlackSwanSeverity):
        nonlocal severity
        _order = [BlackSwanSeverity.NONE, BlackSwanSeverity.WATCH,
                  BlackSwanSeverity.ALERT, BlackSwanSeverity.CRITICAL]
        if _order.index(new_sev) > _order.index(severity):
            severity = new_sev

    # VIX 檢查
    if vix > 40:
        triggers.append(f"VIX = {vix:.1f}（超過 40，極度恐慌）")
        _elevate(BlackSwanSeverity.CRITICAL)
    elif vix > 30:
        triggers.append(f"VIX = {vix:.1f}（超過 30，高度恐慌）")
        _elevate(BlackSwanSeverity.ALERT)
    elif vix > 25:
        triggers.append(f"VIX = {vix:.1f}（超過 25，市場緊張）")
        _elevate(BlackSwanSeverity.WATCH)

    # NASDAQ 單日大幅變動
    if nasdaq_change_pct < -5.0:
        triggers.append(f"NASDAQ 單日暴跌 {nasdaq_change_pct:.1f}%（超過 -5%）")
        _elevate(BlackSwanSeverity.CRITICAL)
    elif nasdaq_change_pct < -3.0:
        triggers.append(f"NASDAQ 單日急跌 {nasdaq_change_pct:.1f}%（超過 -3%）")
        _elevate(BlackSwanSeverity.ALERT)
    elif nasdaq_change_pct > 5.0:
        triggers.append(f"NASDAQ 單日異常暴漲 {nasdaq_change_pct:+.1f}%（可能不可持續）")
        _elevate(BlackSwanSeverity.WATCH)

    # SOX 與 NASDAQ 背離（半導體與科技指數方向相反）
    sox_diff = sox_change_pct - nasdaq_change_pct
    if abs(sox_diff) > 4.0:
        triggers.append(f"SOX 與 NASDAQ 異常背離 {sox_diff:+.1f}%（供應鏈訊號混亂）")
        _elevate(BlackSwanSeverity.ALERT)
    elif abs(sox_diff) > 2.5:
        triggers.append(f"SOX 與 NASDAQ 輕度背離 {sox_diff:+.1f}%")
        _elevate(BlackSwanSeverity.WATCH)

    # 新聞關鍵字掃描（輕量字串比對）
    if news_headlines:
        all_news = " ".join(news_headlines).lower()
        hit = [kw for kw in _CRITICAL_KEYWORDS if kw.lower() in all_news]
        if hit:
            triggers.append(f"新聞出現高風險關鍵字：{', '.join(hit[:5])}")
            _elevate(BlackSwanSeverity.ALERT)

    return BlackSwanSignal(
        severity=severity,
        triggers=triggers,
        recommended_action=_ACTION_MAP[severity],
        vix=vix,
        nasdaq_change_pct=nasdaq_change_pct,
        sox_change_pct=sox_change_pct,
    )


def fetch_vix() -> float:
    """從 yfinance 取得最新 VIX 收盤值。"""
    try:
        import yfinance as yf
        df = yf.Ticker("^VIX").history(period="5d")
        if not df.empty:
            return float(df["Close"].iloc[-1])
    except Exception as e:
        logger.warning(f"VIX fetch failed: {e}")
    return 20.0  # 預設正常值
