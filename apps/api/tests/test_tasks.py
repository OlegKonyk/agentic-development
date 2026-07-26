from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


def iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def future_iso(minutes: int = 5) -> str:
    return iso(datetime.now(UTC) + timedelta(minutes=minutes))


async def create(client: AsyncClient, headers: dict[str, str], **overrides: object) -> dict:
    payload: dict[str, object] = {"title": "A task", **overrides}
    resp = await client.post("/api/tasks", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_healthz(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_openapi_available(client: AsyncClient) -> None:
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    assert "/api/tasks" in resp.json()["paths"]


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "/api/tasks"),
        ("POST", "/api/tasks"),
        ("GET", "/api/tasks/1"),
        ("PATCH", "/api/tasks/1"),
        ("DELETE", "/api/tasks/1"),
    ],
)
async def test_endpoints_require_auth(client: AsyncClient, method: str, url: str) -> None:
    resp = await client.request(method, url, json={"title": "x"})
    assert resp.status_code == 401


async def test_create_task_defaults(client: AsyncClient, alice_headers: dict[str, str]) -> None:
    task = await create(client, alice_headers, title="Buy milk")
    assert task["title"] == "Buy milk"
    assert task["description"] == ""
    assert task["status"] == "todo"
    assert task["due_at"] is None
    assert task["reminder_status"] == "none"
    assert isinstance(task["id"], int)
    assert task["created_at"].endswith("Z")
    datetime.fromisoformat(task["created_at"])  # valid RFC 3339


async def test_create_with_future_due_at(client: AsyncClient, alice_headers: dict) -> None:
    due = future_iso()
    task = await create(client, alice_headers, title="Remind me", due_at=due)
    assert task["due_at"] == due
    assert task["reminder_status"] == "none"


@pytest.mark.parametrize("due_at", ["2020-01-01T00:00:00Z", "not-a-date"])
async def test_create_bad_due_at_422(client: AsyncClient, alice_headers: dict, due_at: str) -> None:
    resp = await client.post(
        "/api/tasks", json={"title": "x", "due_at": due_at}, headers=alice_headers
    )
    assert resp.status_code == 422


async def test_reminder_status_is_read_only(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers, reminder_status="sent")
    assert task["reminder_status"] == "none"


async def test_create_title_boundaries(client: AsyncClient, alice_headers: dict) -> None:
    ok = await client.post("/api/tasks", json={"title": "x" * 200}, headers=alice_headers)
    assert ok.status_code == 201
    too_long = await client.post("/api/tasks", json={"title": "x" * 201}, headers=alice_headers)
    assert too_long.status_code == 422
    empty = await client.post("/api/tasks", json={"title": ""}, headers=alice_headers)
    assert empty.status_code == 422
    blank = await client.post("/api/tasks", json={"title": " "}, headers=alice_headers)
    assert blank.status_code == 422
    missing = await client.post("/api/tasks", json={"description": "x"}, headers=alice_headers)
    assert missing.status_code == 422


@pytest.mark.parametrize("title", [" ", "\t", "\n", "   ", " "])
async def test_create_whitespace_only_title_422(
    client: AsyncClient, alice_headers: dict, title: str
) -> None:
    resp = await client.post("/api/tasks", json={"title": title}, headers=alice_headers)
    assert resp.status_code == 422
    listed = await client.get("/api/tasks", headers=alice_headers)
    assert listed.json()["items"] == []


async def test_blank_title_422_names_title_field(client: AsyncClient, alice_headers: dict) -> None:
    resp = await client.post("/api/tasks", json={"title": " "}, headers=alice_headers)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail[0]["loc"] == ["body", "title"]
    assert detail[0]["type"] == "value_error"


async def test_create_padded_title_stored_verbatim(
    client: AsyncClient, alice_headers: dict
) -> None:
    task = await create(client, alice_headers, title="  Buy milk  ")
    assert task["title"] == "  Buy milk  "


async def test_patch_whitespace_only_title_422(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers, title="keep me", description="keep too")
    resp = await client.patch(
        f"/api/tasks/{task['id']}", json={"title": " "}, headers=alice_headers
    )
    assert resp.status_code == 422
    fetched = await client.get(f"/api/tasks/{task['id']}", headers=alice_headers)
    assert fetched.json()["title"] == "keep me"
    assert fetched.json()["description"] == "keep too"
    assert fetched.json()["status"] == "todo"


