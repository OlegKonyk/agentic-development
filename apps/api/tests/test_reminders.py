import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from app import db, jobs
from app.models import ReminderDelivery, Task
from httpx import AsyncClient
from sqlalchemy import update
from sqlmodel import select
from tenacity import wait_none

pytestmark = pytest.mark.anyio

VENDOR_ENDPOINT = "http://vendor.test/v1/notifications"
TRIGGER = "/api/testing/run-due-reminders"


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs, "RETRY_WAIT", wait_none())


def iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


async def create_due_task(client: AsyncClient, headers: dict[str, str]) -> int:
    """Create a task with a valid future due_at, then backdate it in the DB."""
    resp = await client.post(
        "/api/tasks",
        json={"title": "due now", "due_at": iso(datetime.now(UTC) + timedelta(minutes=2))},
        headers=headers,
    )
    assert resp.status_code == 201
    task_id: int = resp.json()["id"]
    async with db.session_scope() as session:
        await session.execute(
            update(Task)
            .where(Task.id == task_id)  # type: ignore[arg-type]
            .values(due_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()
    return task_id


async def reminder_status(client: AsyncClient, headers: dict[str, str], task_id: int) -> str:
    resp = await client.get(f"/api/tasks/{task_id}", headers=headers)
    status: str = resp.json()["reminder_status"]
    return status


async def test_trigger_with_nothing_due(client: AsyncClient) -> None:
    resp = await client.post(TRIGGER)
    assert resp.status_code == 202
    assert resp.json() == {"enqueued": 0}


async def test_trigger_enqueues_and_posts_to_vendor(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    task_id = await create_due_task(client, alice_headers)
    with respx.mock(assert_all_called=False) as vendor:
        route = vendor.post(VENDOR_ENDPOINT).mock(
            return_value=httpx.Response(202, json={"notification_id": "n-1"})
        )
        resp = await client.post(TRIGGER)
        assert resp.status_code == 202
        assert resp.json() == {"enqueued": 1}
        assert route.call_count == 1
        request = route.calls[0].request
        assert request.headers["x-vendor-key"] == "vendor-key"
        body = json.loads(request.content)
        assert body["task_id"] == task_id
        assert body["title"] == "due now"
        assert body["idempotency_key"] == f"task-{task_id}"
        assert body["due_at"].endswith("Z")
    # Success keeps `pending`; only the delivery webhook flips it to `sent`.
    assert await reminder_status(client, alice_headers, task_id) == "pending"


async def test_trigger_does_not_reenqueue_pending(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await create_due_task(client, alice_headers)
    with respx.mock(assert_all_called=False) as vendor:
        vendor.post(VENDOR_ENDPOINT).mock(
            return_value=httpx.Response(202, json={"notification_id": "n-1"})
        )
        assert (await client.post(TRIGGER)).json() == {"enqueued": 1}
        assert (await client.post(TRIGGER)).json() == {"enqueued": 0}


async def test_task_without_due_at_never_enqueued(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.post("/api/tasks", json={"title": "no due"}, headers=alice_headers)
    assert resp.status_code == 201
    assert (await client.post(TRIGGER)).json() == {"enqueued": 0}


async def test_exhausted_retries_mark_failed(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    task_id = await create_due_task(client, alice_headers)
    with respx.mock(assert_all_called=False) as vendor:
        route = vendor.post(VENDOR_ENDPOINT).mock(return_value=httpx.Response(500))
        resp = await client.post(TRIGGER)
        assert resp.status_code == 202
        assert route.call_count == 3
    assert await reminder_status(client, alice_headers, task_id) == "failed"


async def test_connect_errors_mark_failed(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    task_id = await create_due_task(client, alice_headers)
    with respx.mock(assert_all_called=False) as vendor:
        route = vendor.post(VENDOR_ENDPOINT).mock(side_effect=httpx.ConnectError("boom"))
        await client.post(TRIGGER)
        assert route.call_count == 3
    assert await reminder_status(client, alice_headers, task_id) == "failed"


async def test_retry_then_success_keeps_pending(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    task_id = await create_due_task(client, alice_headers)
    with respx.mock(assert_all_called=False) as vendor:
        route = vendor.post(VENDOR_ENDPOINT)
        route.side_effect = [
            httpx.Response(500),
            httpx.Response(202, json={"notification_id": "n-1"}),
        ]
        await client.post(TRIGGER)
        assert route.call_count == 2
    assert await reminder_status(client, alice_headers, task_id) == "pending"


async def deliveries_for(task_id: int) -> list[str]:
    async with db.session_scope() as session:
        statement = select(ReminderDelivery.outcome).where(ReminderDelivery.task_id == task_id)
        return list((await session.exec(statement)).all())


async def test_exhausted_retries_record_failed_delivery(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    task_id = await create_due_task(client, alice_headers)
    with respx.mock(assert_all_called=False) as vendor:
        vendor.post(VENDOR_ENDPOINT).mock(return_value=httpx.Response(500))
        await client.post(TRIGGER)
    assert await deliveries_for(task_id) == ["failed"]


async def test_task_deleted_mid_flight_still_records_failure(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    """A task deleted while its vendor POST is in flight still contributes its
    failure to the health signal — the delivery row carries no FK to the task."""
    task_id = await create_due_task(client, alice_headers)
    deleted = False

    async def fail_and_delete_task(request: httpx.Request) -> httpx.Response:
        nonlocal deleted
        if not deleted:
            deleted = True
            async with db.session_scope() as session:
                task = await session.get(Task, task_id)
                if task is not None:
                    await session.delete(task)
                    await session.commit()
        return httpx.Response(500)

    with respx.mock(assert_all_called=False) as vendor:
        vendor.post(VENDOR_ENDPOINT).mock(side_effect=fail_and_delete_task)
        await client.post(TRIGGER)
    assert await deliveries_for(task_id) == ["failed"]


async def test_find_due_reminders_filters(client: AsyncClient, alice_headers: dict) -> None:
    task_id = await create_due_task(client, alice_headers)
    await client.post("/api/tasks", json={"title": "not due"}, headers=alice_headers)
    async with db.session_scope() as session:
        due = await jobs.find_due_reminders(session)
        assert [t.id for t in due] == [task_id]
        # as_of far in the past → nothing due yet.
        none_due = await jobs.find_due_reminders(session, datetime(2020, 1, 1, tzinfo=UTC))
        assert none_due == []
