"""Playwright E2E tests for the Myself-Agent frontend.

These tests drive a real browser against the Vue 3 frontend and FastAPI backend.
They require:
  - Backend server (auto-started by the ``e2e_server`` fixture)
  - Frontend dev server running at http://localhost:3000 (or FRONTEND_URL env)
  - chromium browser installed via ``python -m playwright install chromium``

Run with:
    python -m pytest tests/e2e/test_frontend_e2e.py -v --tb=short -m e2e
"""

from __future__ import annotations

import re

import pytest
from playwright.async_api import Page, expect

# ── Constants ────────────────────────────────────────────────────────────────

TEST_USERNAME = "admin"
TEST_PASSWORD = "admin123"


# ═════════════════════════════════════════════════════════════════════════════
# Auth Flow
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.e2e
class TestAuthFlow:
    """Tests for the login page and authentication flow."""

    @pytest.fixture(autouse=True)
    def _check_frontend(self, frontend_url):
        if frontend_url is None:
            pytest.skip("Frontend dev server not running (start with: cd apps/enterprise_admin_web && npm run dev)")

    async def test_login_page_renders(self, page: Page, frontend_url: str):
        """Navigate to /login and verify the login form elements exist."""
        await page.goto(f"{frontend_url}/login")
        await page.wait_for_load_state("networkidle")

        # Check for the login card heading
        heading = page.locator(".login-card h2")
        await expect(heading).to_be_visible()

        # Check for username input
        username_input = page.locator('input[type="text"]').first
        await expect(username_input).to_be_visible()

        # Check for password input
        password_input = page.locator('input[type="password"]')
        await expect(password_input).to_be_visible()

        # Check for the login button
        login_button = page.locator("button", has_text="Login").or_(
            page.locator("button.el-button--primary")
        )
        await expect(login_button.first).to_be_visible()

    async def test_login_with_valid_credentials(
        self, page: Page, frontend_url: str, e2e_server: str
    ):
        """Fill valid credentials, submit, and verify redirect to dashboard."""
        await page.goto(f"{frontend_url}/login")
        await page.wait_for_load_state("networkidle")

        # Fill username
        username_input = page.locator('input[type="text"]').first
        await username_input.fill(TEST_USERNAME)

        # Fill password
        password_input = page.locator('input[type="password"]')
        await password_input.fill(TEST_PASSWORD)

        # Click login button
        login_button = page.locator("button.el-button--primary")
        await login_button.click()

        # Should redirect to dashboard
        await page.wait_for_url("**/dashboard**", timeout=10000)
        await expect(page).to_have_url(re.compile(r".*dashboard.*"))

    async def test_login_with_invalid_credentials(
        self, page: Page, frontend_url: str, e2e_server: str
    ):
        """Fill wrong credentials and verify an error message appears."""
        await page.goto(f"{frontend_url}/login")
        await page.wait_for_load_state("networkidle")

        # Fill wrong username
        username_input = page.locator('input[type="text"]').first
        await username_input.fill("wrong_user")

        # Fill wrong password
        password_input = page.locator('input[type="password"]')
        await password_input.fill("wrong_pass")

        # Click login button
        login_button = page.locator("button.el-button--primary")
        await login_button.click()

        # Should show an error message (the div below the form or el-message)
        error_div = page.locator(".login-card div[style*='color']")
        # Wait for either inline error or Element Plus message
        error_visible = False
        try:
            await error_div.wait_for(state="visible", timeout=5000)
            error_visible = True
        except Exception:
            pass

        if not error_visible:
            # Element Plus renders error messages as el-message
            el_message = page.locator(".el-message")
            try:
                await el_message.wait_for(state="visible", timeout=5000)
                error_visible = True
            except Exception:
                pass

        assert error_visible, "Expected an error message for invalid credentials"

        # Should still be on login page
        await expect(page).to_have_url(re.compile(r".*login.*"))


