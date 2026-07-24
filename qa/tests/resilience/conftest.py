from __future__ import annotations

import os

import httpx
import pytest

# Re-exported pytest fixtures: `toxiproxy` (finalizer removes all toxics) and the
# session-scoped autouse no-leak guard.
from qa_helpers.toxiproxy import toxiproxy, toxiproxy_no_leak_guard  # noqa: F401

DEFAULT_VENDOR_ADMIN_URL = "http://localhost:8081"


@pytest.fixture
def vendor_admin(request: pytest.FixtureRequest) -> httpx.Client:
    """WireMock admin client; finalizer ALWAYS restores default mappings + journal."""
    base = os.environ.get("VENDOR_ADMIN_URL", DEFAULT_VENDOR_ADMIN_URL).rstrip("/")
    client = httpx.Client(base_url=f"{base}/__admin", timeout=10.0)

    def restore() -> None:
        try:
            client.post("/reset")  # default mappings back, journal cleared
        finally:
            client.close()

    request.addfinalizer(restore)
    return client
