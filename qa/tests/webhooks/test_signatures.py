"""Standard-Webhooks signature matrix against POST /api/webhooks/vendor."""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from qa_helpers import ApiClient, rfc3339_in, wait_until
from qa_helpers.webhooks import deliver

WEBHOOK_SECRET = os.environ.get("VENDOR_WEBHOOK_SECRET", "whsec_test")


def _pending_task(api: ApiClient, title: str) -> dict[str, Any]:
    """Create a due task and drive it to reminder_status=pending (webhook precondition)."""
    task = api.create_task(title, due_at=rfc3339_in(2))

    def pending() -> dict[str, Any] | None:
        api.run_due_reminders()
        current = api.get_task(task["id"])
        return current if current["reminder_status"] == "pending" else None

    return wait_until(pending, timeout=20, message=f"task {task['id']} reminder pending")


def _delivered_payload(task_id: int) -> dict[str, Any]:
    return {
        "event": "notification.delivered",
        "notification_id": f"ntf-{uuid.uuid4().hex}",
        "task_id": task_id,
    }


def test_valid_signature_flips_pending_to_sent(alice_api: ApiClient, api_url: str) -> None:
    task = _pending_task(alice_api, "webhook valid signature")
    resp = deliver(api_url, _delivered_payload(task["id"]), WEBHOOK_SECRET)
    assert resp.status_code == 200
    assert alice_api.get_task(task["id"])["reminder_status"] == "sent"


def test_tampered_body_rejected_401(alice_api: ApiClient, api_url: str) -> None:
    task = _pending_task(alice_api, "webhook tampered body")
    payload = _delivered_payload(task["id"])
    tampered = json.dumps({**payload, "notification_id": "ntf-forged"})
    resp = deliver(api_url, payload, WEBHOOK_SECRET, body=tampered)
    assert resp.status_code == 401
    assert alice_api.get_task(task["id"])["reminder_status"] == "pending"


def test_stale_timestamp_rejected_400(alice_api: ApiClient, api_url: str) -> None:
    task = _pending_task(alice_api, "webhook stale timestamp")
    stale_ts = int(time.time()) - 600  # 10 min old, > 5 min allowed skew
    resp = deliver(api_url, _delivered_payload(task["id"]), WEBHOOK_SECRET, ts=stale_ts)
    assert resp.status_code == 400
    assert alice_api.get_task(task["id"])["reminder_status"] == "pending"


def test_duplicate_webhook_id_exactly_one_side_effect(alice_api: ApiClient, api_url: str) -> None:
    first = _pending_task(alice_api, "webhook dedupe first")
    second = _pending_task(alice_api, "webhook dedupe second")
    webhook_id = f"msg-{uuid.uuid4().hex}"

    resp_one = deliver(
        api_url, _delivered_payload(first["id"]), WEBHOOK_SECRET, webhook_id=webhook_id
    )
    resp_two = deliver(
        api_url, _delivered_payload(second["id"]), WEBHOOK_SECRET, webhook_id=webhook_id
    )

    assert (resp_one.status_code, resp_two.status_code) == (200, 200)
    assert alice_api.get_task(first["id"])["reminder_status"] == "sent"
    # Duplicate id was deduped: the second delivery produced no side effect.
    assert alice_api.get_task(second["id"])["reminder_status"] == "pending"
