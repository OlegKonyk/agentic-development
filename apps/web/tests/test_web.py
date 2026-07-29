"""Web UI tests with the upstream API mocked via respx (v2: auth + CSRF).

The app-under-test is driven through TestClient (explicit ASGITransport, which
respx does not patch); the app's outbound httpx calls hit the respx mock.
"""

import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from web.main import (
    BOARD_PAGE_SIZE,
    DEGRADED_REMINDERS_MESSAGE,
    DRAFT_MAX_BYTES,
    PREV_STATUS,
    UTC_ZONE,
    board_url,
    create_app,
    decorate_tasks,
    draft_fits,
    edit_url,
    empty_state,
    filter_options,
    format_due_at,
    local_input_value,
    normalize_input_value,
    normalize_search,
    normalize_status,
    parse_due_at,
    parse_page,
    reminder_health_url,
    resolve_zone,
    safe_next,
    same_user,
    title_rejected,
    to_rfc3339_z,
)

API = "http://localhost:8000"
TOKEN = "tok-alice-0001"
ME = {"id": 1, "email": "alice@example.com"}
AUTH = f"Bearer {TOKEN}"


def iso_in(seconds: float) -> str:
    """RFC3339 UTC `Z` timestamp `seconds` from now — mirrors qa_helpers.rfc3339_in."""
    at = datetime.now(UTC) + timedelta(seconds=seconds)
    return at.replace(microsecond=0).isoformat().replace("+00:00", "Z")


SEEDED = [
    {
        "id": 1,
        "title": "Write the spec",
        "description": "",
        "status": "todo",
        "due_at": None,
        "reminder_status": "none",
        "created_at": "2026-01-01T00:00:00Z",
    },
    {
        "id": 2,
        "title": "Build the API",
        "description": "fastapi",
        "status": "doing",
        "due_at": iso_in(3600),
        "reminder_status": "pending",
        "created_at": "2026-01-01T00:01:00Z",
    },
    {
        "id": 3,
        "title": "Ship it",
        "description": "",
        "status": "done",
        "due_at": None,
        "reminder_status": "none",
        "created_at": "2026-01-01T00:02:00Z",
    },
]


def extract_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "no csrf_token input in page"
    return match.group(1)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def login(client: TestClient) -> str:
    """Drive the real login form; returns the session csrf token."""
    respx.post(f"{API}/api/auth/login").mock(
        return_value=httpx.Response(
            200, json={"token": TOKEN, "expires_at": "2026-01-01T01:00:00Z"}
        )
    )
    csrf = extract_csrf(client.get("/login").text)
    resp = client.post(
        "/login",
        data={"email": "alice@example.com", "password": "pw", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    return csrf


def mock_health(**kwargs: object) -> respx.Route:
    kwargs.setdefault("return_value", httpx.Response(200, json={"state": "healthy"}))
    return respx.get(f"{API}/api/reminders/health").mock(**kwargs)


def page_body(
    items: list[dict], total: int | None = None, limit: int = 20, offset: int = 0
) -> dict:
    """The `{items, total, limit, offset}` envelope `GET /api/tasks` returns."""
    return {
        "items": items,
        "total": total if total is not None else len(items),
        "limit": limit,
        "offset": offset,
    }


def mock_board() -> tuple[respx.Route, respx.Route]:
    me = respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    tasks = respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body(SEEDED))
    )
    mock_health()  # default healthy; tests that care re-mock the same pattern (respx replaces it)
    return me, tasks


# --- helpers ---------------------------------------------------------------


def test_safe_next_allows_relative_paths_only() -> None:
    assert safe_next("/new") == "/new"
    assert safe_next("/") == "/"
    assert safe_next("http://evil.example") == "/"
    assert safe_next("//evil.example") == "/"
    assert safe_next("/\\evil.example") == "/"
    assert safe_next(None) == "/"
    assert safe_next("") == "/"


def test_to_rfc3339_z_interprets_local_value_in_viewer_zone() -> None:
    berlin = ZoneInfo("Europe/Berlin")
    assert to_rfc3339_z("2026-08-25T17:00", berlin) == "2026-08-25T15:00:00Z"
    assert to_rfc3339_z("2026-08-25T17:00", UTC_ZONE) == "2026-08-25T17:00:00Z"
    # an already-offset value keeps its own offset regardless of `zone`
    assert to_rfc3339_z("2026-03-01T12:30:15+02:00", berlin) == "2026-03-01T10:30:15Z"


def test_to_rfc3339_z_uses_offset_in_force_on_the_entered_date() -> None:
    berlin = ZoneInfo("Europe/Berlin")
    # same wall-clock 10:00, summer (CEST, UTC+2) vs winter (CET, UTC+1)
    assert to_rfc3339_z("2026-07-10T10:00", berlin) == "2026-07-10T08:00:00Z"
    assert to_rfc3339_z("2026-01-10T10:00", berlin) == "2026-01-10T09:00:00Z"


def test_resolve_zone_accepts_iana_key() -> None:
    assert resolve_zone("Europe/Berlin").key == "Europe/Berlin"
    assert resolve_zone("America/Los_Angeles").key == "America/Los_Angeles"
    assert resolve_zone("UTC").key == "UTC"
    assert resolve_zone("Europe/Berlin ").key == "Europe/Berlin"  # surrounding whitespace stripped


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "Not/AZone",
        "../../etc/passwd",
        "A" * 200,
    ],
)
def test_resolve_zone_falls_back_to_utc_for_absent_blank_unknown_and_traversal_values(
    raw: str | None,
) -> None:
    assert resolve_zone(raw).key == "UTC"


def test_title_rejected_helper() -> None:
    assert title_rejected([{"loc": ["body", "title"], "type": "value_error"}]) is True
    assert title_rejected([{"loc": ["body", "due_at"], "type": "value_error"}]) is False
    assert title_rejected(None) is False
    assert title_rejected({}) is False
    assert title_rejected("boom") is False
    assert title_rejected([{}]) is False


def test_draft_fits_accepts_typical_and_rejects_oversized() -> None:
    assert draft_fits({"title": "Ship it", "description": "small", "due_at": "2026-08-25T17:00"})
    assert not draft_fits({"title": "x" * (DRAFT_MAX_BYTES + 1), "description": "", "due_at": ""})
    # non-ASCII inflates to `\uXXXX` (6 bytes/char) once JSON-encoded
    boundary_ok = "é" * (DRAFT_MAX_BYTES // 6 - 10)
    assert draft_fits({"title": boundary_ok, "description": "", "due_at": ""})
    boundary_over = "é" * (DRAFT_MAX_BYTES // 6 + 10)
    assert not draft_fits({"title": boundary_over, "description": "", "due_at": ""})


def test_same_user_casefolds_and_rejects_missing_owner_or_email() -> None:
    assert same_user("alice@example.com", "alice@example.com") is True
    assert same_user("Alice@Example.com", "alice@example.com ") is True
    assert same_user("alice@example.com", "bob@example.com") is False
    assert same_user(None, "alice@example.com") is False
    assert same_user("alice@example.com", None) is False
    assert same_user(None, None) is False
    assert same_user("", "") is False


def test_format_due_at_renders_zone_named_label() -> None:
    instant = datetime(2026, 8, 25, 15, 0, tzinfo=UTC)
    assert format_due_at(instant, ZoneInfo("Europe/Berlin")) == "25 Aug 2026, 17:00 (Europe/Berlin)"
    assert format_due_at(instant, UTC_ZONE) == "25 Aug 2026, 15:00 (UTC)"
    assert (
        format_due_at(datetime(2026, 7, 5, 9, 0, tzinfo=UTC), UTC_ZONE)
        == "05 Jul 2026, 09:00 (UTC)"
    )
    plus_two = timezone(timedelta(hours=2))
    assert (
        format_due_at(datetime(2026, 7, 25, 14, 34, tzinfo=plus_two), UTC_ZONE)
        == "25 Jul 2026, 12:34 (UTC)"
    )


def test_parse_due_at_accepts_z_naive_and_rejects_garbage() -> None:
    assert parse_due_at("2026-07-25T12:34:56Z") == datetime(2026, 7, 25, 12, 34, 56, tzinfo=UTC)
    assert parse_due_at("2026-07-25T12:34:56") == datetime(2026, 7, 25, 12, 34, 56, tzinfo=UTC)
    assert parse_due_at(None) is None
    assert parse_due_at("") is None
    assert parse_due_at("not-a-date") is None


def test_decorate_tasks_orders_by_due_then_id() -> None:
    now = datetime(2026, 7, 25, tzinfo=UTC)
    tasks = [
        {"id": 2, "due_at": None},
        {"id": 1, "due_at": "2026-08-01T00:00:00Z"},
        {"id": 3, "due_at": "2026-07-26T00:00:00Z"},
        {"id": 4, "due_at": None},
    ]

    ordered = decorate_tasks(tasks, now, UTC_ZONE)

    assert [t["id"] for t in ordered] == [3, 1, 2, 4]


def test_safe_next_allows_path_with_query() -> None:
    assert safe_next("/?status=todo") == "/?status=todo"
    assert safe_next("//evil?x=1") == "/"


def test_normalize_status_accepts_columns_only() -> None:
    assert normalize_status("todo") == "todo"
    assert normalize_status("doing") == "doing"
    assert normalize_status("done") == "done"
    assert normalize_status(None) is None
    assert normalize_status("") is None
    assert normalize_status("TODO") is None
    assert normalize_status("archived") is None


def test_board_url_builds_filtered_and_plain_urls() -> None:
    assert board_url(None) == "/"
    assert board_url("doing") == "/?status=doing"
    assert board_url(None, 1) == "/"
    assert board_url("todo", 1) == "/?status=todo"
    assert board_url(None, 2) == "/?page=2"
    assert board_url("todo", 2) == "/?status=todo&page=2"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ""),
        ("", ""),
        ("   ", ""),
        (" inv ", "inv"),
        ("x" * 2000, "x" * 1000),
        ("bad\x00term", "badterm"),
    ],
)
def test_normalize_search_trims_clamps_and_drops_unstorable_chars(
    raw: str | None, expected: str
) -> None:
    assert normalize_search(raw) == expected


def test_board_url_encodes_search_term() -> None:
    assert board_url(None, 1, "a&b c#d%e") == "/?q=a%26b%20c%23d%25e"
    assert board_url("todo", 1, "inv") == "/?status=todo&q=inv"
    assert board_url(None, 2, "inv") == "/?q=inv&page=2"
    # empty search yields today's URLs unchanged
    assert board_url(None, 1, "") == "/"
    assert board_url("todo", 1, "") == "/?status=todo"
    assert board_url(None, 2, "") == "/?page=2"


def test_filter_options_preserve_search_and_reset_page() -> None:
    options = filter_options("todo", "inv")

    assert [o["href"] for o in options] == [
        "/?q=inv",
        "/?status=todo&q=inv",
        "/?status=doing&q=inv",
        "/?status=done&q=inv",
    ]


@pytest.mark.parametrize("value", [None, "", "abc", "0", "-1", "9.5"])
def test_parse_page_falls_back_to_one(value: str | None) -> None:
    assert parse_page(value) == 1


