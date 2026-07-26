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
HEALTH = "/api/reminders/health"


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


async def all_deliveries() -> list[ReminderDelivery]:
    async with db.session_scope() as session:
        return list((await session.exec(select(ReminderDelivery))).all())


async def test_health_healthy_when_no_deliveries(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    resp = await client.get(HEALTH, headers=alice_headers)
    assert resp.status_code == 200
    assert resp.json() == {"state": "healthy", "window_seconds": 900}


async def test_health_requires_bearer(client: AsyncClient) -> None:
    assert (await client.get(HEALTH)).status_code == 401
    assert (
        await client.get(HEALTH, headers={"Authorization": "Bearer not-a-token"})
    ).status_code == 401


async def test_failed_delivery_marks_degraded(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await create_due_task(client, alice_headers)
    with respx.mock(assert_all_called=False) as vendor:
        vendor.post(VENDOR_ENDPOINT).mock(return_value=httpx.Response(500))
        await client.post(TRIGGER)
    resp = await client.get(HEALTH, headers=alice_headers)
    assert resp.json()["state"] == "degraded"


async def test_accepted_delivery_stays_healthy(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await create_due_task(client, alice_headers)
    with respx.mock(assert_all_called=False) as vendor:
        vendor.post(VENDOR_ENDPOINT).mock(
            return_value=httpx.Response(202, json={"notification_id": "n-1"})
        )
        await client.post(TRIGGER)
    resp = await client.get(HEALTH, headers=alice_headers)
    assert resp.json()["state"] == "healthy"
    rows = await all_deliveries()
    assert [row.outcome for row in rows] == ["accepted"]


async def test_retry_then_success_records_single_accepted(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    await create_due_task(client, alice_headers)
    with respx.mock(assert_all_called=False) as vendor:
        route = vendor.post(VENDOR_ENDPOINT)
        route.side_effect = [
            httpx.Response(500),
            httpx.Response(202, json={"notification_id": "n-1"}),
        ]
        await client.post(TRIGGER)
    resp = await client.get(HEALTH, headers=alice_headers)
    assert resp.json()["state"] == "healthy"
    rows = await all_deliveries()
    assert [row.outcome for row in rows] == ["accepted"]


async def test_success_after_failure_recovers(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    failing = await create_due_task(client, alice_headers)
    with respx.mock(assert_all_called=False) as vendor:
        vendor.post(VENDOR_ENDPOINT).mock(return_value=httpx.Response(500))
        await client.post(TRIGGER)
    assert (await client.get(HEALTH, headers=alice_headers)).json()["state"] == "degraded"

    succeeding = await create_due_task(client, alice_headers)
    assert succeeding != failing
    with respx.mock(assert_all_called=False) as vendor:
        vendor.post(VENDOR_ENDPOINT).mock(
            return_value=httpx.Response(202, json={"notification_id": "n-2"})
        )
        await client.post(TRIGGER)
    assert (await client.get(HEALTH, headers=alice_headers)).json()["state"] == "healthy"


async def test_failure_outside_window_is_healthy(
    client: AsyncClient, alice_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    task_id = await create_due_task(client, alice_headers)
    with respx.mock(assert_all_called=False) as vendor:
        vendor.post(VENDOR_ENDPOINT).mock(return_value=httpx.Response(500))
        await client.post(TRIGGER)
    async with db.session_scope() as session:
        await session.execute(
            update(ReminderDelivery)
            .where(ReminderDelivery.task_id == task_id)  # type: ignore[arg-type]
            .values(at=datetime.now(UTC) - timedelta(seconds=901))
        )
        await session.commit()

    resp = await client.get(HEALTH, headers=alice_headers)
    assert resp.json()["state"] == "healthy"


async def test_failure_survives_task_deletion(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    task_id = await create_due_task(client, alice_headers)
    with respx.mock(assert_all_called=False) as vendor:
        vendor.post(VENDOR_ENDPOINT).mock(return_value=httpx.Response(500))
        await client.post(TRIGGER)

    assert (await client.delete(f"/api/tasks/{task_id}", headers=alice_headers)).status_code == 204

    resp = await client.get(HEALTH, headers=alice_headers)
    assert resp.status_code == 200
    assert resp.json()["state"] == "degraded"


async def test_same_timestamp_ties_break_by_id(
    client: AsyncClient, alice_headers: dict[str, str]
) -> None:
    task_id = await create_due_task(client, alice_headers)
    same_moment = datetime.now(UTC)
    async with db.session_scope() as session:
        session.add(ReminderDelivery(task_id=task_id, outcome="accepted", at=same_moment))
        session.add(ReminderDelivery(task_id=task_id, outcome="failed", at=same_moment))
        await session.commit()

    resp = await client.get(HEALTH, headers=alice_headers)
    assert resp.json()["state"] == "degraded"
