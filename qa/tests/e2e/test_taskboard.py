"""v1 board flows, authenticated as alice (tasks recreated via the API per test)."""

from __future__ import annotations

import re

from playwright.sync_api import ConsoleMessage, Locator, Page, expect
from qa_helpers import SEED_TASKS, ApiClient, alice_credentials, rfc3339_in, wait_until


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


def test_move_back_done_doing_todo(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("Move me back", "created via API")
    alice_page.goto("/")
    row = _row(alice_page, "Move me back")
    row.get_by_test_id("advance-btn").click()
    row.get_by_test_id("advance-btn").click()
    expect(row.get_by_test_id("task-status")).to_have_text("done")
    row.get_by_test_id("move-back-btn").click()
    expect(row.get_by_test_id("task-status")).to_have_text("doing")
    row.get_by_test_id("move-back-btn").click()
    expect(row.get_by_test_id("task-status")).to_have_text("todo")


def test_move_back_on_todo_task_is_noop(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("Stays todo", "created via API")
    alice_page.goto("/")
    row = _row(alice_page, "Stays todo")
    row.get_by_test_id("move-back-btn").click()
    row = _row(alice_page, "Stays todo")
    expect(row.get_by_test_id("task-status")).to_have_text("todo")
    expect(alice_page.get_by_test_id("task-list").first).to_be_visible()
    expect(alice_page.get_by_test_id("api-error")).to_have_count(0)


def test_move_back_preserves_task_fields(alice_api: ApiClient, alice_page: Page) -> None:
    task = alice_api.create_due_task("Preserve me", in_seconds=2)

    def reminder_pending() -> bool:
        alice_api.run_due_reminders()
        return alice_api.get_task(task["id"])["reminder_status"] != "none"

    wait_until(reminder_pending, timeout=15, message="reminder_status leaves none")

    alice_page.goto("/")
    row = _row(alice_page, "Preserve me")
    task_id = row.get_attribute("data-task-id")
    due_label = row.get_by_test_id("due-at").inner_text()
    reminder_text = row.get_by_test_id("reminder-badge").inner_text()
    row.get_by_test_id("advance-btn").click()
    row = _row(alice_page, "Preserve me")
    row.get_by_test_id("move-back-btn").click()
    row = _row(alice_page, "Preserve me")
    expect(row).to_have_attribute("data-task-id", task_id)
    expect(row.get_by_test_id("task-title")).to_have_text("Preserve me")
    expect(row.get_by_test_id("due-at")).to_have_text(due_label)
    expect(row.get_by_test_id("reminder-badge")).to_have_text(reminder_text)
    expect(row.get_by_test_id("task-status")).to_have_text("todo")


def test_move_back_returns_to_filtered_board(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("Filtered move back", "created via API")
    alice_page.goto("/")
    row = _row(alice_page, "Filtered move back")
    row.get_by_test_id("advance-btn").click()

    alice_page.goto("/?status=doing")
    row = _row(alice_page, "Filtered move back")
    row.get_by_test_id("move-back-btn").click()

    expect(alice_page).to_have_url(re.compile(r"/\?status=doing$"))
    expect(alice_page.get_by_test_id("filter-doing")).to_have_attribute("aria-current", "page")


def test_delete_task_removes_row(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("Delete me", "created via API")
    alice_page.goto("/")
    row = _row(alice_page, "Delete me")
    expect(row).to_be_visible()
    row.get_by_test_id("delete-btn").click()
    expect(row).to_have_count(0)


def test_due_date_renders_human_readable(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("No deadline", "plain task")
    alice_api.create_task("Has deadline", "due in an hour", due_at=rfc3339_in(3600))
    alice_page.goto("/")
    due_row = _row(alice_page, "Has deadline")
    expect(due_row).to_be_visible()
    due_at = due_row.get_by_test_id("due-at")
    expect(due_at).to_be_visible()
    expect(due_at).to_have_text(re.compile(r"^\d{2} [A-Z][a-z]{2} \d{4}, \d{2}:\d{2} UTC$"))
    # The anchored regex above already rules out raw RFC3339 (e.g. "T" as a date/time
    # separator, trailing "Z"); a bare "T" substring check false-positives on "UTC".
    # reminder_status is `none` for a fresh task — no badge rendered.
    expect(_row(alice_page, "No deadline").get_by_test_id("reminder-badge")).to_have_count(0)


def test_future_due_task_has_no_overdue_badge(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("Has deadline", "due in an hour", due_at=rfc3339_in(3600))
    alice_page.goto("/")
    row = _row(alice_page, "Has deadline")
    expect(row).to_be_visible()
    expect(row.get_by_test_id("overdue-badge")).to_have_count(0)


def test_undated_task_has_no_due_or_overdue(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("No deadline", "plain task")
    alice_page.goto("/")
    row = _row(alice_page, "No deadline")
    expect(row).to_be_visible()
    expect(row.get_by_test_id("due-at")).to_have_count(0)
    expect(row.get_by_test_id("overdue-badge")).to_have_count(0)


def test_task_becomes_overdue_after_due_time(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("Soon overdue", "due very soon", due_at=rfc3339_in(2))

    def overdue_badge_shown() -> bool:
        alice_page.goto("/")
        row = alice_page.get_by_test_id("task-row").filter(has_text="Soon overdue")
        return row.get_by_test_id("overdue-badge").count() == 1

    wait_until(overdue_badge_shown, timeout=15, message="overdue-badge shows for past-due task")


def test_column_orders_by_due_date_then_id(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("A", "due in 5 days", due_at=rfc3339_in(5 * 86400))
    alice_api.create_task("B", "no due date")
    alice_api.create_task("C", "due in 1 day", due_at=rfc3339_in(86400))
    alice_page.goto("/")
    titles = alice_page.locator("#column-todo").get_by_test_id("task-title").all_inner_texts()
    assert titles == ["C", "A", "B"]


def test_advance_overdue_task_moves_column_and_still_renders(
    alice_api: ApiClient, alice_page: Page
) -> None:
    alice_api.create_task("Overdue advance", "due very soon", due_at=rfc3339_in(2))

    def overdue_badge_shown() -> bool:
        alice_page.goto("/")
        row = _row(alice_page, "Overdue advance")
        return row.get_by_test_id("overdue-badge").count() == 1

    wait_until(overdue_badge_shown, timeout=15, message="overdue-badge shows for past-due task")
    row = _row(alice_page, "Overdue advance")
    row.get_by_test_id("advance-btn").click()
    row = _row(alice_page, "Overdue advance")
    expect(row.get_by_test_id("task-status")).to_have_text("doing")
    expect(alice_page.get_by_test_id("task-list").first).to_be_visible()
    expect(row.get_by_test_id("overdue-badge")).to_have_count(1)


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


def test_whitespace_only_title_is_rejected_in_ui(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.seed()
    alice_page.goto("/new")
    alice_page.get_by_test_id("title-input").fill(" ")
    alice_page.get_by_test_id("description-input").fill("should survive")
    alice_page.get_by_test_id("due-at-input").fill("2026-03-01T12:30")
    alice_page.get_by_test_id("submit-task").click()

    expect(alice_page).to_have_url(re.compile(r"/new$"))
    expect(alice_page.get_by_test_id("api-error")).to_be_visible()
    expect(alice_page.get_by_test_id("description-input")).to_have_value("should survive")
    expect(alice_page.get_by_test_id("due-at-input")).to_have_value("2026-03-01T12:30")

    alice_page.goto("/")
    expect(alice_page.get_by_test_id("task-count")).to_contain_text(str(len(SEED_TASKS)))
    for title in alice_page.get_by_test_id("task-title").all_inner_texts():
        assert not re.fullmatch(r"\s*", title)
