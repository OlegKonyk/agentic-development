from __future__ import annotations

import os
from collections.abc import Iterator

import httpx
import pytest
from qa_helpers import ApiClient, alice_credentials, bob_credentials

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_VENDOR_ADMIN_URL = "http://localhost:8081"


@pytest.fixture(scope="session")
def api_url() -> str:
    return os.environ.get("API_URL", DEFAULT_API_URL).rstrip("/")


@pytest.fixture(scope="session")
def _fresh_platform(api_url: str) -> None:
    """One reset per session: wipes tasks/sessions/webhook events; users survive.

    Runs before any login (form or API) so the wipe never revokes a session a
    fixture still depends on.
    """
    with ApiClient(api_url) as client:
        client.reset()


@pytest.fixture(scope="session")
def alice_api(api_url: str, _fresh_platform: None) -> Iterator[ApiClient]:
    client = ApiClient(api_url)
    client.login(*alice_credentials())
    yield client
    client.close()


@pytest.fixture(scope="session")
def bob_api(api_url: str, _fresh_platform: None) -> Iterator[ApiClient]:
    client = ApiClient(api_url)
    client.login(*bob_credentials())
    yield client
    client.close()


@pytest.fixture(autouse=True)
def isolated_tasks(alice_api: ApiClient, bob_api: ApiClient) -> None:
    """Users survive reset; every test starts task-free and recreates via the API."""
    for client in (alice_api, bob_api):
        client.delete_all_tasks()


@pytest.fixture
def vendor_admin(request: pytest.FixtureRequest) -> httpx.Client:
    """WireMock admin client; finalizer ALWAYS restores default mappings + journal.

    Shared by the e2e and resilience suites — both need to inject vendor faults.
    """
    base = os.environ.get("VENDOR_ADMIN_URL", DEFAULT_VENDOR_ADMIN_URL).rstrip("/")
    client = httpx.Client(base_url=f"{base}/__admin", timeout=10.0)

    def restore() -> None:
        try:
            client.post("/reset")  # default mappings back, journal cleared
        finally:
            client.close()

    request.addfinalizer(restore)
    return client


@pytest.fixture
def clean_reminder_health(alice_api: ApiClient) -> Iterator[None]:
    """Clear reminder-delivery history before and after: a degraded state must
    never bleed into a later test (same convention as the `toxiproxy` fixture)."""
    alice_api.clear_reminder_deliveries()
    yield
    alice_api.clear_reminder_deliveries()
