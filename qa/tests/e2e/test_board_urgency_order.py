"""Board-wide urgency ordering survives paging and filtering (issue #52)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from playwright.sync_api import Page, expect
from qa_helpers import ApiClient, rfc3339_in, wait_until

PAGE_SIZE = 20


def _row_titles(page: Page) -> list[str]:
    return page.get_by_test_id("task-title").all_inner_texts()


def _walk_pages(page: Page, status: str | None = None) -> list[str]:
    """Collect task titles across every page, in rendered order."""
    page.goto(f"/?status={status}" if status else "/")
    titles: list[str] = []
    while True:
        if status:
            expect(page.get_by_test_id(f"filter-{status}")).to_have_attribute(
                "aria-current", "page"
            )
        titles.extend(_row_titles(page))
        next_link = page.get_by_test_id("pager-next")
        if next_link.count() == 0:
            break
        next_link.click()
    return titles


def test_page_one_holds_the_most_urgent_tasks(alice_api: ApiClient, alice_page: Page) -> None:
    # Created in ascending id but descending urgency (task 24 is soonest-due), so
    # a passing test can't be an id-order accident.
    for i in range(25):
        alice_api.create_task(f"Task {i}", due_at=rfc3339_in(86400 * (25 - i)))

    alice_page.goto("/")

    assert _row_titles(alice_page) == [f"Task {i}" for i in range(24, 4, -1)]


def test_overdue_task_created_last_appears_on_page_one(
    alice_api: ApiClient, alice_page: Page
) -> None:
    for i in range(21):
        alice_api.create_task(f"Filler {i}", due_at=rfc3339_in(86400 * 30))
    alice_api.create_task("Nearly due", due_at=rfc3339_in(2))

    def overdue_on_page_one() -> bool:
        alice_page.goto("/")
        row = alice_page.get_by_test_id("task-row").filter(has_text="Nearly due")
        return row.count() == 1 and row.get_by_test_id("overdue-badge").count() == 1

    wait_until(
        overdue_on_page_one,
        timeout=20,
        interval=1,
        message="overdue task appears on page 1 with its overdue-badge",
    )


def test_no_undated_task_precedes_a_dated_one_across_pages(
    alice_api: ApiClient, alice_page: Page
) -> None:
    for i in range(15):
        alice_api.create_task(f"Dated {i}", due_at=rfc3339_in(86400 * (i + 1)))
    for i in range(10):
        alice_api.create_task(f"Undated {i}")

    titles = _walk_pages(alice_page)

    first_undated = next((i for i, t in enumerate(titles) if t.startswith("Undated")), len(titles))
    assert all(t.startswith("Undated") for t in titles[first_undated:])


def test_every_task_appears_exactly_once_across_pages(
    alice_api: ApiClient, alice_page: Page
) -> None:
    for i in range(24):
        due = rfc3339_in(86400 * (i + 1)) if i % 2 == 0 else None
        alice_api.create_task(f"Task {i}", due_at=due)

    titles = _walk_pages(alice_page)

    assert len(titles) == len(set(titles)) == 24


def test_filtered_board_pages_in_urgency_order(alice_api: ApiClient, alice_page: Page) -> None:
    for i in range(12):
        alice_api.create_task(f"Todo dated {i}", due_at=rfc3339_in(86400 * (i + 1)))
    for i in range(8):
        alice_api.create_task(f"Todo undated {i}")
    noise = alice_api.create_task("Doing noise", due_at=rfc3339_in(60))
    alice_api.set_status(noise["id"], "doing")

    titles = _walk_pages(alice_page, status="todo")

    assert "Doing noise" not in titles
    assert len(titles) == len(set(titles)) == 20
    first_undated = next(
        (i for i, t in enumerate(titles) if t.startswith("Todo undated")), len(titles)
    )
    assert all(t.startswith("Todo undated") for t in titles[first_undated:])


def test_new_soonest_task_lands_first_on_page_one(alice_api: ApiClient, alice_page: Page) -> None:
    for i in range(25):
        alice_api.create_task(f"Existing {i}", due_at=rfc3339_in(86400 * (i + 2)))

    alice_page.goto("/new")
    alice_page.get_by_test_id("title-input").fill("Soonest of all")
    due_soon = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    alice_page.get_by_test_id("due-at-input").fill(due_soon)
    alice_page.get_by_test_id("submit-task").click()

    expect(alice_page).to_have_url(re.compile(r"/$"))
    expect(alice_page.get_by_test_id("task-title").first).to_have_text("Soonest of all")
