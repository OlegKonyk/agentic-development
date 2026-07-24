from __future__ import annotations

import httpx
from playwright.sync_api import ConsoleMessage, Locator, Page, expect
from qa_helpers import SEED_TASKS, ApiClient


def _row(page: Page, title: str) -> Locator:
    return page.get_by_test_id("task-row").filter(has_text=title)


def test_index_lists_seeded_tasks(page: Page) -> None:
    page.goto("/")
    expect(page.get_by_test_id("task-list").first).to_be_visible()
    for spec in SEED_TASKS:
        row = _row(page, spec["title"])
        expect(row).to_be_visible()
        expect(row.get_by_test_id("task-status")).to_have_text(spec["status"])


def test_task_count_matches_seed(page: Page) -> None:
    page.goto("/")
    expect(page.get_by_test_id("task-count")).to_have_text(f"Tasks: {len(SEED_TASKS)}")


def test_create_task_appears_in_todo(page: Page) -> None:
    page.goto("/")
    page.get_by_test_id("new-task-link").click()
    page.get_by_test_id("title-input").fill("Ship the gateway")
    page.get_by_test_id("description-input").fill("Created by Playwright")
    page.get_by_test_id("submit-task").click()
    row = _row(page, "Ship the gateway")
    expect(row).to_be_visible()
    expect(row.get_by_test_id("task-status")).to_have_text("todo")


def test_task_count_increments_after_create(page: Page) -> None:
    page.goto("/")
    expect(page.get_by_test_id("task-count")).to_have_text(f"Tasks: {len(SEED_TASKS)}")
    page.get_by_test_id("new-task-link").click()
    page.get_by_test_id("title-input").fill("Ship the gateway")
    page.get_by_test_id("submit-task").click()
    expect(page.get_by_test_id("task-count")).to_have_text(f"Tasks: {len(SEED_TASKS) + 1}")


def test_advance_task_todo_doing_done(page: Page) -> None:
    page.goto("/")
    row = _row(page, "Set up repo")
    expect(row.get_by_test_id("task-status")).to_have_text("todo")
    row.get_by_test_id("advance-btn").click()
    expect(row.get_by_test_id("task-status")).to_have_text("doing")
    row.get_by_test_id("advance-btn").click()
    expect(row.get_by_test_id("task-status")).to_have_text("done")


def test_task_count_unchanged_after_advance(page: Page) -> None:
    page.goto("/")
    row = _row(page, "Set up repo")
    row.get_by_test_id("advance-btn").click()
    expect(row.get_by_test_id("task-status")).to_have_text("doing")
    expect(page.get_by_test_id("task-count")).to_have_text(f"Tasks: {len(SEED_TASKS)}")


def test_delete_task_removes_row(page: Page) -> None:
    page.goto("/")
    row = _row(page, "Build API")
    expect(row).to_be_visible()
    row.get_by_test_id("delete-btn").click()
    expect(row).to_have_count(0)


def test_task_count_decrements_after_delete(page: Page) -> None:
    page.goto("/")
    row = _row(page, "Build API")
    row.get_by_test_id("delete-btn").click()
    expect(row).to_have_count(0)
    expect(page.get_by_test_id("task-count")).to_have_text(f"Tasks: {len(SEED_TASKS) - 1}")


def test_task_count_zero_when_board_emptied(page: Page) -> None:
    page.goto("/")
    for i in range(len(SEED_TASKS)):
        page.get_by_test_id("delete-btn").first.click()
        expect(page.get_by_test_id("task-row")).to_have_count(len(SEED_TASKS) - i - 1)
    expect(page.get_by_test_id("task-count")).to_have_text("Tasks: 0")


def test_new_page_has_no_task_count(page: Page) -> None:
    page.goto("/")
    page.get_by_test_id("new-task-link").click()
    expect(page.get_by_test_id("task-count")).to_have_count(0)


def test_api_requires_gateway_key(gateway_url: str, api: ApiClient) -> None:
    unauthenticated = httpx.get(f"{gateway_url}/api/tasks")
    assert unauthenticated.status_code == 401

    authenticated = httpx.get(f"{gateway_url}/api/tasks", headers={"x-api-key": api.api_key})
    assert authenticated.status_code == 200


def test_index_has_no_console_errors(page: Page) -> None:
    errors: list[str] = []

    def on_console(msg: ConsoleMessage) -> None:
        if msg.type == "error":
            errors.append(msg.text)

    page.on("console", on_console)
    page.goto("/")
    expect(page.get_by_test_id("task-list").first).to_be_visible()
    assert errors == []