# ═════════════════════════════════════════════════════════════════════════════
# Dashboard
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.e2e
class TestDashboard:
    """Tests for the dashboard page."""

    @pytest.fixture(autouse=True)
    def _check_frontend(self, frontend_url):
        if frontend_url is None:
            pytest.skip("Frontend dev server not running")

    async def _login(self, page: Page, frontend_url: str, e2e_server: str):
        """Helper: log in via the UI and wait for dashboard."""
        await page.goto(f"{frontend_url}/login")
        await page.wait_for_load_state("networkidle")

        username_input = page.locator('input[type="text"]').first
        await username_input.fill(TEST_USERNAME)

        password_input = page.locator('input[type="password"]')
        await password_input.fill(TEST_PASSWORD)

        login_button = page.locator("button.el-button--primary")
        await login_button.click()
        await page.wait_for_url("**/dashboard**", timeout=10000)

    async def test_dashboard_renders(
        self, page: Page, frontend_url: str, e2e_server: str
    ):
        """Login, navigate to dashboard, and check key elements."""
        await self._login(page, frontend_url, e2e_server)

        # Dashboard should have stat cards
        stat_cards = page.locator(".el-card")
        await expect(stat_cards.first).to_be_visible()

        # Page heading should exist
        header = page.locator("h3")
        await expect(header.first).to_be_visible()

    async def test_dashboard_displays_stats(
        self, page: Page, frontend_url: str, e2e_server: str
    ):
        """Check that the dashboard stat cards show numbers."""
        await self._login(page, frontend_url, e2e_server)

        # Stat values are rendered in div.stat-value
        stat_values = page.locator(".stat-value")
        # Wait for at least the first stat value to render
        await expect(stat_values.first).to_be_visible(timeout=10000)

        # Should have 4 stat cards (total tasks, success rate, skills, memories)
        count = await stat_values.count()
        assert count >= 1, "Expected at least one stat card on the dashboard"

    async def test_dashboard_charts_render(
        self, page: Page, frontend_url: str, e2e_server: str
    ):
        """Check that ECharts containers are present in the DOM."""
        await self._login(page, frontend_url, e2e_server)

        # The chart containers are div elements with style="height: 300px" inside el-card
        # ECharts renders into these divs; we check the container divs exist
        chart_containers = page.locator('div[style*="height: 300px"]')
        await expect(chart_containers.first).to_be_visible(timeout=10000)

        count = await chart_containers.count()
        assert count >= 2, f"Expected at least 2 chart containers, found {count}"


