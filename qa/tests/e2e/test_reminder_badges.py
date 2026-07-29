"""Per-row reminder badge: plain-language state, independent of due-date clearing,
filtering/search/paging/row-actions, and distinguishable by text alone (issue #56)."""

from __future__ import annotations

import os
import uuid

import httpx
from playwright.sync_api import Page, expect
from qa_helpers import ApiClient, rfc3339_in, wait_until
from qa_helpers.webhooks import deliver

WEBHOOK_SECRET = os.environ.get("VENDOR_WEBHOOK_SECRET", "whsec_test")

FAULT_503 = {
    "priority": 1,  # outranks the baseline happy-path mapping
    "request": {"method": "POST", "urlPath": "/v1/notifications"},
    "response": {"status": 503, "jsonBody": {"error": "vendor unavailable"}},
}


def _reminder_status_in(api: ApiClient, task_id: int, *want: str) -> str | None:
    api.run_due_reminders()  # deterministic trigger; already-attempted tasks re-enqueue nothing
    status = api.get_task(task_id)["reminder_status"]
    return status if status in want else None


def test_dated_task_shows_scheduled_badge(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("Dated, no attempt yet", due_at=rfc3339_in(3600))
    alice_page.goto("/")

    row = alice_page.get_by_test_id("task-row").filter(has_text="Dated, no attempt yet")
    badge = row.get_by_test_id("reminder-badge")
    expect(badge).to_have_count(1)
    expect(badge).to_have_text("Reminder scheduled")


def test_undated_task_has_no_reminder_badge(alice_api: ApiClient, alice_page: Page) -> None:
    alice_api.create_task("No due date at all")
    alice_page.goto("/")

    row = alice_page.get_by_test_id("task-row").filter(has_text="No due date at all")
    expect(row.get_by_test_id("reminder-badge")).to_have_count(0)


def test_badge_survives_cleared_due_date(alice_api: ApiClient, alice_page: Page) -> None:
    task = alice_api.create_due_task("Clear my due date", in_seconds=2)

    def attempted() -> bool:
        alice_api.run_due_reminders()
        return alice_api.get_task(task["id"])["reminder_status"] != "none"

    wait_until(attempted, timeout=15, message="reminder_status leaves none")

    alice_api.request("PATCH", f"/api/tasks/{task['id']}", json={"due_at": None}).raise_for_status()
    assert alice_api.get_task(task["id"])["due_at"] is None

    alice_page.goto("/")
    row = alice_page.get_by_test_id("task-row").filter(has_text="Clear my due date")
    expect(row.get_by_test_id("reminder-badge")).to_have_count(1)
    expect(row.get_by_test_id("due-at")).to_have_count(0)


def test_reminder_badge_states_are_distinguishable_by_text(
    vendor_admin: httpx.Client,
    alice_api: ApiClient,
    alice_page: Page,
    api_url: str,
    clean_reminder_health: None,
) -> None:
    alice_api.create_task("Badge state: scheduled", due_at=rfc3339_in(3600))

    sent_task = alice_api.create_task(
        f"Badge state: sent-{uuid.uuid4().hex[:8]}", due_at=rfc3339_in(2)
    )

    def sent_notified() -> bool:
        alice_api.run_due_reminders()
        return alice_api.get_task(sent_task["id"])["reminder_status"] == "pending"

    wait_until(sent_notified, timeout=15, message="sent-path task turns pending")
    payload = {
        "event": "notification.delivered",
        "notification_id": f"ntf-{uuid.uuid4().hex}",
        "task_id": sent_task["id"],
    }
    assert deliver(api_url, payload, WEBHOOK_SECRET).status_code == 200
    wait_until(
        lambda: alice_api.get_task(sent_task["id"])["reminder_status"] == "sent",
        timeout=15,
        message="sent-path task turns sent",
    )

    vendor_admin.post("/mappings", json=FAULT_503).raise_for_status()
    failed_task = alice_api.create_task("Badge state: failed", due_at=rfc3339_in(2))
    wait_until(
        lambda: _reminder_status_in(alice_api, failed_task["id"], "failed"),
        timeout=30,
        message="failed-path task turns failed",
    )

    alice_page.goto("/")
    texts = {}
    for title in ("Badge state: scheduled", sent_task["title"], "Badge state: failed"):
        row = alice_page.get_by_test_id("task-row").filter(has_text=title)
        texts[title] = row.get_by_test_id("reminder-badge").inner_text()

    assert texts["Badge state: scheduled"] == "Reminder scheduled"
    assert texts[sent_task["title"]] == "Reminder sent"
    assert texts["Badge state: failed"] == "Reminder failed"
    assert len(set(texts.values())) == 3
    for text in texts.values():
        assert text not in {"none", "pending", "sent", "failed"}


def test_badges_survive_filter_search_page_and_row_actions(
    alice_api: ApiClient, alice_page: Page
) -> None:
    title = f"badge-survives-{uuid.uuid4().hex[:8]}"
    alice_api.create_task(title, due_at=rfc3339_in(3600))
    alice_page.goto("/")

    def badge_text() -> str:
        row = alice_page.get_by_test_id("task-row").filter(has_text=title)
        return row.get_by_test_id("reminder-badge").inner_text()

    baseline = badge_text()
    assert baseline == "Reminder scheduled"
    before_count = alice_page.get_by_test_id("task-count").inner_text()

    alice_page.goto("/?status=todo")
    assert badge_text() == baseline

    alice_page.goto(f"/?q={title}")
    row = alice_page.get_by_test_id("task-row").filter(has_text=title)
    expect(row).to_have_count(1)
    assert badge_text() == baseline

    alice_page.goto("/")
    row = alice_page.get_by_test_id("task-row").filter(has_text=title)
    row.get_by_test_id("advance-btn").click()
    assert badge_text() == baseline
    row = alice_page.get_by_test_id("task-row").filter(has_text=title)
    row.get_by_test_id("move-back-btn").click()
    assert badge_text() == baseline

    expect(alice_page.get_by_test_id("task-count")).to_have_text(before_count)
    expect(
        alice_page.get_by_test_id("task-row").filter(has_text=title).get_by_test_id("overdue-badge")
    ).to_have_count(0)
