import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

DEFAULT_DATABASE_URL = "postgresql+asyncpg://taskboard:taskboard@localhost:5432/taskboard"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def create_db_engine(url: str | None = None) -> AsyncEngine:
    # Two timeout layers (the resilience suite pits a db stall against them):
    # - statement_timeout (server): Postgres kills slow queries.
    # - command_timeout (client): asyncpg gives up when the wire itself stalls
    #   and the server can never answer. Must exceed worst-case per-query wire
    #   latency, so it is a separate, larger knob.
    # No pool_pre_ping: the dialect's ping BEGINs a transaction outside the
    # command_timeout path and hangs forever on a stalled wire — the exact
    # failure it is meant to catch. Dead connections surface on first use
    # instead, bounded by command_timeout, and the pool recycles them.
    command_timeout_s = int(os.environ.get("DB_COMMAND_TIMEOUT_MS", "4000")) / 1000
    return create_async_engine(
        url or database_url(),
        connect_args={
            "timeout": command_timeout_s,  # connection establishment
            "command_timeout": command_timeout_s,  # per-query, client-enforced
            "server_settings": {
                "statement_timeout": os.environ.get("DB_STATEMENT_TIMEOUT_MS", "2000"),
            },
        },
    )


_engine: AsyncEngine | None = None


def engine() -> AsyncEngine:
    """Process-wide engine, created lazily; the app lifespan triggers creation/disposal."""
    global _engine
    if _engine is None:
        _engine = create_db_engine()
    return _engine


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with AsyncSession(engine(), expire_on_commit=False) as session:
        yield session


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def init_db(target: AsyncEngine | None = None, *, drop: bool = False) -> None:
    """Create tables directly. Test helper only — Alembic owns the schema in prod."""
    from app import models  # noqa: F401 — ensure every table is registered on the metadata

    eng = target or engine()
    async with eng.begin() as conn:
        if drop:
            await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
