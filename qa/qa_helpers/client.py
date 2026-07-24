"""Thin httpx client for the taskboard API, used by all QA suites."""

from __future__ import annotations

import os
from types import TracebackType
from typing import Any

import httpx

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_API_KEY = "dev-key"

# Fixed, deterministic seed dataset; tests own their state via reset() + seed().
SEED_TASKS: tuple[dict[str, str], ...] = (
    {"title": "Set up repo", "description": "Initialize repository and CI", "status": "todo"},
    {"title": "Build API", "description": "Implement the taskboard API", "status": "doing"},
    {"title": "Draft spec", "description": "Write the product spec", "status": "done"},
)


class ApiClient:
    """Talks directly to the API origin (not through the gateway).

    Sends x-api-key anyway so the same client works through the gateway
    when constructed with the gateway URL.
    """

    def __init__(self, api_url: str | None = None, api_key: str | None = None) -> None:
        self.api_url = (api_url or os.environ.get("API_URL", DEFAULT_API_URL)).rstrip("/")
        self.api_key = api_key or os.environ.get("GATEWAY_API_KEY", DEFAULT_API_KEY)
        self._client = httpx.Client(
            base_url=self.api_url,
            headers={"x-api-key": self.api_key},
            timeout=10.0,
        )

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

    def reset(self) -> None:
        """Wipe all tasks. Requires the API to run with APP_ENV=test."""
        self._client.post("/api/testing/reset").raise_for_status()

    def list_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        params = {"status": status} if status else None
        resp = self._client.get("/api/tasks", params=params)
        resp.raise_for_status()
        return resp.json()

    def create_task(self, title: str, description: str = "") -> dict[str, Any]:
        resp = self._client.post("/api/tasks", json={"title": title, "description": description})
        resp.raise_for_status()
        return resp.json()

    def set_status(self, task_id: int, status: str) -> dict[str, Any]:
        resp = self._client.patch(f"/api/tasks/{task_id}", json={"status": status})
        resp.raise_for_status()
        return resp.json()

    def seed(self) -> list[dict[str, Any]]:
        """Create the fixed seed tasks via the API; returns the created tasks."""
        created: list[dict[str, Any]] = []
        for spec in SEED_TASKS:
            task = self.create_task(spec["title"], spec["description"])
            if spec["status"] != "todo":
                task = self.set_status(task["id"], spec["status"])
            created.append(task)
        return created
