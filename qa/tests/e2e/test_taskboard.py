"""v1 board flows, authenticated as alice (tasks recreated via the API per test)."""

from __future__ import annotations

from playwright.sync_api import ConsoleMessage, Locator, Page, expect
from qa_helpers import SEED_TASKS, ApiClient, alice_credentials, rfc3339_in


def _row(page: Page, title: str) -> Locator:
    return page.get_by_test_id("task-row").filter(has_text=title)


def test_board_lists_tasks_created_via_api(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.seed()
    alice_page.goto("/")
    expect(alice_page.get_by_test_id("task-list").first).to_be_visible()
    for spec in SEED_TASKS:
        row = _row(alice_page, spec["title"])
        expect(row).to_be_visible()
        expect(row.get_by_test_id("task-status")).to_have_text(spec["status"])
    expect(alice_page.get_by_test_id("task-count")).to_contain_text(str(len(SEED_TASKS)))
    expect(alice_page.get_by_test_id("user-email")).to_contain_text(alice_credentials()[0])


def test_create_task_appears_in_todo(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.seed()
    alice_page.goto("/")
    alice_page.get_by_test_id("new-task-link").click()
    alice_page.get_by_test_id("title-input").fill("Ship the gateway")
    alice_page.get_by_test_id("description-input").fill("Created by Playwright")
    alice_page.get_by_test_id("submit-task").click()
    row = _row(alice_page, "Ship the gateway")
    expect(row).to_be_visible()
    expect(row.get_by_test_id("task-status")).to_have_text("todo")
    expect(alice_page.get_by_test_id("task-count")).to_contain_text(str(len(SEED_TASKS) + 1))


def test_advance_task_todo_doing_done(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("Advance me", "created via API")
    alice_page.goto("/")
    row = _row(alice_page, "Advance me")
    expect(row.get_by_test_id("task-status")).to_have_text("todo")
    row.get_by_test_id("advance-btn").click()
    expect(row.get_by_test_id("task-status")).to_have_text("doing")
    row.get_by_test_id("advance-btn").click()
    expect(row.get_by_test_id("task-status")).to_have_text("done")


def test_delete_task_removes_row(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("Delete me", "created via API")
    alice_page.goto("/")
    row = _row(alice_page, "Delete me")
    expect(row).to_be_visible()
    row.get_by_test_id("delete-btn").click()
    expect(row).to_have_count(0)


def test_due_date_and_reminder_badge_rendering(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("No deadline", "plain task")
    alice_api.create_task("Has deadline", "due in an hour", due_at=rfc3339_in(3600))
    alice_page.goto("/")
    due_row = _row(alice_page, "Has deadline")
    expect(due_row).to_be_visible()
    expect(due_row.get_by_test_id("due-at")).to_be_visible()
    # reminder_status is `none` for a fresh task — no badge rendered.
    expect(_row(alice_page, "No deadline").get_by_test_id("reminder-badge")).to_have_count(0)


def test_board_has_no_console_errors(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.seed()
    errors: list[str] = []

    def on_console(msg: ConsoleMessage) -> None:
        if msg.type == "error":
            errors.append(msg.text)

    alice_page.on("console", on_console)
    alice_page.goto("/")
    expect(alice_page.get_by_test_id("task-list").first).to_be_visible()
    assert errors == []
