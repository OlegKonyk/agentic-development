"""Accessibility smoke checks: accessible names, focus order, landmarks."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect
from qa_helpers import ApiClient


def _form_controls(page: Page, form_selector: str) -> list[str]:
    """`data-testid` of every visible, focusable control inside the form, in DOM order."""
    locators = page.locator(form_selector).locator(
        "input:not([type=hidden]), textarea, select, button"
    )
    testids: list[str] = []
    for locator in locators.all():
        if locator.is_visible():
            testid = locator.get_attribute("data-testid")
            if testid:
                testids.append(testid)
    return testids


def _tab_sequence(page: Page, max_tabs: int = 20) -> list[str]:
    """Tab-driven focus trace via `document.activeElement`.

    Compound controls (e.g. `datetime-local`) keep the same element focused
    across several Tab presses while the browser moves between the control's
    internal date/time segments, so repeats of the immediately preceding
    entry are collapsed — they are not a new control being reached.
    """
    probe = (
        "() => { const el = document.activeElement; "
        "if (!el || el === document.body || el === document.documentElement) return null; "
        "return el.getAttribute('data-testid') || el.tagName.toLowerCase(); }"
    )
    seq: list[str] = []
    for _ in range(max_tabs):
        page.keyboard.press("Tab")
        value = page.evaluate(probe)
        if value is None:
            break
        if seq and value == seq[-1]:
            continue
        if seq and value == seq[0]:
            break
        seq.append(value)
    return seq


class _FakeKeyboard:
    def press(self, key: str) -> None:
        pass


class _FakeFocusPage:
    """Stands in for a Page in `_tab_sequence`: only `keyboard.press` and
    `evaluate` are called, so a real browser isn't needed to test the
    dedup/wrap-around logic."""

    def __init__(self, focus_values: list[str | None]) -> None:
        self.keyboard = _FakeKeyboard()
        self._values = iter(focus_values)

    def evaluate(self, _probe: str) -> str | None:
        return next(self._values, None)


def test_tab_sequence_collapses_repeats_on_same_compound_control() -> None:
    # A datetime-local input keeps document.activeElement on itself while Tab
    # moves between its internal segments — those repeats aren't new controls.
    focus_values = [
        "title-input",
        "description-input",
        "due-at-input",
        "due-at-input",
        "due-at-input",
        "submit-task",
    ]
    page = _FakeFocusPage(focus_values)

    seq = _tab_sequence(page, max_tabs=len(focus_values))

    assert seq == ["title-input", "description-input", "due-at-input", "submit-task"]


def test_login_form_controls_have_accessible_names(page: Page) -> None:
    page.goto("/login")

    expect(
        page.get_by_test_id("email-input"),
        'login email input has no accessible name — is <label for="email"> still in login.html?',
    ).to_have_accessible_name("Email")
    expect(
        page.get_by_test_id("password-input"),
        'login password input has no accessible name — is <label for="password"> '
        "still in login.html?",
    ).to_have_accessible_name("Password")
    expect(
        page.get_by_test_id("submit-login"),
        "login submit button has no accessible name",
    ).to_have_accessible_name("Log in")


def test_new_form_controls_have_accessible_names(alice_page: Page) -> None:
    alice_page.goto("/new")

    expect(
        alice_page.get_by_test_id("title-input"),
        'new-task title input has no accessible name — is <label for="title"> still in new.html?',
    ).to_have_accessible_name("Title")
    expect(
        alice_page.get_by_test_id("description-input"),
        'new-task description textarea has no accessible name — is <label for="description"> '
        "still in new.html?",
    ).to_have_accessible_name("Description")
    expect(
        alice_page.get_by_test_id("due-at-input"),
        'new-task due-at input has no accessible name — is <label for="due_at"> still in new.html?',
    ).to_have_accessible_name(re.compile(r"^Due"))
    expect(
        alice_page.get_by_test_id("submit-task"),
        "new-task submit button has no accessible name",
    ).to_have_accessible_name("Create task")


def test_login_form_focus_order(page: Page) -> None:
    page.goto("/login")

    expected = _form_controls(page, "form.stacked")
    assert expected, "login form has no visible focusable controls"
    assert expected == ["email-input", "password-input", "submit-login"]

    seq = _tab_sequence(page)
    observed = [t for t in seq if t in expected]
    assert observed == expected, (
        f"login form focus order was {observed}, expected {expected} (full tab sequence: {seq})"
    )


def test_new_form_focus_order(alice_page: Page) -> None:
    alice_page.goto("/new")

    expected = _form_controls(alice_page, "form.stacked")
    assert expected, "new-task form has no visible focusable controls"
    assert expected == ["title-input", "description-input", "due-at-input", "submit-task"]

    seq = _tab_sequence(alice_page)
    observed = [t for t in seq if t in expected]
    assert observed == expected, (
        f"new-task form focus order was {observed}, expected {expected} (full tab sequence: {seq})"
    )


@pytest.mark.parametrize(
    "path,fixture_name",
    [
        ("/login", "page"),
        ("/", "alice_page"),
        ("/new", "alice_page"),
        ("/?status=todo", "alice_page"),
    ],
)
def test_pages_expose_banner_and_main_landmarks(
    request: pytest.FixtureRequest, path: str, fixture_name: str
) -> None:
    pg: Page = request.getfixturevalue(fixture_name)
    pg.goto(path)

    expect(
        pg.get_by_role("banner"),
        f"{path}: expected exactly one banner landmark (<header> in base.html)",
    ).to_have_count(1)
    expect(
        pg.get_by_role("main"),
        f"{path}: expected exactly one main landmark (<main> in base.html)",
    ).to_have_count(1)


def test_filter_links_have_accessible_names(alice_page: Page) -> None:
    alice_page.goto("/")

    for status in ("all", "todo", "doing", "done"):
        expect(alice_page.get_by_test_id(f"filter-{status}")).to_have_accessible_name(status)


def test_row_actions_have_task_scoped_accessible_names(
    alice_api: ApiClient, alice_page: Page
) -> None:
    alice_api.create_task("Alpha task")
    alice_api.create_task("Beta task")
    alice_page.goto("/")

    for title in ("Alpha task", "Beta task"):
        row = alice_page.get_by_test_id("task-row").filter(has_text=title)
        expect(row.get_by_test_id("advance-btn")).to_have_accessible_name(f"Advance {title}")
        expect(row.get_by_test_id("delete-btn")).to_have_accessible_name(f"Delete {title}")
        expect(alice_page.get_by_role("button", name=f"Advance {title}", exact=True)).to_have_count(
            1
        )
        expect(alice_page.get_by_role("button", name=f"Delete {title}", exact=True)).to_have_count(
            1
        )


def test_row_action_testids_and_text_are_unchanged(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("Unchanged task")
    alice_page.goto("/")

    row = alice_page.get_by_test_id("task-row").filter(has_text="Unchanged task")
    advance = row.get_by_test_id("advance-btn")
    delete = row.get_by_test_id("delete-btn")
    expect(advance).to_have_text("Advance")
    expect(delete).to_have_text("Delete")
