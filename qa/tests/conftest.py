from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from qa_helpers import ApiClient, alice_credentials, bob_credentials

DEFAULT_API_URL = "http://localhost:8000"


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
