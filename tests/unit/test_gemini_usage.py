"""Gemini 金鑰洩漏防護測試 — 2026-07-07 生產事故修復。

事故：Discord 週覆盤顯示 Gemini 呼叫失敗訊息，內含完整 API 金鑰
（`...generateContent?key=<真實金鑰>`）——舊版把金鑰放在 URL query string，
httpx 例外字串含請求 URL，此字串又被直接回傳並顯示在 Discord。

修法：
1. 全部 6 個 Gemini 呼叫點改用 `x-goog-api-key` header 傳金鑰，金鑰不再進 URL
   （第一輪修復只抓到 5 個，2026-07-11 複查額度風險時才發現
   `supply_chain_agent.py` 也有同樣的漏洞，一併補上）。
2. `redact_secrets()` 作第二道防線，在 log／DB／使用者可見文字出現前過濾金鑰。
"""
import time

import httpx

from src.agents.gemini_usage import record_gemini_call, redact_secrets
from src.config import get_settings
from src.review import layer3_ai_analysis as l3


class TestRedactSecrets:

    def setup_method(self):
        self._settings = get_settings()
        self._orig_key = self._settings.gemini_api_key
        self._settings.gemini_api_key = "FAKESECRETKEY123"

    def teardown_method(self):
        self._settings.gemini_api_key = self._orig_key

    def test_masks_key_when_present(self):
        text = "Server error for url '...generateContent?key=FAKESECRETKEY123'"
        result = redact_secrets(text)
        assert "FAKESECRETKEY123" not in result
        assert "REDACTED" in result

    def test_leaves_unrelated_text_unchanged(self):
        text = "connection timeout after 30s"
        assert redact_secrets(text) == text

    def test_empty_string_passthrough(self):
        assert redact_secrets("") == ""

    def test_no_key_configured_does_not_crash(self):
        self._settings.gemini_api_key = ""
        assert redact_secrets("some error text") == "some error text"


class TestRecordGeminiCall:

    def test_error_message_redacted_before_storing(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "gemini_api_key", "FAKESECRETKEY123")

        captured = {}

        async def fake_log_agent_run(**kwargs):
            captured.update(kwargs)

        import src.database.helpers as helpers_module
        monkeypatch.setattr(helpers_module, "log_agent_run", fake_log_agent_run)

        err = Exception("failed for url '...generateContent?key=FAKESECRETKEY123'")
        import asyncio
        asyncio.run(record_gemini_call("test_run", None, time.monotonic(), error=err))

        assert "FAKESECRETKEY123" not in captured["error_message"]
        assert captured["success"] is False

    def test_success_path_extracts_token_count(self, monkeypatch):
        captured = {}

        async def fake_log_agent_run(**kwargs):
            captured.update(kwargs)

        import src.database.helpers as helpers_module
        monkeypatch.setattr(helpers_module, "log_agent_run", fake_log_agent_run)

        data = {"usageMetadata": {"totalTokenCount": 123}}
        import asyncio
        asyncio.run(record_gemini_call("test_run", "2330", time.monotonic(), data=data))

        assert captured["tokens_used"] == 123
        assert captured["success"] is True


class TestLayer3NoKeyLeak:
    """重現 2026-07-07 事故的整合回歸測試：模擬 Gemini 回 503，確認金鑰不進 URL、
    不出現在回傳給呼叫方（最終會顯示於 Discord）的錯誤文字中。"""

    def _patch(self, monkeypatch, captured):
        monkeypatch.setattr(l3.settings, "gemini_api_key", "FAKESECRETKEY123")

        async def fake_log_agent_run(**kwargs):
            pass

        import src.database.helpers as helpers_module
        monkeypatch.setattr(helpers_module, "log_agent_run", fake_log_agent_run)

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["header"] = request.headers.get("x-goog-api-key")
            return httpx.Response(503, request=request, text="Service Unavailable")

        orig_async_client = httpx.AsyncClient

        def fake_async_client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return orig_async_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", fake_async_client)

    async def test_daily_review_key_not_in_url_or_result(self, monkeypatch):
        captured = {}
        self._patch(monkeypatch, captured)

        result = await l3.run_ai_review({}, {}, {}, {})

        assert "key=" not in captured["url"]
        assert captured["header"] == "FAKESECRETKEY123"
        assert "FAKESECRETKEY123" not in result

    async def test_weekly_review_key_not_in_url_or_result(self, monkeypatch):
        captured = {}
        self._patch(monkeypatch, captured)

        result = await l3.run_weekly_ai_review("07/06-07/10", [], [], 0.0039, 1.0, "多頭低波動")

        assert "key=" not in captured["url"]
        assert captured["header"] == "FAKESECRETKEY123"
        assert "FAKESECRETKEY123" not in result


class TestSupplyChainAgentNoKeyLeak:
    """supply_chain_agent.py 是第一輪修復漏抓的第 6 個呼叫點，補測試。
    只有未在 _KNOWN_SCORES 靜態表中的 symbol 才會真的呼叫 Gemini。"""

    async def test_unknown_symbol_key_not_in_url(self, monkeypatch):
        from src.agents.stock_selection import supply_chain_agent as sca

        # get_settings() 是 @lru_cache 單例，不論在哪裡呼叫都拿到同一個物件，
        # 直接改這個物件的屬性即可，supply_chain_agent 內部是函式內 local import
        monkeypatch.setattr(get_settings(), "gemini_api_key", "FAKESECRETKEY123")

        async def fake_log_agent_run(**kwargs):
            pass

        import src.database.helpers as helpers_module
        monkeypatch.setattr(helpers_module, "log_agent_run", fake_log_agent_run)

        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["header"] = request.headers.get("x-goog-api-key")
            return httpx.Response(503, request=request, text="Service Unavailable")

        orig_async_client = httpx.AsyncClient

        def fake_async_client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return orig_async_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", fake_async_client)

        result = await sca.analyze_supply_chain("9999.TW")  # 不在靜態表中

        assert "key=" not in captured["url"]
        assert captured["header"] == "FAKESECRETKEY123"
        assert "FAKESECRETKEY123" not in result.supply_chain_summary
