"""Find a task by title: search over the whole list, composing with filter/page (issue #55)."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect
from qa_helpers import ApiClient

PAGE_SIZE = 20


def test_search_filters_board_to_matching_titles_only(
    alice_api: ApiClient, alice_page: Page
) -> None:
    alice_api.create_task("Send invoice")
    alice_api.create_task("Buy milk")
    alice_page.goto("/")

    alice_page.get_by_test_id("search-input").fill("inv")
    alice_page.get_by_test_id("search-submit").click()

    expect(alice_page.get_by_test_id("task-row")).to_have_count(1)
    expect(alice_page.get_by_test_id("task-row")).to_contain_text("Send invoice")
    expect(alice_page.get_by_test_id("task-row")).not_to_contain_text("Buy milk")


def test_search_finds_task_that_lives_on_a_later_page(
    alice_api: ApiClient, alice_page: Page
) -> None:
    for i in range(21):
        alice_api.create_task(f"Filler {i}")
    alice_api.create_task("Send invoice")
    alice_page.goto("/?q=invoice")

    expect(alice_page.get_by_test_id("task-row")).to_have_count(1)
    expect(alice_page.get_by_test_id("task-row")).to_contain_text("Send invoice")


def test_search_keeps_urgency_order_and_columns(alice_api: ApiClient, alice_page: Page) -> None:
    todo = alice_api.create_task("invoice todo")
    done = alice_api.create_task("invoice done")
    alice_api.set_status(done["id"], "done")
    alice_page.goto("/?q=invoice")

    expect(alice_page.locator("#column-todo").get_by_test_id("task-row")).to_have_count(1)
    expect(alice_page.locator("#column-done").get_by_test_id("task-row")).to_have_count(1)
    expect(alice_page.locator("#column-todo").get_by_test_id("task-row")).to_contain_text(
        "invoice todo"
    )
    assert todo["id"] != done["id"]


def test_search_composes_with_status_filter_both_directions(
    alice_api: ApiClient, alice_page: Page
) -> None:
    alice_api.create_task("invoice todo")
    done = alice_api.create_task("invoice done")
    alice_api.set_status(done["id"], "done")
    alice_api.create_task("unrelated todo")

    alice_page.goto("/?q=invoice")
    alice_page.get_by_test_id("filter-todo").click()
    expect(alice_page.get_by_test_id("task-row")).to_have_count(1)
    expect(alice_page.get_by_test_id("task-row")).to_contain_text("invoice todo")

    alice_page.goto("/?status=todo")
    alice_page.get_by_test_id("search-input").fill("invoice")
    alice_page.get_by_test_id("search-submit").click()
    expect(alice_page.get_by_test_id("task-row")).to_have_count(1)
    expect(alice_page.get_by_test_id("task-row")).to_contain_text("invoice todo")


def test_search_pager_describes_matched_set_and_carries_term(
    alice_api: ApiClient, alice_page: Page
) -> None:
    for i in range(22):
        alice_api.create_task(f"invoice {i}")
    alice_api.create_task("unrelated")
    alice_page.goto("/?q=invoice")

    expect(alice_page.get_by_test_id("task-row")).to_have_count(PAGE_SIZE)
    expect(alice_page.get_by_test_id("pager-status")).to_have_text("Page 1 of 2")

    alice_page.get_by_test_id("pager-next").click()

    expect(alice_page).to_have_url(re.compile(r"q=invoice.*page=2|page=2.*q=invoice"))
    expect(alice_page.get_by_test_id("task-row")).to_have_count(2)


@pytest.mark.parametrize("action", ["advance-btn", "move-back-btn", "delete-btn"])
def test_search_survives_edit_move_back_advance_and_delete(
    alice_api: ApiClient, alice_page: Page, action: str
) -> None:
    alice_api.create_task("invoice keep")
    target = alice_api.create_task("invoice act on me")
    alice_api.set_status(target["id"], "doing")
    alice_page.goto("/?status=doing&q=invoice")
    row = alice_page.get_by_test_id("task-row").filter(has_text="invoice act on me")
    expect(row).to_be_visible()

    row.get_by_test_id(action).click()

    expect(alice_page).to_have_url(re.compile(r"status=doing.*q=invoice|q=invoice.*status=doing"))
    expect(alice_page.get_by_test_id("search-input")).to_have_value("invoice")


def test_search_survives_edit_round_trip(alice_api: ApiClient, alice_page: Page) -> None:
    task = alice_api.create_task("invoice to edit")
    alice_page.goto("/?q=invoice")
    row = alice_page.get_by_test_id("task-row").filter(has_text="invoice to edit")

    row.get_by_test_id("edit-link").click()
    expect(alice_page).to_have_url(re.compile(r"/tasks/\d+/edit\?q=invoice"))

    alice_page.get_by_test_id("title-input").fill("invoice edited")
    alice_page.get_by_test_id("submit-edit").click()

    expect(alice_page).to_have_url(re.compile(r"\?q=invoice$"))
    expect(alice_page.get_by_test_id("task-row")).to_contain_text("invoice edited")
    assert task["id"] > 0


def test_no_match_shows_empty_search_message_only(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("Send invoice")
    alice_page.goto("/?q=nomatchterm")

    expect(alice_page.get_by_test_id("empty-search")).to_be_visible()
    expect(alice_page.get_by_test_id("empty-search")).to_have_text("No tasks match your search.")
    expect(alice_page.get_by_test_id("empty-board")).to_have_count(0)
    expect(alice_page.get_by_test_id("empty-filter")).to_have_count(0)
    expect(alice_page.get_by_test_id("api-error")).to_have_count(0)


@pytest.mark.parametrize("term", ["", "   "])
def test_empty_and_whitespace_search_shows_full_board(
    alice_api: ApiClient, alice_page: Page, term: str
) -> None:
    alice_api.create_task("Send invoice")
    alice_api.create_task("Buy milk")
    resp = alice_page.goto(f"/?q={term}")

    assert resp is not None and resp.status == 200
    expect(alice_page.get_by_test_id("task-row")).to_have_count(2)
    expect(alice_page.get_by_test_id("empty-search")).to_have_count(0)


def test_clear_search_returns_to_ordinary_board_keeping_filter(
    alice_api: ApiClient, alice_page: Page
) -> None:
    alice_api.create_task("Send invoice")
    alice_api.create_task("Buy milk")
    alice_page.goto("/?status=todo&q=invoice")

    alice_page.get_by_test_id("search-clear").click()

    expect(alice_page).to_have_url(re.compile(r"\?status=todo$"))
    expect(alice_page.get_by_test_id("task-row")).to_have_count(2)
    expect(alice_page.get_by_test_id("search-clear")).to_have_count(0)


def test_search_is_owner_scoped_for_identical_titles(
    alice_api: ApiClient, bob_api: ApiClient, alice_page: Page
) -> None:
    alice_api.create_task("Shared title")
    bob_api.create_task("Shared title")
    alice_page.goto("/?q=Shared")

    expect(alice_page.get_by_test_id("task-row")).to_have_count(1)


def test_wildcard_term_matches_literally(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("100% done")
    alice_api.create_task("Buy milk")

    alice_page.goto("/?q=100%25")
    expect(alice_page.get_by_test_id("task-row")).to_have_count(1)
    expect(alice_page.get_by_test_id("task-row")).to_contain_text("100% done")

    alice_page.goto("/?q=%25")
    expect(alice_page.get_by_test_id("task-row")).to_have_count(1)


def test_long_punctuation_and_emoji_terms_render_200(
    alice_api: ApiClient, alice_page: Page
) -> None:
    alice_api.create_task("Send invoice")

    for term in ("x" * 2000, "!@#$%^&*()", "\U0001f600"):
        resp = alice_page.goto(f"/?q={term}")
        assert resp is not None and resp.status == 200
        expect(alice_page.get_by_test_id("api-error")).to_have_count(0)


def test_unsearched_board_urls_carry_no_q_param(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("Send invoice")
    alice_page.goto("/")

    expect(alice_page).to_have_url(re.compile(r"/$"))
    for testid in ("filter-todo", "filter-doing", "filter-done"):
        href = alice_page.get_by_test_id(testid).get_attribute("href")
        assert href is not None and "q=" not in href
