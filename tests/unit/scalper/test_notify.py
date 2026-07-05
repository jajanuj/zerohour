from datetime import date

import httpx
import pytest

from scalper.notify import ScalperNotifier


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class TestScalperNotifier:
    def test_no_webhook_configured_skips_send(self):
        notifier = ScalperNotifier(webhook_url="")
        assert notifier.send("test") is False

    def test_send_success(self, monkeypatch):
        notifier = ScalperNotifier(webhook_url="https://discord.example/webhook")
        monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(204))
        assert notifier.send("hello") is True

    def test_send_failure_status_returns_false(self, monkeypatch):
        notifier = ScalperNotifier(webhook_url="https://discord.example/webhook")
        monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(500))
        assert notifier.send("hello") is False

    def test_send_exception_does_not_raise(self, monkeypatch):
        notifier = ScalperNotifier(webhook_url="https://discord.example/webhook")

        def _raise(*a, **k):
            raise httpx.ConnectTimeout("timeout")

        monkeypatch.setattr(httpx, "post", _raise)
        assert notifier.send("hello") is False

    def test_daily_summary_formats_percentage(self, monkeypatch):
        notifier = ScalperNotifier(webhook_url="https://discord.example/webhook")
        captured = {}

        def _capture(url, json, timeout):
            captured["content"] = json["content"]
            return FakeResponse(204)

        monkeypatch.setattr(httpx, "post", _capture)
        notifier.daily_summary(date(2026, 7, 6), n_trades=5, win_rate=0.6, net_pnl=1250.0)
        assert "60%" in captured["content"]
        assert "1250" in captured["content"] or "1,250" in captured["content"]
