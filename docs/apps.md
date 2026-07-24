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
| `toxiproxy` | ghcr.io/shopify/toxiproxy:2.12.0 | 8474 (admin) | `GET /version` |
| gateway | wrangler dev (host, not compose) | 8787 | `GET /gw/healthz` |

CI/test profile routing (via toxiproxy listeners): api→db uses `toxiproxy:5433`,
api/worker→vendor uses `toxiproxy:8666`. Dev profile connects directly.
CI Postgres runs on tmpfs with `fsync=off synchronous_commit=off`.

## Domain

- `User {id, email, password_hash, created_at}` — seeded: `alice@example.com` /
  `bob@example.com`, passwords from env `QA_ALICE_PASS` / `QA_BOB_PASS`
  (compose default `correct-horse-a` / `correct-horse-b`).
- `Session {id: uuid, user_id, created_at, expires_at}` — DB-backed: logout
  deletes the row (true revocation, replayed tokens must 401).
- `Task {id, owner_id, title 1..200, description, status todo|doing|done,
  due_at: datetime|null, reminder_status none|pending|sent|failed, created_at}`
  — strictly scoped to owner.
- `WebhookEvent {id: vendor event id (unique — dedupe), received_at, payload}`.

## apps/api — FastAPI, async SQLModel + asyncpg, Alembic (port 8000)

Auth (open): `POST /api/auth/login {email,password}` → 200 `{token, expires_at}`
(opaque session id) | 401 generic (no user enumeration). `POST /api/auth/logout`
(bearer) → 204, deletes session. `GET /api/auth/me` (bearer) → `{id, email}`.

Tasks (require `Authorization: Bearer <token>`, else 401; scoped to owner;
404 for other users' task ids — no existence leak): same CRUD surface as v1
plus `due_at` (optional RFC3339, must be future on create/update else 422) and
read-only `reminder_status`. All v1 contract fixes hold (RFC3339 `Z`
timestamps, documented 400/404, no nullable query params); TaskId path bound is
≤ 2^31-1, matching the INTEGER column (larger ids overflowed asyncpg → 500,
found by contract fuzzing).

Webhooks: `POST /api/webhooks/vendor` — Standard-Webhooks-style HMAC-SHA256 of
`{webhook-id}.{webhook-timestamp}.{raw body}` using `VENDOR_WEBHOOK_SECRET`
(compose default `whsec_test`), headers `webhook-id`, `webhook-timestamp`
(reject > 5 min skew → 400), `webhook-signature` (`v1,<base64>`; bad → 401).
Duplicate `webhook-id` → 200 with **exactly one** side effect. Payload
`{"event": "notification.delivered", "notification_id", "task_id"}` flips that
task's `reminder_status` pending→sent.

Test-only (mounted when `APP_ENV=test`): `POST /api/testing/reset` → 204 wipes
tasks+sessions+webhook events, keeps seeded users; `POST /api/testing/run-due-reminders`
→ 202 `{enqueued: n}` (deterministic trigger — E2E is trigger+poll, never sleep).

Reminder flow: scheduler tick (30s prod, trigger endpoint in tests) finds
`due_at <= now AND reminder_status = 'none'` → marks `pending`, enqueues taskiq
job → job POSTs vendor `/v1/notifications` `{task_id, title, due_at,
idempotency_key}` with 2s timeout + 3 tenacity retries (injectable wait) →
vendor later webhooks delivery → `sent`. Retries exhausted → `failed`.

Config env: `DATABASE_URL`, `REDIS_URL`, `VENDOR_URL`, `VENDOR_API_KEY`
(`vendor-key`), `VENDOR_WEBHOOK_SECRET`, `APP_ENV`, `SESSION_TTL_SECONDS=3600`,
`REQUEST_DEADLINE_MS=8000` (every request runs under an asyncio deadline →
504 JSON on breach; the only timeout that bounds a stalled DB wire, since
asyncpg's BEGIN bypasses `command_timeout`), `DB_COMMAND_TIMEOUT_MS=4000`,
`DB_STATEMENT_TIMEOUT_MS=2000`.
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
`task-status`, `new-task-link`, `advance-btn`, `delete-btn`, `task-count`; new:
`user-email`, `due-at` per row, `reminder-badge` when status ≠ none),
`GET|POST /new` (adds optional `due-at-input`), advance/delete as v1,
`GET /healthz`. All forms carry hidden `csrf_token` (session-stored, compared
on POST; mismatch → 403).

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
`toxiproxy/config.json`): `db` :5433→db:5432, `vendor` :8666→vendor-mock:8080.
Test client: `qa_helpers.toxiproxy.ToxiproxyClient` (httpx wrapper:
`add_toxic`, `remove_toxic`, `reset_all`; always `toxicity=1.0`, `jitter=0`).
Teardown guarantee: fixtures must remove toxics in finalizers; a session guard
asserts no toxics leak between tests.

## QA suites (qa/)

- `tests/e2e/` — pytest-playwright via gateway (8787). Auth fixtures: session-
  scoped login through the real form per seeded user → `storage_state` files in
  tmp (never committed); `alice_page` / `bob_page` / unauthed `page`.
  Covers: v1 flows (authed), unauthed redirect sweep, wrong password, logout
  revocation (replayed cookie → /login), cross-user isolation (alice ≠ bob),
  reminder trigger+poll (`wait_until` helper, deadline 15s, no sleeps).
- `tests/contract/` — Schemathesis v4 against the API (auth'd via bearer
  override), bounded + deterministic as v1.
- `tests/resilience/` — vendor faults via WireMock admin (5xx → reminder
  `failed`, recovery after reset) and Toxiproxy matrix: db latency 500ms →
  still 200 (degraded-but-functional stays under the 8s request deadline);
  db stall (timeout=0) → 5xx JSON by the deadline, never a hang; vendor
  reset_peer → reminder `failed` after retries. The `toxiproxy` fixture's
  teardown removes toxics AND asserts recovery (login succeeds again) so
  poisoned connection pools never bleed into the next test.
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
