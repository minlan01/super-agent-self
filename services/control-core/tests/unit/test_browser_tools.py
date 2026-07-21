"""Unit tests for Browser tools -- imports, URL safety, screenshot naming, graceful degradation."""


import pytest

from packages.executor.tools.base import ExecutionContext
from packages.executor.tools.browser_tools import (
    PLAYWRIGHT_AVAILABLE,
    BrowserClick,
    BrowserExtractText,
    BrowserOpen,
    BrowserScreenshot,
    _is_url_safe,
    _screenshot_filename,
)

# ---------------------------------------------------------------------------
# Import / availability tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBrowserImports:
    def test_playwright_flag_is_bool(self):
        assert isinstance(PLAYWRIGHT_AVAILABLE, bool)

    def test_browser_open_importable(self):
        tool = BrowserOpen()
        assert tool.name == "browser.open"
        assert tool.description != ""

    def test_browser_click_importable(self):
        tool = BrowserClick()
        assert tool.name == "browser.click"

    def test_browser_extract_text_importable(self):
        tool = BrowserExtractText()
        assert tool.name == "browser.extract_text"

    def test_browser_screenshot_importable(self):
        tool = BrowserScreenshot()
        assert tool.name == "browser.screenshot"


# ---------------------------------------------------------------------------
# _is_url_safe tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsUrlSafe:
    def test_safe_url(self):
        ok, reason = _is_url_safe("https://example.com")
        assert ok is True
        assert reason == "ok"

    def test_safe_url_with_path(self):
        ok, reason = _is_url_safe("https://example.com/some/page?q=1")
        assert ok is True

    def test_localhost_blocked(self):
        ok, reason = _is_url_safe("http://localhost")
        assert ok is False
        assert "blocked" in reason.lower()

    def test_localhost_with_port_blocked(self):
        ok, reason = _is_url_safe("http://localhost:8080/api")
        assert ok is False

    def test_127_0_0_1_blocked(self):
        ok, reason = _is_url_safe("http://127.0.0.1")
        assert ok is False

    def test_127_0_0_1_with_port_blocked(self):
        ok, reason = _is_url_safe("http://127.0.0.1:3000")
        assert ok is False

    def test_192_168_private_blocked(self):
        ok, reason = _is_url_safe("http://192.168.1.1")
        assert ok is False

    def test_192_168_with_port_blocked(self):
        ok, reason = _is_url_safe("http://192.168.0.100:8080/admin")
        assert ok is False

    def test_10_private_blocked(self):
        ok, reason = _is_url_safe("http://10.0.0.1")
        assert ok is False

    def test_10_with_port_blocked(self):
        ok, reason = _is_url_safe("https://10.10.10.10:443/secret")
        assert ok is False

    def test_https_localhost_blocked(self):
        ok, reason = _is_url_safe("https://localhost")
        assert ok is False

    def test_public_ip_safe(self):
        ok, reason = _is_url_safe("https://93.184.216.34")
        assert ok is True

    def test_public_domain_safe(self):
        ok, reason = _is_url_safe("https://docs.python.org/3/")
        assert ok is True


# ---------------------------------------------------------------------------
# _screenshot_filename tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScreenshotFilename:
    def test_basic_filename(self):
        ctx = ExecutionContext(task_id="task-123", step_id="step-1")
        filename = _screenshot_filename(ctx, "open", {"step_order": 1})
        assert filename.startswith("task-123_step1_open_")
        assert filename.endswith(".png")
        # Should contain a timestamp
        parts = filename.replace(".png", "").split("_")
        assert len(parts) == 4  # task-123, step1, open, timestamp

    def test_filename_with_suffix(self):
        ctx = ExecutionContext(task_id="task-123", step_id="step-1")
        filename = _screenshot_filename(ctx, "click", {"step_order": 2}, suffix="before")
        assert "before" in filename
        assert filename.endswith(".png")

    def test_filename_contains_step_order(self):
        ctx = ExecutionContext(task_id="task-123", step_id="step-1")
        filename = _screenshot_filename(ctx, "screenshot", {"step_order": 5})
        assert "step5" in filename

    def test_filename_default_step_order(self):
        ctx = ExecutionContext(task_id="task-123", step_id="step-1")
        filename = _screenshot_filename(ctx, "screenshot", {})
        assert "step0" in filename


# ---------------------------------------------------------------------------
# Graceful degradation (Playwright not installed)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBrowserToolsNoPlaywright:
    @pytest.mark.asyncio
    async def test_browser_open_without_playwright(self):
        """BrowserOpen returns error when Playwright is not installed."""
        if PLAYWRIGHT_AVAILABLE:
            pytest.skip("Playwright is installed, skipping degradation test")

        tool = BrowserOpen()
        ctx = ExecutionContext(task_id="t1", step_id="s1")
        result = await tool.execute({"url": "https://example.com"}, ctx)
        assert result.success is False
        assert "Playwright not installed" in result.error

    @pytest.mark.asyncio
    async def test_browser_click_without_playwright(self):
        if PLAYWRIGHT_AVAILABLE:
            pytest.skip("Playwright is installed, skipping degradation test")

        tool = BrowserClick()
        ctx = ExecutionContext(task_id="t1", step_id="s1")
        result = await tool.execute({"selector": "button"}, ctx)
        assert result.success is False
        assert "Playwright not installed" in result.error

    @pytest.mark.asyncio
    async def test_browser_extract_text_without_playwright(self):
        if PLAYWRIGHT_AVAILABLE:
            pytest.skip("Playwright is installed, skipping degradation test")

        tool = BrowserExtractText()
        ctx = ExecutionContext(task_id="t1", step_id="s1")
        result = await tool.execute({"selectors": ["h1"]}, ctx)
        assert result.success is False
        assert "Playwright not installed" in result.error

    @pytest.mark.asyncio
    async def test_browser_screenshot_without_playwright(self):
        if PLAYWRIGHT_AVAILABLE:
            pytest.skip("Playwright is installed, skipping degradation test")

        tool = BrowserScreenshot()
        ctx = ExecutionContext(task_id="t1", step_id="s1")
        result = await tool.execute({"full_page": True}, ctx)
        assert result.success is False
        assert "Playwright not installed" in result.error

    @pytest.mark.asyncio
    async def test_browser_open_blocks_unsafe_url(self):
        """URL safety check runs before Playwright is needed."""
        tool = BrowserOpen()
        ctx = ExecutionContext(task_id="t1", step_id="s1")
        result = await tool.execute({"url": "http://localhost:8080"}, ctx)
        assert result.success is False
        assert "blocked" in result.error.lower()


# ---------------------------------------------------------------------------
# Playwright-installed tests (skipped if not available)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBrowserToolsWithPlaywright:
    @pytest.mark.asyncio
    async def test_browser_open_about_blank(self, tmp_path):
        if not PLAYWRIGHT_AVAILABLE:
            pytest.skip("Playwright not installed")

        tool = BrowserOpen()
        ctx = ExecutionContext(
            task_id="t1",
            step_id="s1",
            workspace_root=str(tmp_path),
            screenshots_dir="screenshots",
            browser_headless=True,
            browser_timeout=30000,
        )
        result = await tool.execute({"url": "about:blank"}, ctx)
        assert result.success is True
        assert result.output is not None
        assert "title" in result.output
        assert len(result.artifacts) >= 1
