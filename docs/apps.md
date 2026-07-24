# Demo Apps — Contracts

The apps are deliberately simple; they exist to give the pipeline something real
to specify, build, test, and deploy. These contracts are load-bearing: QA tests,
the gateway, and agent prompts all assume them.

## Domain: Taskboard

A minimal task tracker. `Task = {id: int, title: str, description: str | "",
status: "todo"|"doing"|"done", created_at: iso8601}`.

## apps/api — FastAPI JSON API (port 8000)

- Package `taskboard-api`, module `app`, run: `uv run uvicorn app.main:app --port 8000`
- Storage: SQLite via SQLModel; file at `$DATA_DIR/tasks.db` (default `./data`)
- Endpoints:
  - `GET /healthz` → `{"status": "ok"}`
  - `GET /api/tasks` → list (optional `?status=` filter)
  - `POST /api/tasks` `{title, description?}` → 201, task (title required, 1..200 chars)
  - `GET /api/tasks/{id}` → task or 404
  - `PATCH /api/tasks/{id}` `{title?, description?, status?}` → task; invalid status → 422
  - `DELETE /api/tasks/{id}` → 204
  - `POST /api/testing/reset` → 204, wipes all tasks. **Only mounted when `APP_ENV=test`.**
- OpenAPI at `/openapi.json` (drives Schemathesis).
- Seeding: `uv run python -m app.seed` — idempotent, fixed dataset (3 known tasks),
  used by QA for a deterministic starting state.

## apps/web — server-rendered UI (port 8001)

- Package `taskboard-web`, module `web`, run: `uv run uvicorn web.main:app --port 8001`
- FastAPI + Jinja2, plain HTML forms (no JS framework). Talks to the API via
  `API_BASE_URL` env (default `http://localhost:8000`).
- Pages:
  - `GET /` — task list grouped by status; each row shows title + status
  - `GET /new` — create form; `POST /new` submits then redirects to `/`
  - `POST /tasks/{id}/advance` — todo→doing→done, redirect to `/`
  - `POST /tasks/{id}/delete` — redirect to `/`
  - `GET /healthz` → `{"status": "ok"}`
- Stable selectors for Playwright: `data-testid="task-list"`, `task-row`,
  `task-title`, `task-status`, `new-task-link`, `title-input`,
  `description-input`, `submit-task`, `advance-btn`, `delete-btn`.

## gateway — Cloudflare Worker (dev port 8787)

- Wrangler v4, `wrangler.jsonc`, TypeScript, `workers_dev: true`.
- Routing: `/api/*` and `/openapi.json` → `API_ORIGIN`; `/gw/healthz` handled in
  the Worker; everything else → `WEB_ORIGIN`. Origins come from vars
  (local defaults `http://localhost:8000` / `http://localhost:8001` via `.dev.vars`).
- Logic (the "little gateway with logic" requirement):
  - API-key check: requests to `/api/*` must send `x-api-key` matching the
    `GATEWAY_API_KEY` var (dev default `dev-key`); `/healthz`, `/openapi.json`
    exempt. 401 JSON on failure.
  - Injects `x-request-id` (uuid) into upstream requests and echoes it in responses.
  - Naive per-isolate rate limit: >60 req/10s per key → 429 (documented as
    per-colo/per-isolate; the GA Rate Limiting binding is the production path).
  - Structured JSON access log via `console.log` (`observability.enabled: true`).
- `GET /gw/healthz` → `{"status":"ok","gateway":"agentic-gateway"}` without auth.

## Local orchestration

- `docker-compose.yml` (repo root): services `api` (8000) and `web` (8001) with
  healthchecks; `docker compose up -d --wait` blocks until healthy. Both
  Dockerfiles build from the repo root (uv workspace).
- Gateway runs on the host: `npm ci && npx wrangler dev` in `gateway/` (CI runs
  it as a background step; `make dev` does both).
- E2E base URL is the gateway: `http://localhost:8787`.

## Python layout

uv workspace (root `pyproject.toml`, members `apps/api`, `apps/web`, `qa`,
`watcher`), Python >= 3.12, one `uv.lock` at the root. Lint: `ruff check` +
`ruff format --check` (config in root pyproject).

## QA suites (qa/)

- `qa/tests/e2e/` — pytest-playwright, `--base-url http://localhost:8787`,
  sends `x-api-key` via API helper where needed; covers create→advance→done→delete.
- `qa/tests/contract/` — Schemathesis v4 in-process/URL run against
  `http://localhost:8000/openapi.json` (direct to API, deterministic seed).
- `qa/seed_check.py` style helpers live in the `qa` package.