def test_parse_page_accepts_positive_integers() -> None:
    assert parse_page("1") == 1
    assert parse_page("2") == 2
    assert parse_page("42") == 42


def test_filter_options_marks_active_and_defaults_to_all() -> None:
    options = filter_options(None)

    assert [o["value"] for o in options] == [None, "todo", "doing", "done"]
    assert [o["label"] for o in options] == ["all", "todo", "doing", "done"]
    assert [o["testid"] for o in options] == [
        "filter-all",
        "filter-todo",
        "filter-doing",
        "filter-done",
    ]
    assert [o["href"] for o in options] == ["/", "/?status=todo", "/?status=doing", "/?status=done"]
    assert sum(1 for o in options if o["active"]) == 1
    assert options[0]["active"] is True

    active_doing = filter_options("doing")
    assert sum(1 for o in active_doing if o["active"]) == 1
    assert next(o for o in active_doing if o["value"] == "doing")["active"] is True


@pytest.mark.parametrize(
    ("api_error", "active", "total", "search", "expected"),
    [
        (True, None, 0, "", None),
        (True, "todo", 0, "", None),
        (True, None, None, "", None),
        (True, "done", 5, "", None),
        (False, None, 0, "", "board"),
        (False, "todo", 0, "", "filter"),
        (False, "doing", 0, "", "filter"),
        (False, "done", 0, "", "filter"),
        (False, None, 3, "", None),
        (False, "todo", 3, "", None),
        (False, None, None, "", None),
        (False, "todo", None, "", None),
        (False, None, 0, "inv", "search"),
        (False, "todo", 0, "inv", "search"),
        (True, None, 0, "inv", None),
        (False, None, 3, "inv", None),
    ],
)
def test_empty_state_helper_truth_table(
    api_error: bool, active: str | None, total: int | None, search: str, expected: str | None
) -> None:
    assert empty_state(api_error, active, total, search) == expected


def test_decorate_tasks_marks_overdue_only_for_past_due() -> None:
    now = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)
    tasks = [
        {"id": 1, "due_at": "2026-07-25T11:59:59Z"},
        {"id": 2, "due_at": "2026-07-25T12:00:01Z"},
        {"id": 3, "due_at": None},
        {"id": 4, "due_at": "2026-07-25T12:00:00Z"},
    ]

    ordered = {t["id"]: t["overdue"] for t in decorate_tasks(tasks, now, UTC_ZONE)}

    assert ordered == {1: True, 2: False, 3: False, 4: False}


def test_decorate_tasks_ordering_and_overdue_are_zone_independent() -> None:
    berlin = ZoneInfo("Europe/Berlin")
    now = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)
    tasks = [
        {"id": 1, "due_at": "2026-07-25T11:59:59Z"},
        {"id": 2, "due_at": "2026-07-25T12:00:01Z"},
        {"id": 3, "due_at": None},
        {"id": 4, "due_at": "2026-07-25T12:00:00Z"},
    ]

    utc_result = decorate_tasks([dict(t) for t in tasks], now, UTC_ZONE)
    berlin_result = decorate_tasks([dict(t) for t in tasks], now, berlin)

    assert [t["id"] for t in utc_result] == [t["id"] for t in berlin_result]
    assert {t["id"]: t["overdue"] for t in utc_result} == {
        t["id"]: t["overdue"] for t in berlin_result
    }


# --- auth gating -----------------------------------------------------------


