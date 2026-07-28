"""Mid-session expiry: login notice and new-task draft preservation (issue #53)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Page, expect
from qa_helpers import alice_credentials, bob_credentials


@pytest.fixture
def expired_alice_page(browser: Browser, base_url: str) -> Iterator[Page]:
    """A browser holding a signed session cookie whose server-side row is gone.

    Logs in through the real form in a dedicated context, captures
    `storage_state()` right after login, then logs out from that same
    context — revoking only that session row. Replaying the captured
    (pre-logout) cookie into a fresh context is indistinguishable from the
    cookie surviving past its TTL, without waiting an hour.
    """
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
    expect(page.get_by_test_id("email-input")).to_be_visible()
    context.close()

    expired_context = browser.new_context(
        base_url=base_url, storage_state=expired_state, timezone_id="UTC"
    )
    yield expired_context.new_page()
    expired_context.close()


def test_expiry_on_submit_shows_message_and_restores_draft_after_relogin(
    expired_alice_page: Page,
) -> None:
    email, password = alice_credentials()
    page = expired_alice_page
    page.goto("/new")
    page.get_by_test_id("title-input").fill("Renew the domain")
    page.get_by_test_id("description-input").fill("before it lapses")
    page.get_by_test_id("due-at-input").fill("2026-08-25T17:00")

    page.get_by_test_id("submit-task").click()

    expect(page.get_by_test_id("session-expired")).to_be_visible()
    assert "/login" in page.url

    page.get_by_test_id("email-input").fill(email)
    page.get_by_test_id("password-input").fill(password)
    page.get_by_test_id("submit-login").click()

    assert page.url.rstrip("/").endswith("/new")
    expect(page.get_by_test_id("title-input")).to_have_value("Renew the domain")
    expect(page.get_by_test_id("description-input")).to_have_value("before it lapses")
    expect(page.get_by_test_id("due-at-input")).to_have_value("2026-08-25T17:00")

    page.get_by_test_id("submit-task").click()
    expect(page.get_by_test_id("task-row").filter(has_text="Renew the domain")).to_be_visible()


def test_restored_draft_is_gone_after_successful_submit(expired_alice_page: Page) -> None:
    email, password = alice_credentials()
    page = expired_alice_page
    page.goto("/new")
    page.get_by_test_id("title-input").fill("One-time draft")
    page.get_by_test_id("submit-task").click()

    page.get_by_test_id("email-input").fill(email)
    page.get_by_test_id("password-input").fill(password)
    page.get_by_test_id("submit-login").click()
    page.get_by_test_id("submit-task").click()

    page.goto("/new")
    expect(page.get_by_test_id("title-input")).to_have_value("")
    expect(page.get_by_test_id("description-input")).to_have_value("")


def test_wrong_password_keeps_the_draft(expired_alice_page: Page) -> None:
    email, password = alice_credentials()
    page = expired_alice_page
    page.goto("/new")
    page.get_by_test_id("title-input").fill("Persisted through a typo")
    page.get_by_test_id("submit-task").click()

    page.get_by_test_id("email-input").fill(email)
    page.get_by_test_id("password-input").fill("definitely-not-the-password")
    page.get_by_test_id("submit-login").click()
    expect(page.get_by_test_id("login-error")).to_be_visible()
    expect(page.get_by_test_id("session-expired")).to_be_visible()

    page.get_by_test_id("email-input").fill(email)
    page.get_by_test_id("password-input").fill(password)
    page.get_by_test_id("submit-login").click()

    expect(page.get_by_test_id("title-input")).to_have_value("Persisted through a typo")


def test_other_user_login_gets_an_empty_form(expired_alice_page: Page) -> None:
    page = expired_alice_page
    page.goto("/new")
    page.get_by_test_id("title-input").fill("Alice's private plan")
    page.get_by_test_id("submit-task").click()

    bob_email, bob_password = bob_credentials()
    page.get_by_test_id("email-input").fill(bob_email)
    page.get_by_test_id("password-input").fill(bob_password)
    page.get_by_test_id("submit-login").click()

    page.goto("/new")
    expect(page.get_by_test_id("title-input")).to_have_value("")
    assert "Alice's private plan" not in page.content()


def test_expired_cookie_cannot_reach_the_board(expired_alice_page: Page) -> None:
    page = expired_alice_page
    page.goto("/")
    expect(page.get_by_test_id("email-input")).to_be_visible()
    assert "/login" in page.url


def test_login_page_after_logout_has_no_expired_message(browser: Browser, base_url: str) -> None:
    email, password = alice_credentials()
    context = browser.new_context(base_url=base_url, timezone_id="UTC")
    page = context.new_page()
    page.goto("/login")
    page.get_by_test_id("email-input").fill(email)
    page.get_by_test_id("password-input").fill(password)
    page.get_by_test_id("submit-login").click()
    expect(page.get_by_test_id("user-email")).to_contain_text(email)

    page.get_by_test_id("logout-btn").click()
    expect(page.get_by_test_id("email-input")).to_be_visible()
    expect(page.get_by_test_id("session-expired")).to_have_count(0)

    page.get_by_test_id("email-input").fill(email)
    page.get_by_test_id("password-input").fill(password)
    page.get_by_test_id("submit-login").click()
    page.goto("/new")
    expect(page.get_by_test_id("title-input")).to_have_value("")
    context.close()
