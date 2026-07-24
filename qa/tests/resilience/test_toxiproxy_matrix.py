"""Toxiproxy chaos matrix: db latency, db stall, vendor connection reset.

Every toxic is removed by the `toxiproxy` fixture finalizer (reset_all), and the
session-scoped no-leak guard asserts nothing survives the suite.
"""

from __future__ import annotations

import time

import httpx
from qa_helpers import ApiClient, rfc3339_in, wait_until
from qa_helpers.toxiproxy import ToxiproxyClient

# 500ms per-round-trip latency: degraded but functional. Kept well under the
# 8s request deadline even for a cold pool connection (handshake + BEGIN +
# queries + commit each pay the toll once).
LATENCY_BUDGET_S = 15.0
# Contract: a stalled db surfaces as 5xx by the 8s request deadline (plus slack).
# The deadline sits ABOVE the degraded-but-working latency scenario on purpose:
# slow traffic must complete, only truly stalled traffic gets cut.
STALL_BUDGET_S = 10.0


def _timed_tasks_request(
    api_url: str, api: ApiClient, timeout: float
) -> tuple[httpx.Response, float]:
    started = time.monotonic()
    resp = httpx.get(f"{api_url}/api/tasks", headers=api.auth_headers, timeout=timeout)
    return resp, time.monotonic() - started


def test_db_latency_api_still_healthy(
    toxiproxy: ToxiproxyClient, alice_api: ApiClient, api_url: str
) -> None:
    toxiproxy.add_toxic("db", "latency", {"latency": 500, "jitter": 0})
    resp, elapsed = _timed_tasks_request(api_url, alice_api, timeout=LATENCY_BUDGET_S + 5)
    assert resp.status_code == 200
    assert elapsed < LATENCY_BUDGET_S, f"latency budget blown: {elapsed:.1f}s"


def test_db_stall_returns_5xx_json_not_hang(
    toxiproxy: ToxiproxyClient, alice_api: ApiClient, api_url: str
) -> None:
    # timeout=0 stalls the connection forever — data stops, socket stays open.
    toxiproxy.add_toxic("db", "timeout", {"timeout": 0})
    resp, elapsed = _timed_tasks_request(api_url, alice_api, timeout=STALL_BUDGET_S + 4)
    assert resp.status_code >= 500
    assert isinstance(resp.json(), dict)  # structured JSON error, not an empty hang
    assert elapsed < STALL_BUDGET_S, f"stall budget blown: {elapsed:.1f}s"


def test_vendor_reset_peer_marks_reminder_failed(
    toxiproxy: ToxiproxyClient, alice_api: ApiClient
) -> None:
    toxiproxy.add_toxic("vendor", "reset_peer", {"timeout": 0})
    task = alice_api.create_task("vendor reset_peer reminder", due_at=rfc3339_in(2))

    def failed() -> str | None:
        alice_api.run_due_reminders()
        status = alice_api.get_task(task["id"])["reminder_status"]
        return status if status == "failed" else None

    status = wait_until(failed, timeout=30, message="reminder_status failed under reset_peer")
    assert status == "failed"
