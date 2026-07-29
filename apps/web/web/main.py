"""Taskboard web UI: server-rendered pages proxying the JSON API (v2, authed)."""

import json
import math
import os
import re
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

STATUS_COLUMNS = ("todo", "doing", "done")
NEXT_STATUS = {"todo": "doing", "doing": "done", "done": "done"}
PREV_STATUS = {"done": "doing", "doing": "todo", "todo": "todo"}
# The web passes `limit` explicitly rather than relying on the API default, so
# a future API default change can't silently resize the board.
BOARD_PAGE_SIZE = 20


def normalize_status(value: str | None) -> str | None:
    """Return `value` when it names a board column, else None (= 'all')."""
    return value if value in STATUS_COLUMNS else None


def parse_page(value: str | None) -> int:
    """1-based page number; anything absent, blank, non-numeric or < 1 -> 1."""
    with suppress(ValueError, TypeError):
        page = int(value)
        if page >= 1:
            return page
    return 1


SEARCH_MAX_LENGTH = 1000  # mirrors the API's SEARCH_MAX_LENGTH bound


def normalize_search(value: str | None) -> str:
    """The board's search term: trimmed, storable, bounded. '' means no search.

    The board is lenient by construction (same posture as `status`/`page`): it
    must render 200 for anything a user can type, so unstorable characters are
    dropped and the term is clamped rather than forwarded into an API 422.
    Clamping is result-preserving — titles are <=200 chars, so no term longer
    than that can match anything.
    """
    term = (value or "").replace("\x00", "")
    term = term.encode("utf-8", "replace").decode("utf-8")  # drop lone surrogates
    return term.strip()[:SEARCH_MAX_LENGTH]


def board_url(status: str | None, page: int = 1, search: str = "") -> str:
    """Board URL carrying the active filter, search term, and page; '/' when at defaults."""
    params = []
    if status:
        params.append(f"status={status}")
    if search:
        params.append(f"q={quote(search, safe='')}")
    if page != 1:
        params.append(f"page={page}")
    return f"/?{'&'.join(params)}" if params else "/"


def edit_url(task_id: int, status: str | None = None, page: int = 1, search: str = "") -> str:
    """Edit-page URL carrying the board the user came from; mirrors board_url()."""
    params = []
    if status:
        params.append(f"status={status}")
    if search:
        params.append(f"q={quote(search, safe='')}")
    if page != 1:
        params.append(f"page={page}")
    query = f"?{'&'.join(params)}" if params else ""
    return f"/tasks/{task_id}/edit{query}"


def empty_state(
    api_error: bool, active: str | None, total: int | None, search: str = ""
) -> str | None:
    """Which empty message the board shows: 'board', 'filter', 'search', or None.

    A failed tasks fetch never reads as "you have no tasks" — the `api-error`
    banner owns that case. `total` is the total of the *rendered* set (the
    matched set when a search is active, the filtered set when a filter is
    active), so exactly one of the messages can apply. A search takes
    precedence over the filter message when both are active.
    """
    if api_error or total:
        return None
    if total is None:
        return None
    if search:
        return "search"
    return "filter" if active else "board"


def filter_options(active: str | None, search: str = "") -> list[dict[str, object]]:
    """The four filter links in order (all, todo, doing, done), active one marked."""
    values: tuple[str | None, ...] = (None, *STATUS_COLUMNS)
    return [
        {
            "value": value,
            "label": value or "all",
            "testid": f"filter-{value or 'all'}",
            "href": board_url(value, 1, search),
            "active": value == active,
        }
        for value in values
    ]


TEMPLATES_DIR = Path(__file__).parent / "templates"

API_UNAVAILABLE_MESSAGE = "The task API is unavailable. Please try again shortly."
INVALID_TITLE_MESSAGE = "Title must contain at least one non-whitespace character."
INVALID_INPUT_MESSAGE = "Please check the task details and try again."
REMINDER_HEALTH_TIMEOUT = 2.0
REMINDER_HEALTH_PATH = "/api/reminders/health"
DEGRADED_REMINDERS_MESSAGE = (
    "Reminder delivery is currently degraded — your reminders may be delayed."
)


def reminder_health_url(api_base_url: str) -> str:
    """Origin for the health call. `REMINDER_HEALTH_BASE_URL` (test profile) routes it
    through a dedicated proxy so a fault can hit this call alone; unset -> same origin
    as every other API call."""
    base = os.environ.get("REMINDER_HEALTH_BASE_URL", "").strip() or api_base_url
    return f"{base.rstrip('/')}{REMINDER_HEALTH_PATH}"


