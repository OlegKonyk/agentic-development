"""Taskboard web UI: server-rendered pages proxying the JSON API (v2, authed)."""

import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

STATUS_COLUMNS = ("todo", "doing", "done")
NEXT_STATUS = {"todo": "doing", "doing": "done", "done": "done"}

TEMPLATES_DIR = Path(__file__).parent / "templates"

API_UNAVAILABLE_MESSAGE = "The task API is unavailable. Please try again shortly."
INVALID_TITLE_MESSAGE = "Title must contain at least one non-whitespace character."
INVALID_INPUT_MESSAGE = "Please check the task details and try again."


class AuthRedirect(Exception):
    """Raised when a protected page is hit without a session token."""

    def __init__(self, url: str) -> None:
        self.url = url


class SessionExpired(Exception):
    """Raised when the API rejects the stored bearer token (401 mid-session)."""


def safe_next(target: str | None) -> str:
    """Allow only same-site relative paths for post-login redirects."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"


def to_rfc3339_z(value: str) -> str:
    """Convert a datetime-local form value to an RFC3339 UTC ``Z`` timestamp."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

# Undated tasks sort after every dated one.
UNDATED = datetime.max.replace(tzinfo=UTC)


def parse_due_at(value: str | None) -> datetime | None:
    """Parse an RFC3339 `due_at` into an aware UTC datetime, or None if absent/invalid."""
    if not value:
        return None
    with suppress(ValueError):
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return None


def format_due_at(value: datetime) -> str:
    """Render an aware datetime as a human-readable UTC label, e.g. '25 Jul 2026, 12:34 UTC'."""
    at = value.astimezone(UTC)
    return f"{at.day:02d} {MONTHS[at.month - 1]} {at.year}, {at:%H:%M} UTC"


def decorate_tasks(tasks: list[dict], now: datetime) -> list[dict]:
    """Add `due_label`/`overdue` presentation keys and sort by urgency in place."""
    decorated = []
    for task in tasks:
        due = parse_due_at(task.get("due_at"))
        task["due_label"] = format_due_at(due) if due else None
        task["overdue"] = due is not None and due < now
        decorated.append((due or UNDATED, task.get("id") or 0, task))
    decorated.sort(key=lambda item: item[:2])
    return [task for _, _, task in decorated]


def title_rejected(detail: object) -> bool:
    """True when a FastAPI validation `detail` rejects the `title` field."""
    if not isinstance(detail, list):
        return False
    return any(isinstance(item, dict) and "title" in (item.get("loc") or []) for item in detail)


