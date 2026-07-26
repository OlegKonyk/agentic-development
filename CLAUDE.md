# agentic-development

An agentic SDLC pipeline (label-driven GitHub Actions state machine where Claude
agents run product/design/dev/QA phases) plus the Taskboard demo apps it operates
on. The pipeline is the product; the apps are the test bed.

## Binding docs — read before changing anything

- `docs/sdlc.md` — the state machine spec. Workflows/scripts implement it; if
  you change behavior, update the spec in the same PR.
- `docs/apps.md` — app contracts (ports, routes, data-testids). QA suites and
  agent prompts depend on these exactly.
- `docs/lab-charter.md` — the experiment method (rounds, metrics, evidence
  rules); per-seat playbooks live in `docs/playbooks/`.

## Layout

- `apps/api`, `apps/web` — FastAPI Taskboard API (8000) + server-rendered UI (8001)
- `gateway/` — Cloudflare Worker gateway (wrangler dev on 8787; auth, rate limit, routing)
- `qa/` — E2E (pytest-playwright) + contract (Schemathesis) suites, `qa_helpers` client
- `.github/workflows/` — the state machine (phase-*.yml, ci, deploy)
- `ci/claude/` — agent assets: plugins (skills per phase), JSON output schemas,
  CI settings, MCP config
- `scripts/` — deterministic glue: run_agent.sh, transition.sh, qa_gate.py,
  resolve_pr.sh, loop_guard.sh, state_lint.py
- `watcher/` — Agent-SDK ticket watcher (phase 2, local runtime model)

## Commands

uv workspace (Python >=3.12, single root lock): `uv sync --all-packages`.
`make test` (unit/integration), `make lint` (ruff + state lint),
`make stack-up && make gateway-dev` then `make seed`, `make e2e`, `make contract`.

## Conventions

- Ruff: line-length 100, rules E,F,I,UP,B,SIM. Typed, minimal, sparse comments.
- Never edit `.github/workflows/` without updating `docs/sdlc.md` — the state
  lint and human review both check this correspondence.
- Label transitions only via `scripts/transition.sh` with an App token; never
  add pipeline labels with GITHUB_TOKEN (events won't chain).
- Agent phases return schema-validated structured output only; if you add a
  phase, add its schema to `ci/claude/schemas/` and a plugin under
  `ci/claude/plugins/`.
