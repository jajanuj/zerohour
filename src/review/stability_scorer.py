from typing import Optional

STABILITY_CRITERIA = {
    "sharpe_3m":         {"threshold": 1.0,  "description": "3個月 Sharpe Ratio > 1.0"},
    "win_rate_20trades": {"threshold": 0.55, "description": "近 20 筆勝率 > 55%"},
    "max_drawdown_3m":   {"threshold": -0.10, "description": "3個月最大回撤 < -10%"},
    "vs_benchmark_3m":   {"threshold": 0.03, "description": "3個月超越基準 > +3%"},
}

AI_REVIEW_FREQUENCY = {
    "unstable":  "daily",
    "stable":    "weekly",
    "excellent": "biweekly",
}


class StabilityScorer:
    """策略穩定度評分器。"""

    def score(self, stats: dict) -> dict:
        """
        Args:
            stats: {
                'sharpe_3m': float,
                'win_rate_20trades': float,
                'max_drawdown_3m': float,   (負值)
                'vs_benchmark_3m': float,
            }
        Returns:
            {
                'passed_criteria': list[str],
                'failed_criteria': list[str],
                'is_stable': bool,
                'review_frequency': str,
                'score': float,   0–100
            }
        """
        passed = []
        failed = []

        sharpe = stats.get("sharpe_3m", 0.0)
        if sharpe >= STABILITY_CRITERIA["sharpe_3m"]["threshold"]:
            passed.append("sharpe_3m")
        else:
            failed.append(f"sharpe_3m ({sharpe:.2f} < {STABILITY_CRITERIA['sharpe_3m']['threshold']})")

        wr = stats.get("win_rate_20trades", 0.0)
        if wr >= STABILITY_CRITERIA["win_rate_20trades"]["threshold"]:
            passed.append("win_rate_20trades")
        else:
            failed.append(f"win_rate ({wr:.1%} < {STABILITY_CRITERIA['win_rate_20trades']['threshold']:.0%})")

        dd = stats.get("max_drawdown_3m", -1.0)
        if dd >= STABILITY_CRITERIA["max_drawdown_3m"]["threshold"]:
            passed.append("max_drawdown_3m")
        else:
            failed.append(f"max_drawdown ({dd:.1%} worse than {STABILITY_CRITERIA['max_drawdown_3m']['threshold']:.0%})")

        excess = stats.get("vs_benchmark_3m", 0.0)
        if excess >= STABILITY_CRITERIA["vs_benchmark_3m"]["threshold"]:
            passed.append("vs_benchmark_3m")
        else:
            failed.append(f"vs_benchmark ({excess:.1%} < {STABILITY_CRITERIA['vs_benchmark_3m']['threshold']:.0%})")

        is_stable = len(passed) == len(STABILITY_CRITERIA)
        score = len(passed) / len(STABILITY_CRITERIA) * 100

        if is_stable and sharpe >= 1.5:
            frequency = AI_REVIEW_FREQUENCY["excellent"]
        elif is_stable:
            frequency = AI_REVIEW_FREQUENCY["stable"]
        else:
            frequency = AI_REVIEW_FREQUENCY["unstable"]

        return {
            "passed_criteria": passed,
            "failed_criteria": failed,
            "is_stable": is_stable,
            "review_frequency": frequency,
            "score": round(score, 1),
        }
