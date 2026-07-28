from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest
from playwright.sync_api import Browser, Page, expect
from qa_helpers import alice_credentials, bob_credentials
from qa_helpers.health_lever import health_lever  # noqa: F401
from qa_helpers.toxiproxy import toxiproxy_no_leak_guard  # noqa: F401

DEFAULT_GATEWAY_URL = "http://localhost:8787"


@pytest.fixture(scope="session")
def base_url(request: pytest.FixtureRequest) -> str:
    # E2E runs through the gateway; --base-url (pytest-playwright) wins if given.
    cli = request.config.getoption("--base-url")
    return (cli or os.environ.get("GATEWAY_URL", DEFAULT_GATEWAY_URL)).rstrip("/")


def _login_storage_state(
    browser: Browser, base_url: str, email: str, password: str, path: str
) -> str:
    """Log in through the REAL /login form once; persist cookies as storage state."""
    context = browser.new_context(base_url=base_url, timezone_id="UTC")
    try:
        page = context.new_page()
        page.goto("/login")
        page.get_by_test_id("email-input").fill(email)
        page.get_by_test_id("password-input").fill(password)
        page.get_by_test_id("submit-login").click()
        expect(page.get_by_test_id("user-email")).to_contain_text(email)
        context.storage_state(path=path)
    finally:
        context.close()
    return path


@pytest.fixture(scope="session")
def alice_storage_state(
    browser: Browser,
    base_url: str,
    tmp_path_factory: pytest.TempPathFactory,
    _fresh_platform: None,
) -> str:
    email, password = alice_credentials()
    path = tmp_path_factory.mktemp("auth-state") / "alice.json"
    return _login_storage_state(browser, base_url, email, password, str(path))


@pytest.fixture(scope="session")
def bob_storage_state(
    browser: Browser,
    base_url: str,
    tmp_path_factory: pytest.TempPathFactory,
    _fresh_platform: None,
) -> str:
    email, password = bob_credentials()
    path = tmp_path_factory.mktemp("auth-state") / "bob.json"
    return _login_storage_state(browser, base_url, email, password, str(path))


@pytest.fixture
def alice_page(browser: Browser, base_url: str, alice_storage_state: str) -> Iterator[Page]:
    context = browser.new_context(
        base_url=base_url, storage_state=alice_storage_state, timezone_id="UTC"
    )
    yield context.new_page()
    context.close()


@pytest.fixture
def bob_page(browser: Browser, base_url: str, bob_storage_state: str) -> Iterator[Page]:
    context = browser.new_context(
        base_url=base_url, storage_state=bob_storage_state, timezone_id="UTC"
    )
    yield context.new_page()
    context.close()


@pytest.fixture
def zoned_alice_page(
    browser: Browser, base_url: str, alice_storage_state: str
) -> Iterator[Callable[[str], Page]]:
    """Factory for an alice page in an arbitrary browser time zone.

    Primes the `tz` cookie with one `goto('/')` before handing back the page, so
    tests never race the base template's one-shot tz-sync reload.
    """
    contexts = []

    def make(timezone_id: str) -> Page:
        context = browser.new_context(
            base_url=base_url, storage_state=alice_storage_state, timezone_id=timezone_id
        )
        contexts.append(context)
        page = context.new_page()
        page.goto("/")
        expect(page.locator("html")).to_have_attribute("data-tz", timezone_id)
        return page

    yield make
    for context in contexts:
        context.close()
