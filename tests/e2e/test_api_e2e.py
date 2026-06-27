"""
E2E API tests — uses httpx against the running server.

Set BASE_URL env var to target a remote server, e.g.:
    BASE_URL=https://zerohour.fly.dev pytest tests/e2e/test_api_e2e.py -v

Default: http://localhost:8000 (local dev server).
"""

import os
import pytest
import httpx

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=60.0) as c:
        yield c


# ── health ────────────────────────────────────────────────────────────────────

def test_health_returns_ok(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "mode" in body


# ── signals ───────────────────────────────────────────────────────────────────

def test_signals_current_structure(client):
    r = client.get("/api/v1/signals/current")
    assert r.status_code == 200
    body = r.json()
    # may have trend/time_diff/combined or all null — structure must match schema
    assert isinstance(body, dict)
    for key in ("trend", "time_diff", "combined"):
        assert key in body


def test_signal_history_returns_list(client):
    r = client.get("/api/v1/signals/history?days=30")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    if data:
        item = data[0]
        for field in ("date", "direction", "confidence", "trend_state"):
            assert field in item, f"missing field {field}"


# ── performance ───────────────────────────────────────────────────────────────

def test_performance_summary_structure(client):
    r = client.get("/api/v1/performance")
    assert r.status_code == 200
    body = r.json()
    for field in ("period", "total_return_pct", "max_drawdown_pct", "win_rate"):
        assert field in body


def test_performance_history_returns_list(client):
    r = client.get("/api/v1/performance/history?days=60")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    if data:
        item = data[0]
        for field in ("date", "total_equity", "total_return_pct"):
            assert field in item


# ── positions ─────────────────────────────────────────────────────────────────

def test_positions_returns_list(client):
    r = client.get("/api/v1/positions")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ── watchlist ─────────────────────────────────────────────────────────────────

def test_watchlist_returns_list(client):
    r = client.get("/api/v1/watchlist")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ── review ────────────────────────────────────────────────────────────────────

def test_weekly_review_endpoint(client):
    r = client.get("/api/v1/review/weekly/latest")
    assert r.status_code == 200  # may return null body, that's fine


def test_daily_review_endpoint(client):
    r = client.get("/api/v1/review/daily/latest")
    assert r.status_code == 200


# ── agents ────────────────────────────────────────────────────────────────────

def test_market_context_endpoint(client):
    r = client.get("/api/v1/agents/market-context/latest")
    assert r.status_code == 200


def test_black_swan_endpoint(client):
    r = client.get("/api/v1/agents/black-swan/status")
    assert r.status_code == 200


# ── manual trigger ────────────────────────────────────────────────────────────

def test_trigger_unknown_task_returns_400(client):
    r = client.post("/api/v1/tasks/nonexistent_task")
    assert r.status_code == 400


def test_trigger_valid_task_queued(client):
    # fetch_us_market_data is a safe read-only task
    r = client.post("/api/v1/tasks/fetch_us_market_data")
    assert r.status_code == 200
    body = r.json()
    assert body["task"] == "fetch_us_market_data"
    assert body["status"] in ("queued", "error")  # error if celery not running


# ── backtest run ──────────────────────────────────────────────────────────────

def test_backtest_run_returns_metrics(client):
    """Quick 1-year backtest to verify the engine returns valid metrics."""
    r = client.post("/api/v1/backtest/run", json={
        "strategy": "S3",
        "symbol": "0050",
        "start_date": "2024-01-01",
        "end_date": "2025-01-01",
        "initial_capital": 1000000,
    }, timeout=120.0)
    assert r.status_code == 200
    body = r.json()
    for field in ("total_return_pct", "annualized_return_pct", "max_drawdown_pct", "sharpe_ratio"):
        assert field in body
        assert isinstance(body[field], (int, float))


# ── backtest compare ──────────────────────────────────────────────────────────

def test_backtest_compare_returns_three_strategies(client):
    r = client.post("/api/v1/backtest/compare", json={
        "symbol": "0050",
        "start_date": "2024-01-01",
        "end_date": "2025-01-01",
        "initial_capital": 1000000,
    }, timeout=180.0)
    assert r.status_code == 200
    body = r.json()
    assert "results" in body
    strategies = {s["strategy"] for s in body["results"]}
    assert strategies == {"S1", "S2", "S3"}
    for s in body["results"]:
        assert "total_return_pct" in s
        assert "max_drawdown_pct" in s
