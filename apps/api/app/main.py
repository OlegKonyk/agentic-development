import os
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, Query
from pydantic.json_schema import SkipJsonSchema
from sqlmodel import Session, select

from app.db import create_db_engine
from app.models import Status, Task, TaskCreate, TaskRead, TaskUpdate


def _get_task(session: Session, task_id: int) -> Task:
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def create_app() -> FastAPI:
    # Tables are created at factory time (not in a lifespan hook) so that
    # httpx ASGITransport-based tests, which skip lifespan, get a ready DB.
    engine = create_db_engine()
    application = FastAPI(title="Taskboard API")

    def get_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    SessionDep = Annotated[Session, Depends(get_session)]
    # ge/le bound the id to SQLite's INTEGER range; out-of-range ids 422 instead
    # of overflowing the driver (found by contract fuzzing).
    TaskId = Annotated[int, Path(ge=1, le=2**63 - 1)]

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/tasks", response_model=list[TaskRead])
    def list_tasks(
        session: SessionDep,
        # SkipJsonSchema keeps null out of the OpenAPI schema: the param is
        # optional-by-absence, not nullable-by-value (contract-tested).
        status: Annotated[Status | SkipJsonSchema[None], Query()] = None,
    ) -> list[Task]:
        statement = select(Task).order_by(Task.id)
        if status is not None:
            statement = statement.where(Task.status == status)
        return list(session.exec(statement).all())

    BAD_BODY = {400: {"description": "Malformed request body"}}

    @application.post("/api/tasks", response_model=TaskRead, status_code=201, responses=BAD_BODY)
    def create_task(payload: TaskCreate, session: SessionDep) -> Task:
        task = Task(title=payload.title, description=payload.description)
        session.add(task)
        session.commit()
        session.refresh(task)
        return task

    NOT_FOUND = {404: {"description": "Task not found"}}

    @application.get("/api/tasks/{task_id}", response_model=TaskRead, responses=NOT_FOUND)
    def get_task(task_id: TaskId, session: SessionDep) -> Task:
        return _get_task(session, task_id)

    @application.patch(
        "/api/tasks/{task_id}",
        response_model=TaskRead,
        responses=NOT_FOUND | BAD_BODY,
    )
    def update_task(task_id: TaskId, payload: TaskUpdate, session: SessionDep) -> Task:
        task = _get_task(session, task_id)
        for key, value in payload.model_dump(exclude_unset=True, exclude_none=True).items():
            setattr(task, key, value)
        session.add(task)
        session.commit()
        session.refresh(task)
        return task

    @application.delete("/api/tasks/{task_id}", status_code=204, responses=NOT_FOUND)
    def delete_task(task_id: TaskId, session: SessionDep) -> None:
        task = _get_task(session, task_id)
        session.delete(task)
        session.commit()

    if os.environ.get("APP_ENV") == "test":

        @application.post("/api/testing/reset", status_code=204)
        def reset(session: SessionDep) -> None:
            for task in session.exec(select(Task)).all():
                session.delete(task)
            session.commit()

    return application


app = create_app()
