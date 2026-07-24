"""Thin httpx client for the taskboard API, used by all QA suites."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any

import httpx

DEFAULT_API_URL = "http://localhost:8000"

# Fixed, deterministic per-test dataset. Seeded users survive /api/testing/reset;
# tasks do not — each test recreates what it needs via the API (see seed()).
SEED_TASKS: tuple[dict[str, str], ...] = (
    {"title": "Set up repo", "description": "Initialize repository and CI", "status": "todo"},
    {"title": "Build API", "description": "Implement the taskboard API", "status": "doing"},
    {"title": "Draft spec", "description": "Write the product spec", "status": "done"},
)


def alice_credentials() -> tuple[str, str]:
    """Seeded user alice; password from QA_ALICE_PASS (compose default)."""
    return "alice@example.com", os.environ.get("QA_ALICE_PASS", "correct-horse-a")


def bob_credentials() -> tuple[str, str]:
    """Seeded user bob; password from QA_BOB_PASS (compose default)."""
    return "bob@example.com", os.environ.get("QA_BOB_PASS", "correct-horse-b")


def rfc3339_in(seconds: float) -> str:
    """RFC3339 UTC `Z` timestamp `seconds` from now — the wire format for due_at."""
    at = datetime.now(UTC) + timedelta(seconds=seconds)
    return at.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ApiClient:
    """Per-user bearer-auth client against the API origin (or the gateway)."""

    def __init__(self, api_url: str | None = None, timeout: float = 10.0) -> None:
        self.api_url = (api_url or os.environ.get("API_URL", DEFAULT_API_URL)).rstrip("/")
        # The gateway guards /api/* with x-api-key; harmless when hitting the API
        # directly, required when api_url points at the gateway.
        self._client = httpx.Client(
            base_url=self.api_url,
            timeout=timeout,
            headers={"x-api-key": os.environ.get("GATEWAY_API_KEY", "dev-key")},
        )
        self._token: str | None = None
        self._email: str | None = None
        self._password: str | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- auth ---------------------------------------------------------------

    @property
    def token(self) -> str:
        if self._token is None:
            raise RuntimeError("not logged in — call login() first")
        return self._token

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def login(self, email: str, password: str) -> str:
        """POST /api/auth/login; stores and returns the opaque bearer token."""
        resp = self._client.post("/api/auth/login", json={"email": email, "password": password})
        resp.raise_for_status()
        self._token = resp.json()["token"]
        self._email, self._password = email, password
        return self.token

    def logout(self) -> None:
        resp = self.request("POST", "/api/auth/logout", retry_auth=False)
        resp.raise_for_status()
        self._token = self._email = self._password = None

    def me(self) -> dict[str, Any]:
        resp = self.request("GET", "/api/auth/me")
        resp.raise_for_status()
        return resp.json()

    def request(
        self, method: str, path: str, *, retry_auth: bool = True, **kwargs: Any
    ) -> httpx.Response:
        """Authed request. On 401 re-logins once with the stored credentials and
        retries: /api/testing/reset revokes every session (users survive, tokens
        do not), so long-lived session-scoped clients must self-heal."""
        headers: dict[str, str] = dict(kwargs.pop("headers", None) or {})
        if self._token is not None:
            headers.setdefault("Authorization", f"Bearer {self._token}")
        resp = self._client.request(method, path, headers=headers, **kwargs)
        if resp.status_code == 401 and retry_auth and self._email and self._password:
            headers["Authorization"] = f"Bearer {self.login(self._email, self._password)}"
            resp = self._client.request(method, path, headers=headers, **kwargs)
        return resp

    # -- test-only endpoints (APP_ENV=test) ---------------------------------

    def reset(self) -> None:
        """Wipe tasks + sessions + webhook events; seeded users survive.

        Sessions are revoked by the wipe, so the client re-logins afterwards
        when it holds credentials.
        """
        self.request("POST", "/api/testing/reset", retry_auth=False).raise_for_status()
        self._token = None
        if self._email and self._password:
            self.login(self._email, self._password)

    def run_due_reminders(self) -> int:
        """Deterministic scheduler trigger; returns the number of enqueued jobs."""
        resp = self.request("POST", "/api/testing/run-due-reminders")
        resp.raise_for_status()
        return int(resp.json()["enqueued"])

    # -- tasks --------------------------------------------------------------

    def list_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        params = {"status": status} if status else None
        resp = self.request("GET", "/api/tasks", params=params)
        resp.raise_for_status()
        return resp.json()

    def get_task(self, task_id: int) -> dict[str, Any]:
        resp = self.request("GET", f"/api/tasks/{task_id}")
        resp.raise_for_status()
        return resp.json()

    def create_task(
        self, title: str, description: str = "", due_at: str | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"title": title, "description": description}
        if due_at is not None:
            payload["due_at"] = due_at
        resp = self.request("POST", "/api/tasks", json=payload)
        resp.raise_for_status()
        return resp.json()

    def create_due_task(self, title: str, in_seconds: float = 2.0) -> dict[str, Any]:
        """Task whose reminder becomes due `in_seconds` from now."""
        return self.create_task(title, due_at=rfc3339_in(in_seconds))

    def set_status(self, task_id: int, status: str) -> dict[str, Any]:
        resp = self.request("PATCH", f"/api/tasks/{task_id}", json={"status": status})
        resp.raise_for_status()
        return resp.json()

    def delete_task(self, task_id: int) -> None:
        self.request("DELETE", f"/api/tasks/{task_id}").raise_for_status()

    def delete_all_tasks(self) -> None:
        """Per-test isolation without touching sessions (unlike reset())."""
        for task in self.list_tasks():
            self.delete_task(task["id"])

    def seed(self) -> list[dict[str, Any]]:
        """Create the fixed seed tasks via the API; returns the created tasks.

        Tasks are owned by the logged-in user; logs in as alice if the client
        holds no token (so a fresh client seeds alice's board rather than 401ing).
        """
        if self._token is None:
            self.login(*alice_credentials())
        created: list[dict[str, Any]] = []
        for spec in SEED_TASKS:
            task = self.create_task(spec["title"], spec["description"])
            if spec["status"] != "todo":
                task = self.set_status(task["id"], spec["status"])
            created.append(task)
        return created
