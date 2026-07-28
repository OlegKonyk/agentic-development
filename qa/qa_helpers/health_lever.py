"""Per-call fault lever for the web app's reminder-health call (issue #31).

Faults only `web-health` :8667→api:8000 — `GET /api/tasks` and every other
web→API call are untouched, so this can drive the "one signal degrades, the
rest stays healthy" scenario that Toxiproxy's `db`/`vendor` proxies can't
(they front every request on the shared connection/timeout budget). Built on
`ToxiproxyClient` so the existing `toxiproxy_no_leak_guard` already covers it.

    from qa_helpers.health_lever import health_lever  # noqa: F401
"""

from __future__ import annotations

import os

import httpx
import pytest

from qa_helpers.toxiproxy import ToxiproxyClient

HEALTH_PROXY = "web-health"
DEFAULT_LEVER_URL = "http://localhost:8667"
FAIL_TOXIC = "health_fail"
TIMEOUT_TOXIC = "health_timeout"
PROBE_TIMEOUT = 5.0


class HealthLever:
    """Engages/releases the `web-health` toxics; probes the listener directly."""

    def __init__(self, toxiproxy: ToxiproxyClient | None = None, url: str | None = None) -> None:
        self._toxiproxy = toxiproxy or ToxiproxyClient()
        self._owns_toxiproxy = toxiproxy is None
        self.url = (url or os.environ.get("HEALTH_LEVER_URL", DEFAULT_LEVER_URL)).rstrip("/")

    def fail(self) -> None:
        """Connection reset: the web app's health call raises `httpx.HTTPError`."""
        self._toxiproxy.add_toxic(HEALTH_PROXY, "reset_peer", {"timeout": 0}, name=FAIL_TOXIC)

    def timeout(self) -> None:
        """Stalls the stream: the web app's health call trips its own 2s timeout."""
        self._toxiproxy.add_toxic(HEALTH_PROXY, "timeout", {"timeout": 0}, name=TIMEOUT_TOXIC)

    def release(self) -> None:
        """Idempotent: removes both toxics regardless of which was engaged."""
        self._toxiproxy.remove_toxic(HEALTH_PROXY, FAIL_TOXIC)
        self._toxiproxy.remove_toxic(HEALTH_PROXY, TIMEOUT_TOXIC)

    def engaged_faults(self) -> list[str]:
        """Toxic names currently on the `web-health` proxy."""
        proxies = self._toxiproxy.list_proxies()
        toxics = proxies.get(HEALTH_PROXY, {}).get("toxics") or []
        return [t["name"] for t in toxics]

    def probe(self, token: str) -> httpx.Response:
        """GET the health endpoint through the lever listener, bypassing the web app."""
        with httpx.Client(base_url=self.url, timeout=PROBE_TIMEOUT) as client:
            return client.get("/api/reminders/health", headers={"Authorization": f"Bearer {token}"})

    def close(self) -> None:
        if self._owns_toxiproxy:
            self._toxiproxy.close()


def _assert_lever_passthrough() -> None:
    """Post-release recovery gate, same discipline as `toxiproxy._assert_recovered`:
    a single strict probe, so a wedged listener surfaces as a failure, not flake."""
    from qa_helpers.client import ApiClient, alice_credentials

    url = os.environ.get("HEALTH_LEVER_URL", DEFAULT_LEVER_URL).rstrip("/")
    with ApiClient() as api, httpx.Client(base_url=url, timeout=PROBE_TIMEOUT) as probe:
        token = api.login(*alice_credentials())
        resp = probe.get("/api/reminders/health", headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()


@pytest.fixture
def health_lever(request: pytest.FixtureRequest) -> HealthLever:
    """Finalizer ALWAYS releases, then asserts the listener passes traffic through again."""
    lever = HealthLever()

    def teardown() -> None:
        try:
            lever.release()
            _assert_lever_passthrough()
        finally:
            lever.close()

    request.addfinalizer(teardown)
    return lever
