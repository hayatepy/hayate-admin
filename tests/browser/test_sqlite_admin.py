from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
import uvicorn
from examples.sqlite.app import create_example, initialize_database, seed_user
from examples.sqlite.generated_queries import list_admin_audit_events
from hayate_sql.adapters import SQLiteDatabase
from playwright.async_api import Page, async_playwright, expect

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        os.environ.get("HAYATE_ADMIN_BROWSER_TESTS") != "1",
        reason="set HAYATE_ADMIN_BROWSER_TESTS=1 after installing Chromium",
    ),
]

PASSWORD = "correct horse battery staple"
SECRET = "browser-test-secret"


@dataclass(frozen=True, slots=True)
class LiveExample:
    url: str
    database_path: Path


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest_asyncio.fixture
async def live_example(tmp_path: Path) -> AsyncIterator[LiveExample]:
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    database_path = tmp_path / "browser.db"
    initialize_database(database_path)
    await seed_user(
        database_path=database_path,
        origin=url,
        auth_secret=SECRET,
        email="operator@example.test",
        password=PASSWORD,
        role="operator",
    )
    example = create_example(
        database_path=database_path,
        origin=url,
        auth_secret=SECRET,
    )
    server = uvicorn.Server(
        uvicorn.Config(
            example.app,
            host="127.0.0.1",
            port=port,
            lifespan="on",
            log_level="warning",
        )
    )
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.02)
    else:
        server.should_exit = True
        await task
        raise RuntimeError("test server did not start")

    try:
        yield LiveExample(url, database_path)
    finally:
        server.should_exit = True
        await task


async def _create_task(page: Page, name: str, status: str) -> None:
    await page.get_by_role("link", name="Add Task").click()
    await page.get_by_label("Name").fill(name)
    await page.get_by_label("Status").select_option(status)
    await page.get_by_label("Active").check()
    await page.get_by_label("Notes").fill(f"Notes for {name}")
    await page.get_by_role("button", name="Create").click()
    await expect(page.get_by_role("heading", name=name)).to_be_visible()
    await page.get_by_role("link", name="Back to Tasks").click()


