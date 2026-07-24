from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from qa_helpers import ApiClient

DEFAULT_GATEWAY_URL = "http://localhost:8787"


@pytest.fixture(scope="session")
def base_url(request: pytest.FixtureRequest) -> str:
    # E2E runs through the gateway; --base-url (pytest-playwright) wins if given.
    cli = request.config.getoption("--base-url")
    return (cli or os.environ.get("GATEWAY_URL", DEFAULT_GATEWAY_URL)).rstrip("/")


@pytest.fixture(scope="session")
def gateway_url(base_url: str) -> str:
    return base_url


@pytest.fixture(scope="session")
def api() -> Iterator[ApiClient]:
    client = ApiClient()
    yield client
    client.close()


@pytest.fixture(autouse=True)
def seeded(api: ApiClient) -> list[dict[str, Any]]:
    """Every test starts from the fixed seed dataset."""
    api.reset()
    return api.seed()
