"""Auth flows: redirects, wrong password, logout revocation, cross-user isolation."""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser, Page, expect
from qa_helpers import ApiClient, alice_credentials, bob_credentials


@pytest.mark.parametrize("path", ["/", "/new"])
def test_unauthed_pages_redirect_to_login(page: Page, path: str) -> None:
    page.goto(path)
    expect(page.get_by_test_id("email-input")).to_be_visible()
    assert "/login" in page.url


def test_wrong_password_shows_login_error(page: Page) -> None:
    email, _ = alice_credentials()
    page.goto("/login")
    page.get_by_test_id("email-input").fill(email)
    page.get_by_test_id("password-input").fill("definitely-not-the-password")
    page.get_by_test_id("submit-login").click()
    expect(page.get_by_test_id("login-error")).to_be_visible()
    assert "/login" in page.url


def test_logout_revokes_session_for_replayed_cookie(browser: Browser, base_url: str) -> None:
    # Dedicated login (NOT the shared alice storage state — logout would revoke it).
    email, password = alice_credentials()
    context = browser.new_context(base_url=base_url)
    page = context.new_page()
    page.goto("/login")
    page.get_by_test_id("email-input").fill(email)
    page.get_by_test_id("password-input").fill(password)
    page.get_by_test_id("submit-login").click()
    expect(page.get_by_test_id("user-email")).to_contain_text(email)

    replayed_state = context.storage_state()  # cookie captured BEFORE logout
    page.get_by_test_id("logout-btn").click()
    expect(page.get_by_test_id("email-input")).to_be_visible()
    assert "/login" in page.url
    context.close()

    # Sessions are DB-backed: the replayed cookie must bounce to /login, not a board.
    replay = browser.new_context(base_url=base_url, storage_state=replayed_state)
    try:
        replay_page = replay.new_page()
        replay_page.goto("/")
        expect(replay_page.get_by_test_id("email-input")).to_be_visible()
        assert "/login" in replay_page.url
    finally:
        replay.close()


def test_users_cannot_see_each_others_tasks(
    alice_api: ApiClient, bob_api: ApiClient, bob_page: Page
) -> None:
    alice_task = alice_api.create_task("Alice private task")
    bob_api.create_task("Bob own task")

    bob_page.goto("/")
    expect(bob_page.get_by_test_id("user-email")).to_contain_text(bob_credentials()[0])
    expect(bob_page.get_by_test_id("task-row").filter(has_text="Bob own task")).to_be_visible()
    expect(bob_page.get_by_test_id("task-row").filter(has_text="Alice private task")).to_have_count(
        0
    )

    # API level: other users' task ids are 404 (no existence leak), never 200/403.
    resp = bob_api.request("GET", f"/api/tasks/{alice_task['id']}", retry_auth=False)
    assert resp.status_code == 404