class AuthRedirect(Exception):
    """Raised when a protected page is hit without a session token."""

    def __init__(self, url: str) -> None:
        self.url = url


DRAFT_MAX_BYTES = 1800  # signed session cookie must stay well under browsers' ~4 KiB limit


def draft_fits(draft: dict[str, str]) -> bool:
    """True when the draft is small enough to ride in the session cookie."""
    return len(json.dumps(draft, separators=(",", ":")).encode()) <= DRAFT_MAX_BYTES


def same_user(owner: str | None, email: str | None) -> bool:
    """True only when a stashed draft belongs to the signed-in account."""
    if not owner or not email:
        return False
    return owner.strip().casefold() == email.strip().casefold()


class SessionExpired(Exception):
    """Raised when the API rejects the stored bearer token (401 mid-session).

    `next_url` is where the user should land after signing back in; `draft` is
    the typed new-task input to carry across the re-login.
    """

    def __init__(self, next_url: str | None = None, draft: dict[str, str] | None = None) -> None:
        self.next_url = next_url
        self.draft = draft


def safe_next(target: str | None) -> str:
    """Allow only same-site relative paths for post-login redirects."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"


TZ_COOKIE = "tz"
TZ_COOKIE_MAX_AGE = 31_536_000
UTC_ZONE = ZoneInfo("UTC")
# IANA keys are letters, digits, and _ + - / only; the bound blocks junk cookies
# before zoneinfo ever touches the filesystem.
ZONE_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+/-]{0,63}$")


def resolve_zone(raw: str | None) -> ZoneInfo:
    """Viewer's zone from the `tz` cookie; UTC when absent, malformed, or unknown."""
    key = (raw or "").strip()
    if ZONE_KEY_RE.fullmatch(key) and ".." not in key:
        with suppress(ZoneInfoNotFoundError, ValueError):
            return ZoneInfo(key)
    return UTC_ZONE


