# Demo Apps — Contracts (v2: reality-grade platform)

Binding contracts for the Taskboard platform. QA suites, the gateway, agent
prompts, and CI all assume these exactly. v2 adds: Postgres, per-user auth,
async reminder jobs, a programmable vendor, signed webhooks, and a chaos layer.

## Topology (compose services + host ports)

| Service | Image / build | Port (host) | Health |
|---|---|---|---|
| `api` | apps/api Dockerfile | 8000 | `GET /healthz` |
| `web` | apps/web Dockerfile | 8001 | `GET /healthz` |
| `worker` | api image, `taskiq worker app.tkq:broker` | — | redis heartbeat |
| `scheduler` | api image, `taskiq scheduler app.tkq:scheduler` | — | process |
| `db` | postgres:17-alpine | 5432 | `pg_isready` |
| `redis` | redis:7-alpine | 6379 | `redis-cli ping` |
| `vendor-mock` | wiremock/wiremock:3.13.2 | 8081→8080 | `GET /__admin/health` |
| `toxiproxy` | ghcr.io/shopify/toxiproxy:2.12.0 | 8474 (admin), 8667 (web→api health lever) | `GET /version` |
| gateway | wrangler dev (host, not compose) | 8787 | `GET /gw/healthz` |

CI/test profile routing (via toxiproxy listeners): api→db uses `toxiproxy:5433`,
api/worker→vendor uses `toxiproxy:8666`. web's `GET /api/reminders/health` call
uses `toxiproxy:8667` (`REMINDER_HEALTH_BASE_URL`), so it can be faulted
independently of `GET /api/tasks`; unset (dev profile) it falls back to
`API_BASE_URL`, same origin as every other web→API call. Dev profile connects
directly.
CI Postgres runs on tmpfs with `fsync=off synchronous_commit=off`.
Test harnesses raise the gateway request budget (`wrangler dev --var
RATE_LIMIT:600`; production-realistic default 60 req/10 s) — full-suite e2e
volume must not trip 429s that single tests would misread as product bugs. The
QA job sources that number from `GATEWAY_RATE_LIMIT` in `phase-qa.yml` and
pre-checks it against the collected e2e test count
(`scripts/e2e_capacity_check.py`, 1.5 requests budgeted per test); raise the
workflow env, the `gateway-dev` Makefile target, and this line together.

## Domain

- `User {id, email, password_hash, created_at}` — seeded: `alice@example.com` /
  `bob@example.com`, passwords from env `QA_ALICE_PASS` / `QA_BOB_PASS`
  (compose default `correct-horse-a` / `correct-horse-b`).
- `Session {id: uuid, user_id, created_at, expires_at}` — DB-backed: logout
  deletes the row (true revocation, replayed tokens must 401).
- `Task {id, owner_id, title 1..200 non-blank (must contain a non-whitespace
  character), description, status todo|doing|done, due_at: datetime|null,
  reminder_status none|pending|sent|failed, created_at}` — strictly scoped to
  owner.
- `WebhookEvent {id: vendor event id (unique — dedupe), received_at, payload}`.
- `ReminderDelivery {id, task_id (indexed, no FK — an outcome outlives its task),
  outcome: accepted|failed, at (tz-aware, indexed)}` — one append-only row per
  `send_reminder` job run; the source of the reminder-delivery health signal.

## apps/api — FastAPI, async SQLModel + asyncpg, Alembic (port 8000)

Auth (open): `POST /api/auth/login {email,password}` → 200 `{token, expires_at}`
(opaque session id) | 401 generic (no user enumeration). `POST /api/auth/logout`
(bearer) → 204, deletes session. `GET /api/auth/me` (bearer) → `{id, email}`.

