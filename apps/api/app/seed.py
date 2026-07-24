"""Idempotent seeding: `python -m app.seed` upserts the 2 QA users and resets
their tasks to a fixed dataset (alice: 3 tasks, one due in +2min; bob: 2 tasks)."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

from pwdlib import PasswordHash
from sqlalchemy import delete, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app import db
from app.models import Task, User

# Fixed timestamp so the seeded dataset is fully deterministic for QA.
SEED_CREATED_AT = datetime(2025, 1, 1, tzinfo=UTC)

# (id, email, password env var, compose default)
SEED_USERS: tuple[tuple[int, str, str, str], ...] = (
    (1, "alice@example.com", "QA_ALICE_PASS", "correct-horse-a"),
    (2, "bob@example.com", "QA_BOB_PASS", "correct-horse-b"),
)

# (id, owner_id, title, status, due_in) — due_in None means no reminder.
SEED_TASKS: tuple[tuple[int, int, str, str, timedelta | None], ...] = (
    (1, 1, "Write the SDLC spec", "done", None),
    (2, 1, "Build the QA agent", "doing", None),
    (3, 1, "Ship the reminder flow", "todo", timedelta(minutes=2)),
    (4, 2, "Review the gateway config", "todo", None),
    (5, 2, "Draft the chaos playbook", "doing", None),
)

_password_hash = PasswordHash.recommended()


def _setval(table: str) -> object:
    # Explicit-id inserts leave the identity sequence behind; realign it so the
    # next API-created row does not collide.
    return text(
        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'),"
        f" (SELECT COALESCE(MAX(id), 1) FROM {table}))"
    )


async def upsert_users(session: AsyncSession, hashes: dict[str, str] | None = None) -> None:
    """Upsert alice/bob with fixed ids. `hashes` lets tests reuse precomputed hashes."""
    for user_id, email, env_var, default in SEED_USERS:
        digest = (hashes or {}).get(email) or _password_hash.hash(os.environ.get(env_var, default))
        existing = (await session.exec(select(User).where(User.email == email))).first()
        if existing is None:
            session.add(
                User(id=user_id, email=email, password_hash=digest, created_at=SEED_CREATED_AT)
            )
        else:
            existing.password_hash = digest
            session.add(existing)
    await session.flush()  # setval must see the inserted rows' MAX(id)
    await session.execute(_setval("users"))


async def reset_tasks(session: AsyncSession, now: datetime | None = None) -> None:
    moment = now or datetime.now(UTC)
    await session.execute(delete(Task))
    for task_id, owner_id, title, status, due_in in SEED_TASKS:
        session.add(
            Task(
                id=task_id,
                owner_id=owner_id,
                title=title,
                description="",
                status=status,
                due_at=moment + due_in if due_in is not None else None,
                created_at=SEED_CREATED_AT,
            )
        )
    await session.flush()  # setval must see the inserted rows' MAX(id)
    await session.execute(_setval("tasks"))


async def seed(now: datetime | None = None) -> None:
    async with db.session_scope() as session:
        await upsert_users(session)
        await reset_tasks(session, now)
        await session.commit()


async def _main() -> None:
    try:
        await seed()
    finally:
        await db.dispose_engine()


if __name__ == "__main__":
    asyncio.run(_main())
