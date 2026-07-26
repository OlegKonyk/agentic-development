"""Reminder-delivery health: derived from recorded delivery attempt outcomes.

Kept separate from jobs.py/main.py so the import direction stays one-way:
jobs writes (record_delivery), main reads (delivery_health); neither imports
the other.
"""

import os
from datetime import UTC, datetime, timedelta

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import DeliveryOutcome, ReminderDelivery, ReminderHealthState

DEFAULT_WINDOW_SECONDS = 900


def health_window_seconds() -> int:
    return int(os.environ.get("REMINDER_HEALTH_WINDOW_SECONDS", str(DEFAULT_WINDOW_SECONDS)))


async def record_delivery(session: AsyncSession, task_id: int, outcome: DeliveryOutcome) -> None:
    """Append one attempt outcome; caller commits."""
    session.add(ReminderDelivery(task_id=task_id, outcome=outcome))


async def delivery_health(
    session: AsyncSession, now: datetime | None = None
) -> ReminderHealthState:
    cutoff = (now or datetime.now(UTC)) - timedelta(seconds=health_window_seconds())
    statement = (
        select(ReminderDelivery.outcome)
        .where(col(ReminderDelivery.at) >= cutoff)
        .order_by(col(ReminderDelivery.at).desc(), col(ReminderDelivery.id).desc())
        .limit(1)
    )
    latest = (await session.exec(statement)).first()
    return "degraded" if latest == "failed" else "healthy"
