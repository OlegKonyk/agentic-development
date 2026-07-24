"""Taskboard web UI: server-rendered pages proxying the JSON API."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

STATUS_COLUMNS = ("todo", "doing", "done")
NEXT_STATUS = {"todo": "doing", "doing": "done", "done": "done"}

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app() -> FastAPI:
    api_base_url = os.environ.get("API_BASE_URL", "http://localhost:8000")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.client = httpx.AsyncClient(base_url=api_base_url, timeout=5.0)
        yield
        await app.state.client.aclose()

    app = FastAPI(title="taskboard-web", lifespan=lifespan)
    templates = Jinja2Templates(directory=TEMPLATES_DIR)

    def api(request: Request) -> httpx.AsyncClient:
        return request.app.state.client

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        columns: dict[str, list[dict]] = {status: [] for status in STATUS_COLUMNS}
        api_error = False
        task_count: int | None = None
        try:
            resp = await api(request).get("/api/tasks")
            resp.raise_for_status()
            tasks = resp.json()
            task_count = len(tasks)
            for task in tasks:
                columns.setdefault(task.get("status", "todo"), []).append(task)
        except httpx.HTTPError:
            api_error = True
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "columns": columns,
                "statuses": STATUS_COLUMNS,
                "api_error": api_error,
                "task_count": task_count,
            },
        )

    @app.get("/new", response_class=HTMLResponse)
    async def new_form(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "new.html", {"api_error": False})

    @app.post("/new", response_model=None)
    async def create_task(
        request: Request,
        title: Annotated[str, Form()],
        description: Annotated[str, Form()] = "",
    ) -> HTMLResponse | RedirectResponse:
        try:
            resp = await api(request).post(
                "/api/tasks", json={"title": title, "description": description}
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            return templates.TemplateResponse(
                request,
                "new.html",
                {"api_error": True, "title": title, "description": description},
            )
        return RedirectResponse(url="/", status_code=303)

    @app.post("/tasks/{task_id}/advance")
    async def advance_task(request: Request, task_id: int) -> RedirectResponse:
        try:
            resp = await api(request).get(f"/api/tasks/{task_id}")
            if resp.status_code == 200:
                current = resp.json().get("status")
                nxt = NEXT_STATUS.get(current)
                if nxt is not None and nxt != current:
                    await api(request).patch(f"/api/tasks/{task_id}", json={"status": nxt})
        except httpx.HTTPError:
            pass  # index will surface the api-error banner
        return RedirectResponse(url="/", status_code=303)

    @app.post("/tasks/{task_id}/delete")
    async def delete_task(request: Request, task_id: int) -> RedirectResponse:
        with suppress(httpx.HTTPError):
            await api(request).delete(f"/api/tasks/{task_id}")
        return RedirectResponse(url="/", status_code=303)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
