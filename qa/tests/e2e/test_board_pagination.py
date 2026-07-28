"""Board pagination: pager control, page navigation, filter/page round-trips (issue #8)."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect
from qa_helpers import ApiClient

PAGE_SIZE = 20


def _create_tasks(api: ApiClient, count: int, prefix: str = "Task") -> None:
    for i in range(count):
        api.create_task(f"{prefix} {i}")


def test_first_page_shows_one_page_and_next_only(alice_api: ApiClient, alice_page: Page) -> None:
    _create_tasks(alice_api, 22)
    alice_page.goto("/")

    expect(alice_page.get_by_test_id("task-row")).to_have_count(PAGE_SIZE)
    expect(alice_page.get_by_test_id("pager")).to_be_visible()
    expect(alice_page.get_by_test_id("pager-next")).to_be_visible()
    expect(alice_page.get_by_test_id("pager-prev")).to_have_count(0)


def test_next_navigates_to_second_page_with_prev_only(
    alice_api: ApiClient, alice_page: Page
) -> None:
    _create_tasks(alice_api, 22)
    alice_page.goto("/")

    alice_page.get_by_test_id("pager-next").click()

    expect(alice_page).to_have_url(re.compile(r"\?page=2$"))
    expect(alice_page.get_by_test_id("task-row")).to_have_count(2)
    expect(alice_page.get_by_test_id("pager-prev")).to_be_visible()
    expect(alice_page.get_by_test_id("pager-next")).to_have_count(0)


def test_pager_preserves_status_filter(alice_api: ApiClient, alice_page: Page) -> None:
    _create_tasks(alice_api, 22)
    alice_page.goto("/?status=todo")

    alice_page.get_by_test_id("pager-next").click()

    expect(alice_page).to_have_url(re.compile(r"status=todo.*page=2|page=2.*status=todo"))
    expect(alice_page.get_by_test_id("filter-todo")).to_have_attribute("aria-current", "page")
    assert alice_page.locator('[aria-current="page"]').count() == 1


def test_task_count_is_grand_total_across_pages(alice_api: ApiClient, alice_page: Page) -> None:
    _create_tasks(alice_api, 22)
    alice_page.goto("/")
    expect(alice_page.get_by_test_id("task-count")).to_contain_text("22")

    alice_page.get_by_test_id("pager-next").click()

    expect(alice_page.get_by_test_id("task-count")).to_contain_text("22")


def test_advance_from_second_page_returns_to_second_page(
    alice_api: ApiClient, alice_page: Page
) -> None:
    _create_tasks(alice_api, 21, prefix="Filler")
    alice_api.create_task("Advance me on page two")
    alice_page.goto("/?page=2")
    row = alice_page.get_by_test_id("task-row").filter(has_text="Advance me on page two")
    expect(row).to_be_visible()

    row.get_by_test_id("advance-btn").click()

    expect(alice_page).to_have_url(re.compile(r"\?page=2$"))


def test_move_back_returns_to_same_page_and_filter(
    alice_api: ApiClient, alice_page: Page
) -> None:
    _create_tasks(alice_api, 21, prefix="Filler")
    alice_api.create_task("Move back on page two")
    alice_page.goto("/?status=todo&page=2")
    row = alice_page.get_by_test_id("task-row").filter(has_text="Move back on page two")
    expect(row).to_be_visible()
    pager_status = alice_page.get_by_test_id("pager-status").inner_text()

    row.get_by_test_id("move-back-btn").click()

    expect(alice_page).to_have_url(re.compile(r"status=todo.*page=2|page=2.*status=todo"))
    expect(alice_page.get_by_test_id("pager-status")).to_have_text(pager_status)
    assert alice_page.locator('[aria-current="page"]').count() == 1


def test_delete_from_second_page_returns_to_second_page(
    alice_api: ApiClient, alice_page: Page
) -> None:
    _create_tasks(alice_api, 21, prefix="Filler")
    alice_api.create_task("Delete me on page two")
    alice_page.goto("/?page=2")
    row = alice_page.get_by_test_id("task-row").filter(has_text="Delete me on page two")
    expect(row).to_be_visible()

    row.get_by_test_id("delete-btn").click()

    expect(alice_page).to_have_url(re.compile(r"\?page=2$"))
    remaining = alice_page.get_by_test_id("task-row").filter(has_text="Delete me on page two")
    expect(remaining).to_have_count(0)


@pytest.mark.parametrize("value", ["", "abc", "0", "-1"])
def test_invalid_page_param_renders_first_page(
    alice_api: ApiClient, alice_page: Page, value: str
) -> None:
    _create_tasks(alice_api, 22)

    resp = alice_page.goto(f"/?page={value}")

    assert resp is not None and resp.status == 200
    expect(alice_page.get_by_test_id("task-row")).to_have_count(PAGE_SIZE)
    expect(alice_page.get_by_test_id("pager-prev")).to_have_count(0)


def test_out_of_range_page_renders_first_page(alice_api: ApiClient, alice_page: Page) -> None:
    _create_tasks(alice_api, 22)

    resp = alice_page.goto("/?page=999")

    assert resp is not None and resp.status == 200
    expect(alice_page.get_by_test_id("task-row")).to_have_count(PAGE_SIZE)
    expect(alice_page.get_by_test_id("pager-prev")).to_have_count(0)
