"""
Dashboard browser E2E tests using Playwright.

Requirements:
    pip install playwright pytest-playwright
    playwright install chromium

Run:
    BASE_URL=https://zerohour.fly.dev pytest tests/e2e/test_dashboard_playwright.py -v
    # or against local server:
    pytest tests/e2e/test_dashboard_playwright.py -v
"""

import os
import re
import pytest

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

# Playwright fixtures are provided by pytest-playwright plugin.
# Skip entire file gracefully if playwright is not installed.
playwright_available = True
try:
    import playwright  # noqa: F401
except ImportError:
    playwright_available = False

pytestmark = pytest.mark.skipif(
    not playwright_available,
    reason="playwright not installed — run: pip install playwright pytest-playwright && playwright install chromium",
)


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


# ── Dashboard loads ───────────────────────────────────────────────────────────

def test_dashboard_title(page, base_url):
    page.goto(base_url)
    assert "ZeroHour" in page.title()


def test_dashboard_navbar_present(page, base_url):
    page.goto(base_url)
    page.wait_for_selector(".navbar", timeout=5000)


def test_dashboard_signal_section_visible(page, base_url):
    page.goto(base_url)
    page.wait_for_selector(".section-title", timeout=5000)
    headings = page.locator(".section-title").all_text_contents()
    assert any("訊號" in h for h in headings)


def test_dashboard_equity_chart_section_present(page, base_url):
    page.goto(base_url)
    # equity-chart canvas must exist in DOM
    page.wait_for_selector("#equity-chart", timeout=5000)


def test_dashboard_signal_history_section_present(page, base_url):
    page.goto(base_url)
    page.wait_for_selector("#signal-history-area", timeout=5000)


def test_dashboard_compare_section_present(page, base_url):
    page.goto(base_url)
    page.wait_for_selector("#compare-area", timeout=5000)


def test_dashboard_trigger_buttons_present(page, base_url):
    page.goto(base_url)
    page.wait_for_selector(".trigger-grid", timeout=5000)
    buttons = page.locator(".trigger-btn").all()
    assert len(buttons) >= 4


# ── API calls from browser ────────────────────────────────────────────────────

def test_health_api_from_browser(page, base_url):
    """Verify health endpoint returns 200 via fetch (browser context)."""
    page.goto(base_url)
    result = page.evaluate("""async () => {
        const r = await fetch('/api/v1/health');
        return { status: r.status, body: await r.json() };
    }""")
    assert result["status"] == 200
    assert result["body"]["status"] == "ok"


def test_signals_api_from_browser(page, base_url):
    page.goto(base_url)
    result = page.evaluate("""async () => {
        const r = await fetch('/api/v1/signals/current');
        return r.status;
    }""")
    assert result == 200


def test_signal_history_api_from_browser(page, base_url):
    page.goto(base_url)
    result = page.evaluate("""async () => {
        const r = await fetch('/api/v1/signals/history?days=30');
        return r.status;
    }""")
    assert result == 200


# ── Interaction ───────────────────────────────────────────────────────────────

def test_refresh_button_clickable(page, base_url):
    page.goto(base_url)
    page.wait_for_selector("#refresh-btn", timeout=5000)
    page.click("#refresh-btn")
    # after click, button briefly shows loading then re-enables
    page.wait_for_function("document.getElementById('refresh-btn').disabled === false", timeout=30000)


def test_compare_button_exists_and_enabled(page, base_url):
    page.goto(base_url)
    btn = page.locator("#cmp-btn")
    btn.wait_for(timeout=5000)
    assert btn.is_enabled()


def test_dark_mode_body_renders(page, base_url):
    """Page should render without JS errors."""
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base_url)
    page.wait_for_timeout(2000)
    critical = [e for e in errors if "undefined" not in e.lower() and "404" not in e]
    assert len(critical) == 0, f"JS errors: {critical}"
