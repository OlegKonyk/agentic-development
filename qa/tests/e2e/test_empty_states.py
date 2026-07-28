"""Empty-board and empty-filter messages (issue #50)."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect
from qa_helpers import ApiClient


def test_empty_board_message_and_link_reach_new_task_page(alice_page: Page) -> None:
    alice_page.goto("/")

    expect(alice_page.get_by_test_id("empty-board")).to_be_visible()
    alice_page.get_by_test_id("empty-board-new-link").click()

    expect(alice_page).to_have_url(re.compile(r"/new$"))
    expect(alice_page.get_by_test_id("title-input")).to_be_visible()


def test_board_with_tasks_shows_no_empty_message(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.seed()
    alice_page.goto("/")

    expect(alice_page.get_by_test_id("empty-board")).to_have_count(0)
    expect(alice_page.get_by_test_id("empty-filter")).to_have_count(0)


def test_filtered_column_with_no_matches_shows_empty_filter_message(
    alice_api: ApiClient, alice_page: Page
) -> None:
    alice_api.create_task("Only todo task")
    alice_page.goto("/?status=done")

    empty_filter = alice_page.get_by_test_id("empty-filter")
    expect(empty_filter).to_be_visible()
    expect(empty_filter).to_contain_text("done")
    expect(alice_page.get_by_test_id("empty-board")).to_have_count(0)
    expect(alice_page.get_by_test_id("api-error")).to_have_count(0)


def test_zero_tasks_filtered_shows_only_empty_filter_message(alice_page: Page) -> None:
    alice_page.goto("/?status=todo")

    expect(alice_page.get_by_test_id("empty-filter")).to_have_count(1)
    expect(alice_page.get_by_test_id("empty-board")).to_have_count(0)


def test_filtered_column_with_matches_shows_no_empty_message(
    alice_api: ApiClient, alice_page: Page
) -> None:
    alice_api.create_task("Todo one")
    alice_page.goto("/?status=todo")

    expect(alice_page.get_by_test_id("empty-board")).to_have_count(0)
    expect(alice_page.get_by_test_id("empty-filter")).to_have_count(0)


def test_empty_state_pages_keep_single_banner_and_main_landmarks(alice_page: Page) -> None:
    for url, testid in (("/", "empty-board"), ("/?status=done", "empty-filter")):
        alice_page.goto(url)

        expect(alice_page.get_by_role("banner")).to_have_count(1)
        expect(alice_page.get_by_role("main")).to_have_count(1)
        expect(alice_page.get_by_test_id(testid)).to_be_visible()


def test_creating_a_task_clears_the_empty_board_message(alice_page: Page) -> None:
    alice_page.goto("/")
    expect(alice_page.get_by_test_id("empty-board")).to_be_visible()

    alice_page.get_by_test_id("new-task-link").click()
    alice_page.get_by_test_id("title-input").fill("First task")
    alice_page.get_by_test_id("submit-task").click()

    expect(alice_page.get_by_test_id("task-row")).to_have_count(1)
    expect(alice_page.get_by_test_id("empty-board")).to_have_count(0)


def test_advancing_the_last_task_out_of_a_filter_shows_the_empty_filter_message(
    alice_api: ApiClient, alice_page: Page
) -> None:
    alice_api.create_task("Leaving todo")
    alice_page.goto("/?status=todo")

    alice_page.get_by_test_id("advance-btn").click()

    expect(alice_page.get_by_test_id("task-row")).to_have_count(0)
    expect(alice_page.get_by_test_id("empty-filter")).to_be_visible()