async def test_patch_null_title_is_noop(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers, title="unchanged")
    resp = await client.patch(
        f"/api/tasks/{task['id']}", json={"title": None}, headers=alice_headers
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "unchanged"


async def test_list_tasks_and_status_filter(client: AsyncClient, alice_headers: dict) -> None:
    a = await create(client, alice_headers, title="one")
    b = await create(client, alice_headers, title="two")
    await client.patch(f"/api/tasks/{b['id']}", json={"status": "doing"}, headers=alice_headers)

    all_resp = await client.get("/api/tasks", headers=alice_headers)
    assert all_resp.status_code == 200
    assert [t["id"] for t in all_resp.json()["items"]] == [a["id"], b["id"]]

    todo = await client.get("/api/tasks", params={"status": "todo"}, headers=alice_headers)
    assert [t["id"] for t in todo.json()["items"]] == [a["id"]]

    done = await client.get("/api/tasks", params={"status": "done"}, headers=alice_headers)
    assert done.json()["items"] == []


async def test_list_tasks_invalid_status_filter(client: AsyncClient, alice_headers: dict) -> None:
    resp = await client.get("/api/tasks", params={"status": "bogus"}, headers=alice_headers)
    assert resp.status_code == 422


async def test_owner_scoping(client: AsyncClient, alice_headers: dict, bob_headers: dict) -> None:
    alice_task = await create(client, alice_headers, title="alice's")
    bob_task = await create(client, bob_headers, title="bob's")

    alice_list = (await client.get("/api/tasks", headers=alice_headers)).json()["items"]
    assert [t["id"] for t in alice_list] == [alice_task["id"]]
    bob_list = (await client.get("/api/tasks", headers=bob_headers)).json()["items"]
    assert [t["id"] for t in bob_list] == [bob_task["id"]]


async def test_cross_user_task_ids_404(
    client: AsyncClient, alice_headers: dict, bob_headers: dict
) -> None:
    task = await create(client, alice_headers, title="private")
    url = f"/api/tasks/{task['id']}"
    assert (await client.get(url, headers=bob_headers)).status_code == 404
    patch = await client.patch(url, json={"status": "done"}, headers=bob_headers)
    assert patch.status_code == 404
    assert (await client.delete(url, headers=bob_headers)).status_code == 404
    # Untouched for the owner.
    assert (await client.get(url, headers=alice_headers)).status_code == 200


async def test_get_task(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers, title="find me")
    resp = await client.get(f"/api/tasks/{task['id']}", headers=alice_headers)
    assert resp.status_code == 200
    assert resp.json() == task


async def test_get_unknown_task_404(client: AsyncClient, alice_headers: dict) -> None:
    resp = await client.get("/api/tasks/9999", headers=alice_headers)
    assert resp.status_code == 404


async def test_task_id_out_of_range_422(client: AsyncClient, alice_headers: dict) -> None:
    resp = await client.get(f"/api/tasks/{2**63}", headers=alice_headers)
    assert resp.status_code == 422


async def test_patch_fields(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers, title="old", description="d")
    due = future_iso()
    resp = await client.patch(
        f"/api/tasks/{task['id']}",
        json={"title": "new", "description": "e", "status": "done", "due_at": due},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "new"
    assert body["description"] == "e"
    assert body["status"] == "done"
    assert body["due_at"] == due


async def test_patch_partial_leaves_other_fields(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers, title="keep me", description="keep too")
    resp = await client.patch(
        f"/api/tasks/{task['id']}", json={"status": "doing"}, headers=alice_headers
    )
    body = resp.json()
    assert body["title"] == "keep me"
    assert body["description"] == "keep too"
    assert body["status"] == "doing"


async def test_patch_empty_body_is_noop(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers, title="unchanged")
    resp = await client.patch(f"/api/tasks/{task['id']}", json={}, headers=alice_headers)
    assert resp.status_code == 200
    assert resp.json() == task


async def test_patch_past_due_at_422(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers)
    resp = await client.patch(
        f"/api/tasks/{task['id']}",
        json={"due_at": "2020-01-01T00:00:00Z"},
        headers=alice_headers,
    )
    assert resp.status_code == 422


async def test_patch_invalid_status_422(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers)
    resp = await client.patch(
        f"/api/tasks/{task['id']}", json={"status": "finished"}, headers=alice_headers
    )
    assert resp.status_code == 422


async def test_patch_unknown_task_404(client: AsyncClient, alice_headers: dict) -> None:
    resp = await client.patch("/api/tasks/9999", json={"status": "done"}, headers=alice_headers)
    assert resp.status_code == 404


async def test_delete_task(client: AsyncClient, alice_headers: dict) -> None:
    task = await create(client, alice_headers, title="doomed")
    resp = await client.delete(f"/api/tasks/{task['id']}", headers=alice_headers)
    assert resp.status_code == 204
    assert resp.content == b""
    assert (await client.get(f"/api/tasks/{task['id']}", headers=alice_headers)).status_code == 404


async def test_delete_unknown_task_404(client: AsyncClient, alice_headers: dict) -> None:
    resp = await client.delete("/api/tasks/9999", headers=alice_headers)
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        '{"title": "\\ud800"}',
        '{"title": "ok", "description": "a\\u0000b"}',
    ],
    ids=["surrogate-title", "nul-description"],
)
async def test_create_task_unstorable_strings_422(
    client: AsyncClient, alice_headers: dict, body: str
) -> None:
    # Same family as the login regression: surrogates/NUL crash the asyncpg
    # bind into a 500 unless rejected at the model boundary.
    resp = await client.post(
        "/api/tasks",
        content=body.encode("utf-8"),
        headers={"Content-Type": "application/json", **alice_headers},
    )
    assert resp.status_code == 422


