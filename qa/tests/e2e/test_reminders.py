"""Full reminder loop: due task -> trigger -> vendor call -> signed webhook -> UI badge.

The vendor mock never pushes webhooks itself; the test closes the loop by
signing the delivery webhook with qa_helpers.webhooks.deliver.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import httpx
from playwright.sync_api import Page
from qa_helpers import ApiClient, rfc3339_in, wait_until
from qa_helpers.webhooks import deliver

VENDOR_ADMIN_URL = os.environ.get("VENDOR_ADMIN_URL", "http://localhost:8081").rstrip("/")
WEBHOOK_SECRET = os.environ.get("VENDOR_WEBHOOK_SECRET", "whsec_test")


def _vendor_notification_calls(task_id: int) -> list[dict[str, Any]]:
    resp = httpx.get(f"{VENDOR_ADMIN_URL}/__admin/requests", timeout=5.0)
    resp.raise_for_status()
    calls: list[dict[str, Any]] = []
    for entry in resp.json().get("requests", []):
        req = entry.get("request", {})
        if req.get("method") != "POST" or "/v1/notifications" not in req.get("url", ""):
            continue
        try:
            body = json.loads(req.get("body") or "{}")
        except ValueError:
            continue
        if body.get("task_id") == task_id:
            calls.append(entry)
    return calls


def test_reminder_full_loop(alice_api: ApiClient, alice_page: Page, api_url: str) -> None:
    title = f"reminder-loop-{uuid.uuid4().hex[:8]}"
    task = alice_api.create_task(title, due_at=rfc3339_in(2))

    def vendor_called() -> list[dict[str, Any]]:
        alice_api.run_due_reminders()  # deterministic trigger+poll — never sleep
        return _vendor_notification_calls(task["id"])

    assert wait_until(vendor_called, timeout=15, message="vendor notification call")

    payload = {
        "event": "notification.delivered",
        "notification_id": f"ntf-{uuid.uuid4().hex}",
        "task_id": task["id"],
    }
    assert deliver(api_url, payload, WEBHOOK_SECRET).status_code == 200

    def badge_sent() -> bool:
        alice_page.goto("/")
        badge = (
            alice_page.get_by_test_id("task-row")
            .filter(has_text=title)
            .get_by_test_id("reminder-badge")
        )
        return badge.count() == 1 and "sent" in badge.inner_text()

    wait_until(badge_sent, timeout=15, message="reminder-badge shows sent")
