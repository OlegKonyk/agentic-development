import asyncio
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import cache

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

# Env must be pinned before any `app.*` import (pytest imports conftest first;
# app modules are imported lazily inside fixtures below for the same reason).
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://taskboard:taskboard@localhost:5432/taskboard_test"
)
os.environ["APP_ENV"] = "test"
os.environ["TASKIQ_BROKER"] = "inmemory"
os.environ["VENDOR_URL"] = "http://vendor.test"
os.environ["VENDOR_API_KEY"] = "vendor-key"
os.environ["VENDOR_WEBHOOK_SECRET"] = "whsec_test"
os.environ.setdefault("QA_ALICE_PASS", "correct-horse-a")
os.environ.setdefault("QA_BOB_PASS", "correct-horse-b")

AppFactory = Callable[..., FastAPI]

ALICE = "alice@example.com"
BOB = "bob@example.com"
PASSWORDS = {ALICE: os.environ["QA_ALICE_PASS"], BOB: os.environ["QA_BOB_PASS"]}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@cache
def seed_hashes() -> dict[str, str]:
    # Argon2 is deliberately slow; hash each seed password once per run.
    from app.auth import password_hash

    return {email: password_hash.hash(password) for email, password in PASSWORDS.items()}


@pytest.fixture(scope="session")
def _database() -> None:
    """Fresh schema once per session, via the init helper (Alembic owns prod)."""
    from app import db

    async def prepare() -> None:
        engine = db.create_db_engine()
        try:
            await db.init_db(engine, drop=True)
        finally:
            await engine.dispose()

    asyncio.run(prepare())


@pytest.fixture
async def db_setup(_database: None) -> AsyncIterator[None]:
    """Per-test isolation: truncate everything, re-seed the two users."""
    from app import db, seed

    engine = db.engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE tasks, sessions, webhook_events, reminder_deliveries, users "
                "RESTART IDENTITY CASCADE"
            )
        )
    async with db.session_scope() as session:
        await seed.upsert_users(session, hashes=seed_hashes())
        await session.commit()
    yield
    # asyncpg pools are event-loop-bound; drop the engine with this test's loop.
    await db.dispose_engine()


@pytest.fixture
def make_app(monkeypatch: pytest.MonkeyPatch) -> AppFactory:
    def _make(app_env: str | None = "test") -> FastAPI:
        if app_env is None:
            monkeypatch.delenv("APP_ENV", raising=False)
        else:
            monkeypatch.setenv("APP_ENV", app_env)
        from app.main import create_app

        return create_app()

    return _make


@asynccontextmanager
async def client_for(app: FastAPI) -> AsyncIterator[AsyncClient]:
    # ASGITransport skips lifespan; run it explicitly so startup/shutdown match prod.
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c,
    ):
        yield c


@pytest.fixture
async def client(db_setup: None, make_app: AppFactory) -> AsyncIterator[AsyncClient]:
    async with client_for(make_app()) as c:
        yield c


async def login(client: AsyncClient, email: str = ALICE, password: str | None = None) -> str:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password or PASSWORDS[email]}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def alice_headers(client: AsyncClient) -> dict[str, str]:
    return bearer(await login(client, ALICE))


@pytest.fixture
async def bob_headers(client: AsyncClient) -> dict[str, str]:
    return bearer(await login(client, BOB))
