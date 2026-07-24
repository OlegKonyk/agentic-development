from datetime import UTC, datetime, timedelta

import pytest
from app import db
from app.models import Task, User
from app.seed import SEED_CREATED_AT, SEED_TASKS, SEED_USERS, seed
from httpx import AsyncClient
from sqlmodel import select

from tests.conftest import ALICE, bearer, login

pytestmark = pytest.mark.anyio

EXPECTED_OWNERS = [1, 1, 1, 2, 2]


async def db_tasks() -> list[Task]:
    async with db.session_scope() as session:
        statement = select(Task).order_by(Task.id)  # type: ignore[arg-type]
        return list((await session.exec(statement)).all())


async def test_seed_creates_fixed_dataset(db_setup: None) -> None:
    now = datetime.now(UTC)
    await seed(now)
    tasks = await db_tasks()
    assert [t.id for t in tasks] == [1, 2, 3, 4, 5]
    assert [t.owner_id for t in tasks] == EXPECTED_OWNERS
    assert all(t.created_at == SEED_CREATED_AT for t in tasks)
    assert all(t.reminder_status == "none" for t in tasks)
    assert len(SEED_TASKS) == 5
    assert len(SEED_USERS) == 2

    # Exactly one task carries a reminder, due 2 minutes out.
    due = [t for t in tasks if t.due_at is not None]
    assert [t.id for t in due] == [3]
    assert due[0].owner_id == 1
    assert due[0].due_at == now + timedelta(minutes=2)

    async with db.session_scope() as session:
        users = list((await session.exec(select(User).order_by(User.id))).all())  # type: ignore[arg-type]
    assert [(u.id, u.email) for u in users] == [(1, "alice@example.com"), (2, "bob@example.com")]


async def test_seed_is_idempotent(db_setup: None) -> None:
    await seed()
    await seed()
    tasks = await db_tasks()
    assert [t.id for t in tasks] == [1, 2, 3, 4, 5]
    async with db.session_scope() as session:
        assert len((await session.exec(select(User))).all()) == 2


async def test_seeded_credentials_work(client: AsyncClient) -> None:
    await seed()
    token = await login(client, ALICE)
    resp = await client.get("/api/tasks", headers=bearer(token))
    assert resp.status_code == 200
    assert [t["id"] for t in resp.json()] == [1, 2, 3]


async def test_sequences_realigned_after_seed(client: AsyncClient) -> None:
    await seed()
    token = await login(client, ALICE)
    resp = await client.post("/api/tasks", json={"title": "post-seed"}, headers=bearer(token))
    assert resp.status_code == 201
    assert resp.json()["id"] == 6


async def test_seed_resets_extra_tasks(client: AsyncClient) -> None:
    token = await login(client, ALICE)
    resp = await client.post("/api/tasks", json={"title": "extra"}, headers=bearer(token))
    assert resp.status_code == 201

    await seed()

    listed = (await client.get("/api/tasks", headers=bearer(token))).json()
    assert [t["id"] for t in listed] == [1, 2, 3]
