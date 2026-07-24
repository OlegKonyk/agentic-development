# agentic-development

**An agentic SDLC, end to end:** an idea filed as a GitHub issue flows through
product → design → development → QA → deploy, with each phase executed by a
Claude Code agent inside a deterministic, label-driven GitHub Actions state
machine. The demo apps underneath are deliberately tiny — the pipeline is the
product.

## North star

> File an idea. A spec appears. A design appears. A PR appears with tests. A QA
> agent boots the stack, verifies the acceptance criteria in a real browser, and
> posts an evidence-backed verdict that gates the merge. A human merges. It
> deploys. The ticket closes itself.

The design follows the 2025–26 industry consensus (Anthropic's *Building
Effective Agents*, GitHub's agentic workflows): **workflows over agents** —
deterministic orchestration owns every state transition; the model only fills in
content inside a phase, and always through schema-validated structured output.

```mermaid
flowchart LR
    A[💡 issue<br/>stage:idea] -->|human: stage:spec| B[🤖 product<br/>agent]
    B --> C[🤖 design<br/>agent]
    C --> D[🤖 dev agent<br/>opens PR]
    D -->|qa-ready| E[🤖 QA agent<br/>tier1 + tier2]
    E -->|qa-passed| F[👤 human<br/>merges]
    E -->|qa-failed| D2[🤖 rework] --> E
    F --> G[🚀 deploy<br/>ticket closes]
```

## What's here

| Path | What |
|---|---|
| `docs/sdlc.md` | **The state-machine spec** — labels, phase contracts, gates, trust boundaries |
| `docs/apps.md` / `docs/setup.md` | App contracts / one-time setup |
| `.github/workflows/` | The pipeline: `phase-product`, `phase-design`, `phase-dev`, `phase-qa`, `ci`, `deploy`, `nightly-fuzz`, `assistant` |
| `ci/claude/` | Agent assets: per-phase skill plugins, JSON output schemas, CI settings, Playwright MCP config |
| `scripts/` | Deterministic glue: `run_agent.sh` (the one Claude invocation), `qa_gate.py`, `transition.sh`, `loop_guard.sh`, `resolve_pr.sh`, `state_lint.py` |
| `apps/api` + `apps/web` | Taskboard demo: FastAPI JSON API + server-rendered UI |
| `gateway/` | Cloudflare Worker gateway (Wrangler v4): API-key auth, rate limiting, routing, request IDs |
| `qa/` | Deterministic suites: Playwright E2E + Schemathesis contract tests |
| `watcher/` | Phase 2: an Agent-SDK "ticket watcher" service — the same state machine, local runtime |

## The QA agent (the centerpiece)

`phase-qa.yml` fires when a PR gets `qa-ready`:

1. **Tier 1 (deterministic, the hard gate):** boots the full stack (compose +
   `wrangler dev`), seeds data, runs unit/integration, Schemathesis contract,
   and Playwright E2E suites. Exit codes gate directly.
2. **Tier 2 (agentic):** one bounded `claude -p` run — the `/qa:qa-run` skill —
   verifies each acceptance criterion in a real browser via Playwright MCP,
   runs an exploratory charter (console + network inspection after every flow),
   and triages tier-1 failures as bug/infra/flake.
3. **The gate is code, not vibes:** `scripts/qa_gate.py` combines tier-1
   outcomes with the agent's schema-validated verdict, posts the
   `qa/agent-verdict` commit status on the head SHA (required by branch
   protection), posts an evidence-backed comment, and the App token flips the
   label — `qa-passed`, `qa-failed` (dev agent reworks, max 3 cycles), or
   `needs-human`.

## Try it

```bash
make install && make stack-up && make gateway-dev &   # local stack
make seed && make test && make e2e                    # local suites
```

Pipeline: complete `docs/setup.md` (≈10 minutes), then file a feature issue and
add the `stage:spec` label. That label is the only human act until the merge
button.

## Design rules that keep it predictable

- The model never chooses a state transition; labels move only via
  `scripts/transition.sh` under the `sdlc-orchestrator` App token.
- Every agent returns structured output validated against a committed JSON
  schema; free text is never parsed for control flow.
- Every agent claim needs evidence (repro steps, artifacts) — a `fail` without
  reproduction is downgraded to `blocked` by the gate.
- Bounded everything: `--max-turns`, job timeouts, per-ticket concurrency
  groups, loop guards on the label timeline, 3-strike QA↔rework cap.
