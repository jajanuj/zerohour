"""X-API-Key 驗證 middleware 測試 — 2026-07-06 老闆核准。

settings.api_key 為空 = 驗證停用；設定後 /api/v1/* 需帶正確 key，
/api/v1/health 與非 /api/v1 路徑豁免。
"""
from fastapi.testclient import TestClient

import src.main as main_module
from src.main import app


class TestApiKeyGuard:

    def setup_method(self):
        self._orig = main_module.settings.api_key
        self.client = TestClient(app)

    def teardown_method(self):
        main_module.settings.api_key = self._orig

    def test_disabled_when_key_not_configured(self):
        main_module.settings.api_key = ""
        r = self.client.get("/api/v1/agents/gemini-usage")
        assert r.status_code != 401

    def test_missing_key_rejected(self):
        main_module.settings.api_key = "secret123"
        r = self.client.get("/api/v1/agents/gemini-usage")
        assert r.status_code == 401

    def test_wrong_key_rejected(self):
        main_module.settings.api_key = "secret123"
        r = self.client.get(
            "/api/v1/agents/gemini-usage", headers={"X-API-Key": "wrong"}
        )
        assert r.status_code == 401

    def test_correct_key_passes(self):
        main_module.settings.api_key = "secret123"
        r = self.client.get(
            "/api/v1/agents/gemini-usage", headers={"X-API-Key": "secret123"}
        )
        assert r.status_code != 401

    def test_health_exempt(self):
        main_module.settings.api_key = "secret123"
        r = self.client.get("/api/v1/health")
        assert r.status_code == 200

    def test_dashboard_root_exempt(self):
        main_module.settings.api_key = "secret123"
        r = self.client.get("/")
        assert r.status_code == 200

    def test_post_task_trigger_protected(self):
        # 高危端點（可觸發 Gemini 呼叫燒額度）必須被擋
        main_module.settings.api_key = "secret123"
        r = self.client.post("/api/v1/tasks/generate_signal")
        assert r.status_code == 401
