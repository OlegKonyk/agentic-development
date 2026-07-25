"""Web UI tests with the upstream API mocked via respx (v2: auth + CSRF).

The app-under-test is driven through TestClient (explicit ASGITransport, which
respx does not patch); the app's outbound httpx calls hit the respx mock.
"""

import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from web.main import (
    create_app,
    decorate_tasks,
    format_due_at,
    parse_due_at,
    safe_next,
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


def mock_board() -> tuple[respx.Route, respx.Route]:
    me = respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    tasks = respx.get(f"{API}/api/tasks").mock(return_value=httpx.Response(200, json=SEEDED))
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


def test_to_rfc3339_z_converts_datetime_local() -> None:
    assert to_rfc3339_z("2026-03-01T12:30") == "2026-03-01T12:30:00Z"
    assert to_rfc3339_z("2026-03-01T12:30:15+02:00") == "2026-03-01T10:30:15Z"


def test_title_rejected_helper() -> None:
    assert title_rejected([{"loc": ["body", "title"], "type": "value_error"}]) is True
    assert title_rejected([{"loc": ["body", "due_at"], "type": "value_error"}]) is False
    assert title_rejected(None) is False
    assert title_rejected({}) is False
    assert title_rejected("boom") is False
    assert title_rejected([{}]) is False


def test_format_due_at_renders_human_label() -> None:
    assert format_due_at(datetime(2026, 7, 25, 12, 34, 56, tzinfo=UTC)) == "25 Jul 2026, 12:34 UTC"
    assert format_due_at(datetime(2026, 7, 5, 9, 0, tzinfo=UTC)) == "05 Jul 2026, 09:00 UTC"
    plus_two = timezone(timedelta(hours=2))
    assert format_due_at(datetime(2026, 7, 25, 14, 34, tzinfo=plus_two)) == "25 Jul 2026, 12:34 UTC"


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

    ordered = decorate_tasks(tasks, now)

    assert [t["id"] for t in ordered] == [3, 1, 2, 4]


def test_decorate_tasks_marks_overdue_only_for_past_due() -> None:
    now = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)
    tasks = [
        {"id": 1, "due_at": "2026-07-25T11:59:59Z"},
        {"id": 2, "due_at": "2026-07-25T12:00:01Z"},
        {"id": 3, "due_at": None},
        {"id": 4, "due_at": "2026-07-25T12:00:00Z"},
    ]

    ordered = {t["id"]: t["overdue"] for t in decorate_tasks(tasks, now)}

    assert ordered == {1: True, 2: False, 3: False, 4: False}


# --- auth gating -----------------------------------------------------------


def test_unauthed_board_redirects_to_login_with_next(client: TestClient) -> None:
    resp = client.get("/", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=/"


def test_unauthed_new_redirects_to_login_with_next(client: TestClient) -> None:
    resp = client.get("/new", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login?next=/new"


def test_login_form_renders(client: TestClient) -> None:
    resp = client.get("/login")

    assert resp.status_code == 200
    for testid in ("email-input", "password-input", "submit-login"):
        assert f'data-testid="{testid}"' in resp.text
    assert 'data-testid="login-error"' not in resp.text
    assert 'name="csrf_token"' in resp.text


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
    assert format_due_at(parse_due_at(SEEDED[1]["due_at"])) in body
    assert body.count('data-testid="reminder-badge"') == 1
    assert 'data-testid="reminder-badge">pending<' in body


@respx.mock
def test_index_due_at_renders_human_label_not_raw_iso(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    due_at = "2026-07-25T12:34:56Z"
    task = {**SEEDED[0], "id": 10, "due_at": due_at}
    respx.get(f"{API}/api/tasks").mock(return_value=httpx.Response(200, json=[task]))

    body = client.get("/").text

    assert "25 Jul 2026, 12:34 UTC" in body
    assert due_at not in body


@respx.mock
def test_index_overdue_badge_only_for_past_due(client: TestClient) -> None:
    login(client)
    respx.get(f"{API}/api/auth/me").mock(return_value=httpx.Response(200, json=ME))
    tasks = [
        {**SEEDED[0], "id": 11, "title": "Past due", "due_at": "2020-01-01T00:00:00Z"},
        {**SEEDED[0], "id": 12, "title": "Future due", "due_at": iso_in(3600)},
        {**SEEDED[0], "id": 13, "title": "No due date", "due_at": None},
    ]
    respx.get(f"{API}/api/tasks").mock(return_value=httpx.Response(200, json=tasks))

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
    respx.get(f"{API}/api/tasks").mock(return_value=httpx.Response(200, json=tasks))

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
    respx.get(f"{API}/api/tasks").mock(return_value=httpx.Response(200, json=[task]))

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


# --- new task --------------------------------------------------------------


@respx.mock
def test_new_form_renders(client: TestClient) -> None:
    login(client)

    resp = client.get("/new")

    assert resp.status_code == 200
    for testid in ("title-input", "description-input", "due-at-input", "submit-task"):
        assert f'data-testid="{testid}"' in resp.text


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
def test_new_task_api_401_clears_session(client: TestClient) -> None:
    csrf = login(client)
    respx.post(f"{API}/api/tasks").mock(return_value=httpx.Response(401))

    resp = client.post(
        "/new", data={"title": "New one", "csrf_token": csrf}, follow_redirects=False
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


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


def test_healthz(client: TestClient) -> None:
    resp = client.get("/healthz")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