def create_app() -> FastAPI:
    api_base_url = os.environ.get("API_BASE_URL", "http://localhost:8000")
    secret_key = os.environ.get("SECRET_KEY", "dev-session-secret")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.client = httpx.AsyncClient(base_url=api_base_url, timeout=5.0)
        yield
        await app.state.client.aclose()

    app = FastAPI(title="taskboard-web", lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=secret_key, same_site="lax", https_only=False)
    templates = Jinja2Templates(directory=TEMPLATES_DIR)

    def api(request: Request) -> httpx.AsyncClient:
        return request.app.state.client

    def ensure_csrf(request: Request) -> str:
        token = request.session.get("csrf")
        if not token:
            token = secrets.token_urlsafe(32)
            request.session["csrf"] = token
        return token

    def check_csrf(request: Request, submitted: str) -> None:
        expected = request.session.get("csrf")
        if not expected or not submitted or not secrets.compare_digest(expected, submitted):
            raise HTTPException(status_code=403, detail="CSRF token mismatch")

    def require_token(request: Request) -> str:
        token = request.session.get("token")
        if not token:
            raise AuthRedirect(f"/login?next={quote(request.url.path)}")
        return token

    def bearer(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    @app.exception_handler(AuthRedirect)
    async def on_auth_redirect(request: Request, exc: AuthRedirect) -> RedirectResponse:
        return RedirectResponse(url=exc.url, status_code=303)

    @app.exception_handler(SessionExpired)
    async def on_session_expired(request: Request, exc: SessionExpired) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request, next: str = "/") -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"csrf": ensure_csrf(request), "next": safe_next(next), "error": False},
        )

    @app.post("/login", response_model=None)
    async def login(
        request: Request,
        email: Annotated[str, Form()],
        password: Annotated[str, Form()],
        csrf_token: Annotated[str, Form()] = "",
        next: Annotated[str, Form()] = "/",
    ) -> HTMLResponse | RedirectResponse:
        check_csrf(request, csrf_token)
        try:
            resp = await api(request).post(
                "/api/auth/login", json={"email": email, "password": password}
            )
        except httpx.HTTPError:
            resp = None
        if resp is not None and resp.status_code == 200:
            request.session["token"] = resp.json()["token"]
            return RedirectResponse(url=safe_next(next), status_code=303)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"csrf": ensure_csrf(request), "next": safe_next(next), "error": True},
        )

    @app.post("/logout")
    async def logout(request: Request, csrf_token: Annotated[str, Form()] = "") -> RedirectResponse:
        check_csrf(request, csrf_token)
        token = request.session.get("token")
        if token:
            with suppress(httpx.HTTPError):  # session is cleared regardless
                await api(request).post("/api/auth/logout", headers=bearer(token))
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        token = require_token(request)
        columns: dict[str, list[dict]] = {status: [] for status in STATUS_COLUMNS}
        task_count = 0
        user_email: str | None = None
        api_error = False
        try:
            me = await api(request).get("/api/auth/me", headers=bearer(token))
            if me.status_code == 401:
                raise SessionExpired
            me.raise_for_status()
            user_email = me.json()["email"]
            resp = await api(request).get("/api/tasks", headers=bearer(token))
            if resp.status_code == 401:
                raise SessionExpired
            resp.raise_for_status()
            for task in resp.json():
                columns.setdefault(task.get("status", "todo"), []).append(task)
                task_count += 1
        except httpx.HTTPError:
            api_error = True
        now = datetime.now(UTC)
        columns = {status: decorate_tasks(tasks, now) for status, tasks in columns.items()}
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "columns": columns,
                "statuses": STATUS_COLUMNS,
                "api_error": api_error,
                "authed": True,
                "user_email": user_email,
                "task_count": task_count,
                "csrf": ensure_csrf(request),
            },
        )

    @app.get("/new", response_class=HTMLResponse)
    async def new_form(request: Request) -> HTMLResponse:
        require_token(request)
        return templates.TemplateResponse(
            request,
            "new.html",
            {"api_error": False, "authed": True, "csrf": ensure_csrf(request)},
        )

    @app.post("/new", response_model=None)
    async def create_task(
        request: Request,
        title: Annotated[str, Form()],
        description: Annotated[str, Form()] = "",
        due_at: Annotated[str, Form()] = "",
        csrf_token: Annotated[str, Form()] = "",
    ) -> HTMLResponse | RedirectResponse:
        check_csrf(request, csrf_token)
        token = require_token(request)
        payload: dict[str, str] = {"title": title, "description": description}
        api_error = False
        error_message = API_UNAVAILABLE_MESSAGE
        try:
            if due_at.strip():
                payload["due_at"] = to_rfc3339_z(due_at.strip())
            resp = await api(request).post("/api/tasks", json=payload, headers=bearer(token))
            if resp.status_code == 401:
                raise SessionExpired
            if resp.status_code == 422:
                api_error = True
                body: dict = {}
                with suppress(ValueError):
                    body = resp.json()
                error_message = (
                    INVALID_TITLE_MESSAGE
                    if title_rejected(body.get("detail"))
                    else INVALID_INPUT_MESSAGE
                )
            else:
                resp.raise_for_status()
        except (httpx.HTTPError, ValueError):
            api_error = True
        if api_error:
            return templates.TemplateResponse(
                request,
                "new.html",
                {
                    "api_error": True,
                    "error_message": error_message,
                    "authed": True,
                    "csrf": ensure_csrf(request),
                    "title": title,
                    "description": description,
                    "due_at": due_at,
                },
            )
        return RedirectResponse(url="/", status_code=303)

    @app.post("/tasks/{task_id}/advance")
    async def advance_task(
        request: Request, task_id: int, csrf_token: Annotated[str, Form()] = ""
    ) -> RedirectResponse:
        check_csrf(request, csrf_token)
        token = require_token(request)
        try:
            resp = await api(request).get(f"/api/tasks/{task_id}", headers=bearer(token))
            if resp.status_code == 401:
                raise SessionExpired
            if resp.status_code == 200:
                current = resp.json().get("status")
                nxt = NEXT_STATUS.get(current)
                if nxt is not None and nxt != current:
                    patched = await api(request).patch(
                        f"/api/tasks/{task_id}", json={"status": nxt}, headers=bearer(token)
                    )
                    if patched.status_code == 401:
                        raise SessionExpired
        except httpx.HTTPError:
            pass  # index will surface the api-error banner
        return RedirectResponse(url="/", status_code=303)

    @app.post("/tasks/{task_id}/delete")
    async def delete_task(
        request: Request, task_id: int, csrf_token: Annotated[str, Form()] = ""
    ) -> RedirectResponse:
        check_csrf(request, csrf_token)
        token = require_token(request)
        try:
            resp = await api(request).delete(f"/api/tasks/{task_id}", headers=bearer(token))
            if resp.status_code == 401:
                raise SessionExpired
        except httpx.HTTPError:
            pass  # index will surface the api-error banner
        return RedirectResponse(url="/", status_code=303)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