Tasks (require `Authorization: Bearer <token>`, else 401; scoped to owner;
404 for other users' task ids — no existence leak): same CRUD surface as v1
plus `due_at` (optional RFC3339, must be future on create/update else 422) and
read-only `reminder_status`. `GET /api/tasks` returns a paginated envelope
`{items: [Task...], total, limit, offset}` — not a bare array. `limit`
(default 20, `1..100`) and `offset` (default 0, `0..2147483647`) are optional
query params, non-nullable in the schema, and compose with `status`: both the
returned page and `total` describe the filtered set. `total` ignores
`limit`/`offset` and is stable across every page of the same query; `limit`/
`offset` in the response echo the effective values (including defaults). An
`offset` past the end of the result set is `200` with `items: []` and the
correct `total` — never 404. Out-of-bounds or non-integer `limit`/`offset` →
422, same validation-error shape as `due_at`/`title` (the `offset` upper bound
guards the same asyncpg bind-overflow class as the `TaskId` path bound).
Ordering is unchanged (ascending task id). A whitespace-only `title` on create
or update → 422, same validation-error shape as `due_at`. A JSON string carrying an
unpaired UTF-16 surrogate or NUL (`\u0000`) — valid JSON, unstorable in
Postgres — → 422 on every model-validated body route (login and tasks); the
raw-body webhook route neutralizes them instead (strict `json.loads` → 400,
stored payload is `decode(errors="replace")` text). 422 bodies are themselves
safe to serialize: the echoed offending input — including undecodable raw
bytes from non-JSON content types — is sanitized. All v1
contract fixes hold (RFC3339 `Z` timestamps, documented 400/404, no nullable query params); TaskId path bound is
≤ 2^31-1, matching the INTEGER column (larger ids overflowed asyncpg → 500,
found by contract fuzzing).

Reminder health: `GET /api/reminders/health` (bearer required, else 401) → 200
`{"state": "healthy"|"degraded", "window_seconds": int}`. System-wide (not
scoped to the caller) — degraded iff the most recent `ReminderDelivery` inside
the trailing `REMINDER_HEALTH_WINDOW_SECONDS` window has outcome `failed`; a
later `accepted` clears it, and a failure aging out of the window clears it.
The response carries no task ids, counts, or timestamps, so owner-scoping is
never broken by it.

Webhooks: `POST /api/webhooks/vendor` — Standard-Webhooks-style HMAC-SHA256 of
`{webhook-id}.{webhook-timestamp}.{raw body}` using `VENDOR_WEBHOOK_SECRET`
(compose default `whsec_test`), headers `webhook-id`, `webhook-timestamp`
(reject > 5 min skew → 400), `webhook-signature` (`v1,<base64>`; bad → 401).
Duplicate `webhook-id` → 200 with **exactly one** side effect. Payload
`{"event": "notification.delivered", "notification_id", "task_id"}` flips that
task's `reminder_status` pending→sent.

Test-only (mounted when `APP_ENV=test`): `POST /api/testing/reset` → 204 wipes
tasks+sessions+webhook events+reminder-delivery history, keeps seeded users;
`POST /api/testing/run-due-reminders` → 202 `{enqueued: n}` (deterministic
trigger — E2E is trigger+poll, never sleep); `POST
/api/testing/clear-reminder-deliveries` → 204, wipes only `reminder_deliveries`
(sessions and tasks survive — a health-only reset for suites that need to clear
a degraded signal without revoking logins).

Reminder flow: scheduler tick (30s prod, trigger endpoint in tests) finds
`due_at <= now AND reminder_status = 'none'` → marks `pending`, enqueues taskiq
job → job POSTs vendor `/v1/notifications` `{task_id, title, due_at,
idempotency_key}` with 2s timeout + 3 tenacity retries (injectable wait) →
vendor later webhooks delivery → `sent`. Retries exhausted → `failed`. Each job
run also appends exactly one `ReminderDelivery` row (`accepted` on vendor 2xx,
`failed` once retries exhaust — recorded even if the task was deleted
mid-flight), which is what `GET /api/reminders/health` reads.

Config env: `DATABASE_URL`, `REDIS_URL`, `VENDOR_URL`, `VENDOR_API_KEY`
(`vendor-key`), `VENDOR_WEBHOOK_SECRET`, `APP_ENV`, `SESSION_TTL_SECONDS=3600`,
`REMINDER_HEALTH_WINDOW_SECONDS=900` (recency window for the reminder-delivery
health signal, on api + worker),
`REQUEST_DEADLINE_MS=8000` (every request runs under an asyncio deadline →
504 JSON on breach; the only timeout that bounds a stalled DB wire, since
asyncpg's BEGIN bypasses `command_timeout`), `DB_COMMAND_TIMEOUT_MS=4000`,
`DB_STATEMENT_TIMEOUT_MS=2000`, `DB_PING_TIMEOUT_MS=3000` (bounded pre-use
connection ping healing stale pooled connections; exhausted validation →
503 `database unavailable`, distinct from the 504 deadline).
Migrations: `uv run --package taskboard-api alembic -c apps/api/alembic.ini upgrade head`.
Seed (idempotent, fixed ids/timestamps): `uv run --package taskboard-api python -m app.seed`
— 2 users, alice: 3 tasks (one due +2min), bob: 2 tasks.

## apps/web — server-rendered UI (port 8001)

Owns no data; holds the API bearer token in a signed session cookie
(`SessionMiddleware`, `SECRET_KEY` env, same_site=lax, https_only=False).
Protected pages without a valid token → 303 to `/login?next=...`; API 401 mid-
session → clear cookie + 303 `/login`.

Routes: `GET /login` (form: `email-input`, `password-input`, `submit-login`,
error banner `login-error`), `POST /login` (CSRF-checked; success → 303 `/`),
`POST /logout` (`logout-btn`) → API logout + clear cookie + 303 `/login`,
`GET /` board (v1 testids unchanged: `task-list`, `task-row`, `task-title`,
`task-status`, `new-task-link`, `advance-btn`, `delete-btn`, `task-count`;
`user-email`; `due-at` per row now renders a human-readable UTC label, e.g.
`25 Jul 2026, 12:34 UTC`, instead of the raw RFC3339 timestamp, and is present
only when the task has a `due_at`; `reminder-badge` when status ≠ none; new
`overdue-badge` per row, present only when `due_at` is strictly in the past
(absent from the DOM otherwise, not merely hidden); within each column, rows
are ordered by soonest `due_at` first, undated tasks last, ascending task id
as tie-break — `GET /api/tasks` ordering and payload are unchanged, this is a
web-layer-only concern); row actions carry task-scoped accessible names, DOM
order `Move back <title>` / `Advance <title>` / `Delete <title>`
(`aria-label="Move back <title>"` / `"Advance <title>"` / `"Delete <title>"`),
testids and visible text unchanged, `GET|POST /new` (adds optional
`due-at-input`), advance/delete as v1, `GET /healthz`. All forms carry hidden
`csrf_token` (session-stored, compared on POST; mismatch → 403).

`POST /tasks/{id}/move-back` — moves a task one column back (`done → doing`,
`doing → todo`; `todo` is the floor, submitting it on a `todo` task is a
no-op). Row action `data-testid="move-back-btn"`, visible text `Move back`,
CSS class `btn-back`, rendered as the first action on every row in every
column, alongside `advance-btn` and `delete-btn`. CSRF-checked (mismatch →
403, nothing mutated); no session → 303 `/login?next=...`; API 401 mid-
session → session cleared, 303 `/login`; another user's task id → silent
no-op, 303 back to the caller's own board (no existence leak). Carries the
same hidden `status`/`page` inputs as advance/delete and redirects 303 back
to the same filtered/paged board. Internally issues `GET /api/tasks/{id}`
then, only when the mapped status differs, `PATCH /api/tasks/{id}` with body
exactly `{"status": ...}` — no other field is sent, so `due_at` and
`reminder_status` are never touched by this action.

`GET /` also accepts an optional `status` query param (`todo|doing|done`);
any other value, including absent or empty, renders the full three-column
board with HTTP 200 (never a 422 — this is a web-layer view filter). When a
filter is active the board now passes `status` through to `GET /api/tasks`
(previously always unfiltered), so a paged, filtered board doesn't render a
page that's empty for the active column.

`GET /` also accepts an optional `page` query param (1-based). Absent, blank,
non-numeric, `< 1`, or beyond the last page → renders page 1 with HTTP 200,
never a 422 — same lenient posture as `status`. The board fetches one page of
`BOARD_PAGE_SIZE = 20` tasks (`GET /api/tasks?limit=20&offset=(page-1)*20`,
plus `status` when filtered). A pager renders after the board, present only
when there is more than one page: `data-testid="pager"` (`<nav aria-label="Task
pages">`, absent from the DOM — not merely hidden — on a single-page board),
`data-testid="pager-prev"` (present only when `page > 1`, `aria-label="Previous
page"`, `rel="prev"`), `data-testid="pager-next"` (present only when `page <
page_count`, `aria-label="Next page"`, `rel="next"`), `data-testid="pager-status"`
(text `Page {n} of {m}`). Pager links carry no `aria-current` — the board's
single `aria-current="page"` stays on the active status-filter link. Pager
URLs preserve the active filter (`/?status=todo&page=2`); page-1 URLs omit
`page` entirely, so `/` and `/?status=todo` stay byte-identical to today.
`task-count` is unchanged in meaning: the user's grand total across all
statuses, independent of page and filter. Each row's move-back/advance/delete
form carries a hidden `name="page"` input; all three actions redirect back to
the same page and filter. `GET /` fetches `/api/reminders/health` (dedicated 2s timeout)
after the tasks fetch — skipped when the tasks fetch already failed — and
renders a degraded-service banner (`data-testid="reminder-degraded-banner"`,
`role="status"`, no `tabindex`/`autofocus`) as the first element of the board
content block, above the filter nav, only when the health state is exactly
`degraded`; any other outcome (healthy, non-200, timeout, connection error,
unparseable body, 401) renders no banner and never blocks or breaks the board.
The banner adds no landmark (the page keeps exactly one `banner` and one
`main`) and is absent from the DOM when not showing, not merely hidden; `/new`
and `/login` never render it. The health call's origin is `API_BASE_URL`
unless `REMINDER_HEALTH_BASE_URL` is set (test profile only), in which case
that origin is used instead — routing only, no change to the call's headers,
timeout, or outcome handling; every other web→API call is unaffected.
Otherwise the board's first content element (the
second, when the degraded banner is present) is a filter nav
`data-testid="status-filter"` with four links — `filter-all` (→ `/`),
`filter-todo`, `filter-doing`, `filter-done` (→ `/?status=<status>`) — of
which exactly one carries `aria-current="page"` (plus a cosmetic `.active`
class), `filter-all` when unfiltered or the status value is unrecognised.
`task-count` keeps showing the user's total across all statuses regardless of
the active filter. Each row's move-back/advance/delete form carries a hidden
`name="status"` input holding the active filter, so all three actions
redirect back to the same filtered (or unfiltered) board. Protected-page auth
redirects now preserve the query string in `next` (e.g. unauthed `GET
/?status=todo` → 303 `/login?next=/%3Fstatus%3Dtodo`); `/` and `/new`
redirects are unchanged.

When the tasks fetch succeeded and the rendered set is empty, the board shows
exactly one empty-state message. Unfiltered with zero tasks:
`data-testid="empty-board"` (text `No tasks yet.`) rendered between the filter
nav and the board, carrying `data-testid="empty-board-new-link"` → `GET /new`.
Filtered (`?status=<todo|doing|done>`) with no match: `data-testid="empty-filter"`
(text `Nothing in <status> right now.`) rendered inside that column, after its
`<h2>`. Never both — a zero-task user on a filtered board sees `empty-filter`
only. Both are absent from the DOM (not merely hidden) when they do not apply,
and are suppressed entirely when the tasks fetch failed (`api-error` owns that
case). Neither carries a role, landmark, `tabindex`, or `autofocus`: the page
keeps exactly one `banner`, one `main`, and — when the degraded banner is also
showing — exactly one `status` region. An unrecognised `status` value falls
back to the full board, so the empty-board rule applies to it.

## Vendor contract (what WireMock simulates)

`POST /v1/notifications` (header `x-vendor-key: vendor-key`) → 202
`{"notification_id": "..."}`. Baseline happy-path mappings mounted from
`vendor-mock/mappings/`. The QA agent and resilience tests program faults at
runtime via `http://localhost:8081/__admin` (stubs, `fixedDelayMilliseconds`,
`fault: CONNECTION_RESET_BY_PEER|MALFORMED_RESPONSE_CHUNK`, scenarios,
`POST /__admin/reset`). Vendor webhook deliveries are simulated by tests (and
the QA agent) signing payloads with `VENDOR_WEBHOOK_SECRET`.

## Chaos contract (Toxiproxy)

Admin `http://localhost:8474`. Proxies (pre-populated from
`toxiproxy/config.json`): `db` :5433→db:5432, `vendor` :8666→vendor-mock:8080,
`web-health` :8667→api:8000. Test client: `qa_helpers.toxiproxy.ToxiproxyClient`
(httpx wrapper: `add_toxic`, `remove_toxic`, `reset_all`; always
`toxicity=1.0`, `jitter=0`). Teardown guarantee: fixtures must remove toxics in
finalizers; a session guard asserts no toxics leak between tests.

`web-health` faults **only** the web app's `GET /api/reminders/health` call
(via `REMINDER_HEALTH_BASE_URL`), leaving `GET /api/tasks` and every other
web→API call untouched — the lever ticket #31 added so QA can prove "one
signal degrades, the rest stays healthy" ACs end-to-end, which the shared
`db`/`vendor` proxies can't (every fault on them also breaks `GET /api/tasks`).
Default state: enabled, no toxics — transparent passthrough, same as `db`.
Test client: `qa_helpers.health_lever.HealthLever`, built on top of
`ToxiproxyClient` (so its toxics are covered by the same leak guard); modes
`fail()` (`reset_peer`, toxic name `health_fail` — the web app sees
`httpx.HTTPError`) and `timeout()` (`timeout`, toxic name `health_timeout` —
stalls the stream past the web app's 2s health-call timeout), `release()`
(idempotent), `engaged_faults()`, and `probe(token)` (GETs the health endpoint
directly through `localhost:8667`, bypassing the web app). Fixture
`qa_helpers.health_lever.health_lever` (imported into `qa/tests/e2e/conftest.py`)
finalizes by releasing and then asserting the listener passes a request
through again, mirroring the `toxiproxy` fixture's recovery gate.

## QA suites (qa/)

- `tests/e2e/` — pytest-playwright via gateway (8787). Auth fixtures: session-
  scoped login through the real form per seeded user → `storage_state` files in
  tmp (never committed); `alice_page` / `bob_page` / unauthed `page`.
  Covers: v1 flows (authed), unauthed redirect sweep, wrong password, logout
  revocation (replayed cookie → /login), cross-user isolation (alice ≠ bob),
  reminder trigger+poll (`wait_until` helper, deadline 15s, no sleeps),
  accessibility smoke (non-empty accessible names on form controls and board
  row actions, keyboard focus order on the login and new-task forms, exactly
  one banner + one main landmark per page), and the degraded-reminders banner
  driven by WireMock vendor faults + recovery (`vendor_admin`,
  `clean_reminder_health` fixtures) — appears/clears deterministically, board
  stays functional (advance/delete still work) while showing, and the page
  keeps exactly one banner/main landmark plus one `status` region with no
  stolen focus. Also imports the Toxiproxy no-leak guard (previously only in
  `tests/resilience/`) so the `health_lever` fixture's toxics are covered too.
  `tests/e2e/test_health_lever.py` proves the partial-degradation class of AC:
  the `health_lever` fixture faults only the reminder-health call (fail or
  timeout) and the board still renders with no degraded banner, `GET
  /api/tasks` returns an identical envelope through the gateway, and board
  actions (advance/delete) keep working.
- `tests/contract/` — Schemathesis v4 against the API (auth'd via bearer
  override), replaying a committed corpus (`tests/contract/corpus.json`, ≤25
  cases per operation) instead of generating on the fly — no PRNG in the
  gating path, so the verdict is a pure function of the commit. Refresh with
  `make contract-refresh` after an API change; a schema-digest guard fails
  loudly if the corpus drifts from the live schema. Plus an explicit check
  that `GET /api/reminders/health` is documented and 401s unauthenticated.
- `tests/resilience/` — vendor faults via WireMock admin (5xx → reminder
  `failed`, recovery after reset) and Toxiproxy matrix: db latency 500ms →
  still 200 (degraded-but-functional stays under the 8s request deadline);
  db stall (timeout=0) → 5xx JSON by the deadline, never a hang; vendor
  reset_peer → reminder `failed` after retries. The `toxiproxy` fixture's
  teardown removes toxics AND asserts recovery (login succeeds again) so
  poisoned connection pools never bleed into the next test. Reminder-delivery
  health (AC-10): WireMock 5xx and Toxiproxy `reset_peer` on the vendor proxy
  each flip `GET /api/reminders/health` to `degraded`, observed via
  `wait_until` (never sleep), recovering after the fault clears.
- `tests/webhooks/` — signature matrix: valid, tampered body → 401, stale
  timestamp → 400, duplicate id → single side effect; helper
  `qa_helpers.webhooks.sign(payload, secret, ts)`.
- Shared: `qa_helpers.wait_until(fn, timeout, interval)` raising with last
  state; bare `sleep()` is banned in suites.

## Python layout

uv workspace unchanged (`apps/api`, `apps/web`, `qa`, `watcher`). New API deps:
sqlalchemy[asyncio], asyncpg, alembic, taskiq, taskiq-redis, taskiq-fastapi,
tenacity, pwdlib[argon2], httpx. Unit/integration tests use savepoint-rollback
fixtures (`join_transaction_mode="create_savepoint"`) against compose Postgres;
taskiq `InMemoryBroker(await_inplace=True)` in unit tier; at least one E2E path
exercises the real worker.
