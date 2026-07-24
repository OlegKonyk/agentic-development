"""Vendor faults programmed via the WireMock admin API: failure and recovery."""

from __future__ import annotations

import httpx
from qa_helpers import ApiClient, rfc3339_in, wait_until

FAULT_503 = {
    "priority": 1,  # outranks the baseline happy-path mapping
    "request": {"method": "POST", "urlPath": "/v1/notifications"},
    "response": {"status": 503, "jsonBody": {"error": "vendor unavailable"}},
}


def _reminder_status_in(api: ApiClient, task_id: int, *want: str) -> str | None:
    api.run_due_reminders()  # deterministic trigger; already-pending tasks re-enqueue nothing
    status = api.get_task(task_id)["reminder_status"]
    return status if status in want else None


def test_vendor_503_marks_failed_then_recovers(
    vendor_admin: httpx.Client, alice_api: ApiClient
) -> None:
    # Fault: every notification POST 503s -> tenacity retries exhaust -> failed.
    vendor_admin.post("/mappings", json=FAULT_503).raise_for_status()
    broken = alice_api.create_task("vendor-503 reminder", due_at=rfc3339_in(2))
    status = wait_until(
        lambda: _reminder_status_in(alice_api, broken["id"], "failed"),
        timeout=30,
        message="reminder_status failed under vendor 503",
    )
    assert status == "failed"

    # Recovery: restore the baseline mappings; a NEW due task gets through.
    vendor_admin.post("/mappings/reset").raise_for_status()
    recovered = alice_api.create_task("vendor recovery reminder", due_at=rfc3339_in(2))
    status = wait_until(
        lambda: _reminder_status_in(alice_api, recovered["id"], "pending", "sent"),
        timeout=30,
        message="reminder_status pending/sent after vendor recovery",
    )
    assert status in {"pending", "sent"}

    # The recovered task's notification actually reached the vendor.
    def vendor_saw_it() -> bool:
        entries = vendor_admin.get("/requests").json().get("requests", [])
        return any(
            f'"task_id": {recovered["id"]}' in body or f'"task_id":{recovered["id"]}' in body
            for body in ((e.get("request", {}).get("body") or "") for e in entries)
        )

    wait_until(vendor_saw_it, timeout=15, message="vendor journal has the recovered call")
