"""System-wide degraded-reminder-delivery banner: fault-injection driven (issue #7)."""

from __future__ import annotations

import re

import httpx
from playwright.sync_api import Page, expect
from qa_helpers import ApiClient, rfc3339_in, wait_until

FAULT_5XX = {
    "priority": 1,  # outranks the baseline happy-path mapping
    "request": {"method": "POST", "urlPath": "/v1/notifications"},
    "response": {"status": 503, "jsonBody": {"error": "vendor unavailable"}},
}


def _force_degraded(vendor_admin: httpx.Client, alice_api: ApiClient) -> None:
    vendor_admin.post("/mappings", json=FAULT_5XX).raise_for_status()
    alice_api.create_task("degraded-banner-fault", due_at=rfc3339_in(2))

    def health_degraded() -> bool:
        alice_api.run_due_reminders()
        return alice_api.reminder_health()["state"] == "degraded"

    wait_until(health_degraded, timeout=30, message="reminder health degraded under vendor fault")


def test_no_degraded_banner_on_healthy_board(
    alice_api: ApiClient, alice_page: Page, clean_reminder_health: None
) -> None:
    alice_page.goto("/")

    expect(alice_page.get_by_test_id("reminder-degraded-banner")).to_have_count(0)


def test_banner_appears_under_vendor_fault_then_clears_after_recovery(
    vendor_admin: httpx.Client,
    alice_api: ApiClient,
    alice_page: Page,
    clean_reminder_health: None,
) -> None:
    _force_degraded(vendor_admin, alice_api)

    alice_page.goto("/")
    banner = alice_page.get_by_test_id("reminder-degraded-banner")
    expect(banner).to_have_count(1)
    expect(banner).to_contain_text("Reminder delivery is currently degraded")
    expect(banner).to_contain_text("reminders may be delayed")

    vendor_admin.post("/mappings/reset").raise_for_status()
    alice_api.create_task("degraded-banner-recovery", due_at=rfc3339_in(2))

    def health_healthy() -> bool:
        alice_api.run_due_reminders()
        return alice_api.reminder_health()["state"] == "healthy"

    wait_until(health_healthy, timeout=30, message="reminder health healthy after recovery")

    alice_page.goto("/")
    expect(alice_page.get_by_test_id("reminder-degraded-banner")).to_have_count(0)


def test_board_stays_functional_while_degraded(
    vendor_admin: httpx.Client,
    alice_api: ApiClient,
    alice_page: Page,
    clean_reminder_health: None,
) -> None:
    _force_degraded(vendor_admin, alice_api)
    alice_api.create_task("Other task")

    alice_page.goto("/?status=todo")

    expect(alice_page.get_by_test_id("reminder-degraded-banner")).to_have_count(1)
    expect(alice_page.get_by_test_id("task-list")).to_be_visible()
    expect(alice_page.get_by_test_id("task-row")).to_have_count(2)
    expect(alice_page.get_by_test_id("task-count")).to_be_visible()
    expect(alice_page.get_by_test_id("status-filter")).to_be_visible()

    faulted_row = alice_page.get_by_test_id("task-row").filter(has_text="degraded-banner-fault")
    expect(faulted_row.get_by_test_id("reminder-badge")).to_have_text("Reminder failed")
    expect(alice_page.get_by_role("banner")).to_have_count(1)
    expect(alice_page.get_by_role("main")).to_have_count(1)
    expect(alice_page.get_by_role("status")).to_have_count(1)

    row = alice_page.get_by_test_id("task-row").filter(has_text="Other task")
    row.get_by_test_id("advance-btn").click()

    expect(alice_page).to_have_url(re.compile(r"\?status=todo$"))
    expect(alice_page.get_by_test_id("task-row").filter(has_text="Other task")).to_have_count(0)


def test_degraded_banner_and_empty_board_render_together(
    vendor_admin: httpx.Client,
    alice_api: ApiClient,
    alice_page: Page,
    clean_reminder_health: None,
) -> None:
    vendor_admin.post("/mappings", json=FAULT_5XX).raise_for_status()
    task = alice_api.create_task("degraded-empty-board", due_at=rfc3339_in(2))

    def health_degraded() -> bool:
        alice_api.run_due_reminders()
        return alice_api.reminder_health()["state"] == "degraded"

    wait_until(health_degraded, timeout=30, message="reminder health degraded under vendor fault")
    alice_api.delete_task(task["id"])  # a ReminderDelivery outlives its task

    alice_page.goto("/")

    banner = alice_page.get_by_test_id("reminder-degraded-banner")
    empty_board = alice_page.get_by_test_id("empty-board")
    expect(banner).to_be_visible()
    expect(empty_board).to_be_visible()
    banner_box = banner.bounding_box()
    empty_box = empty_board.bounding_box()
    assert banner_box is not None
    assert empty_box is not None
    assert banner_box["y"] < empty_box["y"]
    expect(alice_page.get_by_role("banner")).to_have_count(1)
    expect(alice_page.get_by_role("main")).to_have_count(1)
    expect(alice_page.get_by_role("status")).to_have_count(1)


def test_degraded_board_keeps_single_banner_and_main_landmarks(
    vendor_admin: httpx.Client,
    alice_api: ApiClient,
    alice_page: Page,
    clean_reminder_health: None,
) -> None:
    _force_degraded(vendor_admin, alice_api)

    alice_page.goto("/")

    expect(alice_page.get_by_test_id("reminder-degraded-banner")).to_have_count(1)
    expect(alice_page.get_by_role("banner")).to_have_count(1)
    expect(alice_page.get_by_role("main")).to_have_count(1)
    expect(alice_page.get_by_role("status")).to_have_count(1)
    assert alice_page.evaluate("document.activeElement === document.body") is True
