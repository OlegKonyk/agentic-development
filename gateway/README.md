# agentic-gateway

Cloudflare Worker (Wrangler v4, TypeScript, dependency-free) fronting the
Taskboard apps on dev port 8787.

## Commands

```sh
npm ci
npm run dev        # wrangler dev on http://localhost:8787
npm run typecheck  # tsc --noEmit
npm run deploy     # wrangler deploy (use --env production for prod vars)
```

Local var overrides: copy `.dev.vars.example` to `.dev.vars`.

## What it does

- Routing: `/api/*` and `/openapi.json` proxy to `API_ORIGIN`;
  `GET /gw/healthz` is answered in the Worker (`{"status":"ok","gateway":"agentic-gateway"}`,
  no auth); everything else proxies to `WEB_ORIGIN`.
- Auth: `/api/*` requires `x-api-key` matching the `GATEWAY_API_KEY` var
  (dev default `dev-key`); `/healthz` and `/openapi.json` are exempt.
  Failure: `401 {"error":"unauthorized"}`.
- Request IDs: a `crypto.randomUUID()` `x-request-id` is set on every upstream
  request and echoed on the response.
- Rate limit: naive per-isolate sliding window — more than 60 requests per 10s
  per api-key (or client IP when keyless) returns `429 {"error":"rate_limited"}`.
  This is per-colo/per-isolate; the GA Rate Limiting binding is the production path.
- Logging: one structured JSON `console.log` per request
  (`{ts, method, path, status, requestId, ms}`), surfaced via
  `observability.enabled: true`.

In real deployments `GATEWAY_API_KEY` moves out of `vars` into
`wrangler secret put GATEWAY_API_KEY --env production`.
