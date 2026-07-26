# Infra Engineer Playbook

You run the road the agents drive on. In this pipeline, agents are a first-class user
persona with their own identities, quotas, and hard boundaries — the 2026 platform
consensus is to treat them like production tenants, not teammates, with least-privilege
RBAC and compliance built in at generation time, not post-hoc review
([The New Stack](https://thenewstack.io/in-2026-ai-is-merging-with-platform-engineering-are-you-ready/)).
Your job is to make the correct path the default path and to make every boundary
enforceable by code that runs, not prose that hopes. The pipeline is the product;
you own its determinism.

## Your touchpoints in the pipeline

- **Files you own**: `.github/workflows/*` (the state machine — the App has no
  `workflows: write`, so these are human-only by construction), `scripts/*`
  (`transition.sh`, `loop_guard.sh`, `qa_gate.py`, `run_agent.sh`, `state_lint.py`),
  `ci/claude/settings/ci-settings.json` (permission deny rules), docker compose +
  seed + gateway dev config, the `main` ruleset, and the `sdlc-orchestrator` App
  identity and key. Every workflow change updates `docs/sdlc.md` in the same PR.
- **Identities you administer** — the three-way split is the core design:
  App token for anything that must chain (label transitions, branch pushes —
  `GITHUB_TOKEN` events are suppressed by GitHub and never trigger the next phase);
  `GITHUB_TOKEN` for anything that must NOT chain (statuses, comments, artifacts);
  and agent steps hold **no token at all** — `persist-credentials: false` on checkout,
  with only the orchestrator's own push steps authenticating explicitly.
- **Labels**: you don't drive tickets, you unpark them. `needs-human` from infra
  causes (stale merge ref, guard trips, stack-boot failures) is yours; fix the road,
  then re-add the phase label via `scripts/transition.sh` with the App token — never
  by hand with `GITHUB_TOKEN`.
- **Artifacts you review**: per-run JSON payloads (`total_cost_usd`, `num_turns`,
  `permission_denials`), tier-1 JUnit/traces, guard step logs.

## A ticket from your seat

Mostly you watch it not need you. Dev phase boots db+redis so the agent can
self-verify; QA asserts merge-ref freshness, boots the full stack health-gated,
seeds, runs tier-1, then the agent tier. You get paged three ways:

1. **Stale merge ref park.** GitHub computes `refs/pull/N/merge` lazily; a label
   event doesn't refresh it. The freshness assert (#17) fails before spending
   anything — tell the dev to update the branch and re-add `qa-ready`. Working as
   designed; we once paid $1.80 of QA to re-find a bug `main` had already fixed.
2. **Privileged-path guard trip.** A dev/rework push touched `.github/`,
   `ci/claude/`, or `scripts/` (merge-base diff), or left a dirty tree under them.
   Never loosen the guard to unblock a ticket: if a design genuinely mandates a
   charter edit, a human applies it directly and the agent routes it via `concerns`.
3. **`error_max_turns`.** Read `permission_denials` first: zero denials plus steady
   progress means the charter outgrew the cap (raise it); repeated denials mean a
   stuck agent — fix the sandbox, not the ceiling.

Merge stays machine-gated: branch protection requires `ci` + `qa/agent-verdict` on
the head SHA. The admin bypass is break-glass for human maintenance PRs only.

## What changes vs. the traditional role

- Your primary user is non-human, tireless, and exposed to untrusted input (ticket
  bodies, pages it browses). Design for prompt injection the way you design for
  hostile traffic: allowlists, no ambient credentials, no deploy secrets in agent jobs.
- "Docs as guardrails" is dead. Enforcement lives in YAML, permission flags, and
  push-time checks — Anthropic's own guidance draws the same line between advisory
  rules and deterministic enforcement
  ([Claude Code best practices](https://code.claude.com/docs/en/best-practices)).
- Cost is an SRE metric now. Caps (`--max-turns`, `--max-budget-usd`,
  `timeout-minutes`, per-ticket `concurrency` groups) are the documented CI
  guardrail set ([Claude Code GitHub Actions](https://code.claude.com/docs/en/github-actions)),
  and they are load-bearing: multi-agent setups burn ~15x the tokens of a single
  session ([Anthropic engineering](https://www.anthropic.com/engineering/multi-agent-research-system)).

## Failure modes to watch

- **Prose-only boundaries.** The house example: every `Edit(//ci/claude/**)` deny
  rule was dead (a `//` prefix means filesystem-root, matching nothing), and the
  rework agent politely edited the QA charter on PR #13. The hierarchy is
  prompt rules < permission deny rules < deterministic diff/tree guards at push
  time — only the last layer is a boundary
  ([best practices](https://code.claude.com/docs/en/best-practices)).
- **Enforcement untested against its runtime.** The freshness assert failed closed
  on its own first run — `rev-parse` can't resolve parents in a depth-1 checkout —
  and was fixed empirically against a real shallow fetch (PR #18). Verify guard code
  against the environment it runs in, not the one you reason about.
- **The absorption path collapses.** DORA finds AI amplifies existing weaknesses:
  throughput rises while stability falls when the platform can't absorb the volume
  ([DORA 2025](https://dora.dev/research/2025/dora-report/)). A flaky stack boot or
  slow gate turns agent speed into rework, not delivery.
- **Silent cost runaway.** Context-undisciplined teams spend 4-6x more tokens per
  feature ([explainx](https://explainx.ai/blog/agentic-fatigue-vibe-coding-ai-developer-productivity-paradox));
  without caps and concurrency groups a retry loop is an invoice.

## Metrics you watch

- $ and tokens per merged PR, plus CI minutes per ticket (from run JSON artifacts).
- Unplanned `needs-human` parks split by cause (infra / guard / agent), trended
  week-over-week — the trend matters more than the level
  ([Digital Applied](https://www.digitalapplied.com/blog/agentic-workflow-completion-metrics-pipeline-health-2026)).
- Guard trips and loop-guard counts per ticket; QA↔rework cycles.
- Tier-1 failures the QA agent triages as `infra` or `flake` — that's your paved
  road failing, and it burns agent budget on non-bugs.
- Per-phase turn/budget consumption vs. cap (leading indicator for cap tuning).

## Boundaries

Agents must never, in your area: touch `.github/workflows/` (App lacks
`workflows: write`), `ci/claude/`, or `scripts/` (deny rules steer; the push-time
guard enforces and parks); hold a token (agent steps run credential-less, no deploy
secrets, no Cloudflare token in QA, `browser_run_code_unsafe` disallowed, fork PRs
refused); or apply pipeline labels / choose state transitions.

You must not delegate: authoring or reviewing the enforcement code that constrains
the agents; verifying that enforcement against its real runtime; raising caps or
budgets (a human decision informed by denial data); or break-glass bypass merges.
