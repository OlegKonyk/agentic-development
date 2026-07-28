"""Edit an existing task: title/description/due-date changes, clearing a due
date, validation, auth gating and cross-user isolation (issue #54)."""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Locator, Page, expect
from qa_helpers import ApiClient, alice_credentials, bob_credentials, rfc3339_in, wait_until


def _row(page: Page, title: str) -> Locator:
    return page.get_by_test_id("task-row").filter(has_text=title)


def test_edit_link_opens_prefilled_form(alice_api: ApiClient, alice_page: Page) -> None:
    task = alice_api.create_task("Edit me", "original description", due_at=rfc3339_in(3600))
    alice_page.goto("/")
    row = _row(alice_page, "Edit me")
    row.get_by_test_id("edit-link").click()

    expect(alice_page).to_have_url(re.compile(rf"/tasks/{task['id']}/edit$"))
    expect(alice_page.get_by_test_id("title-input")).to_have_value("Edit me")
    expect(alice_page.get_by_test_id("description-input")).to_have_value("original description")
    expect(alice_page.get_by_test_id("due-at-input")).not_to_have_value("")
    expect(alice_page.get_by_test_id("submit-edit")).to_be_visible()
    expect(alice_page.get_by_test_id("edit-cancel")).to_be_visible()


def test_edit_title_updates_board_and_leaves_rest(alice_api: ApiClient, alice_page: Page) -> None:
    task = alice_api.create_task("Old title", "keep me", due_at=rfc3339_in(3600))
    alice_page.goto("/")
    _row(alice_page, "Old title").get_by_test_id("edit-link").click()

    alice_page.get_by_test_id("title-input").fill("New title")
    alice_page.get_by_test_id("submit-edit").click()

    expect(alice_page).to_have_url(re.compile(r"/$"))
    expect(_row(alice_page, "New title")).to_be_visible()
    fetched = alice_api.get_task(task["id"])
    assert fetched["description"] == "keep me"
    assert fetched["due_at"] == task["due_at"]
    assert fetched["status"] == "todo"
    assert fetched["reminder_status"] == "none"


def test_edit_description_persists(alice_api: ApiClient, alice_page: Page) -> None:
    task = alice_api.create_task("Describe me", "old description")
    alice_page.goto("/")
    _row(alice_page, "Describe me").get_by_test_id("edit-link").click()

    alice_page.get_by_test_id("description-input").fill("new description")
    alice_page.get_by_test_id("submit-edit").click()

    assert alice_api.get_task(task["id"])["description"] == "new description"
    alice_page.goto(f"/tasks/{task['id']}/edit")
    expect(alice_page.get_by_test_id("description-input")).to_have_value("new description")


