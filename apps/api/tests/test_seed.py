from pathlib import Path

import pytest
from app.db import create_db_engine
from app.models import Task
from app.seed import SEED_TASKS, seed
from sqlmodel import Session, select

from tests.conftest import AppFactory, client_for

pytestmark = pytest.mark.anyio

EXPECTED = [
    (1, "Write the SDLC spec", "done"),
    (2, "Build the QA agent", "doing"),
    (3, "Deploy the gateway", "todo"),
]


def db_rows(data_dir: Path) -> list[tuple[int | None, str, str]]:
    engine = create_db_engine(data_dir)
    with Session(engine) as session:
        tasks = session.exec(select(Task).order_by(Task.id)).all()
        return [(t.id, t.title, t.status) for t in tasks]


def test_seed_creates_fixed_dataset(data_dir: Path) -> None:
    seed()
    assert db_rows(data_dir) == EXPECTED
    assert len(SEED_TASKS) == 3


def test_seed_is_idempotent(data_dir: Path) -> None:
    seed()
    seed()
    assert db_rows(data_dir) == EXPECTED


async def test_seed_resets_extra_tasks(data_dir: Path, make_app: AppFactory) -> None:
    async with client_for(make_app()) as client:
        resp = await client.post("/api/tasks", json={"title": "extra"})
        assert resp.status_code == 201

        seed()

        listed = (await client.get("/api/tasks")).json()
        assert [(t["id"], t["title"], t["status"]) for t in listed] == EXPECTED
        # Deterministic fixed timestamp on every seeded task.
        assert len({t["created_at"] for t in listed}) == 1
