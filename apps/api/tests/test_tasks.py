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
    missing = await client.post("/api/tasks", json={"description": "x"}, headers=alice_headers)
    assert missing.status_code == 422


async def test_list_tasks_and_status_filter(client: AsyncClient, alice_headers: dict) -> None:
    a = await create(client, alice_headers, title="one")
    b = await create(client, alice_headers, title="two")
    await client.patch(f"/api/tasks/{b['id']}", json={"status": "doing"}, headers=alice_headers)

    all_resp = await client.get("/api/tasks", headers=alice_headers)
    assert all_resp.status_code == 200
    assert [t["id"] for t in all_resp.json()] == [a["id"], b["id"]]

    todo = await client.get("/api/tasks", params={"status": "todo"}, headers=alice_headers)
    assert [t["id"] for t in todo.json()] == [a["id"]]

    done = await client.get("/api/tasks", params={"status": "done"}, headers=alice_headers)
    assert done.json() == []


async def test_list_tasks_invalid_status_filter(client: AsyncClient, alice_headers: dict) -> None:
    resp = await client.get("/api/tasks", params={"status": "bogus"}, headers=alice_headers)
    assert resp.status_code == 422


async def test_owner_scoping(client: AsyncClient, alice_headers: dict, bob_headers: dict) -> None:
    alice_task = await create(client, alice_headers, title="alice's")
    bob_task = await create(client, bob_headers, title="bob's")

    alice_list = (await client.get("/api/tasks", headers=alice_headers)).json()
    assert [t["id"] for t in alice_list] == [alice_task["id"]]
    bob_list = (await client.get("/api/tasks", headers=bob_headers)).json()
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
