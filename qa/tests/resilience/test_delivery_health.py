"""Reminder-delivery health signal (AC-10): WireMock vendor faults and Toxiproxy
connection resets both flip it degraded, and it recovers deterministically —
no sleep, only wait_until polling.
"""

from __future__ import annotations

import httpx
from qa_helpers import ApiClient, rfc3339_in, wait_until
from qa_helpers.toxiproxy import ToxiproxyClient

FAULT_5XX = {
    "priority": 1,  # outranks the baseline happy-path mapping
    "request": {"method": "POST", "urlPath": "/v1/notifications"},
    "response": {"status": 503, "jsonBody": {"error": "vendor unavailable"}},
}


def test_health_degrades_under_vendor_5xx_and_recovers_after_reset(
    vendor_admin: httpx.Client, alice_api: ApiClient, clean_reminder_health: None
) -> None:
    vendor_admin.post("/mappings", json=FAULT_5XX).raise_for_status()
    alice_api.create_task("resilience-health-503", due_at=rfc3339_in(2))

    def degraded() -> bool:
        alice_api.run_due_reminders()
        return alice_api.reminder_health()["state"] == "degraded"

    wait_until(degraded, timeout=30, message="reminder health degraded under vendor 503")

    vendor_admin.post("/mappings/reset").raise_for_status()
    alice_api.create_task("resilience-health-recovery", due_at=rfc3339_in(2))

    def healthy() -> bool:
        alice_api.run_due_reminders()
        return alice_api.reminder_health()["state"] == "healthy"

    wait_until(healthy, timeout=30, message="reminder health healthy after vendor recovery")


def test_health_degrades_on_vendor_connection_reset(
    toxiproxy: ToxiproxyClient, alice_api: ApiClient, clean_reminder_health: None
) -> None:
    toxiproxy.add_toxic("vendor", "reset_peer", {"timeout": 0})
    alice_api.create_task("resilience-health-reset-peer", due_at=rfc3339_in(2))

    def degraded() -> bool:
        alice_api.run_due_reminders()
        return alice_api.reminder_health()["state"] == "degraded"

    wait_until(degraded, timeout=30, message="reminder health degraded under vendor reset_peer")
