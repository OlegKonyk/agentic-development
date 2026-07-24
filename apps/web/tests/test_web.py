"""Web UI tests with the upstream API mocked via respx.

The app-under-test is driven through TestClient (explicit ASGITransport, which
respx does not patch); the app's outbound httpx calls hit the respx mock.
"""

import json
from collections.abc import Iterator

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from web.main import create_app

API = "http://localhost:8000"

SEEDED = [
    {
        "id": 1,
        "title": "Write the spec",
        "description": "",
        "status": "todo",
        "created_at": "2026-01-01T00:00:00Z",
    },
    {
        "id": 2,
        "title": "Build the API",
        "description": "fastapi",
        "status": "doing",
        "created_at": "2026-01-01T00:01:00Z",
    },
    {
        "id": 3,
        "title": "Ship it",
        "description": "",
        "status": "done",
        "created_at": "2026-01-01T00:02:00Z",
    },
]


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@respx.mock
def test_index_renders_seeded_tasks(client: TestClient) -> None:
    respx.get(f"{API}/api/tasks").mock(return_value=httpx.Response(200, json=SEEDED))

    resp = client.get("/")

    assert resp.status_code == 200
    body = resp.text
    for task in SEEDED:
        assert task["title"] in body
    assert 'data-testid="task-list"' in body
    assert body.count('data-testid="task-row"') == 3
    assert 'data-testid="api-error"' not in body


@respx.mock
def test_index_shows_error_banner_when_api_down(client: TestClient) -> None:
    respx.get(f"{API}/api/tasks").mock(side_effect=httpx.ConnectError("refused"))

    resp = client.get("/")

    assert resp.status_code == 200
    assert 'data-testid="api-error"' in resp.text


def test_new_form_renders(client: TestClient) -> None:
    resp = client.get("/new")

    assert resp.status_code == 200
    for testid in ("title-input", "description-input", "submit-task"):
        assert f'data-testid="{testid}"' in resp.text


@respx.mock
def test_new_task_posts_to_api_and_redirects(client: TestClient) -> None:
    created = {**SEEDED[0], "id": 4, "title": "New one", "description": "details"}
    route = respx.post(f"{API}/api/tasks").mock(return_value=httpx.Response(201, json=created))

    resp = client.post(
        "/new",
        data={"title": "New one", "description": "details"},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert route.called
    assert json.loads(route.calls.last.request.content) == {
        "title": "New one",
        "description": "details",
    }


@respx.mock
def test_new_task_api_down_renders_error_banner(client: TestClient) -> None:
    respx.post(f"{API}/api/tasks").mock(side_effect=httpx.ConnectError("refused"))

    resp = client.post("/new", data={"title": "New one"}, follow_redirects=False)

    assert resp.status_code == 200
    assert 'data-testid="api-error"' in resp.text


@respx.mock
def test_advance_patches_next_status_and_redirects(client: TestClient) -> None:
    respx.get(f"{API}/api/tasks/1").mock(return_value=httpx.Response(200, json=SEEDED[0]))
    patch = respx.patch(f"{API}/api/tasks/1").mock(
        return_value=httpx.Response(200, json={**SEEDED[0], "status": "doing"})
    )

    resp = client.post("/tasks/1/advance", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert json.loads(patch.calls.last.request.content) == {"status": "doing"}


@respx.mock
def test_advance_done_task_stays_done(client: TestClient) -> None:
    respx.get(f"{API}/api/tasks/3").mock(return_value=httpx.Response(200, json=SEEDED[2]))
    patch = respx.patch(f"{API}/api/tasks/3").mock(return_value=httpx.Response(200, json=SEEDED[2]))

    resp = client.post("/tasks/3/advance", follow_redirects=False)

    assert resp.status_code == 303
    assert not patch.called


@respx.mock
def test_delete_proxies_and_redirects(client: TestClient) -> None:
    route = respx.delete(f"{API}/api/tasks/2").mock(return_value=httpx.Response(204))

    resp = client.post("/tasks/2/delete", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert route.called


def test_healthz(client: TestClient) -> None:
    resp = client.get("/healthz")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