async def test_real_browser_create_search_filter_sort_edit_delete(
    live_example: LiveExample,
) -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []
    request_failures: list[str] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context()
        login = await context.request.post(
            f"{live_example.url}/api/auth/sign-in/email",
            headers={"origin": live_example.url, "sec-fetch-site": "same-origin"},
            data={"email": "operator@example.test", "password": PASSWORD},
        )
        assert login.ok

        page = await context.new_page()
        page.on(
            "console",
            lambda message: (
                console_errors.append(message.text) if message.type == "error" else None
            ),
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "requestfailed",
            lambda request: (
                request_failures.append(f"{request.method} {request.url}: {request.failure}")
                if "/export.csv" not in request.url
                else None
            ),
        )

        await page.goto(f"{live_example.url}/admin/tasks")
        await expect(page.get_by_role("heading", name="Tasks")).to_be_visible()
        await _create_task(page, "Zulu task", "open")
        await _create_task(page, "Alpha task", "closed")

        await page.get_by_role("link", name="Add Task").click()
        await page.get_by_role("link", name="Search Parent task").click()
        await expect(page.get_by_role("heading", name="Choose Parent task")).to_be_visible()
        await page.get_by_label("Search Parent task").fill("Alpha")
        await page.get_by_role("button", name="Search").click()
        await expect(page.get_by_role("status")).to_contain_text("1 matching authorized record.")
        await page.get_by_role("link", name="Choose").click()
        await expect(page.get_by_label("Parent task")).to_have_value("2")
        await page.get_by_label("Name").fill("Related child")
        await page.get_by_label("Status").select_option("open")
        await page.get_by_label("Active").check()
        await page.get_by_label("Notes").fill("Notes for Related child")
        await page.get_by_role("button", name="Create").click()
        await expect(page.get_by_role("heading", name="Related child")).to_be_visible()
        await expect(page.get_by_role("link", name="Alpha task")).to_be_visible()

        await page.goto(f"{live_example.url}/admin/tasks")
        await expect(page.locator("tbody tr")).to_have_count(2)
        await page.get_by_role("link", name="Next").click()
        await expect(page.locator("tbody tr")).to_have_count(1)
        await expect(page.locator("tbody tr")).to_contain_text("Related child")
        await page.get_by_role("link", name="First").click()
        await expect(page.locator("tbody tr")).to_have_count(2)

        await page.goto(f"{live_example.url}/admin/tasks/object/2/inline/subtasks")
        await expect(page.get_by_role("heading", name="Subtasks for Alpha task")).to_be_visible()
        await expect(page.locator('input[value="Related child"]')).to_have_count(1)
        await page.get_by_role("button", name="Delete inline record").click()
        await expect(page.locator('input[value="Related child"]')).to_have_count(0)
        await page.get_by_role("link", name="Back to parent record").click()
        await page.get_by_role("link", name="Back to Tasks").click()

        await page.get_by_role("link", name="Name", exact=True).click()
        rows = page.locator("tbody tr")
        await expect(rows).to_have_count(2)
        await expect(rows.nth(0)).to_contain_text("Alpha task")

        await page.get_by_label("Select Zulu task").check()
        await page.get_by_label("Action").select_option("close")
        await page.get_by_role("button", name="Apply to selected").click()
        await expect(page.get_by_role("heading", name="Close selected")).to_be_visible()
        await expect(page.get_by_role("status")).to_contain_text("1 completed; 0 failed.")
        await page.get_by_role("link", name="Return to Tasks").click()

        await page.get_by_role("link", name="Closed tasks by name").click()
        await expect(page.get_by_role("link", name="Closed tasks by name")).to_have_attribute(
            "aria-current",
            "page",
        )
        await expect(page.locator("tbody tr")).to_have_count(2)
        async with page.expect_download() as download_info:
            await page.get_by_role("link", name="Export CSV").click()
        download = await download_info.value
        assert download.suggested_filename == "tasks.csv"
        download_path = await download.path()
        assert download_path is not None
        exported = Path(download_path).read_text(encoding="utf-8")
        assert exported.splitlines()[0] == "ID,Name,Status,Active,Parent task"
        assert "Zulu task" in exported
        assert "Alpha task" in exported
        assert "Notes for" not in exported
        await page.get_by_role("link", name="All records").click()

        await page.get_by_label("Search").fill("Zulu")
        await page.get_by_role("button", name="Apply", exact=True).click()
        await expect(page.locator("tbody tr")).to_have_count(1)
        await expect(page.locator("tbody tr")).to_contain_text("Zulu task")

        await page.get_by_label("Search").fill("Alpha")
        await page.get_by_label("Status").select_option("closed")
        await page.get_by_role("button", name="Apply", exact=True).click()
        await expect(page.locator("tbody tr")).to_have_count(1)
        await expect(page.locator("tbody tr")).to_contain_text("Alpha task")

        await page.get_by_role("link", name="Edit").click()
        await page.get_by_label("Name").fill("Beta task")
        await page.get_by_label("Status").select_option("open")
        await page.get_by_role("button", name="Save changes").click()
        await expect(page.get_by_role("heading", name="Beta task")).to_be_visible()

        await page.get_by_role("link", name="History").click()
        await expect(page.get_by_role("heading", name="History for 2")).to_be_visible()
        await expect(page.get_by_text("submitted values are not recorded")).to_be_visible()
        await expect(page.get_by_text("Beta task")).to_have_count(0)
        await page.get_by_role("link", name="Back to record").click()

        await page.get_by_role("link", name="Delete").click()
        await page.get_by_role("button", name="Confirm delete").click()
        await expect(page.get_by_role("heading", name="Tasks")).to_be_visible()
        await expect(page.get_by_text("Beta task")).to_have_count(0)

        assert console_errors == []
        assert page_errors == []
        assert request_failures == []
        await context.close()
        await browser.close()

    database = SQLiteDatabase(live_example.database_path)
    try:
        events = await list_admin_audit_events(database)
    finally:
        await database.close()
    assert [event["phase"] for event in events].count("success") == 8
    assert sum(event["operation"] == "close" for event in events) == 2
    assert sum(event["action"] == "resource:export" for event in events) == 2
    assert "Zulu task" not in repr(events)
    assert "Alpha task" not in repr(events)
    assert "Beta task" not in repr(events)