def test_new_due_date_reorders_column(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("Stays soon", "", due_at=rfc3339_in(60))
    later = alice_api.create_task("Moves sooner", "", due_at=rfc3339_in(5 * 86400))
    alice_page.goto("/")
    _row(alice_page, "Moves sooner").get_by_test_id("edit-link").click()

    alice_page.get_by_test_id("due-at-input").fill("2026-08-25T17:00")
    alice_page.get_by_test_id("submit-edit").click()

    titles = alice_page.locator("#column-todo").get_by_test_id("task-title").all_inner_texts()
    assert titles == ["Moves sooner", "Stays soon"]
    fetched = alice_api.get_task(later["id"])
    assert fetched["due_at"] is not None


def test_clearing_due_date_removes_due_and_overdue(alice_api: ApiClient, alice_page: Page) -> None:
    task = alice_api.create_task("Has a deadline", "", due_at=rfc3339_in(3600))
    alice_page.goto("/")
    _row(alice_page, "Has a deadline").get_by_test_id("edit-link").click()

    alice_page.get_by_test_id("due-at-input").fill("")
    alice_page.get_by_test_id("submit-edit").click()

    row = _row(alice_page, "Has a deadline")
    expect(row.get_by_test_id("due-at")).to_have_count(0)
    expect(row.get_by_test_id("overdue-badge")).to_have_count(0)
    assert alice_api.get_task(task["id"])["due_at"] is None


def test_edit_title_of_overdue_task_keeps_past_due(alice_api: ApiClient, alice_page: Page) -> None:
    task = alice_api.create_task("Soon overdue", "", due_at=rfc3339_in(2))

    def overdue_badge_shown() -> bool:
        alice_page.goto("/")
        row = _row(alice_page, "Soon overdue")
        return row.get_by_test_id("overdue-badge").count() == 1

    wait_until(overdue_badge_shown, timeout=15, message="overdue-badge shows for past-due task")

    _row(alice_page, "Soon overdue").get_by_test_id("edit-link").click()
    alice_page.get_by_test_id("title-input").fill("Still overdue")
    alice_page.get_by_test_id("submit-edit").click()

    expect(alice_page).to_have_url(re.compile(r"/$"))
    expect(alice_page.get_by_test_id("api-error")).to_have_count(0)
    row = _row(alice_page, "Still overdue")
    expect(row.get_by_test_id("overdue-badge")).to_be_visible()
    fetched = alice_api.get_task(task["id"])
    assert fetched["due_at"] == task["due_at"]


def test_past_due_date_rejected_with_error_and_typed_values(
    alice_api: ApiClient, alice_page: Page
) -> None:
    task = alice_api.create_task("Reject me", "keep typed")
    alice_page.goto(f"/tasks/{task['id']}/edit")

    alice_page.get_by_test_id("title-input").fill("Reject me")
    alice_page.get_by_test_id("description-input").fill("keep typed")
    alice_page.get_by_test_id("due-at-input").fill("2020-01-01T00:00")
    alice_page.get_by_test_id("submit-edit").click()

    expect(alice_page.get_by_test_id("api-error")).to_be_visible()
    expect(alice_page.get_by_test_id("description-input")).to_have_value("keep typed")
    expect(alice_page.get_by_test_id("due-at-input")).to_have_value("2020-01-01T00:00")
    assert alice_api.get_task(task["id"])["due_at"] is None


def test_whitespace_only_title_rejected(alice_api: ApiClient, alice_page: Page) -> None:
    task = alice_api.create_task("Original title")
    alice_page.goto(f"/tasks/{task['id']}/edit")

    alice_page.get_by_test_id("title-input").fill(" ")
    alice_page.get_by_test_id("description-input").fill("should survive")
    alice_page.get_by_test_id("submit-edit").click()

    expect(alice_page).to_have_url(re.compile(rf"/tasks/{task['id']}/edit$"))
    expect(alice_page.get_by_test_id("api-error")).to_be_visible()
    expect(alice_page.get_by_test_id("description-input")).to_have_value("should survive")
    assert alice_api.get_task(task["id"])["title"] == "Original title"


def test_edit_returns_to_filtered_paged_board(alice_api: ApiClient, alice_page: Page) -> None:
    task = alice_api.create_task("Filtered edit", "")
    alice_api.set_status(task["id"], "doing")
    alice_page.goto("/?status=doing")
    _row(alice_page, "Filtered edit").get_by_test_id("edit-link").click()

    expect(alice_page).to_have_url(re.compile(rf"/tasks/{task['id']}/edit\?status=doing$"))
    alice_page.get_by_test_id("title-input").fill("Filtered edit saved")
    alice_page.get_by_test_id("submit-edit").click()

    expect(alice_page).to_have_url(re.compile(r"/\?status=doing$"))
    expect(alice_page.get_by_test_id("filter-doing")).to_have_attribute("aria-current", "page")
    expect(_row(alice_page, "Filtered edit saved")).to_be_visible()


def test_cancel_returns_to_same_board_unchanged(alice_api: ApiClient, alice_page: Page) -> None:
    task = alice_api.create_task("Do not touch", "original")
    alice_page.goto("/?status=todo")
    _row(alice_page, "Do not touch").get_by_test_id("edit-link").click()

    alice_page.get_by_test_id("title-input").fill("Should not save")
    alice_page.get_by_test_id("edit-cancel").click()

    expect(alice_page).to_have_url(re.compile(r"/\?status=todo$"))
    expect(_row(alice_page, "Do not touch")).to_be_visible()
    assert alice_api.get_task(task["id"])["title"] == "Do not touch"


def test_cross_user_edit_discloses_nothing_and_does_not_modify(
    alice_api: ApiClient, bob_page: Page
) -> None:
    bobs_email = bob_credentials()[0]
    alice_task = alice_api.create_task("Alice's private title", "alice's private description")

    bob_page.goto(f"/tasks/{alice_task['id']}/edit")
    expect(bob_page).to_have_url(re.compile(r"/$"))
    expect(bob_page.get_by_test_id("user-email")).to_contain_text(bobs_email)
    assert "Alice's private title" not in bob_page.content()
    assert "alice's private description" not in bob_page.content()

    # Same-context request (real session cookie + a real csrf token from bob's
    # own board), aimed at alice's task id: must not disclose or mutate it.
    bob_page.goto("/new")
    csrf = bob_page.locator('input[name="csrf_token"]').get_attribute("value")
    resp = bob_page.request.post(
        f"/tasks/{alice_task['id']}/edit",
        form={"title": "hijacked", "csrf_token": csrf},
    )
    assert resp.ok
    assert "hijacked" not in resp.text()
    assert alice_api.get_task(alice_task["id"])["title"] == "Alice's private title"


@pytest.fixture
def expired_alice_page(browser: Browser, base_url: str) -> Iterator[Page]:
    email, password = alice_credentials()
    context = browser.new_context(base_url=base_url, timezone_id="UTC")
    page = context.new_page()
    page.goto("/login")
    page.get_by_test_id("email-input").fill(email)
    page.get_by_test_id("password-input").fill(password)
    page.get_by_test_id("submit-login").click()
    expect(page.get_by_test_id("user-email")).to_contain_text(email)

    expired_state = context.storage_state()  # captured BEFORE logout
    page.get_by_test_id("logout-btn").click()
    context.close()

    expired_context = browser.new_context(
        base_url=base_url, storage_state=expired_state, timezone_id="UTC"
    )
    yield expired_context.new_page()
    expired_context.close()


def test_edit_with_revoked_session_lands_on_login_with_notice(
    alice_api: ApiClient, expired_alice_page: Page
) -> None:
    task = alice_api.create_task("Expired session edit")
    page = expired_alice_page

    page.goto(f"/tasks/{task['id']}/edit")

    expect(page.get_by_test_id("session-expired")).to_be_visible()
    assert "/login" in page.url
