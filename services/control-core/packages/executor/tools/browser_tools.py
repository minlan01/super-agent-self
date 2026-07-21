"""Browser tools for the Controlled Agent Platform.

Provides web browsing capabilities via Playwright with URL safety checks,
screenshot capture, text extraction, and element interaction.

Playwright is an optional dependency. Tools gracefully degrade when unavailable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from packages.policy.ssrf_guard import validate_url_fast
from packages.policy.unified_registry import tool_registry

from .base import ExecutionContext, ToolBase, ToolResult

logger = logging.getLogger(__name__)

try:
    from playwright.async_api import (
        Page,
        async_playwright,
    )

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

_playwright: Any = None
_browser: Any = None
_browser_lock = asyncio.Lock()

_PLAYWRIGHT_NOT_INSTALLED = (
    "Playwright not installed. Install with: pip install playwright && playwright install"
)


def _is_url_safe(url: str) -> tuple[bool, str]:
    """Check URL against SSRF protection policy."""
    return validate_url_fast(url)


# ---------------------------------------------------------------------------
# Browser lifecycle helpers
# ---------------------------------------------------------------------------


async def _get_page(context: ExecutionContext) -> Page:
    """Return a Playwright page, lazily initialising the browser if needed.

    If ``context._browser_context`` is already set (from a prior call),
    a new page is created from that shared context.  Otherwise the browser
    is launched and stored on *context* for reuse.
    """
    global _playwright, _browser

    if context._browser_context is not None:
        return await (context._browser_context).new_page()

    async with _browser_lock:
        if _browser is None:
            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(
                headless=context.browser_headless,
            )
        context._browser_context = await _browser.new_context()
    return await context._browser_context.new_page()


async def _close_browser() -> None:
    """Shut down the shared browser and playwright instance."""
    global _playwright, _browser
    async with _browser_lock:
        if _browser:
            try:
                await _browser.close()
            except Exception as exc:
                logger.warning("Error closing browser: %s", exc)
            _browser = None
        if _playwright:
            try:
                await _playwright.stop()
            except Exception as exc:
                logger.warning("Error stopping playwright: %s", exc)
            _playwright = None


# ---------------------------------------------------------------------------
# Screenshot helper
# ---------------------------------------------------------------------------


def _screenshot_filename(
    context: ExecutionContext,
    tool_name: str,
    args: dict[str, Any],
    suffix: str = "",
) -> str:
    timestamp = int(time.time() * 1000)
    step = args.get("step_order", 0)
    name = f"{context.task_id}_step{step}_{tool_name}_{timestamp}"
    if suffix:
        name = f"{name}_{suffix}"
    return f"{name}.png"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool_registry.register(
    category="browser",
    risk_level="low",
    emoji="🌐",
    params_schema={
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {"type": "string", "description": "URL to open"},
        },
        "additionalProperties": False,
    },
)
class BrowserOpen(ToolBase):
    """Open a URL in the browser and take a screenshot."""

    name = "browser.open"
    description = "Open a URL in the browser"

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        if not PLAYWRIGHT_AVAILABLE:
            return ToolResult(success=False, error=_PLAYWRIGHT_NOT_INSTALLED)

        url: str = args.get("url", "")
        safe, reason = _is_url_safe(url)
        if not safe:
            return ToolResult(success=False, error=reason)

        try:
            page = await _get_page(context)
            await page.goto(url, timeout=context.browser_timeout, wait_until="load")

            title = await page.title()

            screenshot_path = context.screenshots_path
            filename = _screenshot_filename(context, "open", args)
            full_path = f"{screenshot_path}/{filename}"
            await page.screenshot(path=full_path)

            return ToolResult(
                success=True,
                output={"title": title, "url": url},
                artifacts=[full_path],
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


@tool_registry.register(
    category="browser",
    risk_level="low",
    emoji="🖱️",
    params_schema={
        "type": "object",
        "required": ["selector"],
        "properties": {
            "selector": {"type": "string", "description": "CSS selector"},
            "wait_after": {"type": "integer", "description": "Wait ms after click", "default": 1000},
        },
        "additionalProperties": False,
    },
)
class BrowserClick(ToolBase):
    """Click an element by CSS selector."""

    name = "browser.click"
    description = "Click an element by CSS selector"

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        if not PLAYWRIGHT_AVAILABLE:
            return ToolResult(success=False, error=_PLAYWRIGHT_NOT_INSTALLED)

        selector: str = args.get("selector", "")
        wait_after: int = args.get("wait_after", 1000)

        try:
            page = await _get_page(context)
            await page.wait_for_selector(selector, timeout=context.browser_timeout)

            # Before-screenshot
            before_path = f"{context.screenshots_path}/{_screenshot_filename(context, 'click', args, 'before')}"
            await page.screenshot(path=before_path)

            await page.click(selector)

            await asyncio.sleep(wait_after / 1000)

            # After-screenshot
            after_path = f"{context.screenshots_path}/{_screenshot_filename(context, 'click', args, 'after')}"
            await page.screenshot(path=after_path)

            return ToolResult(
                success=True,
                output={"selector": selector, "wait_after_ms": wait_after},
                artifacts=[before_path, after_path],
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


@tool_registry.register(
    category="browser",
    risk_level="low",
    emoji="📄",
    params_schema={
        "type": "object",
        "properties": {
            "selectors": {
                "type": "array",
                "items": {"type": "string"},
                "default": ["h1", "article", "table"],
            },
        },
        "additionalProperties": False,
    },
)
class BrowserExtractText(ToolBase):
    """Extract text from the page by CSS selectors."""

    name = "browser.extract_text"
    description = "Extract text from page by selectors"

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        if not PLAYWRIGHT_AVAILABLE:
            return ToolResult(success=False, error=_PLAYWRIGHT_NOT_INSTALLED)

        selectors: list[str] = args.get("selectors", ["h1", "article", "table"])
        result: dict[str, Any] = {}

        try:
            page = await _get_page(context)

            for sel in selectors:
                elements = await page.query_selector_all(sel)
                if not elements:
                    result[sel] = None
                    continue

                # Special handling for tables — structured row data
                if sel.lower() == "table" or sel == "table":
                    rows: list[list[str]] = []
                    for el in elements:
                        trs = await el.query_selector_all("tr")
                        for tr in trs:
                            cells = await tr.query_selector_all("th, td")
                            row = [await cell.inner_text() for cell in cells]
                            if row:
                                rows.append(row)
                    result[sel] = rows if rows else None
                else:
                    texts: list[str] = []
                    for el in elements:
                        text = await el.inner_text()
                        if text.strip():
                            texts.append(text.strip())
                    result[sel] = texts if texts else None

            return ToolResult(success=True, output=result)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


@tool_registry.register(
    category="browser",
    risk_level="low",
    emoji="📸",
    params_schema={
        "type": "object",
        "properties": {
            "full_page": {"type": "boolean", "default": False},
        },
        "additionalProperties": False,
    },
)
class BrowserScreenshot(ToolBase):
    """Take a screenshot of the current page."""

    name = "browser.screenshot"
    description = "Take a screenshot"

    async def execute(self, args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        if not PLAYWRIGHT_AVAILABLE:
            return ToolResult(success=False, error=_PLAYWRIGHT_NOT_INSTALLED)

        full_page: bool = args.get("full_page", False)

        try:
            page = await _get_page(context)
            filename = _screenshot_filename(context, "screenshot", args)
            full_path = f"{context.screenshots_path}/{filename}"
            await page.screenshot(path=full_path, full_page=full_page)

            return ToolResult(
                success=True,
                output={"screenshot": full_path, "full_page": full_page},
                artifacts=[full_path],
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
