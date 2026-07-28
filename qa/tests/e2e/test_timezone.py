"""Due times entered on the New task form are interpreted in the viewer's own
time zone (ticket #51): named at entry, read back unambiguously, correct
across DST, and never a silent UTC guess."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import Browser, ConsoleMessage, Page, expect
from qa_helpers import ApiClient, rfc3339_in, wait_until


def _next_month_first(month: int) -> datetime:
    """The next occurrence of the 1st of `month`, strictly in the future."""
    now = datetime.now(ZoneInfo("Europe/Berlin"))
    year = now.year if now.month < month else now.year + 1
    return datetime(year, month, 1, 10, 0)


def _local_value(at: datetime) -> str:
    """`datetime-local` form value for a naive wall-clock `at`."""
    return at.strftime("%Y-%m-%dT%H:%M")


def test_new_form_names_the_viewers_time_zone(zoned_alice_page: Callable[[str], Page]) -> None:
    page = zoned_alice_page("Europe/Berlin")
    page.goto("/new")

    hint = page.get_by_test_id("due-at-zone")
    expect(hint).to_be_visible()
    expect(hint).to_have_text("Times are in Europe/Berlin.")
    expect(page.get_by_test_id("due-at-input")).to_have_accessible_name(re.compile(r"^Due"))


def test_entered_time_is_stored_as_the_intended_instant(
    alice_api: ApiClient, zoned_alice_page: Callable[[str], Page]
) -> None:
    page = zoned_alice_page("Europe/Berlin")
    page.goto("/new")
    page.get_by_test_id("title-input").fill("AC-2 stored instant")
    page.get_by_test_id("due-at-input").fill("2026-08-25T17:00")
    page.get_by_test_id("submit-task").click()
    expect(page).to_have_url(re.compile(r"/$"))

    task = next(t for t in alice_api.list_tasks() if t["title"] == "AC-2 stored instant")
    assert task["due_at"] == "2026-08-25T15:00:00Z"


def test_board_reads_back_the_entered_wall_clock_time(
    alice_api: ApiClient, zoned_alice_page: Callable[[str], Page]
) -> None:
    page = zoned_alice_page("Europe/Berlin")
    page.goto("/new")
    page.get_by_test_id("title-input").fill("AC-3 wall clock readback")
    page.get_by_test_id("due-at-input").fill("2026-08-25T17:00")
    page.get_by_test_id("submit-task").click()

    row = page.get_by_test_id("task-row").filter(has_text="AC-3 wall clock readback")
    expect(row.get_by_test_id("due-at")).to_have_text("25 Aug 2026, 17:00 (Europe/Berlin)")


def test_local_future_time_behind_utc_is_accepted(
    zoned_alice_page: Callable[[str], Page],
) -> None:
    page = zoned_alice_page("America/Los_Angeles")
    local_due = _local_value(datetime.now(ZoneInfo("America/Los_Angeles")) + timedelta(minutes=5))

    page.goto("/new")
    page.get_by_test_id("title-input").fill("AC-4 behind utc")
    page.get_by_test_id("due-at-input").fill(local_due)
    page.get_by_test_id("submit-task").click()

    expect(page).to_have_url(re.compile(r"/$"))
    expect(page.get_by_test_id("api-error")).to_have_count(0)
    expect(page.get_by_test_id("task-row").filter(has_text="AC-4 behind utc")).to_be_visible()


def test_past_local_time_is_rejected_and_preserves_fields(
    zoned_alice_page: Callable[[str], Page],
) -> None:
    page = zoned_alice_page("Europe/Berlin")
    past_due = _local_value(datetime.now(ZoneInfo("Europe/Berlin")) - timedelta(hours=1))

    page.goto("/new")
    page.get_by_test_id("title-input").fill("AC-5 past rejected")
    page.get_by_test_id("description-input").fill("should survive")
    page.get_by_test_id("due-at-input").fill(past_due)
    page.get_by_test_id("submit-task").click()

    expect(page).to_have_url(re.compile(r"/new$"))
    expect(page.get_by_test_id("api-error")).to_be_visible()
    expect(page.get_by_test_id("title-input")).to_have_value("AC-5 past rejected")
    expect(page.get_by_test_id("description-input")).to_have_value("should survive")
    expect(page.get_by_test_id("due-at-input")).to_have_value(past_due)


def test_due_date_across_a_dst_transition_keeps_wall_clock(
    alice_api: ApiClient, zoned_alice_page: Callable[[str], Page]
) -> None:
    page = zoned_alice_page("Europe/Berlin")
    summer = _next_month_first(7)
    winter = _next_month_first(1)

    for label, at in (("summer", summer), ("winter", winter)):
        page.goto("/new")
        page.get_by_test_id("title-input").fill(f"AC-6 dst {label}")
        page.get_by_test_id("due-at-input").fill(_local_value(at))
        page.get_by_test_id("submit-task").click()
        expect(page).to_have_url(re.compile(r"/$"))
        row = page.get_by_test_id("task-row").filter(has_text=f"AC-6 dst {label}")
        expect(row.get_by_test_id("due-at")).to_have_text(
            f"01 {'Jul' if label == 'summer' else 'Jan'} {at.year}, 10:00 (Europe/Berlin)"
        )

    summer_task = next(t for t in alice_api.list_tasks() if t["title"] == "AC-6 dst summer")
    winter_task = next(t for t in alice_api.list_tasks() if t["title"] == "AC-6 dst winter")
    summer_hour = int(summer_task["due_at"][11:13])
    winter_hour = int(winter_task["due_at"][11:13])
    assert abs(summer_hour - winter_hour) == 1, (
        f"expected offsets one hour apart: summer={summer_task['due_at']} "
        f"winter={winter_task['due_at']}"
    )


def test_overdue_badge_flips_at_the_intended_local_moment(
    alice_api: ApiClient, zoned_alice_page: Callable[[str], Page]
) -> None:
    page = zoned_alice_page("Europe/Berlin")
    due_local = _local_value(datetime.now(ZoneInfo("Europe/Berlin")) + timedelta(seconds=3))
    page.goto("/new")
    page.get_by_test_id("title-input").fill("AC-7 overdue flip")
    page.get_by_test_id("due-at-input").fill(due_local)
    page.get_by_test_id("submit-task").click()

    row = page.get_by_test_id("task-row").filter(has_text="AC-7 overdue flip")
    expect(row.get_by_test_id("overdue-badge")).to_have_count(0)

    def overdue_shown() -> bool:
        page.goto("/")
        row = page.get_by_test_id("task-row").filter(has_text="AC-7 overdue flip")
        return row.get_by_test_id("overdue-badge").count() == 1

    wait_until(overdue_shown, timeout=15, message="overdue-badge shows at the intended moment")


def test_reminder_fires_at_the_intended_instant(
    alice_api: ApiClient, zoned_alice_page: Callable[[str], Page]
) -> None:
    page = zoned_alice_page("Europe/Berlin")
    due_local = _local_value(datetime.now(ZoneInfo("Europe/Berlin")) + timedelta(seconds=3))
    page.goto("/new")
    page.get_by_test_id("title-input").fill("AC-8 reminder instant")
    page.get_by_test_id("due-at-input").fill(due_local)
    page.get_by_test_id("submit-task").click()
    expect(page).to_have_url(re.compile(r"/$"))

    task = next(t for t in alice_api.list_tasks() if t["title"] == "AC-8 reminder instant")

    def reminder_left_none() -> bool:
        alice_api.run_due_reminders()
        return alice_api.get_task(task["id"])["reminder_status"] != "none"

    wait_until(reminder_left_none, timeout=90, interval=2, message="reminder leaves 'none'")


def test_without_javascript_times_are_utc_and_labelled_utc(
    browser: Browser, base_url: str, alice_storage_state: str
) -> None:
    context = browser.new_context(
        base_url=base_url,
        storage_state=alice_storage_state,
        timezone_id="Europe/Berlin",
        java_script_enabled=False,
    )
    try:
        page = context.new_page()
        page.goto("/new")
        expect(page.get_by_test_id("due-at-zone")).to_have_text("Times are in UTC.")

        page.get_by_test_id("title-input").fill("AC-9 no js")
        page.get_by_test_id("due-at-input").fill(rfc3339_in(3600)[:16])
        page.get_by_test_id("submit-task").click()

        row = page.get_by_test_id("task-row").filter(has_text="AC-9 no js")
        expect(row.get_by_test_id("due-at")).to_contain_text("(UTC)")
    finally:
        context.close()


def test_malformed_tz_cookie_falls_back_to_utc(
    browser: Browser, base_url: str, alice_storage_state: str
) -> None:
    context = browser.new_context(base_url=base_url, storage_state=alice_storage_state)
    try:
        context.add_cookies([{"name": "tz", "value": "../../etc/passwd", "url": base_url}])
        page = context.new_page()
        resp = page.goto("/new")
        assert resp is not None and resp.status == 200
        expect(page.get_by_test_id("due-at-zone")).to_have_text("Times are in UTC.")
        expect(page.locator("html")).to_have_attribute("data-tz", "UTC")
    finally:
        context.close()


def test_zone_sync_script_logs_no_console_errors_and_keeps_landmarks(
    browser: Browser, base_url: str, alice_storage_state: str
) -> None:
    context = browser.new_context(
        base_url=base_url, storage_state=alice_storage_state, timezone_id="Europe/Berlin"
    )
    try:
        page = context.new_page()
        errors: list[str] = []
        reloads = 0

        def on_console(msg: ConsoleMessage) -> None:
            if msg.type == "error":
                errors.append(msg.text)

        def on_frame_navigated(frame: object) -> None:
            nonlocal reloads
            if frame is page.main_frame:
                reloads += 1

        page.on("console", on_console)
        page.on("framenavigated", on_frame_navigated)

        for path in ("/", "/new", "/login"):
            page.goto(path)
            expect(page.get_by_role("banner")).to_have_count(1)
            expect(page.get_by_role("main")).to_have_count(1)

        assert errors == []
        # each goto is one navigation; the sync script may add at most one
        # reload per page when the server's default zone disagrees.
        assert reloads <= 2 * 3
    finally:
        context.close()