def to_rfc3339_z(value: str, zone: ZoneInfo) -> str:
    """Convert a datetime-local form value, interpreted in `zone`, to an RFC3339 UTC timestamp."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone)
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


def local_input_value(due_at: str | None, zone: ZoneInfo) -> str:
    """A task's RFC3339 `due_at` as the `datetime-local` value the form shows;
    '' when the task is undated or the timestamp is unparseable."""
    dt = parse_due_at(due_at)
    return "" if dt is None else dt.astimezone(zone).strftime("%Y-%m-%dT%H:%M")


def normalize_input_value(raw: str, zone: ZoneInfo) -> str:
    """A submitted `datetime-local` value in the same canonical minute form;
    '' when blank. Raises ValueError when unparseable."""
    value = raw.strip()
    return local_input_value(to_rfc3339_z(value, zone), zone) if value else ""


def format_due_at(value: datetime, zone: ZoneInfo) -> str:
    """Render an aware datetime in `zone`, e.g. '25 Jul 2026, 12:34 (Europe/Berlin)'."""
    at = value.astimezone(zone)
    return f"{at.day:02d} {MONTHS[at.month - 1]} {at.year}, {at:%H:%M} ({zone.key})"


def decorate_tasks(tasks: list[dict], now: datetime, zone: ZoneInfo) -> list[dict]:
    """Add `due_label`/`overdue` presentation keys and sort by urgency in place."""
    decorated = []
    for task in tasks:
        due = parse_due_at(task.get("due_at"))
        task["due_label"] = format_due_at(due, zone) if due else None
        task["overdue"] = due is not None and due < now
        decorated.append((due or UNDATED, task.get("id") or 0, task))
    decorated.sort(key=lambda item: item[:2])
    return [task for _, _, task in decorated]


def title_rejected(detail: object) -> bool:
    """True when a FastAPI validation `detail` rejects the `title` field."""
    if not isinstance(detail, list):
        return False
    return any(isinstance(item, dict) and "title" in (item.get("loc") or []) for item in detail)


async def reminders_degraded(
    client: httpx.AsyncClient, token: str, url: str = REMINDER_HEALTH_PATH
) -> bool:
    """True only on a definite `degraded`; any doubt reads as healthy."""
    try:
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=REMINDER_HEALTH_TIMEOUT,
        )
        if resp.status_code != 200:
            return False
        return resp.json().get("state") == "degraded"
    except (httpx.HTTPError, ValueError):
        return False


def create_app() -> FastAPI:
    api_base_url = os.environ.get("API_BASE_URL", "http://localhost:8000")
    health_url = reminder_health_url(api_base_url)
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
            target = request.url.path
            if request.url.query:
                target = f"{target}?{request.url.query}"
            raise AuthRedirect(f"/login?next={quote(target)}")
        return token

    def bearer(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    async def shift_status(
        request: Request, task_id: int, token: str, moves: dict[str, str]
    ) -> None:
        """Move a task one column per `moves`; a no-op when the map is a fixed point."""
        try:
            resp = await api(request).get(f"/api/tasks/{task_id}", headers=bearer(token))
            if resp.status_code == 401:
                raise SessionExpired
            if resp.status_code == 200:
                current = resp.json().get("status")
                nxt = moves.get(current)
                if nxt is not None and nxt != current:
                    patched = await api(request).patch(
                        f"/api/tasks/{task_id}", json={"status": nxt}, headers=bearer(token)
                    )
                    if patched.status_code == 401:
                        raise SessionExpired
        except httpx.HTTPError:
            pass  # index will surface the api-error banner

    @app.exception_handler(AuthRedirect)
    async def on_auth_redirect(request: Request, exc: AuthRedirect) -> RedirectResponse:
        return RedirectResponse(url=exc.url, status_code=303)

    @app.exception_handler(SessionExpired)
    async def on_session_expired(request: Request, exc: SessionExpired) -> RedirectResponse:
        owner = request.session.get("email")
        request.session.clear()  # the dead token and csrf go, unconditionally
        request.session["expired"] = True
        if exc.draft and owner and draft_fits(exc.draft):
            request.session["draft"] = exc.draft
            request.session["draft_owner"] = owner
        url = f"/login?next={quote(exc.next_url)}" if exc.next_url else "/login"
        return RedirectResponse(url=url, status_code=303)

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request, next: str = "/") -> HTMLResponse:
        zone = resolve_zone(request.cookies.get(TZ_COOKIE))
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "csrf": ensure_csrf(request),
                "next": safe_next(next),
                "error": False,
                "session_expired": bool(request.session.get("expired")),
                "tz_name": zone.key,
                "tz_sync": True,
            },
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
            request.session["email"] = email.strip()
            request.session.pop("expired", None)
            if not same_user(request.session.get("draft_owner"), email):
                request.session.pop("draft", None)
                request.session.pop("draft_owner", None)
            return RedirectResponse(url=safe_next(next), status_code=303)
        zone = resolve_zone(request.cookies.get(TZ_COOKIE))
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "csrf": ensure_csrf(request),
                "next": safe_next(next),
                "error": True,
                "session_expired": bool(request.session.get("expired")),
                "tz_name": zone.key,
                "tz_sync": False,
            },
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
    async def index(
        request: Request,
        status: str | None = None,
        q: str | None = None,
        page: str | None = None,
    ) -> HTMLResponse:
        token = require_token(request)
        zone = resolve_zone(request.cookies.get(TZ_COOKIE))
        active = normalize_status(status)
        search = normalize_search(q)
        visible = (active,) if active else STATUS_COLUMNS
        columns: dict[str, list[dict]] = {status: [] for status in STATUS_COLUMNS}
        current = parse_page(page)
        page_count = 1
        task_count = 0
        view_total: int | None = None
        user_email: str | None = None
        api_error = False
        try:
            me = await api(request).get("/api/auth/me", headers=bearer(token))
            if me.status_code == 401:
                raise SessionExpired
            me.raise_for_status()
            user_email = me.json()["email"]

            async def fetch_page(current_page: int) -> dict:
                params: dict[str, str | int] = {
                    "limit": BOARD_PAGE_SIZE,
                    "offset": (current_page - 1) * BOARD_PAGE_SIZE,
                }
                if active:
                    params["status"] = active
                if search:
                    params["q"] = search
                resp = await api(request).get("/api/tasks", params=params, headers=bearer(token))
                if resp.status_code == 401:
                    raise SessionExpired
                resp.raise_for_status()
                return resp.json()

            body = await fetch_page(current)
            page_count = max(1, math.ceil(body["total"] / BOARD_PAGE_SIZE))
            if current > page_count:
                current = 1
                body = await fetch_page(current)
            view_total = body["total"]
            for task in body["items"]:
                columns.setdefault(task.get("status", "todo"), []).append(task)
            if active or search:
                count_resp = await api(request).get(
                    "/api/tasks", params={"limit": 1}, headers=bearer(token)
                )
                if count_resp.status_code == 401:
                    raise SessionExpired
                count_resp.raise_for_status()
                task_count = count_resp.json()["total"]
            else:
                task_count = body["total"]
        except httpx.HTTPError:
            api_error = True
        # Skip the health round-trip when the tasks fetch already failed: a
        # second doomed call adds nothing, and AC-8 requires the api-error
        # banner to show without the degraded banner alongside it.
        degraded = False if api_error else await reminders_degraded(api(request), token, health_url)
        empty = empty_state(api_error, active, view_total, search)
        now = datetime.now(UTC)
        columns = {status: decorate_tasks(tasks, now, zone) for status, tasks in columns.items()}
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "columns": columns,
                "statuses": visible,
                "filters": filter_options(active, search),
                "active_status": active,
                "search": search,
                "api_error": api_error,
                "empty_state": empty,
                "authed": True,
                "user_email": user_email,
                "task_count": task_count,
                "csrf": ensure_csrf(request),
                "reminders_degraded": degraded,
                "page": current,
                "page_count": page_count,
                "has_prev": current > 1,
                "has_next": current < page_count,
                "prev_url": board_url(active, current - 1, search),
                "next_url": board_url(active, current + 1, search),
                "tz_name": zone.key,
                "tz_sync": True,
                "edit_url": edit_url,
                "board_url": board_url,
            },
        )

    @app.get("/new", response_class=HTMLResponse)
    async def new_form(request: Request) -> HTMLResponse:
        require_token(request)
        zone = resolve_zone(request.cookies.get(TZ_COOKIE))
        draft: dict[str, str] = {}
        if same_user(request.session.get("draft_owner"), request.session.get("email")):
            draft = request.session.get("draft") or {}
        return templates.TemplateResponse(
            request,
            "new.html",
            {
                "api_error": False,
                "authed": True,
                "csrf": ensure_csrf(request),
                "title": draft.get("title", ""),
                "description": draft.get("description", ""),
                "due_at": draft.get("due_at", ""),
                "tz_name": zone.key,
                "tz_sync": True,
            },
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
        request.session.pop("draft", None)
        request.session.pop("draft_owner", None)
        zone = resolve_zone(request.cookies.get(TZ_COOKIE))
        payload: dict[str, str] = {"title": title, "description": description}
        api_error = False
        error_message = API_UNAVAILABLE_MESSAGE
        try:
            if due_at.strip():
                payload["due_at"] = to_rfc3339_z(due_at.strip(), zone)
            resp = await api(request).post("/api/tasks", json=payload, headers=bearer(token))
            if resp.status_code == 401:
                raise SessionExpired(
                    next_url="/new",
                    draft={"title": title, "description": description, "due_at": due_at},
                )
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
                    "tz_name": zone.key,
                    "tz_sync": False,
                },
            )
        return RedirectResponse(url="/", status_code=303)

    @app.get("/tasks/{task_id}/edit", response_model=None)
    async def edit_form(
        request: Request,
        task_id: int,
        status: str | None = None,
        q: str | None = None,
        page: str | None = None,
    ) -> HTMLResponse | RedirectResponse:
        token = require_token(request)
        zone = resolve_zone(request.cookies.get(TZ_COOKIE))
        active = normalize_status(status)
        search = normalize_search(q)
        current_page = parse_page(page)
        back = board_url(active, current_page, search)
        here = edit_url(task_id, active, current_page, search)
        try:
            resp = await api(request).get(f"/api/tasks/{task_id}", headers=bearer(token))
            if resp.status_code == 401:
                raise SessionExpired(next_url=here)
            if resp.status_code == 404:
                return RedirectResponse(url=back, status_code=303)
            resp.raise_for_status()
        except httpx.HTTPError:
            return templates.TemplateResponse(
                request,
                "edit.html",
                {
                    "api_error": True,
                    "error_message": API_UNAVAILABLE_MESSAGE,
                    "authed": True,
                    "csrf": ensure_csrf(request),
                    "task_id": task_id,
                    "title": "",
                    "description": "",
                    "due_at": "",
                    "status": active or "",
                    "search": search,
                    "page": current_page,
                    "board_url": back,
                    "tz_name": zone.key,
                    "tz_sync": False,
                },
            )
        task = resp.json()
        return templates.TemplateResponse(
            request,
            "edit.html",
            {
                "authed": True,
                "csrf": ensure_csrf(request),
                "task_id": task_id,
                "title": task["title"],
                "description": task["description"],
                "due_at": local_input_value(task["due_at"], zone),
                "status": active or "",
                "search": search,
                "page": current_page,
                "board_url": back,
                "api_error": False,
                "tz_name": zone.key,
                "tz_sync": True,
            },
        )

    @app.post("/tasks/{task_id}/edit", response_model=None)
    async def save_task(
        request: Request,
        task_id: int,
        title: Annotated[str, Form()],
        description: Annotated[str, Form()] = "",
        due_at: Annotated[str, Form()] = "",
        csrf_token: Annotated[str, Form()] = "",
        status: Annotated[str, Form()] = "",
        q: Annotated[str, Form()] = "",
        page: Annotated[str, Form()] = "",
    ) -> HTMLResponse | RedirectResponse:
        check_csrf(request, csrf_token)
        token = require_token(request)
        zone = resolve_zone(request.cookies.get(TZ_COOKIE))
        active = normalize_status(status)
        search = normalize_search(q)
        current_page = parse_page(page)
        back = board_url(active, current_page, search)
        here = edit_url(task_id, active, current_page, search)

        def rerender(error_message: str) -> HTMLResponse:
            return templates.TemplateResponse(
                request,
                "edit.html",
                {
                    "api_error": True,
                    "error_message": error_message,
                    "authed": True,
                    "csrf": ensure_csrf(request),
                    "task_id": task_id,
                    "title": title,
                    "description": description,
                    "due_at": due_at,
                    "status": active or "",
                    "search": search,
                    "page": current_page,
                    "board_url": back,
                    "tz_name": zone.key,
                    "tz_sync": False,
                },
            )

        try:
            existing = await api(request).get(f"/api/tasks/{task_id}", headers=bearer(token))
            if existing.status_code == 401:
                raise SessionExpired(next_url=here)
            if existing.status_code == 404:
                return RedirectResponse(url=back, status_code=303)
            existing.raise_for_status()
        except httpx.HTTPError:
            return rerender(API_UNAVAILABLE_MESSAGE)

        current = local_input_value(existing.json().get("due_at"), zone)
        try:
            submitted = normalize_input_value(due_at, zone)
        except ValueError:
            return rerender(INVALID_INPUT_MESSAGE)

        payload: dict[str, object] = {"title": title, "description": description}
        if submitted != current:
            payload["due_at"] = to_rfc3339_z(submitted, zone) if submitted else None

        try:
            resp = await api(request).patch(
                f"/api/tasks/{task_id}", json=payload, headers=bearer(token)
            )
            if resp.status_code == 401:
                raise SessionExpired(next_url=here)
            if resp.status_code == 404:
                return RedirectResponse(url=back, status_code=303)
            if resp.status_code == 422:
                body: dict = {}
                with suppress(ValueError):
                    body = resp.json()
                message = (
                    INVALID_TITLE_MESSAGE
                    if title_rejected(body.get("detail"))
                    else INVALID_INPUT_MESSAGE
                )
                return rerender(message)
            resp.raise_for_status()
        except httpx.HTTPError:
            return rerender(API_UNAVAILABLE_MESSAGE)
        return RedirectResponse(url=back, status_code=303)

    @app.post("/tasks/{task_id}/advance")
    async def advance_task(
        request: Request,
        task_id: int,
        csrf_token: Annotated[str, Form()] = "",
        status: Annotated[str, Form()] = "",
        q: Annotated[str, Form()] = "",
        page: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        check_csrf(request, csrf_token)
        token = require_token(request)
        await shift_status(request, task_id, token, NEXT_STATUS)
        url = board_url(normalize_status(status), parse_page(page), normalize_search(q))
        return RedirectResponse(url=url, status_code=303)

    @app.post("/tasks/{task_id}/move-back")
    async def move_task_back(
        request: Request,
        task_id: int,
        csrf_token: Annotated[str, Form()] = "",
        status: Annotated[str, Form()] = "",
        q: Annotated[str, Form()] = "",
        page: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        check_csrf(request, csrf_token)
        token = require_token(request)
        await shift_status(request, task_id, token, PREV_STATUS)
        url = board_url(normalize_status(status), parse_page(page), normalize_search(q))
        return RedirectResponse(url=url, status_code=303)

    @app.post("/tasks/{task_id}/delete")
    async def delete_task(
        request: Request,
        task_id: int,
        csrf_token: Annotated[str, Form()] = "",
        status: Annotated[str, Form()] = "",
        q: Annotated[str, Form()] = "",
        page: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        check_csrf(request, csrf_token)
        token = require_token(request)
        try:
            resp = await api(request).delete(f"/api/tasks/{task_id}", headers=bearer(token))
            if resp.status_code == 401:
                raise SessionExpired
        except httpx.HTTPError:
            pass  # index will surface the api-error banner
        url = board_url(normalize_status(status), parse_page(page), normalize_search(q))
        return RedirectResponse(url=url, status_code=303)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
