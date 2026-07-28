"""Proof suite for the web-health fault-injection lever (issue #31): the
reminder-health signal can be faulted alone while GET /api/tasks and the board
stay healthy — the AC-7-class scenario ticket #7 could not prove black-box."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect
from qa_helpers import ApiClient, alice_credentials
from qa_helpers.health_lever import HealthLever


def test_tasks_api_unaffected_under_health_fail(
    health_lever: HealthLever, alice_api: ApiClient, base_url: str
) -> None:
    alice_api.create_task("baseline under health fault")
    with ApiClient(base_url) as gateway_api:
        gateway_api.login(*alice_credentials())
        baseline = gateway_api.page_tasks()

        health_lever.fail()
        faulted = gateway_api.page_tasks()

    assert faulted == baseline


def test_board_renders_normally_under_health_fail(
    health_lever: HealthLever, alice_api: ApiClient, alice_page: Page
) -> None:
    for title in ("Board fail A", "Board fail B", "Board fail C"):
        alice_api.create_task(title)

    health_lever.fail()
    alice_page.goto("/")

    expect(alice_page.get_by_test_id("task-list").first).to_be_visible()
    expect(alice_page.get_by_test_id("task-row")).to_have_count(3)
    expect(alice_page.get_by_test_id("task-count")).to_be_visible()
    expect(alice_page.get_by_test_id("status-filter")).to_be_visible()
    expect(alice_page.get_by_test_id("reminder-degraded-banner")).to_have_count(0)


def test_board_renders_normally_under_health_timeout(
    health_lever: HealthLever, alice_api: ApiClient, alice_page: Page
) -> None:
    for title in ("Board timeout A", "Board timeout B"):
        alice_api.create_task(title)

    health_lever.timeout()
    alice_page.goto("/")

    expect(alice_page.get_by_test_id("task-list").first).to_be_visible()
    expect(alice_page.get_by_test_id("task-row")).to_have_count(2)
    expect(alice_page.get_by_test_id("task-count")).to_be_visible()
    expect(alice_page.get_by_test_id("status-filter")).to_be_visible()
    expect(alice_page.get_by_test_id("reminder-degraded-banner")).to_have_count(0)


@pytest.mark.parametrize("mode", ["fail", "timeout"])
def test_board_actions_work_under_health_fault(
    health_lever: HealthLever, alice_api: ApiClient, alice_page: Page, mode: str
) -> None:
    alice_api.create_task("advance under fault")
    alice_api.create_task("delete under fault")
    getattr(health_lever, mode)()

    alice_page.goto("/?status=todo")
    row = alice_page.get_by_test_id("task-row").filter(has_text="advance under fault")
    row.get_by_test_id("advance-btn").click()

    expect(alice_page).to_have_url(re.compile(r"\?status=todo$"))
    expect(
        alice_page.get_by_test_id("task-row").filter(has_text="advance under fault")
    ).to_have_count(0)
    expect(alice_page.get_by_test_id("reminder-degraded-banner")).to_have_count(0)

    row = alice_page.get_by_test_id("task-row").filter(has_text="delete under fault")
    row.get_by_test_id("delete-btn").click()

    expect(
        alice_page.get_by_test_id("task-row").filter(has_text="delete under fault")
    ).to_have_count(0)
    expect(alice_page.get_by_test_id("reminder-degraded-banner")).to_have_count(0)


def test_release_restores_passthrough(
    health_lever: HealthLever, alice_api: ApiClient, alice_page: Page
) -> None:
    health_lever.fail()
    health_lever.release()

    assert health_lever.engaged_faults() == []
    probe = health_lever.probe(alice_api.token)
    assert probe.status_code == 200
    assert alice_api.reminder_health()["state"] == "healthy"

    alice_page.goto("/")
    expect(alice_page.get_by_test_id("reminder-degraded-banner")).to_have_count(0)


def test_lever_is_inert_by_default(health_lever: HealthLever, alice_api: ApiClient) -> None:
    assert health_lever.engaged_faults() == []
    probe = health_lever.probe(alice_api.token)
    assert probe.status_code == 200
