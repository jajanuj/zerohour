from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class ComplianceViolation:
    rule: str
    expected: str
    actual: str
    severity: str  # CRITICAL | WARNING | INFO


@dataclass
class ComplianceReport:
    trade_date: date
    passed: bool
    violations: list[ComplianceViolation] = field(default_factory=list)
    score: float = 100.0


class RuleComplianceChecker:
    """
    Layer 1：規則遵守度自動檢查。

    檢查項目：
    1. 訊號門檻
    2. 進場時間窗口（09:00–09:30）
    3. 停損線設定正確性
    4. 趨勢環境（BEAR 時禁止做多）
    """

    def check(self, trade: dict, signal: dict, config: dict) -> ComplianceReport:
        violations: list[ComplianceViolation] = []

        # 規則 1：訊號門檻
        nasdaq_chg = abs(signal.get("nasdaq_change_pct", 0))
        threshold = config.get("us_signal_threshold", 1.5)
        if nasdaq_chg < threshold and trade.get("direction") == "BUY":
            violations.append(ComplianceViolation(
                rule="訊號門檻",
                expected=f"NASDAQ 變動 ≥ {threshold}%",
                actual=f"NASDAQ 變動 = {nasdaq_chg:.2f}%",
                severity="CRITICAL",
            ))

        # 規則 2：進場時間窗口
        entry_time = trade.get("entry_time")
        if entry_time is not None:
            in_window = (
                entry_time.hour == 9 and entry_time.minute <= 30
            ) or entry_time.hour < 9
            if not in_window and trade.get("direction") == "BUY":
                violations.append(ComplianceViolation(
                    rule="進場時間窗口",
                    expected="09:00–09:30",
                    actual=entry_time.strftime("%H:%M"),
                    severity="WARNING",
                ))

        # 規則 3：停損設定
        entry_price = trade.get("entry_price", 0)
        stop_loss = trade.get("stop_loss_price")
        if entry_price and stop_loss:
            sl_pct = config.get("index_stop_loss_pct", 0.12)
            expected_stop = entry_price * (1 - sl_pct)
            if abs(stop_loss - expected_stop) > entry_price * 0.005:
                violations.append(ComplianceViolation(
                    rule="停損設定",
                    expected=f"{expected_stop:.2f}",
                    actual=f"{stop_loss:.2f}",
                    severity="CRITICAL",
                ))

        # 規則 4：趨勢環境
        trend_state = signal.get("trend_state")
        if trend_state == "BEAR" and trade.get("direction") == "BUY":
            violations.append(ComplianceViolation(
                rule="趨勢過濾",
                expected="BEAR 環境不得做多",
                actual="BEAR 環境執行 BUY",
                severity="CRITICAL",
            ))

        score = 100.0
        for v in violations:
            score -= 30 if v.severity == "CRITICAL" else 10
        score = max(0.0, score)

        return ComplianceReport(
            trade_date=date.today(),
            passed=score >= 70,
            violations=violations,
            score=score,
        )
