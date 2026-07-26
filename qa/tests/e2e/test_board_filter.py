"""Board status filter: URL-driven, bookmarkable, owner-scoped (issue #4)."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect
from qa_helpers import SEED_TASKS, ApiClient, alice_credentials


def test_unfiltered_board_shows_all_three_columns(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.seed()
    alice_page.goto("/")

    expect(alice_page.get_by_test_id("task-row")).to_have_count(len(SEED_TASKS))
    for status in ("todo", "doing", "done"):
        expect(alice_page.locator(f"#column-{status}")).to_be_visible()


def test_filter_link_navigates_and_narrows_board(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.seed()
    alice_page.goto("/")

    alice_page.get_by_test_id("filter-doing").click()

    expect(alice_page).to_have_url(re.compile(r"\?status=doing$"))
    expect(alice_page.get_by_test_id("task-row")).to_have_count(1)
    expect(alice_page.get_by_test_id("task-row").get_by_test_id("task-status")).to_have_text(
        "doing"
    )


def test_filtered_url_survives_reload(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.seed()
    alice_page.goto("/?status=todo")

    alice_page.reload()

    expect(alice_page.get_by_test_id("task-row")).to_have_count(1)
    expect(alice_page.get_by_test_id("task-row").get_by_test_id("task-status")).to_have_text("todo")
    expect(alice_page.get_by_test_id("filter-todo")).to_have_attribute("aria-current", "page")


def test_all_link_returns_to_full_board(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.seed()
    alice_page.goto("/?status=done")

    alice_page.get_by_test_id("filter-all").click()

    expect(alice_page).to_have_url(re.compile(r"/$"))
    expect(alice_page.get_by_test_id("task-row")).to_have_count(len(SEED_TASKS))


@pytest.mark.parametrize("status", ["all", "todo", "doing", "done"])
def test_active_filter_is_indicated(alice_api: ApiClient, alice_page: Page, status: str) -> None:
    alice_api.seed()
    url = "/" if status == "all" else f"/?status={status}"
    alice_page.goto(url)

    expect(alice_page.get_by_test_id("status-filter")).to_be_visible()
    expect(alice_page.get_by_test_id(f"filter-{status}")).to_have_attribute("aria-current", "page")
    assert alice_page.locator('[aria-current="page"]').count() == 1


def test_filter_with_no_matching_tasks_renders_empty_board(
    alice_api: ApiClient, alice_page: Page
) -> None:
    alice_api.create_task("Only todo task")
    alice_page.goto("/?status=done")

    expect(alice_page.get_by_test_id("task-list")).to_be_visible()
    expect(alice_page.get_by_test_id("task-row")).to_have_count(0)
    expect(alice_page.get_by_test_id("api-error")).to_have_count(0)


def test_unknown_filter_value_renders_full_board(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.seed()
    alice_page.goto("/?status=archived")

    expect(alice_page.get_by_test_id("task-row")).to_have_count(len(SEED_TASKS))
    expect(alice_page.get_by_test_id("filter-all")).to_have_attribute("aria-current", "page")
    expect(alice_page.get_by_test_id("api-error")).to_have_count(0)


def test_advance_keeps_filter_and_removes_task(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("Advance me")
    alice_page.goto("/?status=todo")
    row = alice_page.get_by_test_id("task-row").filter(has_text="Advance me")

    row.get_by_test_id("advance-btn").click()

    expect(alice_page).to_have_url(re.compile(r"\?status=todo$"))
    expect(alice_page.get_by_test_id("task-row").filter(has_text="Advance me")).to_have_count(0)


def test_delete_keeps_filter(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("Delete me")
    alice_page.goto("/?status=todo")
    row = alice_page.get_by_test_id("task-row").filter(has_text="Delete me")

    row.get_by_test_id("delete-btn").click()

    expect(alice_page).to_have_url(re.compile(r"\?status=todo$"))
    expect(alice_page.get_by_test_id("task-row").filter(has_text="Delete me")).to_have_count(0)


def test_unauthed_filtered_url_redirects_to_login_then_returns(
    page: Page, alice_api: ApiClient
) -> None:
    alice_api.seed()
    email, password = alice_credentials()
    page.goto("/?status=todo")

    expect(page).to_have_url(re.compile(r"/login"))
    page.get_by_test_id("email-input").fill(email)
    page.get_by_test_id("password-input").fill(password)
    page.get_by_test_id("submit-login").click()

    expect(page).to_have_url(re.compile(r"\?status=todo$"))
    expect(page.get_by_test_id("task-row")).to_have_count(1)


def test_filter_respects_owner_scoping(
    alice_api: ApiClient, bob_api: ApiClient, bob_page: Page
) -> None:
    alice_api.create_task("Alice todo task")
    bob_api.create_task("Bob todo task")
    bob_page.goto("/?status=todo")

    expect(bob_page.get_by_test_id("task-row")).to_have_count(1)
    expect(bob_page.get_by_test_id("task-row")).to_contain_text("Bob todo task")
    expect(bob_page.get_by_test_id("task-row")).not_to_contain_text("Alice todo task")


def test_task_count_is_total_when_filtered(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.seed()
    alice_page.goto("/?status=done")

    expect(alice_page.get_by_test_id("task-count")).to_contain_text(str(len(SEED_TASKS)))
