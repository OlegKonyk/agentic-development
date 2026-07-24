"""Toxiproxy admin client + pytest fixtures for the chaos layer.

Proxies (pre-populated from toxiproxy/config.json): `db` :5433→db:5432,
`vendor` :8666→vendor-mock:8080. Import the fixtures into a conftest:

    from qa_helpers.toxiproxy import toxiproxy, toxiproxy_no_leak_guard  # noqa: F401
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from types import TracebackType
from typing import Any

import httpx
import pytest

DEFAULT_TOXIPROXY_URL = "http://localhost:8474"


class ToxiproxyClient:
    """httpx wrapper over the Toxiproxy admin API. Always toxicity=1.0, jitter=0."""

    def __init__(self, url: str | None = None, timeout: float = 5.0) -> None:
        self.url = (url or os.environ.get("TOXIPROXY_URL", DEFAULT_TOXIPROXY_URL)).rstrip("/")
        self._client = httpx.Client(base_url=self.url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ToxiproxyClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def list_proxies(self) -> dict[str, Any]:
        resp = self._client.get("/proxies")
        resp.raise_for_status()
        return resp.json()

    def add_toxic(
        self,
        proxy: str,
        type: str,  # noqa: A002 — mirrors the Toxiproxy API field name
        attributes: dict[str, Any],
        name: str | None = None,
        *,
        stream: str = "downstream",
    ) -> dict[str, Any]:
        """Add a toxic to `proxy`; latency toxics get jitter=0 unless overridden."""
        if type == "latency":
            attributes = {"jitter": 0, **attributes}
        resp = self._client.post(
            f"/proxies/{proxy}/toxics",
            json={
                "name": name or f"{type}_{stream}",
                "type": type,
                "stream": stream,
                "toxicity": 1.0,
                "attributes": attributes,
            },
        )
        resp.raise_for_status()
        return resp.json()

    def remove_toxic(self, proxy: str, name: str) -> None:
        resp = self._client.delete(f"/proxies/{proxy}/toxics/{name}")
        if resp.status_code != 404:  # already gone is fine (idempotent teardown)
            resp.raise_for_status()

    def reset_all(self) -> None:
        """Delete all toxics on every proxy and re-enable all proxies."""
        self._client.post("/reset").raise_for_status()

    def leaked_state(self) -> dict[str, Any]:
        """Proxies that still carry toxics or are disabled; {} when clean."""
        leaked: dict[str, Any] = {}
        for name, proxy in self.list_proxies().items():
            toxics = proxy.get("toxics") or []
            if toxics or not proxy.get("enabled", True):
                leaked[name] = {
                    "enabled": proxy.get("enabled"),
                    "toxics": [t.get("name") for t in toxics],
                }
        return leaked


def _assert_recovered(timeout: float = 15.0) -> None:
    """Post-chaos recovery gate: a DB-touching request must succeed again.

    Chaos kills pooled connections; the first request after the toxic clears
    pays for that (5xx) while SQLAlchemy recycles the pool. Draining that
    error here makes 'the system recovered' an explicit teardown assertion —
    and keeps it from bleeding into the next test's setup.
    """
    from qa_helpers.client import ApiClient, alice_credentials
    from qa_helpers.wait_until import wait_until

    with ApiClient() as api:

        def healthy() -> bool | None:
            try:
                api.login(*alice_credentials())
                return True
            except httpx.HTTPError:
                return None

        wait_until(healthy, timeout=timeout, message="API recovery after chaos teardown")


@pytest.fixture
def toxiproxy(request: pytest.FixtureRequest) -> ToxiproxyClient:
    """Admin client whose finalizer ALWAYS removes toxics, re-enables proxies,
    and then asserts the stack actually recovered."""
    client = ToxiproxyClient()

    def teardown() -> None:
        try:
            client.reset_all()
            _assert_recovered()
        finally:
            client.close()

    request.addfinalizer(teardown)
    return client


@pytest.fixture(scope="session", autouse=True)
def toxiproxy_no_leak_guard() -> Iterator[None]:
    """Session guard: no toxic may outlive the test that added it."""
    yield
    with ToxiproxyClient() as client:
        leaked = client.leaked_state()
    assert leaked == {}, f"toxics leaked past per-test teardown: {leaked}"
