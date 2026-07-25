import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, FastAPI, HTTPException, Path, Query
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic.json_schema import SkipJsonSchema
from sqlalchemy import delete
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app import db
from app.auth import CurrentUser
from app.auth import router as auth_router
from app.db import SessionDep
from app.jobs import enqueue_due
from app.models import Session as AuthSession
from app.models import Status, Task, TaskCreate, TaskRead, TaskUpdate, User, WebhookEvent
from app.tkq import broker
from app.webhooks import router as webhooks_router

# ge/le bound the id to the DB BIGINT range; out-of-range ids 422 instead of
# overflowing the driver (found by contract fuzzing in v1).
TaskId = Annotated[int, Path(ge=1, le=2**31 - 1)]

BAD_BODY = {400: {"description": "Malformed request body"}}
NOT_FOUND = {404: {"description": "Task not found"}}

tasks_router = APIRouter(
    prefix="/api/tasks",
    tags=["tasks"],
    responses={401: {"description": "Not authenticated"}},
)


async def _get_owned_task(session: AsyncSession, user: User, task_id: int) -> Task:
    # Other users' ids 404 (not 403): no task-existence leak across owners.
    task = await session.get(Task, task_id)
    if task is None or task.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@tasks_router.get("", response_model=list[TaskRead])
async def list_tasks(
    session: SessionDep,
    user: CurrentUser,
    # SkipJsonSchema keeps null out of the OpenAPI schema: the param is
    # optional-by-absence, not nullable-by-value (contract-tested).
    status: Annotated[Status | SkipJsonSchema[None], Query()] = None,
) -> list[Task]:
    statement = select(Task).where(Task.owner_id == user.id).order_by(col(Task.id))
    if status is not None:
        statement = statement.where(Task.status == status)
    return list((await session.exec(statement)).all())


@tasks_router.post("", response_model=TaskRead, status_code=201, responses=BAD_BODY)
async def create_task(payload: TaskCreate, session: SessionDep, user: CurrentUser) -> Task:
    task = Task(
        owner_id=user.id,  # type: ignore[arg-type]
        title=payload.title,
        description=payload.description,
        due_at=payload.due_at,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


@tasks_router.get("/{task_id}", response_model=TaskRead, responses=NOT_FOUND)
async def get_task(task_id: TaskId, session: SessionDep, user: CurrentUser) -> Task:
    return await _get_owned_task(session, user, task_id)


@tasks_router.patch("/{task_id}", response_model=TaskRead, responses=NOT_FOUND | BAD_BODY)
async def update_task(
    task_id: TaskId, payload: TaskUpdate, session: SessionDep, user: CurrentUser
) -> Task:
    task = await _get_owned_task(session, user, task_id)
    for key, value in payload.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(task, key, value)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


@tasks_router.delete("/{task_id}", status_code=204, responses=NOT_FOUND)
async def delete_task(task_id: TaskId, session: SessionDep, user: CurrentUser) -> None:
    task = await _get_owned_task(session, user, task_id)
    await session.delete(task)
    await session.commit()


testing_router = APIRouter(prefix="/api/testing", tags=["testing"])


@testing_router.post("/reset", status_code=204)
async def reset(session: SessionDep) -> None:
    # Wipe tasks, sessions, and webhook events; keep the seeded users.
    for model in (Task, AuthSession, WebhookEvent):
        await session.execute(delete(model))
    await session.commit()


@testing_router.post("/run-due-reminders", status_code=202)
async def run_due_reminders() -> dict[str, int]:
    # Deterministic trigger for E2E: same code path as the 30s scheduler tick.
    return {"enqueued": await enqueue_due()}


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    db.engine()  # create the process-wide async engine
    if not broker.is_worker_process:
        await broker.startup()
    yield
    if not broker.is_worker_process:
        await broker.shutdown()
    await db.dispose_engine()


class RequestDeadlineMiddleware:
    """Bound every request with an asyncio deadline (504 on breach).

    The last line of defense against stalled I/O: driver-level timeouts don't
    cover every await (asyncpg's transaction BEGIN bypasses command_timeout,
    verified by the db-stall resilience test), but cancelling the request task
    bounds them all.
    """

    def __init__(self, app: object, timeout_s: float) -> None:
        self.app = app
        self.timeout_s = timeout_s

    async def __call__(self, scope: dict, receive: object, send: object) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)  # type: ignore[operator]
            return
        started = False

        async def tracking_send(message: dict) -> None:
            nonlocal started
            started = True
            await send(message)  # type: ignore[operator]

        try:
            async with asyncio.timeout(self.timeout_s):
                await self.app(scope, receive, tracking_send)  # type: ignore[operator]
        except TimeoutError:
            if started:  # response underway — nothing coherent left to send
                raise
            body = json.dumps({"detail": "request deadline exceeded"}).encode()
            await send(  # type: ignore[operator]
                {
                    "type": "http.response.start",
                    "status": 504,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})  # type: ignore[operator]


def _surrogate_safe(value: object) -> object:
    """Strip unpaired surrogates so a value survives json.dumps().encode().

    FastAPI's 422 body echoes the offending input; a lone surrogate in that echo
    crashes JSONResponse.render into a 500 — the exact failure the 422 reports.
    """
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(value, list):
        return [_surrogate_safe(item) for item in value]
    if isinstance(value, dict):
        return {_surrogate_safe(key): _surrogate_safe(item) for key, item in value.items()}
    return value


def create_app() -> FastAPI:
    application = FastAPI(title="Taskboard API", lifespan=lifespan)
    application.add_middleware(
        RequestDeadlineMiddleware,
        timeout_s=int(os.environ.get("REQUEST_DEADLINE_MS", "8000")) / 1000,
    )

    @application.exception_handler(db.DatabaseUnavailableError)
    async def on_db_unavailable(request: object, exc: db.DatabaseUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "database unavailable"})

    @application.exception_handler(RequestValidationError)
    async def on_validation_error(request: object, exc: RequestValidationError) -> JSONResponse:
        # jsonable_encoder first (it stringifies non-serializable ctx values),
        # then sanitize: the echoed input may hold the surrogates being rejected.
        return JSONResponse(
            status_code=422,
            content={"detail": _surrogate_safe(jsonable_encoder(exc.errors()))},
        )

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(auth_router)
    application.include_router(tasks_router)
    application.include_router(webhooks_router)
    if os.environ.get("APP_ENV") == "test":
        application.include_router(testing_router)
    return application


app = create_app()
