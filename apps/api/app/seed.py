"""Idempotent seeding: `python -m app.seed` resets the DB to 3 fixed known tasks."""

from datetime import UTC, datetime

from sqlmodel import Session, select

from app.db import create_db_engine
from app.models import Task

SEED_TASKS: tuple[tuple[str, str], ...] = (
    ("Write the SDLC spec", "done"),
    ("Build the QA agent", "doing"),
    ("Deploy the gateway", "todo"),
)

# Fixed timestamp so the seeded dataset is fully deterministic for QA.
SEED_CREATED_AT = datetime(2025, 1, 1, tzinfo=UTC)


def seed() -> None:
    engine = create_db_engine()
    with Session(engine) as session:
        for task in session.exec(select(Task)).all():
            session.delete(task)
        for task_id, (title, status) in enumerate(SEED_TASKS, start=1):
            session.add(
                Task(
                    id=task_id,
                    title=title,
                    description="",
                    status=status,
                    created_at=SEED_CREATED_AT,
                )
            )
        session.commit()


if __name__ == "__main__":
    seed()