async def test_patch_surrogate_status_echo_is_422_not_500(
    client: AsyncClient, alice_headers: dict
) -> None:
    # Body validation fires before the 404 lookup, so no task row is needed.
    # Pins the echo path alone: status is a Literal (no storable-string
    # validator), so the 422 body reflects the raw surrogate input, which
    # used to crash response serialization into a 500.
    resp = await client.patch(
        "/api/tasks/1",
        content=b'{"status": "\\ud800"}',
        headers={"Content-Type": "application/json", **alice_headers},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]


# --- pagination (issue #8) --------------------------------------------------


async def test_list_returns_envelope_shape(client: AsyncClient, alice_headers: dict) -> None:
    await create(client, alice_headers, title="only task")
    resp = await client.get("/api/tasks", headers=alice_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"items", "total", "limit", "offset"}
    assert body["limit"] == 20
    assert body["offset"] == 0


async def test_list_default_limit_caps_page(client: AsyncClient, alice_headers: dict) -> None:
    for i in range(25):
        await create(client, alice_headers, title=f"task {i}")
    resp = await client.get("/api/tasks", headers=alice_headers)
    body = resp.json()
    assert len(body["items"]) == 20
    assert body["total"] == 25


async def test_list_limit_offset_slice(client: AsyncClient, alice_headers: dict) -> None:
    tasks = [await create(client, alice_headers, title=f"task {i}") for i in range(12)]
    resp = await client.get("/api/tasks", params={"limit": 5, "offset": 5}, headers=alice_headers)
    body = resp.json()
    assert [t["id"] for t in body["items"]] == [t["id"] for t in tasks[5:10]]
    assert body["limit"] == 5
    assert body["offset"] == 5


async def test_list_total_stable_across_pages(client: AsyncClient, alice_headers: dict) -> None:
    for i in range(12):
        await create(client, alice_headers, title=f"task {i}")
    first = await client.get("/api/tasks", params={"limit": 5, "offset": 0}, headers=alice_headers)
    second = await client.get("/api/tasks", params={"limit": 5, "offset": 5}, headers=alice_headers)
    assert first.json()["total"] == second.json()["total"] == 12


async def test_list_offset_past_end_is_empty_200(client: AsyncClient, alice_headers: dict) -> None:
    for i in range(3):
        await create(client, alice_headers, title=f"task {i}")
    resp = await client.get("/api/tasks", params={"offset": 100}, headers=alice_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 3


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": -1},
        {"offset": -1},
        {"limit": "abc"},
        {"offset": 1.5},
    ],
)
async def test_list_invalid_pagination_params_422(
    client: AsyncClient, alice_headers: dict, params: dict
) -> None:
    resp = await client.get("/api/tasks", params=params, headers=alice_headers)
    assert resp.status_code == 422


async def test_list_huge_offset_422_not_500(client: AsyncClient, alice_headers: dict) -> None:
    resp = await client.get("/api/tasks", params={"offset": 2**63}, headers=alice_headers)
    assert resp.status_code == 422


async def test_list_status_filter_scopes_page_and_total(
    client: AsyncClient, alice_headers: dict
) -> None:
    for i in range(8):
        await create(client, alice_headers, title=f"todo {i}")
    for i in range(2):
        done = await create(client, alice_headers, title=f"done {i}")
        await client.patch(
            f"/api/tasks/{done['id']}", json={"status": "done"}, headers=alice_headers
        )

    resp = await client.get(
        "/api/tasks", params={"status": "todo", "limit": 5}, headers=alice_headers
    )
    body = resp.json()
    assert len(body["items"]) == 5
    assert all(t["status"] == "todo" for t in body["items"])
    assert body["total"] == 8


async def test_list_pagination_is_owner_scoped(
    client: AsyncClient, alice_headers: dict, bob_headers: dict
) -> None:
    alice_tasks = [await create(client, alice_headers, title=f"alice {i}") for i in range(3)]
    await create(client, bob_headers, title="bob's")

    resp = await client.get("/api/tasks", params={"limit": 100, "offset": 0}, headers=alice_headers)
    body = resp.json()
    assert [t["id"] for t in body["items"]] == [t["id"] for t in alice_tasks]
    assert body["total"] == 3
