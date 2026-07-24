from datetime import datetime

import pytest
from httpx import AsyncClient

from tests.conftest import AppFactory, client_for

pytestmark = pytest.mark.anyio


async def create(client: AsyncClient, **overrides: object) -> dict:
    payload: dict[str, object] = {"title": "A task", **overrides}
    resp = await client.post("/api/tasks", json=payload)
    assert resp.status_code == 201
    return resp.json()


async def test_healthz(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_openapi_available(client: AsyncClient) -> None:
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    assert "/api/tasks" in resp.json()["paths"]


async def test_create_task_defaults(client: AsyncClient) -> None:
    task = await create(client, title="Buy milk")
    assert task["title"] == "Buy milk"
    assert task["description"] == ""
    assert task["status"] == "todo"
    assert isinstance(task["id"], int)
    datetime.fromisoformat(task["created_at"])  # valid iso8601


async def test_create_task_with_description(client: AsyncClient) -> None:
    task = await create(client, title="Buy milk", description="2 liters")
    assert task["description"] == "2 liters"


async def test_create_title_boundaries(client: AsyncClient) -> None:
    ok = await client.post("/api/tasks", json={"title": "x" * 200})
    assert ok.status_code == 201
    too_long = await client.post("/api/tasks", json={"title": "x" * 201})
    assert too_long.status_code == 422
    empty = await client.post("/api/tasks", json={"title": ""})
    assert empty.status_code == 422
    missing = await client.post("/api/tasks", json={"description": "no title"})
    assert missing.status_code == 422


async def test_list_tasks_and_status_filter(client: AsyncClient) -> None:
    a = await create(client, title="one")
    b = await create(client, title="two")
    await client.patch(f"/api/tasks/{b['id']}", json={"status": "doing"})

    all_resp = await client.get("/api/tasks")
    assert all_resp.status_code == 200
    assert [t["id"] for t in all_resp.json()] == [a["id"], b["id"]]

    todo_resp = await client.get("/api/tasks", params={"status": "todo"})
    assert [t["id"] for t in todo_resp.json()] == [a["id"]]

    done_resp = await client.get("/api/tasks", params={"status": "done"})
    assert done_resp.json() == []


async def test_list_tasks_invalid_status_filter(client: AsyncClient) -> None:
    resp = await client.get("/api/tasks", params={"status": "bogus"})
    assert resp.status_code == 422


async def test_get_task(client: AsyncClient) -> None:
    task = await create(client, title="find me")
    resp = await client.get(f"/api/tasks/{task['id']}")
    assert resp.status_code == 200
    assert resp.json() == task


async def test_get_unknown_task_404(client: AsyncClient) -> None:
    resp = await client.get("/api/tasks/9999")
    assert resp.status_code == 404


async def test_patch_fields(client: AsyncClient) -> None:
    task = await create(client, title="old", description="d")
    resp = await client.patch(
        f"/api/tasks/{task['id']}",
        json={"title": "new", "description": "e", "status": "done"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "new"
    assert body["description"] == "e"
    assert body["status"] == "done"
    assert body["id"] == task["id"]


async def test_patch_partial_leaves_other_fields(client: AsyncClient) -> None:
    task = await create(client, title="keep me", description="keep too")
    resp = await client.patch(f"/api/tasks/{task['id']}", json={"status": "doing"})
    body = resp.json()
    assert body["title"] == "keep me"
    assert body["description"] == "keep too"
    assert body["status"] == "doing"


async def test_patch_empty_body_is_noop(client: AsyncClient) -> None:
    task = await create(client, title="unchanged")
    resp = await client.patch(f"/api/tasks/{task['id']}", json={})
    assert resp.status_code == 200
    assert resp.json() == task


async def test_patch_invalid_status_422(client: AsyncClient) -> None:
    task = await create(client)
    resp = await client.patch(f"/api/tasks/{task['id']}", json={"status": "finished"})
    assert resp.status_code == 422


async def test_patch_invalid_title_422(client: AsyncClient) -> None:
    task = await create(client)
    resp = await client.patch(f"/api/tasks/{task['id']}", json={"title": "x" * 201})
    assert resp.status_code == 422


async def test_patch_unknown_task_404(client: AsyncClient) -> None:
    resp = await client.patch("/api/tasks/9999", json={"status": "done"})
    assert resp.status_code == 404


async def test_delete_task(client: AsyncClient) -> None:
    task = await create(client, title="doomed")
    resp = await client.delete(f"/api/tasks/{task['id']}")
    assert resp.status_code == 204
    assert resp.content == b""
    assert (await client.get(f"/api/tasks/{task['id']}")).status_code == 404


async def test_delete_unknown_task_404(client: AsyncClient) -> None:
    resp = await client.delete("/api/tasks/9999")
    assert resp.status_code == 404


async def test_reset_wipes_all_tasks(client: AsyncClient) -> None:
    await create(client, title="one")
    await create(client, title="two")
    resp = await client.post("/api/testing/reset")
    assert resp.status_code == 204
    assert (await client.get("/api/tasks")).json() == []


async def test_reset_not_mounted_outside_test_env(make_app: AppFactory) -> None:
    async with client_for(make_app(app_env="production")) as client:
        await create(client, title="survivor")
        resp = await client.post("/api/testing/reset")
        assert resp.status_code == 404
        assert len((await client.get("/api/tasks")).json()) == 1


async def test_reset_not_mounted_when_env_unset(make_app: AppFactory) -> None:
    async with client_for(make_app(app_env=None)) as client:
        resp = await client.post("/api/testing/reset")
        assert resp.status_code == 404


async def test_data_persists_across_app_instances(make_app: AppFactory) -> None:
    async with client_for(make_app()) as client:
        task = await create(client, title="durable")
    async with client_for(make_app()) as client:
        resp = await client.get(f"/api/tasks/{task['id']}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "durable"
