"""Reminder jobs: find due tasks, mark + enqueue, deliver to the vendor."""

import os
from datetime import UTC, datetime

import httpx
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential
from tenacity.wait import wait_base

from app import db
from app.models import Task, rfc3339
from app.reminders import record_delivery
from app.tkq import broker

VENDOR_TIMEOUT_SECONDS = 2.0
VENDOR_ATTEMPTS = 3

# Injectable wait strategy: tests swap in tenacity.wait_none().
RETRY_WAIT: wait_base = wait_exponential(multiplier=0.5, max=5)


def _vendor_url() -> str:
    return os.environ.get("VENDOR_URL", "http://localhost:8081").rstrip("/")


def _vendor_key() -> str:
    return os.environ.get("VENDOR_API_KEY", "vendor-key")


async def _post_notification(payload: dict[str, object]) -> None:
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(VENDOR_ATTEMPTS),
        wait=RETRY_WAIT,
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    ):
        with attempt:
            async with httpx.AsyncClient(timeout=VENDOR_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{_vendor_url()}/v1/notifications",
                    json=payload,
                    headers={"x-vendor-key": _vendor_key()},
                )
                response.raise_for_status()


@broker.task(task_name="send_reminder")
async def send_reminder(task_id: int) -> None:
    async with db.session_scope() as session:
        task = await session.get(Task, task_id)
        if task is None or task.reminder_status != "pending" or task.due_at is None:
            return
        payload: dict[str, object] = {
            "task_id": task.id,
            "title": task.title,
            "due_at": rfc3339(task.due_at),
            "idempotency_key": f"task-{task.id}",
        }
    try:
        await _post_notification(payload)
        # Success keeps the task `pending`: the vendor's delivery webhook is
        # what flips it to `sent`.
        async with db.session_scope() as session:
            await record_delivery(session, task_id, "accepted")
            await session.commit()
    except httpx.HTTPError:
        async with db.session_scope() as session:
            # Recorded unconditionally, even if the task was deleted mid-flight:
            # the health signal reflects the attempt, not the task's survival.
            await record_delivery(session, task_id, "failed")
            task = await session.get(Task, task_id)
            if task is not None and task.reminder_status == "pending":
                task.reminder_status = "failed"
                session.add(task)
            await session.commit()


async def find_due_reminders(session: AsyncSession, as_of: datetime | None = None) -> list[Task]:
    moment = as_of or datetime.now(UTC)
    statement = (
        select(Task)
        .where(
            col(Task.due_at).is_not(None),
            col(Task.due_at) <= moment,
            Task.reminder_status == "none",
        )
        .order_by(col(Task.id))
    )
    return list((await session.exec(statement)).all())


async def enqueue_due(as_of: datetime | None = None) -> int:
    """Mark due tasks `pending` and enqueue a send_reminder job for each."""
    async with db.session_scope() as session:
        due = await find_due_reminders(session, as_of)
        ids = [task.id for task in due if task.id is not None]
        for task in due:
            task.reminder_status = "pending"
            session.add(task)
        await session.commit()
    for task_id in ids:
        await send_reminder.kiq(task_id)
    return len(ids)


@broker.task(task_name="run_due_reminders", schedule=[{"interval": 30}])
async def run_due_reminders() -> int:
    return await enqueue_due()