def test_unauthed_board_redirects_to_login_with_next(client: TestClient) -> None:
    resp = client.get("/", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=/"


def test_unauthed_new_redirects_to_login_with_next(client: TestClient) -> None:
    resp = client.get("/new", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=/new"


def test_unauthed_filtered_board_redirects_with_encoded_next(client: TestClient) -> None:
    resp = client.get("/?status=todo", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=/%3Fstatus%3Dtodo"


def test_login_form_renders(client: TestClient) -> None:
    resp = client.get("/login")

    assert resp.status_code == 200
    for testid in ("email-input", "password-input", "submit-login"):
        assert f'data-testid="{testid}"' in resp.text
    assert 'data-testid="login-error"' not in resp.text
    assert 'name="csrf_token"' in resp.text


def test_base_template_emits_tz_sync_script_and_server_zone(client: TestClient) -> None:
    resp = client.get("/login")

    assert resp.status_code == 200
    assert 'data-tz="UTC"' in resp.text
    assert 'data-tz-sync="1"' in resp.text
    assert "Intl.DateTimeFormat().resolvedOptions().timeZone" in resp.text


@respx.mock
def test_login_success_sets_session_and_redirects(client: TestClient) -> None:
    login(client)
    mock_board()

    resp = client.get("/")

    assert resp.status_code == 200
    assert 'data-testid="user-email"' in resp.text
    assert "alice@example.com" in resp.text


@respx.mock
def test_login_wrong_password_shows_generic_banner(client: TestClient) -> None:
    respx.post(f"{API}/api/auth/login").mock(
        return_value=httpx.Response(401, json={"detail": "invalid credentials"})
    )
    csrf = extract_csrf(client.get("/login").text)

    resp = client.post(
        "/login",
        data={"email": "alice@example.com", "password": "nope", "csrf_token": csrf},
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert 'data-testid="login-error"' in resp.text


def test_login_csrf_mismatch_is_403(client: TestClient) -> None:
    client.get("/login")  # establish session csrf

    resp = client.post(
        "/login",
        data={"email": "a@example.com", "password": "pw", "csrf_token": "wrong"},
        follow_redirects=False,
    )

    assert resp.status_code == 403


@respx.mock
def test_login_next_redirect_is_sanitized(client: TestClient) -> None:
    respx.post(f"{API}/api/auth/login").mock(
        return_value=httpx.Response(
            200, json={"token": TOKEN, "expires_at": "2026-01-01T01:00:00Z"}
        )
    )
    csrf = extract_csrf(client.get("/login?next=http://evil.example").text)

    resp = client.post(
        "/login",
        data={
            "email": "alice@example.com",
            "password": "pw",
            "csrf_token": csrf,
            "next": "http://evil.example",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


@respx.mock
def test_login_next_relative_path_is_honored(client: TestClient) -> None:
    respx.post(f"{API}/api/auth/login").mock(
        return_value=httpx.Response(
            200, json={"token": TOKEN, "expires_at": "2026-01-01T01:00:00Z"}
        )
    )
    csrf = extract_csrf(client.get("/login?next=/new").text)

    resp = client.post(
        "/login",
        data={
            "email": "alice@example.com",
            "password": "pw",
            "csrf_token": csrf,
            "next": "/new",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/new"


@respx.mock
def test_api_401_mid_session_clears_cookie_and_redirects(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(401))

    resp = client.get("/", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
    # session was cleared: the next hit is the plain unauthed redirect
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=/"


@respx.mock
def test_board_401_redirects_to_bare_login_and_still_flags_expiry(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(401))

    resp = client.get("/", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
    body = client.get("/login").text
    assert 'data-testid="session-expired"' in body


@respx.mock
def test_expired_session_is_unauthenticated_while_draft_is_stashed(client: TestClient) -> None:
    csrf = login(client)
    respx.post(f"{API}/api/tasks").mock(return_value=httpx.Response(401))
    client.post("/new", data={"title": "New one", "csrf_token": csrf}, follow_redirects=False)

    resp = client.get("/", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=/"


@respx.mock
def test_logout_calls_api_clears_session_and_redirects(client: TestClient) -> None:
    csrf = login(client)
    route = respx.post(f"{API}/api/auth/logout").mock(return_value=httpx.Response(204))

    resp = client.post("/logout", data={"csrf_token": csrf}, follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
    assert route.called
    assert route.calls.last.request.headers["Authorization"] == AUTH
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=/"


# --- board -----------------------------------------------------------------


@respx.mock
def test_index_renders_seeded_tasks_with_bearer(client: TestClient) -> None:
    login(client)
    _, tasks_route = mock_board()

    resp = client.get("/")

    assert resp.status_code == 200
    body = resp.text
    for task in SEEDED:
        assert task["title"] in body
    assert 'data-testid="task-list"' in body
    assert body.count('data-testid="task-row"') == 3
    assert 'data-testid="api-error"' not in body
    assert 'data-testid="logout-btn"' in body
    assert tasks_route.calls.last.request.headers["Authorization"] == AUTH


@respx.mock
def test_index_header_shows_email_and_count(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/").text

    assert 'data-testid="user-email">alice@example.com<' in body
    assert 'data-testid="task-count">3<' in body


@respx.mock
def test_index_due_at_and_reminder_badge_render_only_when_set(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/").text

    assert body.count('data-testid="due-at"') == 1
    assert format_due_at(parse_due_at(SEEDED[1]["due_at"]), UTC_ZONE) in body
    assert body.count('data-testid="reminder-badge"') == 1
    assert 'data-testid="reminder-badge">pending<' in body


@respx.mock
def test_index_due_at_renders_human_label_not_raw_iso(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    due_at = "2026-07-25T12:34:56Z"
    task = {**SEEDED[0], "id": 10, "due_at": due_at}
    respx.get(f"{API}/api/tasks").mock(return_value=httpx.Response(200, json=page_body([task])))
    mock_health()

    body = client.get("/").text

    assert "25 Jul 2026, 12:34 (UTC)" in body
    assert due_at not in body


@respx.mock
def test_index_due_label_uses_cookie_zone(client: TestClient) -> None:
    login(client)
    client.cookies.set("tz", "Europe/Berlin")
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    task = {**SEEDED[0], "id": 10, "due_at": "2026-08-25T15:00:00Z"}
    respx.get(f"{API}/api/tasks").mock(return_value=httpx.Response(200, json=page_body([task])))
    mock_health()

    body = client.get("/").text

    assert "25 Aug 2026, 17:00 (Europe/Berlin)" in body
    assert 'data-tz="Europe/Berlin"' in body


@respx.mock
def test_index_with_malformed_tz_cookie_renders_utc_label_and_200(client: TestClient) -> None:
    login(client)
    client.cookies.set("tz", "../../etc/passwd")
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    task = {**SEEDED[0], "id": 10, "due_at": "2026-07-25T12:34:56Z"}
    respx.get(f"{API}/api/tasks").mock(return_value=httpx.Response(200, json=page_body([task])))
    mock_health()

    resp = client.get("/")

    assert resp.status_code == 200
    assert "25 Jul 2026, 12:34 (UTC)" in resp.text
    assert "../../etc/passwd" not in resp.text
    assert 'data-tz="UTC"' in resp.text


@respx.mock
def test_index_overdue_badge_only_for_past_due(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    tasks = [
        {**SEEDED[0], "id": 11, "title": "Past due", "due_at": "2020-01-01T00:00:00Z"},
        {**SEEDED[0], "id": 12, "title": "Future due", "due_at": iso_in(3600)},
        {**SEEDED[0], "id": 13, "title": "No due date", "due_at": None},
    ]
    respx.get(f"{API}/api/tasks").mock(return_value=httpx.Response(200, json=page_body(tasks)))
    mock_health()

    body = client.get("/").text

    assert body.count('data-testid="overdue-badge"') == 1
    start = body.index('data-task-id="11"')
    next_row = body.index('data-testid="task-row"', start)
    assert 'data-testid="overdue-badge"' in body[start:next_row]


@respx.mock
def test_index_orders_column_by_due_then_id(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    tasks = [
        {**SEEDED[0], "id": 21, "title": "A", "due_at": iso_in(5 * 86400), "status": "todo"},
        {**SEEDED[0], "id": 22, "title": "B", "due_at": None, "status": "todo"},
        {**SEEDED[0], "id": 23, "title": "C", "due_at": iso_in(86400), "status": "todo"},
    ]
    respx.get(f"{API}/api/tasks").mock(return_value=httpx.Response(200, json=page_body(tasks)))
    mock_health()

    body = client.get("/").text

    assert body.index(">C<") < body.index(">A<") < body.index(">B<")


@respx.mock
def test_index_overdue_and_reminder_badges_are_independent(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    task = {
        **SEEDED[0],
        "id": 31,
        "title": "Overdue with reminder",
        "due_at": "2020-01-01T00:00:00Z",
        "reminder_status": "pending",
    }
    respx.get(f"{API}/api/tasks").mock(return_value=httpx.Response(200, json=page_body([task])))
    mock_health()

    body = client.get("/").text

    assert body.count('data-testid="overdue-badge"') == 1
    assert body.count('data-testid="reminder-badge"') == 1
    assert 'data-testid="reminder-badge">pending<' in body


@respx.mock
def test_index_shows_error_banner_when_api_down(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{API}/api/tasks").mock(side_effect=httpx.ConnectError("refused"))

    resp = client.get("/")

    assert resp.status_code == 200
    assert 'data-testid="api-error"' in resp.text
    assert "The task API is unavailable. Please try again shortly." in resp.text


# --- reminder degraded banner ------------------------------------------------


@respx.mock
def test_board_shows_degraded_banner_when_health_degraded(client: TestClient) -> None:
    login(client)
    mock_board()
    mock_health(return_value=httpx.Response(200, json={"state": "degraded"}))

    resp = client.get("/")

    assert resp.status_code == 200
    assert 'data-testid="reminder-degraded-banner"' in resp.text
    assert DEGRADED_REMINDERS_MESSAGE in resp.text


@respx.mock
def test_board_omits_degraded_banner_when_healthy(client: TestClient) -> None:
    login(client)
    mock_board()
    mock_health(return_value=httpx.Response(200, json={"state": "healthy"}))

    resp = client.get("/")

    assert resp.status_code == 200
    assert 'data-testid="reminder-degraded-banner"' not in resp.text


@respx.mock
def test_degraded_banner_absent_on_health_500(client: TestClient) -> None:
    login(client)
    mock_board()
    mock_health(return_value=httpx.Response(500))

    resp = client.get("/")

    assert resp.status_code == 200
    assert 'data-testid="reminder-degraded-banner"' not in resp.text
    assert 'data-testid="api-error"' not in resp.text


@respx.mock
def test_degraded_banner_absent_on_health_connect_error(client: TestClient) -> None:
    login(client)
    mock_board()
    mock_health(side_effect=httpx.ConnectError("refused"))

    resp = client.get("/")

    assert resp.status_code == 200
    assert 'data-testid="reminder-degraded-banner"' not in resp.text
    assert 'data-testid="api-error"' not in resp.text


@respx.mock
def test_degraded_banner_absent_on_health_malformed_body(client: TestClient) -> None:
    login(client)
    mock_board()
    mock_health(return_value=httpx.Response(200, text="not json"))

    resp = client.get("/")

    assert resp.status_code == 200
    assert 'data-testid="reminder-degraded-banner"' not in resp.text
    assert 'data-testid="api-error"' not in resp.text


@respx.mock
def test_degraded_banner_absent_on_health_401(client: TestClient) -> None:
    login(client)
    mock_board()
    mock_health(return_value=httpx.Response(401))

    resp = client.get("/")

    assert resp.status_code == 200
    assert 'data-testid="reminder-degraded-banner"' not in resp.text
    assert 'data-testid="api-error"' not in resp.text


@respx.mock
def test_health_not_requested_when_tasks_api_down(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{API}/api/tasks").mock(side_effect=httpx.ConnectError("refused"))
    health_route = mock_health()

    resp = client.get("/")

    assert resp.status_code == 200
    assert not health_route.called
    assert 'data-testid="api-error"' in resp.text
    assert 'data-testid="reminder-degraded-banner"' not in resp.text


@respx.mock
def test_degraded_banner_precedes_status_filter_and_board_renders(client: TestClient) -> None:
    login(client)
    mock_board()
    mock_health(return_value=httpx.Response(200, json={"state": "degraded"}))

    resp = client.get("/")
    body = resp.text

    assert body.index('data-testid="reminder-degraded-banner"') < body.index(
        'data-testid="status-filter"'
    )
    assert 'data-testid="task-list"' in body
    assert body.count('data-testid="task-row"') == 3
    assert 'data-testid="task-count">3<' in body
    assert 'data-testid="advance-btn"' in body
    assert 'data-testid="delete-btn"' in body


@respx.mock
def test_degraded_banner_markup_is_role_status(client: TestClient) -> None:
    login(client)
    mock_board()
    mock_health(return_value=httpx.Response(200, json={"state": "degraded"}))

    body = client.get("/").text
    start = body.index('data-testid="reminder-degraded-banner"')
    tag_start = body.rindex("<div", 0, start)
    tag_end = body.index(">", start)
    tag = body[tag_start:tag_end]

    assert 'role="status"' in tag
    assert "tabindex" not in tag
    assert "autofocus" not in tag


@respx.mock
def test_new_and_login_pages_never_render_degraded_banner(client: TestClient) -> None:
    login(client)

    login_body = client.get("/login").text
    new_body = client.get("/new").text

    assert 'data-testid="reminder-degraded-banner"' not in login_body
    assert 'data-testid="reminder-degraded-banner"' not in new_body


# --- reminder health origin (fault-injection lever) --------------------------


def test_reminder_health_url_defaults_to_api_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REMINDER_HEALTH_BASE_URL", raising=False)
    assert reminder_health_url(API) == f"{API}/api/reminders/health"

    monkeypatch.setenv("REMINDER_HEALTH_BASE_URL", "")
    assert reminder_health_url(API) == f"{API}/api/reminders/health"


def test_reminder_health_url_honours_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMINDER_HEALTH_BASE_URL", "http://lever:8667/")
    assert reminder_health_url(API) == "http://lever:8667/api/reminders/health"


@respx.mock
def test_health_call_uses_override_origin_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMINDER_HEALTH_BASE_URL", "http://lever:8667")
    with TestClient(create_app()) as client:
        login(client)
        me = respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
        tasks = respx.get(f"{API}/api/tasks").mock(
            return_value=httpx.Response(200, json=page_body(SEEDED))
        )
        base_health = respx.get(f"{API}/api/reminders/health").mock(
            return_value=httpx.Response(200, json={"state": "healthy"})
        )
        lever_health = respx.get("http://lever:8667/api/reminders/health").mock(
            return_value=httpx.Response(200, json={"state": "degraded"})
        )

        resp = client.get("/")

        assert resp.status_code == 200
        assert 'data-testid="reminder-degraded-banner"' in resp.text
        assert lever_health.called
        assert base_health.call_count == 0
        assert me.called
        assert tasks.called


@respx.mock
@pytest.mark.parametrize(
    "fault", [httpx.ConnectError("refused"), httpx.ReadTimeout("stalled")], ids=["fail", "timeout"]
)
def test_board_renders_without_banner_when_health_origin_faults(
    monkeypatch: pytest.MonkeyPatch, fault: Exception
) -> None:
    monkeypatch.setenv("REMINDER_HEALTH_BASE_URL", "http://lever:8667")
    with TestClient(create_app()) as client:
        login(client)
        respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
        respx.get(f"{API}/api/tasks").mock(return_value=httpx.Response(200, json=page_body(SEEDED)))
        respx.get("http://lever:8667/api/reminders/health").mock(side_effect=fault)

        resp = client.get("/")

        assert resp.status_code == 200
        assert resp.text.count('data-testid="task-row"') == 3
        assert 'data-testid="reminder-degraded-banner"' not in resp.text


# --- board status filter -----------------------------------------------------


@respx.mock
def test_index_unfiltered_renders_all_three_columns(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/").text

    assert body.count('data-testid="task-row"') == 3
    for status in ("todo", "doing", "done"):
        assert f'id="column-{status}"' in body


@respx.mock
def test_index_filtered_renders_only_that_column(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/?status=doing").text

    assert body.count('data-testid="task-row"') == 1
    assert "Build the API" in body
    assert "Write the spec" not in body
    assert "Ship it" not in body
    assert 'id="column-todo"' not in body
    assert 'id="column-done"' not in body


@respx.mock
def test_index_filtered_marks_active_filter_link(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/?status=doing").text

    assert body.count('aria-current="page"') == 1
    start = body.index('data-testid="filter-doing"')
    end = body.index(">", start)
    assert 'aria-current="page"' in body[start:end]


@respx.mock
def test_index_unknown_status_renders_full_board_200(client: TestClient) -> None:
    login(client)
    mock_board()

    resp = client.get("/?status=archived")

    assert resp.status_code == 200
    body = resp.text
    assert body.count('data-testid="task-row"') == 3
    start = body.index('data-testid="filter-all"')
    end = body.index(">", start)
    assert 'aria-current="page"' in body[start:end]


@respx.mock
def test_index_empty_status_param_renders_full_board(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/?status=").text

    assert body.count('data-testid="task-row"') == 3


@respx.mock
def test_index_task_count_stays_total_when_filtered(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/?status=done").text

    assert 'data-testid="task-count">3<' in body


@respx.mock
def test_index_filter_control_always_present(client: TestClient) -> None:
    login(client)
    mock_board()

    for url in ("/", "/?status=todo"):
        body = client.get(url).text
        assert 'data-testid="status-filter"' in body
        for testid in ("filter-all", "filter-todo", "filter-doing", "filter-done"):
            assert f'data-testid="{testid}"' in body


@respx.mock
def test_index_api_error_still_renders_filter_control(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{API}/api/tasks").mock(side_effect=httpx.ConnectError("refused"))

    resp = client.get("/?status=todo")

    assert resp.status_code == 200
    assert 'data-testid="api-error"' in resp.text
    assert 'data-testid="status-filter"' in resp.text
    assert 'data-testid="task-row"' not in resp.text


@respx.mock
def test_index_row_forms_carry_active_filter(client: TestClient) -> None:
    login(client)
    mock_board()

    filtered = client.get("/?status=todo").text
    assert 'name="status" value="todo"' in filtered

    unfiltered = client.get("/").text
    assert 'name="status" value="">' in unfiltered


@respx.mock
def test_advance_redirects_back_to_filtered_board(client: TestClient) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=SEEDED[0]))
    patch = respx.patch(f"{API}/api/tasks/1").mock(
        return_value=httpx.Response(200, json={**SEEDED[0], "status": "doing"})
    )

    resp = client.post(
        "/tasks/1/advance",
        data={"csrf_token": csrf, "status": "todo"},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/?status=todo"
    assert patch.calls.last.request.headers["Authorization"] == AUTH


@respx.mock
def test_advance_without_filter_redirects_to_board(client: TestClient) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=SEEDED[0]))
    respx.patch(f"{API}/api/tasks/1").mock(
        return_value=httpx.Response(200, json={**SEEDED[0], "status": "doing"})
    )

    resp = client.post("/tasks/1/advance", data={"csrf_token": csrf}, follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


@respx.mock
def test_advance_ignores_unknown_filter_value(client: TestClient) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=SEEDED[0]))
    respx.patch(f"{API}/api/tasks/1").mock(
        return_value=httpx.Response(200, json={**SEEDED[0], "status": "doing"})
    )

    resp = client.post(
        "/tasks/1/advance",
        data={"csrf_token": csrf, "status": "bogus"},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


@respx.mock
def test_delete_redirects_back_to_filtered_board(client: TestClient) -> None:
    csrf = login(client)
    respx.delete(f"{API}/api/tasks/2").mock(return_value=httpx.Response(204))

    resp = client.post(
        "/tasks/2/delete",
        data={"csrf_token": csrf, "status": "done"},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/?status=done"


@respx.mock
def test_delete_without_filter_redirects_to_board(client: TestClient) -> None:
    csrf = login(client)
    respx.delete(f"{API}/api/tasks/2").mock(return_value=httpx.Response(204))

    resp = client.post("/tasks/2/delete", data={"csrf_token": csrf}, follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


# --- empty state --------------------------------------------------------------


@respx.mock
def test_board_with_zero_tasks_renders_empty_board_message(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body([], total=0))
    )
    mock_health()

    body = client.get("/").text

    assert 'data-testid="empty-board"' in body
    assert "No tasks yet." in body
    start = body.index('data-testid="empty-board-new-link"')
    tag_start = body.rindex("<a", 0, start)
    tag_end = body.index(">", start)
    assert 'href="/new"' in body[tag_start:tag_end]
    assert "Add your first task" in body
    assert 'data-testid="empty-filter"' not in body


@respx.mock
def test_board_with_tasks_renders_no_empty_message(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/").text

    assert 'data-testid="empty-board"' not in body
    assert 'data-testid="empty-filter"' not in body


@respx.mock
def test_filtered_board_with_no_matches_renders_empty_filter_message(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{API}/api/tasks").mock(
        side_effect=[
            httpx.Response(200, json=page_body([], total=0)),
            httpx.Response(200, json=page_body(SEEDED, total=3)),
        ]
    )
    mock_health()

    body = client.get("/?status=done").text

    assert 'data-testid="empty-filter"' in body
    assert "Nothing in done right now." in body
    assert 'data-testid="empty-board"' not in body
    assert 'data-testid="task-count">3<' in body


@respx.mock
def test_zero_task_filtered_board_shows_only_empty_filter(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body([], total=0))
    )
    mock_health()

    body = client.get("/?status=todo").text

    assert body.count('data-testid="empty-') == 1
    assert 'data-testid="empty-filter"' in body
    assert 'data-testid="empty-board"' not in body


@respx.mock
def test_filtered_board_with_matches_renders_no_empty_message(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/?status=todo").text

    assert 'data-testid="empty-board"' not in body
    assert 'data-testid="empty-filter"' not in body


@pytest.mark.parametrize("url", ["/", "/?status=done"])
@respx.mock
def test_api_error_suppresses_empty_messages(client: TestClient, url: str) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{API}/api/tasks").mock(side_effect=httpx.ConnectError("refused"))

    body = client.get(url).text

    assert 'data-testid="api-error"' in body
    assert 'data-testid="empty-board"' not in body
    assert 'data-testid="empty-filter"' not in body


@respx.mock
def test_empty_state_renders_after_degraded_banner_and_filter_nav(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body([], total=0))
    )
    mock_health(return_value=httpx.Response(200, json={"state": "degraded"}))

    body = client.get("/").text

    banner_index = body.index('data-testid="reminder-degraded-banner"')
    filter_index = body.index('data-testid="status-filter"')
    empty_index = body.index('data-testid="empty-board"')
    assert banner_index < filter_index < empty_index


@respx.mock
def test_empty_state_markup_adds_no_roles_or_landmarks(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body([], total=0))
    )
    mock_health()

    for url in ("/", "/?status=todo"):
        body = client.get(url).text
        assert body.count("<header") == 1
        assert body.count("<main") == 1
        testid = "empty-board" if url == "/" else "empty-filter"
        start = body.index(f'data-testid="{testid}"')
        tag_start = body.rindex("<p", 0, start)
        tag_end = body.index(">", start)
        tag = body[tag_start:tag_end]
        assert "role=" not in tag
        assert "tabindex" not in tag
        assert "autofocus" not in tag


@respx.mock
def test_empty_filter_message_renders_once_inside_the_filtered_column(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body([], total=0))
    )
    mock_health()

    body = client.get("/?status=doing").text

    assert body.count('data-testid="empty-filter"') == 1
    column_index = body.index('id="column-doing"')
    empty_index = body.index('data-testid="empty-filter"')
    assert column_index < empty_index


@respx.mock
def test_unknown_status_with_zero_tasks_shows_empty_board_message(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body([], total=0))
    )
    mock_health()

    body = client.get("/?status=archived").text

    assert 'data-testid="empty-board"' in body
    assert 'data-testid="empty-filter"' not in body


# --- board pagination --------------------------------------------------------


def make_tasks(n: int, status: str = "todo") -> list[dict]:
    return [
        {
            "id": i,
            "title": f"Task {i}",
            "description": "",
            "status": status,
            "due_at": None,
            "reminder_status": "none",
            "created_at": "2026-01-01T00:00:00Z",
        }
        for i in range(1, n + 1)
    ]


@respx.mock
def test_board_requests_page_with_limit_and_offset(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    tasks_route = respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body(make_tasks(20), total=25))
    )
    mock_health()

    client.get("/?page=2")

    params = tasks_route.calls.last.request.url.params
    assert params["limit"] == "20"
    assert params["offset"] == "20"


@respx.mock
def test_board_passes_status_filter_to_api(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    tasks_route = respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body(make_tasks(3, "todo")))
    )
    mock_health()

    client.get("/?status=todo")

    assert tasks_route.calls[0].request.url.params["status"] == "todo"


@respx.mock
def test_pager_absent_on_single_page(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/").text

    assert 'data-testid="pager"' not in body


@respx.mock
def test_pager_next_only_on_first_page(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body(make_tasks(20), total=25))
    )
    mock_health()

    body = client.get("/").text

    assert 'data-testid="pager"' in body
    assert 'data-testid="pager-next"' in body
    assert 'data-testid="pager-prev"' not in body


@respx.mock
def test_pager_prev_only_on_last_page(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body(make_tasks(5), total=25))
    )
    mock_health()

    body = client.get("/?page=2").text

    assert 'data-testid="pager"' in body
    assert 'data-testid="pager-prev"' in body
    assert 'data-testid="pager-next"' not in body


@respx.mock
def test_pager_links_preserve_status_filter(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body(make_tasks(20, "todo"), total=25))
    )
    mock_health()

    body = client.get("/?status=todo").text

    assert 'href="/?status=todo&amp;page=2"' in body


@respx.mock
def test_pager_status_text(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body(make_tasks(20), total=25))
    )
    mock_health()

    body = client.get("/").text

    assert 'data-testid="pager-status">Page 1 of 2<' in body


@respx.mock
def test_task_count_is_grand_total_when_filtered(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    tasks_route = respx.get(f"{API}/api/tasks").mock(
        side_effect=[
            httpx.Response(200, json=page_body(make_tasks(5, "todo"), total=5)),
            httpx.Response(200, json=page_body(make_tasks(1), total=30)),
        ]
    )
    mock_health()

    body = client.get("/?status=todo").text

    assert 'data-testid="task-count">30<' in body
    assert tasks_route.call_count == 2


@pytest.mark.parametrize("value", ["", "abc", "0", "-1", "9.5"])
@respx.mock
def test_invalid_page_param_falls_back_to_first_page(client: TestClient, value: str) -> None:
    login(client)
    mock_board()

    resp = client.get(f"/?page={value}")

    assert resp.status_code == 200
    assert 'data-testid="pager"' not in resp.text


@respx.mock
def test_out_of_range_page_refetches_first_page(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    tasks_route = respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body(SEEDED, total=len(SEEDED)))
    )
    mock_health()

    resp = client.get("/?page=5")

    assert resp.status_code == 200
    assert 'data-testid="pager"' not in resp.text
    assert tasks_route.call_count == 2


@respx.mock
def test_advance_redirects_to_same_page_and_filter(client: TestClient) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=SEEDED[0]))
    respx.patch(f"{API}/api/tasks/1").mock(
        return_value=httpx.Response(200, json={**SEEDED[0], "status": "doing"})
    )

    resp = client.post(
        "/tasks/1/advance",
        data={"csrf_token": csrf, "status": "todo", "page": "2"},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/?status=todo&page=2"


@respx.mock
def test_delete_redirects_to_same_page_and_filter(client: TestClient) -> None:
    csrf = login(client)
    respx.delete(f"{API}/api/tasks/2").mock(return_value=httpx.Response(204))

    resp = client.post(
        "/tasks/2/delete",
        data={"csrf_token": csrf, "status": "todo", "page": "2"},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/?status=todo&page=2"


@respx.mock
def test_page_fetch_error_still_renders_api_error_banner(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{API}/api/tasks").mock(side_effect=httpx.ConnectError("refused"))

    resp = client.get("/?page=2")

    assert resp.status_code == 200
    assert 'data-testid="api-error"' in resp.text
    assert 'data-testid="pager"' not in resp.text


# --- board urgency ordering (issue #52) --------------------------------------


@respx.mock
def test_board_requests_a_single_page_of_board_page_size(client: TestClient) -> None:
    # AC-9: a user with hundreds of tasks still costs the web layer one page.
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    tasks_route = respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body(make_tasks(20), total=500))
    )
    mock_health()

    client.get("/")

    assert tasks_route.call_count == 1
    params = tasks_route.calls.last.request.url.params
    assert params["limit"] == str(BOARD_PAGE_SIZE)
    assert params["offset"] == "0"


@respx.mock
def test_board_requests_a_single_page_and_one_count_call_when_filtered(
    client: TestClient,
) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    tasks_route = respx.get(f"{API}/api/tasks").mock(
        side_effect=[
            httpx.Response(200, json=page_body(make_tasks(20, "todo"), total=500)),
            httpx.Response(200, json=page_body(make_tasks(1), total=800)),
        ]
    )
    mock_health()

    client.get("/?status=todo")

    assert tasks_route.call_count == 2
    for call in tasks_route.calls:
        assert int(call.request.url.params["limit"]) <= BOARD_PAGE_SIZE
    page_call, count_call = tasks_route.calls[0], tasks_route.calls[1]
    assert page_call.request.url.params["limit"] == str(BOARD_PAGE_SIZE)
    assert count_call.request.url.params["limit"] == "1"


@respx.mock
def test_board_preserves_server_order_within_columns(client: TestClient) -> None:
    # decorate_tasks re-sorts on the same (due_at, id) key the server already
    # ordered by, so a page already in urgency order must render unchanged.
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    tasks = [
        {**SEEDED[0], "id": 5, "title": "Most urgent", "status": "todo", "due_at": iso_in(60)},
        {**SEEDED[0], "id": 9, "title": "Less urgent", "status": "todo", "due_at": iso_in(3600)},
        {**SEEDED[0], "id": 7, "title": "Least urgent", "status": "todo", "due_at": None},
    ]
    respx.get(f"{API}/api/tasks").mock(return_value=httpx.Response(200, json=page_body(tasks)))
    mock_health()

    body = client.get("/").text

    assert body.index(">Most urgent<") < body.index(">Less urgent<") < body.index(">Least urgent<")


# --- new task --------------------------------------------------------------


@respx.mock
def test_new_form_renders(client: TestClient) -> None:
    login(client)

    resp = client.get("/new")

    assert resp.status_code == 200
    for testid in ("title-input", "description-input", "due-at-input", "submit-task"):
        assert f'data-testid="{testid}"' in resp.text


@respx.mock
def test_new_form_zone_hint_uses_cookie_zone(client: TestClient) -> None:
    login(client)
    client.cookies.set("tz", "Europe/Berlin")

    resp = client.get("/new")

    assert resp.status_code == 200
    assert 'data-testid="due-at-zone"' in resp.text
    assert "Times are in Europe/Berlin." in resp.text
    assert 'aria-describedby="due-at-zone"' in resp.text


@respx.mock
def test_new_form_zone_hint_defaults_to_utc_without_cookie(client: TestClient) -> None:
    login(client)

    resp = client.get("/new")

    assert resp.status_code == 200
    assert "Times are in UTC." in resp.text


@respx.mock
def test_new_task_posts_to_api_and_redirects(client: TestClient) -> None:
    csrf = login(client)
    created = {**SEEDED[0], "id": 4, "title": "New one", "description": "details"}
    route = respx.post(f"{API}/api/tasks").mock(return_value=httpx.Response(201, json=created))

    resp = client.post(
        "/new",
        data={"title": "New one", "description": "details", "csrf_token": csrf},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert route.called
    assert route.calls.last.request.headers["Authorization"] == AUTH
    assert json.loads(route.calls.last.request.content) == {
        "title": "New one",
        "description": "details",
    }


@respx.mock
def test_new_task_due_at_converted_to_rfc3339_z(client: TestClient) -> None:
    csrf = login(client)
    created = {**SEEDED[1], "id": 5, "title": "Due one"}
    route = respx.post(f"{API}/api/tasks").mock(return_value=httpx.Response(201, json=created))

    resp = client.post(
        "/new",
        data={"title": "Due one", "due_at": "2026-03-01T12:30", "csrf_token": csrf},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert json.loads(route.calls.last.request.content) == {
        "title": "Due one",
        "description": "",
        "due_at": "2026-03-01T12:30:00Z",
    }


@respx.mock
def test_create_task_converts_due_at_using_cookie_zone(client: TestClient) -> None:
    csrf = login(client)
    client.cookies.set("tz", "Europe/Berlin")
    created = {**SEEDED[1], "id": 5, "title": "Due one"}
    route = respx.post(f"{API}/api/tasks").mock(return_value=httpx.Response(201, json=created))

    resp = client.post(
        "/new",
        data={"title": "Due one", "due_at": "2026-08-25T17:00", "csrf_token": csrf},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert json.loads(route.calls.last.request.content)["due_at"] == "2026-08-25T15:00:00Z"


@respx.mock
def test_create_task_error_rerender_preserves_due_value_and_disables_tz_sync(
    client: TestClient,
) -> None:
    csrf = login(client)
    client.cookies.set("tz", "Europe/Berlin")
    respx.post(f"{API}/api/tasks").mock(
        return_value=httpx.Response(
            422,
            json={"detail": [{"loc": ["body", "title"], "type": "value_error"}]},
        )
    )

    resp = client.post(
        "/new",
        data={
            "title": " ",
            "due_at": "2026-08-25T17:00",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert 'data-tz="Europe/Berlin"' in resp.text
    assert 'data-tz-sync="1"' not in resp.text
    assert "2026-08-25T17:00" in resp.text


@respx.mock
def test_new_task_blank_title_shows_validation_banner_and_keeps_values(
    client: TestClient,
) -> None:
    csrf = login(client)
    respx.post(f"{API}/api/tasks").mock(
        return_value=httpx.Response(
            422,
            json={"detail": [{"loc": ["body", "title"], "type": "value_error"}]},
        )
    )

    resp = client.post(
        "/new",
        data={
            "title": " ",
            "description": "should survive",
            "due_at": "2026-03-01T12:30",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert 'data-testid="api-error"' in resp.text
    assert "Title must contain at least one non-whitespace character." in resp.text
    assert "should survive" in resp.text
    assert "2026-03-01T12:30" in resp.text


@respx.mock
def test_new_task_other_422_shows_generic_message(client: TestClient) -> None:
    csrf = login(client)
    respx.post(f"{API}/api/tasks").mock(
        return_value=httpx.Response(
            422,
            json={"detail": [{"loc": ["body", "due_at"], "type": "value_error"}]},
        )
    )

    resp = client.post(
        "/new", data={"title": "New one", "csrf_token": csrf}, follow_redirects=False
    )

    assert resp.status_code == 200
    assert 'data-testid="api-error"' in resp.text
    assert "Please check the task details and try again." in resp.text
    assert "Title must contain at least one non-whitespace character." not in resp.text


@respx.mock
def test_new_task_422_with_unparseable_body_still_shows_banner(client: TestClient) -> None:
    csrf = login(client)
    respx.post(f"{API}/api/tasks").mock(return_value=httpx.Response(422, text="not json"))

    resp = client.post(
        "/new", data={"title": "New one", "csrf_token": csrf}, follow_redirects=False
    )

    assert resp.status_code == 200
    assert 'data-testid="api-error"' in resp.text


@respx.mock
def test_new_task_csrf_mismatch_is_403(client: TestClient) -> None:
    login(client)
    route = respx.post(f"{API}/api/tasks").mock(return_value=httpx.Response(201, json=SEEDED[0]))

    resp = client.post("/new", data={"title": "x", "csrf_token": "wrong"}, follow_redirects=False)

    assert resp.status_code == 403
    assert not route.called


@respx.mock
def test_new_task_api_down_renders_error_banner(client: TestClient) -> None:
    csrf = login(client)
    respx.post(f"{API}/api/tasks").mock(side_effect=httpx.ConnectError("refused"))

    resp = client.post(
        "/new", data={"title": "New one", "csrf_token": csrf}, follow_redirects=False
    )

    assert resp.status_code == 200
    assert 'data-testid="api-error"' in resp.text
    assert "The task API is unavailable. Please try again shortly." in resp.text


@respx.mock
def test_new_task_api_401_redirects_to_login_next_new_and_stashes_draft(
    client: TestClient,
) -> None:
    csrf = login(client)
    respx.post(f"{API}/api/tasks").mock(return_value=httpx.Response(401))

    resp = client.post(
        "/new",
        data={
            "title": "New one",
            "description": "some notes",
            "due_at": "2026-03-01T12:30",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=/new"

    body = client.get("/login").text
    assert 'data-testid="session-expired"' in body

    login(client)
    new_body = client.get("/new").text
    assert 'value="New one"' in new_body
    assert "some notes" in new_body
    assert 'value="2026-03-01T12:30"' in new_body


# --- session expiry: login notice & draft restore ---------------------------


def test_session_expired_notice_absent_on_direct_login_page_and_unauthed_redirect(
    client: TestClient,
) -> None:
    body = client.get("/login").text
    assert 'data-testid="session-expired"' not in body

    resp = client.get("/new", follow_redirects=False)
    assert resp.status_code == 303
    login_body = client.get(resp.headers["location"]).text
    assert 'data-testid="session-expired"' not in login_body


@respx.mock
def test_session_expired_notice_absent_after_logout(client: TestClient) -> None:
    csrf = login(client)

    respx.post(f"{API}/api/auth/logout").mock(return_value=httpx.Response(204))
    resp = client.post("/logout", data={"csrf_token": csrf}, follow_redirects=False)

    assert resp.status_code == 303
    body = client.get(resp.headers["location"]).text
    assert 'data-testid="session-expired"' not in body


@respx.mock
def test_relogin_after_expiry_redirects_to_new_and_prefills_draft(client: TestClient) -> None:
    csrf = login(client)
    client.cookies.set("tz", "Europe/Berlin")
    respx.post(f"{API}/api/tasks").mock(return_value=httpx.Response(401))
    client.post(
        "/new",
        data={
            "title": "Non-ASCII tïtle",
            "description": "some notes\nmore",
            "due_at": "2026-08-25T17:00",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )

    resp = client.post(
        "/login",
        data={
            "email": "alice@example.com",
            "password": "pw",
            "csrf_token": extract_csrf(client.get("/login").text),
            "next": "/new",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/new"
    body = client.get(resp.headers["location"]).text
    assert 'value="Non-ASCII tïtle"' in body
    assert "some notes\nmore" in body
    assert 'value="2026-08-25T17:00"' in body
    assert "Times are in Europe/Berlin." in body


@respx.mock
def test_restored_draft_submit_sends_original_values_and_clears_stash(client: TestClient) -> None:
    csrf = login(client)
    respx.post(f"{API}/api/tasks").mock(return_value=httpx.Response(401))
    client.post(
        "/new",
        data={
            "title": "Restore me",
            "description": "details",
            "due_at": "2026-03-01T12:30",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    login(client)
    new_csrf = extract_csrf(client.get("/new").text)

    route = respx.post(f"{API}/api/tasks").mock(
        return_value=httpx.Response(201, json={**SEEDED[0], "id": 9, "title": "Restore me"})
    )
    resp = client.post(
        "/new",
        data={
            "title": "Restore me",
            "description": "details",
            "due_at": "2026-03-01T12:30",
            "csrf_token": new_csrf,
        },
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert json.loads(route.calls.last.request.content) == {
        "title": "Restore me",
        "description": "details",
        "due_at": "2026-03-01T12:30:00Z",
    }
    empty_body = client.get("/new").text
    assert 'value="Restore me"' not in empty_body
    assert "details" not in empty_body


@respx.mock
def test_wrong_password_keeps_draft_and_shows_both_banners(client: TestClient) -> None:
    csrf = login(client)
    respx.post(f"{API}/api/tasks").mock(return_value=httpx.Response(401))
    client.post("/new", data={"title": "Keep me", "csrf_token": csrf}, follow_redirects=False)

    respx.post(f"{API}/api/auth/login").mock(
        return_value=httpx.Response(401, json={"detail": "invalid credentials"})
    )
    wrong_csrf = extract_csrf(client.get("/login").text)
    resp = client.post(
        "/login",
        data={"email": "alice@example.com", "password": "nope", "csrf_token": wrong_csrf},
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert 'data-testid="login-error"' in resp.text
    assert 'data-testid="session-expired"' in resp.text

    login(client)
    body = client.get("/new").text
    assert 'value="Keep me"' in body


@respx.mock
def test_draft_dropped_when_a_different_user_logs_in(client: TestClient) -> None:
    csrf = login(client)
    respx.post(f"{API}/api/tasks").mock(return_value=httpx.Response(401))
    client.post(
        "/new",
        data={"title": "Alice's secret plan", "csrf_token": csrf},
        follow_redirects=False,
    )

    respx.post(f"{API}/api/auth/login").mock(
        return_value=httpx.Response(
            200, json={"token": "tok-bob-0001", "expires_at": "2026-01-01T01:00:00Z"}
        )
    )
    bob_csrf = extract_csrf(client.get("/login").text)
    resp = client.post(
        "/login",
        data={"email": "bob@example.com", "password": "pw", "csrf_token": bob_csrf},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    body = client.get("/new").text
    assert "Alice's secret plan" not in body
    assert 'value="Alice' not in body


@respx.mock
def test_post_new_clears_a_stale_stashed_draft(client: TestClient) -> None:
    csrf = login(client)
    respx.post(f"{API}/api/tasks").mock(return_value=httpx.Response(401))
    client.post("/new", data={"title": "Stale draft", "csrf_token": csrf}, follow_redirects=False)
    login(client)

    new_csrf = extract_csrf(client.get("/new").text)
    respx.post(f"{API}/api/tasks").mock(
        return_value=httpx.Response(201, json={**SEEDED[0], "id": 10, "title": "Fresh submit"})
    )
    resp = client.post(
        "/new",
        data={"title": "Fresh submit", "csrf_token": new_csrf},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    body = client.get("/new").text
    assert "Stale draft" not in body


@respx.mock
def test_oversized_draft_is_not_stashed_and_session_stays_usable(client: TestClient) -> None:
    csrf = login(client)
    respx.post(f"{API}/api/tasks").mock(return_value=httpx.Response(401))

    resp = client.post(
        "/new",
        data={"title": "x" * (DRAFT_MAX_BYTES + 500), "csrf_token": csrf},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=/new"
    login_body = client.get("/login").text
    assert 'data-testid="session-expired"' in login_body

    login(client)
    body = client.get("/new").text
    assert "x" * (DRAFT_MAX_BYTES + 500) not in body


@respx.mock
def test_session_expired_notice_markup_carries_no_role_tabindex_or_landmark(
    client: TestClient,
) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(401))
    client.get("/", follow_redirects=False)

    body = client.get("/login").text

    assert 'data-testid="session-expired"' in body
    start = body.index('data-testid="session-expired"')
    tag_start = body.rindex("<div", 0, start)
    tag_end = body.index(">", start)
    tag = body[tag_start:tag_end]
    assert "role=" not in tag
    assert "tabindex" not in tag
    assert "autofocus" not in tag


@respx.mock
def test_restored_draft_values_are_html_escaped(client: TestClient) -> None:
    csrf = login(client)
    respx.post(f"{API}/api/tasks").mock(return_value=httpx.Response(401))
    client.post(
        "/new",
        data={"title": '<script>"boom"</script>', "csrf_token": csrf},
        follow_redirects=False,
    )
    login(client)

    body = client.get("/new").text

    assert '<script>"boom"</script>' not in body
    assert "&lt;script&gt;" in body


@respx.mock
def test_new_task_error_rerender_paths_leave_no_stashed_draft(client: TestClient) -> None:
    csrf = login(client)
    respx.post(f"{API}/api/tasks").mock(
        return_value=httpx.Response(
            422,
            json={"detail": [{"loc": ["body", "title"], "type": "value_error"}]},
        )
    )
    client.post(
        "/new",
        data={"title": " ", "description": "kept locally", "csrf_token": csrf},
        follow_redirects=False,
    )

    body = client.get("/new").text
    assert "kept locally" not in body


# --- edit task ---------------------------------------------------------------


def test_edit_url_builds_filtered_and_plain_urls() -> None:
    assert edit_url(5) == "/tasks/5/edit"
    assert edit_url(5, "doing") == "/tasks/5/edit?status=doing"
    assert edit_url(5, None, 1) == "/tasks/5/edit"
    assert edit_url(5, "todo", 1) == "/tasks/5/edit?status=todo"
    assert edit_url(5, None, 2) == "/tasks/5/edit?page=2"
    assert edit_url(5, "todo", 2) == "/tasks/5/edit?status=todo&page=2"


def test_edit_url_carries_search() -> None:
    assert edit_url(5, None, 1, "inv") == "/tasks/5/edit?q=inv"
    assert edit_url(5, "todo", 1, "inv") == "/tasks/5/edit?status=todo&q=inv"
    assert edit_url(5, "todo", 2, "inv") == "/tasks/5/edit?status=todo&q=inv&page=2"


def test_local_input_value_handles_undated_and_unparseable() -> None:
    assert local_input_value(None, UTC_ZONE) == ""
    assert local_input_value("", UTC_ZONE) == ""
    assert local_input_value("not-a-date", UTC_ZONE) == ""


def test_local_input_value_converts_to_viewer_zone() -> None:
    berlin = ZoneInfo("Europe/Berlin")
    assert local_input_value("2026-08-25T15:00:00Z", berlin) == "2026-08-25T17:00"
    assert local_input_value("2026-08-25T15:00:00Z", UTC_ZONE) == "2026-08-25T15:00"


def test_normalize_input_value_blank_and_roundtrip() -> None:
    berlin = ZoneInfo("Europe/Berlin")
    assert normalize_input_value("", berlin) == ""
    assert normalize_input_value("   ", berlin) == ""
    normalized = normalize_input_value("2026-08-25T17:00", berlin)
    assert normalized == "2026-08-25T17:00"
    # round-trips through local_input_value on the same instant
    as_wire = to_rfc3339_z(normalized, berlin)
    assert local_input_value(as_wire, berlin) == normalized


def test_normalize_input_value_raises_on_garbage() -> None:
    with pytest.raises(ValueError):
        normalize_input_value("not-a-date", UTC_ZONE)


@respx.mock
def test_edit_form_prefills_from_api(client: TestClient) -> None:
    login(client)
    task = {**SEEDED[1], "id": 2}
    respx.get(f"{API}/api/tasks/2").mock(return_value=httpx.Response(200, json=task))

    resp = client.get("/tasks/2/edit")

    assert resp.status_code == 200
    body = resp.text
    assert f'value="{task["title"]}"' in body
    assert task["description"] in body
    assert 'data-testid="submit-edit"' in body
    assert 'data-testid="edit-cancel"' in body
    assert 'data-tz-sync="1"' in body


@respx.mock
def test_edit_form_due_at_prefilled_in_viewer_zone(client: TestClient) -> None:
    login(client)
    client.cookies.set("tz", "Europe/Berlin")
    task = {**SEEDED[0], "id": 1, "due_at": "2026-08-25T15:00:00Z"}
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=task))

    body = client.get("/tasks/1/edit").text

    assert 'value="2026-08-25T17:00"' in body
    assert "Times are in Europe/Berlin." in body


@respx.mock
def test_edit_form_undated_task_has_empty_due_field(client: TestClient) -> None:
    login(client)
    task = {**SEEDED[0], "id": 1, "due_at": None}
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=task))

    body = client.get("/tasks/1/edit").text

    assert re.search(r'data-testid="due-at-input"[^>]*value="">', body)


@respx.mock
def test_edit_form_cancel_link_points_at_originating_board(client: TestClient) -> None:
    login(client)
    task = {**SEEDED[0], "id": 1}
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=task))

    body = client.get("/tasks/1/edit?status=doing&page=2").text

    start = body.index('data-testid="edit-cancel"')
    tag_start = body.rindex("<a", 0, start)
    tag_end = body.index(">", start)
    assert 'href="/?status=doing&amp;page=2"' in body[tag_start:tag_end]


@respx.mock
def test_edit_form_unknown_task_redirects_to_board_with_no_leak(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/tasks/999").mock(return_value=httpx.Response(404))

    resp = client.get("/tasks/999/edit", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


@respx.mock
def test_edit_form_api_down_shows_error_banner(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/tasks/1").mock(side_effect=httpx.ConnectError("refused"))

    resp = client.get("/tasks/1/edit")

    assert resp.status_code == 200
    assert 'data-testid="api-error"' in resp.text


@respx.mock
def test_edit_form_api_401_redirects_to_login_with_next(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(401))

    resp = client.get("/tasks/1/edit?status=todo", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=/tasks/1/edit%3Fstatus%3Dtodo"
    body = client.get("/login").text
    assert 'data-testid="session-expired"' in body


def test_unauthed_edit_redirects_to_login_with_next(client: TestClient) -> None:
    resp = client.get("/tasks/1/edit?status=todo", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=/tasks/1/edit%3Fstatus%3Dtodo"


@respx.mock
def test_edit_task_sends_title_and_description_without_due_at_when_untouched(
    client: TestClient,
) -> None:
    csrf = login(client)
    task = {**SEEDED[1], "id": 2}
    respx.get(f"{API}/api/tasks/2").mock(return_value=httpx.Response(200, json=task))
    patch = respx.patch(f"{API}/api/tasks/2").mock(
        return_value=httpx.Response(200, json={**task, "title": "Renamed"})
    )
    current_due = local_input_value(task["due_at"], UTC_ZONE)

    resp = client.post(
        "/tasks/2/edit",
        data={
            "title": "Renamed",
            "description": task["description"],
            "due_at": current_due,
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    sent = json.loads(patch.calls.last.request.content)
    assert sent == {"title": "Renamed", "description": task["description"]}
    assert "due_at" not in sent


@respx.mock
def test_edit_task_clearing_due_field_sends_explicit_null(client: TestClient) -> None:
    csrf = login(client)
    task = {**SEEDED[1], "id": 2}
    respx.get(f"{API}/api/tasks/2").mock(return_value=httpx.Response(200, json=task))
    patch = respx.patch(f"{API}/api/tasks/2").mock(
        return_value=httpx.Response(200, json={**task, "due_at": None})
    )

    resp = client.post(
        "/tasks/2/edit",
        data={
            "title": task["title"],
            "description": task["description"],
            "due_at": "",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )

    assert resp.status_code == 303
    sent = json.loads(patch.calls.last.request.content)
    assert sent["due_at"] is None


@respx.mock
def test_edit_task_new_due_date_converted_to_rfc3339_z(client: TestClient) -> None:
    csrf = login(client)
    client.cookies.set("tz", "Europe/Berlin")
    task = {**SEEDED[0], "id": 1, "due_at": None}
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=task))
    patch = respx.patch(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=task))

    resp = client.post(
        "/tasks/1/edit",
        data={
            "title": task["title"],
            "description": "",
            "due_at": "2026-08-25T17:00",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )

    assert resp.status_code == 303
    sent = json.loads(patch.calls.last.request.content)
    assert sent["due_at"] == "2026-08-25T15:00:00Z"


@respx.mock
def test_edit_task_never_sends_status(client: TestClient) -> None:
    csrf = login(client)
    task = {**SEEDED[0], "id": 1}
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=task))
    patch = respx.patch(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=task))

    client.post(
        "/tasks/1/edit",
        data={"title": task["title"], "description": "", "csrf_token": csrf},
        follow_redirects=False,
    )

    sent = json.loads(patch.calls.last.request.content)
    assert "status" not in sent


@respx.mock
def test_edit_task_redirects_to_originating_filtered_paged_board(client: TestClient) -> None:
    csrf = login(client)
    task = {**SEEDED[0], "id": 1}
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=task))
    respx.patch(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=task))

    resp = client.post(
        "/tasks/1/edit",
        data={
            "title": task["title"],
            "description": "",
            "status": "doing",
            "page": "2",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/?status=doing&page=2"


@respx.mock
def test_edit_task_past_due_date_shows_error_and_keeps_typed_values(client: TestClient) -> None:
    csrf = login(client)
    task = {**SEEDED[0], "id": 1, "due_at": None}
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=task))
    respx.patch(f"{API}/api/tasks/1").mock(
        return_value=httpx.Response(
            422, json={"detail": [{"loc": ["body", "due_at"], "type": "value_error"}]}
        )
    )

    resp = client.post(
        "/tasks/1/edit",
        data={
            "title": "Kept title",
            "description": "kept desc",
            "due_at": "2020-01-01T00:00",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert 'data-testid="api-error"' in resp.text
    assert "Please check the task details and try again." in resp.text
    assert 'value="Kept title"' in resp.text
    assert "kept desc" in resp.text
    assert 'value="2020-01-01T00:00"' in resp.text
    assert 'data-tz-sync="1"' not in resp.text


@respx.mock
def test_edit_task_whitespace_title_shows_title_error(client: TestClient) -> None:
    csrf = login(client)
    task = {**SEEDED[0], "id": 1}
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=task))
    respx.patch(f"{API}/api/tasks/1").mock(
        return_value=httpx.Response(
            422, json={"detail": [{"loc": ["body", "title"], "type": "value_error"}]}
        )
    )

    resp = client.post(
        "/tasks/1/edit",
        data={"title": " ", "description": "", "csrf_token": csrf},
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert "Title must contain at least one non-whitespace character." in resp.text


@respx.mock
def test_edit_task_overdue_untouched_due_date_saves_without_error(client: TestClient) -> None:
    csrf = login(client)
    task = {**SEEDED[0], "id": 1, "due_at": "2020-01-01T00:00:00Z"}
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=task))
    patch = respx.patch(f"{API}/api/tasks/1").mock(
        return_value=httpx.Response(200, json={**task, "title": "Still overdue"})
    )

    resp = client.post(
        "/tasks/1/edit",
        data={
            "title": "Still overdue",
            "description": "",
            "due_at": local_input_value(task["due_at"], UTC_ZONE),
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )

    assert resp.status_code == 303
    sent = json.loads(patch.calls.last.request.content)
    assert "due_at" not in sent


@respx.mock
def test_edit_task_unparseable_due_input_shows_error_and_issues_no_patch(
    client: TestClient,
) -> None:
    csrf = login(client)
    task = {**SEEDED[0], "id": 1}
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=task))
    patch = respx.patch(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=task))

    resp = client.post(
        "/tasks/1/edit",
        data={"title": "x", "description": "", "due_at": "garbage", "csrf_token": csrf},
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert 'data-testid="api-error"' in resp.text
    assert not patch.called


@respx.mock
def test_edit_task_api_down_on_write_shows_error_banner(client: TestClient) -> None:
    csrf = login(client)
    task = {**SEEDED[0], "id": 1}
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=task))
    respx.patch(f"{API}/api/tasks/1").mock(side_effect=httpx.ConnectError("refused"))

    resp = client.post(
        "/tasks/1/edit",
        data={"title": "x", "description": "", "csrf_token": csrf},
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert 'data-testid="api-error"' in resp.text
    assert "The task API is unavailable. Please try again shortly." in resp.text


@respx.mock
def test_edit_task_csrf_mismatch_is_403_and_makes_no_api_call(client: TestClient) -> None:
    login(client)
    get_route = respx.get(f"{API}/api/tasks/1").mock(
        return_value=httpx.Response(200, json=SEEDED[0])
    )
    patch_route = respx.patch(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200))

    resp = client.post(
        "/tasks/1/edit",
        data={"title": "x", "csrf_token": "wrong"},
        follow_redirects=False,
    )

    assert resp.status_code == 403
    assert not get_route.called
    assert not patch_route.called


@respx.mock
def test_edit_task_read_404_redirects_and_issues_no_patch(client: TestClient) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(404))
    patch = respx.patch(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200))

    resp = client.post(
        "/tasks/1/edit",
        data={"title": "x", "status": "done", "csrf_token": csrf},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/?status=done"
    assert not patch.called


@respx.mock
def test_edit_task_api_401_on_read_redirects_to_login(client: TestClient) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(401))

    resp = client.post(
        "/tasks/1/edit",
        data={"title": "x", "csrf_token": csrf},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=/tasks/1/edit"
    body = client.get("/login").text
    assert 'data-testid="session-expired"' in body


@respx.mock
def test_edit_task_api_401_on_write_redirects_to_login(client: TestClient) -> None:
    csrf = login(client)
    task = {**SEEDED[0], "id": 1}
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=task))
    respx.patch(f"{API}/api/tasks/1").mock(return_value=httpx.Response(401))

    resp = client.post(
        "/tasks/1/edit",
        data={"title": "x", "csrf_token": csrf},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=/tasks/1/edit"


@respx.mock
def test_board_rows_carry_edit_link_preserving_filter_and_page(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/?status=todo&page=1").text

    assert body.count('data-testid="edit-link"') >= 1
    start = body.index('data-testid="edit-link"')
    tag_start = body.rindex("<a", 0, start)
    tag_end = body.index(">", start)
    assert 'href="/tasks/1/edit?status=todo"' in body[tag_start:tag_end]


@respx.mock
def test_board_row_actions_keep_existing_order_after_edit_link(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/").text

    row_start = body.index('data-testid="task-row"')
    row_end = body.index('data-testid="task-row"', row_start + 1)
    row = body[row_start:row_end]
    assert row.index('data-testid="edit-link"') < row.index('data-testid="move-back-btn"')
    assert row.index('data-testid="move-back-btn"') < row.index('data-testid="advance-btn"')
    assert row.index('data-testid="advance-btn"') < row.index('data-testid="delete-btn"')


# --- advance / delete ------------------------------------------------------


@respx.mock
def test_advance_patches_next_status_and_redirects(client: TestClient) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=SEEDED[0]))
    patch = respx.patch(f"{API}/api/tasks/1").mock(
        return_value=httpx.Response(200, json={**SEEDED[0], "status": "doing"})
    )

    resp = client.post("/tasks/1/advance", data={"csrf_token": csrf}, follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert patch.calls.last.request.headers["Authorization"] == AUTH
    assert json.loads(patch.calls.last.request.content) == {"status": "doing"}


@respx.mock
def test_advance_done_task_stays_done(client: TestClient) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/3").mock(return_value=httpx.Response(200, json=SEEDED[2]))
    patch = respx.patch(f"{API}/api/tasks/3").mock(return_value=httpx.Response(200, json=SEEDED[2]))

    resp = client.post("/tasks/3/advance", data={"csrf_token": csrf}, follow_redirects=False)

    assert resp.status_code == 303
    assert not patch.called


@respx.mock
def test_advance_csrf_mismatch_is_403(client: TestClient) -> None:
    login(client)

    resp = client.post("/tasks/1/advance", data={"csrf_token": "wrong"}, follow_redirects=False)

    assert resp.status_code == 403


@respx.mock
def test_delete_proxies_with_bearer_and_redirects(client: TestClient) -> None:
    csrf = login(client)
    route = respx.delete(f"{API}/api/tasks/2").mock(return_value=httpx.Response(204))

    resp = client.post("/tasks/2/delete", data={"csrf_token": csrf}, follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert route.called
    assert route.calls.last.request.headers["Authorization"] == AUTH


@respx.mock
def test_delete_csrf_mismatch_is_403(client: TestClient) -> None:
    login(client)
    route = respx.delete(f"{API}/api/tasks/2").mock(return_value=httpx.Response(204))

    resp = client.post("/tasks/2/delete", data={"csrf_token": "wrong"}, follow_redirects=False)

    assert resp.status_code == 403
    assert not route.called


# --- move-back ---------------------------------------------------------------


def test_prev_status_map_is_one_column_back() -> None:
    assert PREV_STATUS == {"done": "doing", "doing": "todo", "todo": "todo"}


@respx.mock
@pytest.mark.parametrize(
    "task_id,before,after",
    [(3, SEEDED[2], "doing"), (2, SEEDED[1], "todo")],
    ids=["done-to-doing", "doing-to-todo"],
)
def test_move_back_patches_previous_status_and_redirects(
    client: TestClient, task_id: int, before: dict, after: str
) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/{task_id}").mock(return_value=httpx.Response(200, json=before))
    patch = respx.patch(f"{API}/api/tasks/{task_id}").mock(
        return_value=httpx.Response(200, json={**before, "status": after})
    )

    resp = client.post(
        f"/tasks/{task_id}/move-back", data={"csrf_token": csrf}, follow_redirects=False
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert patch.calls.last.request.headers["Authorization"] == AUTH
    assert json.loads(patch.calls.last.request.content) == {"status": after}


@respx.mock
def test_move_back_todo_task_stays_todo(client: TestClient) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=SEEDED[0]))
    patch = respx.patch(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=SEEDED[0]))

    resp = client.post("/tasks/1/move-back", data={"csrf_token": csrf}, follow_redirects=False)

    assert resp.status_code == 303
    assert not patch.called


@respx.mock
def test_move_back_patch_body_carries_status_only(client: TestClient) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/3").mock(return_value=httpx.Response(200, json=SEEDED[2]))
    patch = respx.patch(f"{API}/api/tasks/3").mock(
        return_value=httpx.Response(200, json={**SEEDED[2], "status": "doing"})
    )

    client.post("/tasks/3/move-back", data={"csrf_token": csrf}, follow_redirects=False)

    assert json.loads(patch.calls.last.request.content) == {"status": "doing"}


@respx.mock
def test_move_back_csrf_mismatch_is_403(client: TestClient) -> None:
    login(client)
    route = respx.get(f"{API}/api/tasks/3").mock(return_value=httpx.Response(200, json=SEEDED[2]))

    resp = client.post("/tasks/3/move-back", data={"csrf_token": "wrong"}, follow_redirects=False)

    assert resp.status_code == 403
    assert not route.called


@respx.mock
def test_move_back_missing_csrf_is_403(client: TestClient) -> None:
    login(client)
    route = respx.get(f"{API}/api/tasks/3").mock(return_value=httpx.Response(200, json=SEEDED[2]))

    resp = client.post("/tasks/3/move-back", data={}, follow_redirects=False)

    assert resp.status_code == 403
    assert not route.called


def test_move_back_without_session_redirects_to_login(client: TestClient) -> None:
    csrf = extract_csrf(client.get("/login").text)

    resp = client.post("/tasks/1/move-back", data={"csrf_token": csrf}, follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=/tasks/1/move-back"


@respx.mock
def test_move_back_api_401_clears_session_and_redirects(client: TestClient) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(401))

    resp = client.post("/tasks/1/move-back", data={"csrf_token": csrf}, follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


@respx.mock
def test_move_back_other_users_task_404_is_noop(client: TestClient) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/99").mock(return_value=httpx.Response(404))

    resp = client.post("/tasks/99/move-back", data={"csrf_token": csrf}, follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


@respx.mock
def test_move_back_api_down_still_redirects_to_board(client: TestClient) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/1").mock(side_effect=httpx.ConnectError("refused"))

    resp = client.post("/tasks/1/move-back", data={"csrf_token": csrf}, follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


@respx.mock
def test_move_back_redirects_back_to_filtered_board(client: TestClient) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/3").mock(return_value=httpx.Response(200, json=SEEDED[2]))
    respx.patch(f"{API}/api/tasks/3").mock(
        return_value=httpx.Response(200, json={**SEEDED[2], "status": "doing"})
    )

    resp = client.post(
        "/tasks/3/move-back",
        data={"csrf_token": csrf, "status": "done"},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/?status=done"


@respx.mock
def test_move_back_redirects_to_same_page_and_filter(client: TestClient) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/3").mock(return_value=httpx.Response(200, json=SEEDED[2]))
    respx.patch(f"{API}/api/tasks/3").mock(
        return_value=httpx.Response(200, json={**SEEDED[2], "status": "doing"})
    )

    resp = client.post(
        "/tasks/3/move-back",
        data={"csrf_token": csrf, "status": "done", "page": "2"},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/?status=done&page=2"


@respx.mock
def test_move_back_ignores_unknown_filter_value(client: TestClient) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/3").mock(return_value=httpx.Response(200, json=SEEDED[2]))
    respx.patch(f"{API}/api/tasks/3").mock(
        return_value=httpx.Response(200, json={**SEEDED[2], "status": "doing"})
    )

    resp = client.post(
        "/tasks/3/move-back",
        data={"csrf_token": csrf, "status": "bogus"},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


@respx.mock
def test_advance_still_uses_next_status_after_refactor(client: TestClient) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/3").mock(return_value=httpx.Response(200, json=SEEDED[2]))
    patch = respx.patch(f"{API}/api/tasks/3").mock(return_value=httpx.Response(200, json=SEEDED[2]))

    resp = client.post("/tasks/3/advance", data={"csrf_token": csrf}, follow_redirects=False)

    assert resp.status_code == 303
    assert not patch.called


def test_healthz(client: TestClient) -> None:
    resp = client.get("/healthz")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# --- accessibility markup ---------------------------------------------------


@respx.mock
def test_index_row_actions_carry_task_scoped_aria_labels(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/").text

    assert 'aria-label="Move back Write the spec"' in body
    assert 'aria-label="Advance Write the spec"' in body
    assert 'aria-label="Delete Write the spec"' in body
    assert body.count('aria-label="Move back') == len(SEEDED)
    assert body.count('aria-label="Delete') == len(SEEDED)


@respx.mock
def test_index_rows_render_move_back_form(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/").text

    assert body.count('data-testid="move-back-btn"') == len(SEEDED)
    assert f'action="/tasks/{SEEDED[0]["id"]}/move-back"' in body
    assert body.count('class="btn-back" data-testid="move-back-btn"') == len(SEEDED)


@respx.mock
def test_index_row_action_aria_labels_are_escaped(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    task = {**SEEDED[0], "title": '<script>"boom"</script>'}
    respx.get(f"{API}/api/tasks").mock(return_value=httpx.Response(200, json=page_body([task])))
    mock_health()

    body = client.get("/").text

    assert '<script>"boom"</script>' not in body
    assert "&lt;script&gt;" in body
    assert "&#34;" in body


def test_login_form_labels_are_associated(client: TestClient) -> None:
    body = client.get("/login").text

    assert '<label for="email">' in body
    assert 'id="email"' in body
    assert '<label for="password">' in body
    assert 'id="password"' in body


@respx.mock
def test_new_form_labels_are_associated(client: TestClient) -> None:
    login(client)

    body = client.get("/new").text

    assert '<label for="title">' in body
    assert 'id="title"' in body
    assert '<label for="description">' in body
    assert 'id="description"' in body
    assert '<label for="due_at">' in body
    assert 'id="due_at"' in body


@respx.mock
def test_pages_render_banner_and_main_landmarks(client: TestClient) -> None:
    login(client)
    mock_board()

    login_body = client.get("/login").text
    board_body = client.get("/").text

    for body in (login_body, board_body):
        assert body.count("<header>") == 1
        assert body.count("<main>") == 1


# --- board search (issue #55) -------------------------------------------------


@respx.mock
def test_board_forwards_search_term_to_api(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    tasks_route = respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body(SEEDED))
    )
    mock_health()

    client.get("/?q=inv")

    params = tasks_route.calls[0].request.url.params
    assert params["q"] == "inv"
    assert params["limit"] == "20"
    assert params["offset"] == "0"


@respx.mock
def test_board_omits_q_param_when_search_blank(client: TestClient) -> None:
    login(client)
    _, tasks_route = mock_board()

    client.get("/?q=%20%20")

    assert "q" not in tasks_route.calls.last.request.url.params


@respx.mock
def test_board_renders_search_input_prefilled_and_clear_link(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/?q=inv").text

    assert 'data-testid="search-input"' in body
    assert 'value="inv"' in body
    assert 'data-testid="search-clear"' in body
    start = body.index('data-testid="search-clear"')
    tag_start = body.rindex("<a", 0, start)
    tag_end = body.index(">", start)
    assert 'href="/"' in body[tag_start:tag_end]


@respx.mock
def test_board_omits_clear_link_without_search(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/").text

    assert 'data-testid="search-clear"' not in body


@respx.mock
def test_board_renders_empty_search_message_and_not_empty_board_or_filter(
    client: TestClient,
) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body([], total=0))
    )
    mock_health()

    resp = client.get("/?q=nomatch")

    assert resp.status_code == 200
    body = resp.text
    assert 'data-testid="empty-search"' in body
    assert "No tasks match your search." in body
    assert 'data-testid="empty-board"' not in body
    assert 'data-testid="empty-filter"' not in body


@respx.mock
def test_board_search_pager_and_filter_links_carry_term(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body(make_tasks(20, "todo"), total=25))
    )
    mock_health()

    body = client.get("/?status=todo&q=inv").text

    assert 'href="/?status=todo&amp;q=inv&amp;page=2"' in body
    start = body.index('data-testid="filter-doing"')
    end = body.index(">", start)
    tag = body[body.rindex("<a", 0, start) : end]
    assert 'href="/?status=doing&amp;q=inv"' in tag


@respx.mock
def test_board_row_forms_and_edit_link_carry_search(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/?q=spec").text

    start = body.index('data-testid="edit-link"')
    tag_end = body.index(">", start)
    assert 'href="/tasks/1/edit?q=spec"' in body[body.rindex("<a", 0, start) : tag_end]
    assert 'name="q" value="spec"' in body


@respx.mock
def test_board_task_count_stays_grand_total_under_search(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    tasks_route = respx.get(f"{API}/api/tasks").mock(
        side_effect=[
            httpx.Response(200, json=page_body(make_tasks(1, "todo"), total=1)),
            httpx.Response(200, json=page_body(make_tasks(1), total=30)),
        ]
    )
    mock_health()

    body = client.get("/?q=inv").text

    assert 'data-testid="task-count">30<' in body
    assert tasks_route.call_count == 2


@respx.mock
def test_board_out_of_range_page_with_search_refetches_page_one(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    tasks_route = respx.get(f"{API}/api/tasks").mock(
        return_value=httpx.Response(200, json=page_body(SEEDED, total=len(SEEDED)))
    )
    mock_health()

    resp = client.get("/?q=inv&page=5")

    assert resp.status_code == 200
    assert 'data-testid="pager"' not in resp.text
    # out-of-range refetch (2 calls) plus the grand-total count fetch a search triggers
    assert tasks_route.call_count == 3


@respx.mock
def test_board_long_or_unstorable_search_term_renders_200(client: TestClient) -> None:
    login(client)
    _, tasks_route = mock_board()

    long_resp = client.get("/?" + "q=" + "x" * 2000)
    assert long_resp.status_code == 200
    assert 'data-testid="api-error"' not in long_resp.text
    assert len(tasks_route.calls[0].request.url.params["q"]) == 1000

    nul_resp = client.get("/?q=bad%00term")
    assert nul_resp.status_code == 200
    assert 'data-testid="api-error"' not in nul_resp.text
    assert tasks_route.calls[-2].request.url.params["q"] == "badterm"


@respx.mock
def test_advance_move_back_delete_redirect_back_to_searched_board(client: TestClient) -> None:
    csrf = login(client)
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=SEEDED[0]))
    respx.patch(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=SEEDED[0]))
    respx.delete(f"{API}/api/tasks/1").mock(return_value=httpx.Response(204))

    for action in ("advance", "move-back", "delete"):
        resp = client.post(
            f"/tasks/1/{action}",
            data={"csrf_token": csrf, "status": "todo", "q": "inv", "page": "2"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/?status=todo&q=inv&page=2"


@respx.mock
def test_edit_get_and_post_round_trip_preserves_search(client: TestClient) -> None:
    csrf = login(client)
    task = {**SEEDED[0], "id": 1}
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=task))
    respx.patch(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=task))

    get_body = client.get("/tasks/1/edit?status=todo&q=inv&page=2").text
    assert 'name="q" value="inv"' in get_body
    assert 'href="/?status=todo&amp;q=inv&amp;page=2"' in get_body

    resp = client.post(
        "/tasks/1/edit",
        data={
            "title": task["title"],
            "description": task["description"],
            "status": "todo",
            "q": "inv",
            "page": "2",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/?status=todo&q=inv&page=2"


@respx.mock
def test_search_form_renders_after_status_filter_nav(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/").text

    assert body.index('data-testid="status-filter"') < body.index('data-testid="search-form"')


@respx.mock
def test_search_form_adds_no_landmark_or_role(client: TestClient) -> None:
    login(client)
    mock_board()

    body = client.get("/").text

    start = body.index('data-testid="search-form"')
    tag_end = body.index(">", start)
    tag_start = body.rindex("<form", 0, start)
    tag = body[tag_start:tag_end]
    assert "role=" not in tag
    assert body.count("<header>") == 1
    assert body.count("<main>") == 1
