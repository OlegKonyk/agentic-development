interface Env {
  API_ORIGIN: string;
  WEB_ORIGIN: string;
  GATEWAY_API_KEY: string;
  // Test harnesses override the request budget (--var RATE_LIMIT:600): the
  // tier-1 e2e suite's cumulative volume outgrew the default and tripped 429s
  // on unrelated tests (PR #24, twice). Default stays production-realistic.
  RATE_LIMIT?: string;
}

const RATE_WINDOW_MS = 10_000;
const DEFAULT_RATE_LIMIT = 60;

function rateLimit(env: Env): number {
  const parsed = Number(env.RATE_LIMIT);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_RATE_LIMIT;
}

// Per-isolate state: resets on isolate recycle, not shared across colos.
// The GA Rate Limiting binding is the production path.
const hits = new Map<string, number[]>();

function isRateLimited(key: string, limit: number): boolean {
  const now = Date.now();
  const recent = (hits.get(key) ?? []).filter((t) => now - t < RATE_WINDOW_MS);
  recent.push(now);
  hits.set(key, recent);
  return recent.length > limit;
}

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function proxy(request: Request, origin: string, requestId: string): Promise<Response> {
  const url = new URL(request.url);
  const target = new URL(url.pathname + url.search, origin);
  const headers = new Headers(request.headers);
  headers.set("x-request-id", requestId);
  return fetch(target.toString(), {
    method: request.method,
    headers,
    body: request.body,
    redirect: "manual",
  });
}

async function handle(request: Request, env: Env, requestId: string): Promise<Response> {
  const path = new URL(request.url).pathname;

  const apiKey = request.headers.get("x-api-key");
  const rateKey = apiKey ?? request.headers.get("cf-connecting-ip") ?? "unknown";
  if (isRateLimited(rateKey, rateLimit(env))) {
    return json({ error: "rate_limited" }, 429);
  }

  if (path === "/gw/healthz") {
    return json({ status: "ok", gateway: "agentic-gateway" }, 200);
  }

  if (path.startsWith("/api/") || path === "/openapi.json") {
    const exempt = path === "/healthz" || path === "/openapi.json";
    if (!exempt && apiKey !== env.GATEWAY_API_KEY) {
      return json({ error: "unauthorized" }, 401);
    }
    return proxy(request, env.API_ORIGIN, requestId);
  }

  return proxy(request, env.WEB_ORIGIN, requestId);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const start = Date.now();
    const requestId = crypto.randomUUID();
    const path = new URL(request.url).pathname;

    let response: Response;
    try {
      response = await handle(request, env, requestId);
    } catch {
      response = json({ error: "bad_gateway" }, 502);
    }

    const out = new Response(response.body, response);
    out.headers.set("x-request-id", requestId);

    console.log(
      JSON.stringify({
        ts: new Date().toISOString(),
        method: request.method,
        path,
        status: out.status,
        requestId,
        ms: Date.now() - start,
      }),
    );
    return out;
  },
} satisfies ExportedHandler<Env>;