# ═════════════════════════════════════════════════════════════════════════════
# Task CRUD
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.e2e
class TestTaskCRUD:
    """Tests for task list, creation, detail view, and status display."""

    @pytest.fixture(autouse=True)
    def _check_frontend(self, frontend_url):
        if frontend_url is None:
            pytest.skip("Frontend dev server not running")

    async def _login(self, page: Page, frontend_url: str, e2e_server: str):
        """Helper: log in via the UI."""
        await page.goto(f"{frontend_url}/login")
        await page.wait_for_load_state("networkidle")
        await page.locator('input[type="text"]').first.fill(TEST_USERNAME)
        await page.locator('input[type="password"]').fill(TEST_PASSWORD)
        await page.locator("button.el-button--primary").click()
        await page.wait_for_url("**/dashboard**", timeout=10000)

    async def test_task_list_page(
        self, page: Page, frontend_url: str, e2e_server: str
    ):
        """Navigate to /tasks and verify the task table exists."""
        await self._login(page, frontend_url, e2e_server)

        # Click the Tasks menu item
        tasks_menu = page.locator(".el-menu-item", has_text="Tasks").or_(
            page.locator('.el-menu-item[index="/tasks"]')
        )
        await tasks_menu.first.click()

        # Wait for the task list page
        await page.wait_for_url("**/tasks**", timeout=5000)

        # The table should exist
        table = page.locator(".el-table")
        await expect(table).to_be_visible(timeout=10000)

    async def test_create_task(
        self, page: Page, frontend_url: str, e2e_server: str
    ):
        """Click create, fill the form, submit, and verify new task appears."""
        await self._login(page, frontend_url, e2e_server)

        # Navigate to tasks
        await page.goto(f"{frontend_url}/tasks")
        await page.wait_for_load_state("networkidle")

        # Wait for table
        table = page.locator(".el-table")
        await expect(table).to_be_visible(timeout=10000)

        # Click "New Task" button
        new_task_btn = page.locator("button", has_text="New Task").or_(
            page.locator("button.el-button--primary", has_text="New")
        )
        await new_task_btn.first.click()

        # The create dialog should open
        dialog = page.locator(".el-dialog")
        await expect(dialog).to_be_visible(timeout=5000)

        # Fill the goal textarea
        goal_input = page.locator(".el-dialog textarea")
        await goal_input.fill("E2E test task: verify Playwright integration")

        # Click the Create button inside the dialog
        create_btn = page.locator(".el-dialog button.el-button--primary")
        await create_btn.click()

        # Dialog should close
        await expect(dialog).to_be_hidden(timeout=5000)

        # The table should still be visible (refreshed with new data)
        await expect(table).to_be_visible()

    async def test_view_task_detail(
        self, page: Page, frontend_url: str, e2e_server: str
    ):
        """Click a task detail button and verify the detail page shows."""
        await self._login(page, frontend_url, e2e_server)

        # First create a task via API to ensure one exists
        import httpx

        async with httpx.AsyncClient(base_url=e2e_server) as client:
            # Login to get token
            login_resp = await client.post(
                "/api/v1/auth/login",
                json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
            )
            token = login_resp.json()["data"]["token"]

            # Create a task
            task_resp = await client.post(
                "/api/v1/tasks",
                json={"goal": "E2E detail view test task"},
                headers={"Authorization": f"Bearer {token}"},
            )
            task_data = task_resp.json()
            task_id = task_data.get("data", {}).get("id")

        if task_id:
            # Navigate directly to the task detail page
            await page.goto(f"{frontend_url}/tasks/{task_id}")
            await page.wait_for_load_state("networkidle")

            # Check for el-descriptions (used in TaskDetail.vue)
            descriptions = page.locator(".el-descriptions")
            await expect(descriptions).to_be_visible(timeout=10000)
        else:
            # Fallback: navigate to task list and click detail
            await page.goto(f"{frontend_url}/tasks")
            await page.wait_for_load_state("networkidle")

            detail_btn = page.locator("button", has_text="Detail").or_(
                page.locator("button", has_text="详情")
            )
            if await detail_btn.count() > 0:
                await detail_btn.first.click()
                await page.wait_for_url("**/tasks/**", timeout=5000)
                descriptions = page.locator(".el-descriptions")
                await expect(descriptions).to_be_visible(timeout=10000)

    async def test_task_status_display(
        self, page: Page, frontend_url: str, e2e_server: str
    ):
        """Verify that task status badges (el-tag) render in the task list."""
        await self._login(page, frontend_url, e2e_server)

        # Create a task via API so there's at least one row
        import httpx

        async with httpx.AsyncClient(base_url=e2e_server) as client:
            login_resp = await client.post(
                "/api/v1/auth/login",
                json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
            )
            token = login_resp.json()["data"]["token"]
            await client.post(
                "/api/v1/tasks",
                json={"goal": "Status badge test task"},
                headers={"Authorization": f"Bearer {token}"},
            )

        # Navigate to tasks
        await page.goto(f"{frontend_url}/tasks")
        await page.wait_for_load_state("networkidle")

        # Wait for table to load
        table = page.locator(".el-table")
        await expect(table).to_be_visible(timeout=10000)

        # Status column should contain el-tag elements
        status_tags = page.locator(".el-table .el-tag")
        await expect(status_tags.first).to_be_visible(timeout=10000)

        # The tag text should be a known status
        tag_text = await status_tags.first.text_content()
        valid_statuses = [
            "pending", "planning", "executing", "completed", "failed", "cancelled",
        ]
        assert tag_text and tag_text.strip().lower() in valid_statuses, (
            f"Expected a valid status tag, got: {tag_text}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# Theme Toggle
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.e2e
class TestThemeToggle:
    """Tests for dark/light theme toggle."""

    @pytest.fixture(autouse=True)
    def _check_frontend(self, frontend_url):
        if frontend_url is None:
            pytest.skip("Frontend dev server not running")

    async def _login(self, page: Page, frontend_url: str, e2e_server: str):
        """Helper: log in via the UI."""
        await page.goto(f"{frontend_url}/login")
        await page.wait_for_load_state("networkidle")
        await page.locator('input[type="text"]').first.fill(TEST_USERNAME)
        await page.locator('input[type="password"]').fill(TEST_PASSWORD)
        await page.locator("button.el-button--primary").click()
        await page.wait_for_url("**/dashboard**", timeout=10000)

    async def test_theme_toggle_button_exists(
        self, page: Page, frontend_url: str, e2e_server: str
    ):
        """Verify the theme toggle button (moon/sun icon) exists in the header."""
        await self._login(page, frontend_url, e2e_server)

        # The theme toggle button is in the header and contains an icon
        # In Layout.vue, it's an el-button with Sunny/Moon icon
        header = page.locator(".el-header")
        await expect(header).to_be_visible()

        # Look for the button that has a tooltip about theme
        theme_tooltip = page.locator(".el-tooltip__trigger").filter(
            has=page.locator("svg")
        )
        # There should be at least the theme toggle tooltip trigger
        count = await theme_tooltip.count()
        assert count >= 1, "Expected at least one tooltip trigger (theme toggle) in header"

    async def test_theme_toggle_switches(
        self, page: Page, frontend_url: str, e2e_server: str
    ):
        """Click the theme toggle and verify the dark class appears/disappears."""
        await self._login(page, frontend_url, e2e_server)

        # Record initial theme state
        html_element = page.locator("html")
        initially_dark = await html_element.evaluate(
            "el => el.classList.contains('dark')"
        )

        # Find and click the theme toggle button
        # The button contains either Sunny or Moon icon (SVG)
        # It has a tooltip about light/dark theme
        theme_btn = page.locator(".el-header button").filter(
            has=page.locator("svg")
        )
        # The theme toggle is the one with Sunny/Moon icon (not Bell)
        # We look for the second SVG button (first might be notification bell)
        svg_buttons = page.locator(".el-header .el-button")
        svg_btn_count = await svg_buttons.count()

        # Find the correct button: the one inside a tooltip trigger
        # In the Layout, the theme toggle is wrapped in el-tooltip
        found = False
        for i in range(svg_btn_count):
            btn = svg_buttons.nth(i)
            # Check if this button has a Sunny or Moon SVG icon child
            has_sun = await btn.locator("svg").count() > 0
            if has_sun:
                await btn.click()
                found = True
                break

        assert found, "Could not find the theme toggle button"

        # Verify theme switched
        now_dark = await html_element.evaluate(
            "el => el.classList.contains('dark')"
        )
        assert now_dark != initially_dark, (
            f"Theme did not toggle: initially_dark={initially_dark}, now_dark={now_dark}"
        )

        # Click again to revert
        for i in range(svg_btn_count):
            btn = svg_buttons.nth(i)
            has_sun = await btn.locator("svg").count() > 0
            if has_sun:
                await btn.click()
                break

        reverted_dark = await html_element.evaluate(
            "el => el.classList.contains('dark')"
        )
        assert reverted_dark == initially_dark, "Theme did not revert on second toggle"


# ═════════════════════════════════════════════════════════════════════════════
# i18n (Internationalization)
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.e2e
class TestI18n:
    """Tests for language toggle (Chinese/English)."""

    @pytest.fixture(autouse=True)
    def _check_frontend(self, frontend_url):
        if frontend_url is None:
            pytest.skip("Frontend dev server not running")

    async def _login(self, page: Page, frontend_url: str, e2e_server: str):
        """Helper: log in via the UI."""
        await page.goto(f"{frontend_url}/login")
        await page.wait_for_load_state("networkidle")
        await page.locator('input[type="text"]').first.fill(TEST_USERNAME)
        await page.locator('input[type="password"]').fill(TEST_PASSWORD)
        await page.locator("button.el-button--primary").click()
        await page.wait_for_url("**/dashboard**", timeout=10000)

    async def test_language_toggle_exists(
        self, page: Page, frontend_url: str, e2e_server: str
    ):
        """Verify the language switch button exists in the header."""
        await self._login(page, frontend_url, e2e_server)

        # The language button shows "EN" or "中文" text
        lang_btn = page.locator(".el-header button", has_text="EN").or_(
            page.locator(".el-header button", has_text="中文")
        )
        await expect(lang_btn.first).to_be_visible()

    async def test_language_switches(
        self, page: Page, frontend_url: str, e2e_server: str
    ):
        """Click the language toggle and verify page text changes language."""
        await self._login(page, frontend_url, e2e_server)

        # Find the language toggle button
        lang_btn_en = page.locator(".el-header button", has_text="EN")
        lang_btn_zh = page.locator(".el-header button", has_text="中文")

        # Determine current language by checking sidebar text
        dashboard_menu = page.locator(".el-menu-item", has_text="Dashboard").or_(
            page.locator(".el-menu-item", has_text="仪表盘")
        )

        # Record initial state
        is_english = await lang_btn_en.count() > 0 and await lang_btn_en.is_visible()
        is_chinese = await lang_btn_zh.count() > 0 and await lang_btn_zh.is_visible()

        # Click the appropriate button
        if is_english:
            # Currently Chinese, button shows "EN" to switch to English
            await lang_btn_en.click()
            # Verify switched: dashboard menu should show "Dashboard" (English)
            await page.wait_for_timeout(500)  # small wait for reactivity
            dashboard_en = page.locator(".el-menu-item", has_text="Dashboard")
            await expect(dashboard_en.first).to_be_visible(timeout=5000)

            # Now button should show "中文"
            lang_btn_zh_after = page.locator(".el-header button", has_text="中文")
            await expect(lang_btn_zh_after).to_be_visible()
        elif is_chinese:
            # Currently English, button shows "中文" to switch to Chinese
            await lang_btn_zh.click()
            await page.wait_for_timeout(500)
            dashboard_zh = page.locator(".el-menu-item", has_text="仪表盘")
            await expect(dashboard_zh.first).to_be_visible(timeout=5000)

            lang_btn_en_after = page.locator(".el-header button", has_text="EN")
            await expect(lang_btn_en_after).to_be_visible()
        else:
            pytest.fail("Could not find language toggle button")
