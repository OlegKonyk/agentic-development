# QA Engineer Playbook

You own the verification signal every agent in this pipeline iterates against. Agents generate code and tests faster than anyone can read them, so the bottleneck has moved from writing coverage to [validating confidence](https://www.devassure.io/blog/autonomous-coding-agents-rewriting-qa-playbook-2026/) — deciding what counts as evidence and building checks agents cannot fool. Anthropic's first-listed practice for agent autonomy is ["give the agent a check it can run"](https://code.claude.com/docs/en/best-practices); in this lab, you are the person who builds, guards, and calibrates those checks. The tier-1 suites, the exploratory charter, and the gate rules in `qa_gate.py` are your product. The apps are just the test bed.

## Your touchpoints in the pipeline

**Labels you apply** (humans may add these directly; all other transitions are App-token-only via `scripts/transition.sh`):

- `qa-ready` on a PR — re-trigger QA after a branch update, a flake, or a charter change.
- Un-parking `needs-human`: fix the cause, then re-add the phase label (usually `qa-ready`).
- `stage:spec` on retro-filed `stage:idea` issues that propose QA improvements — you are the entry gate for spend on your own tooling.

**Artifacts you review**: the QA verdict comment (per-AC evidence table, findings, tier-1 triage, machine-readable block), JUnit XML and Playwright traces from tier-1, and the full agent run JSON — especially `permission_denials`, `num_turns`, `total_cost_usd`.

**Files you own**:

- `qa/tests/{contract,e2e,resilience,webhooks}` + `qa/qa_helpers` — the tier-1 suites (API unit tests live in `apps/api`). Tier-1 red always wins over agent opinion; this is the hard gate.
- `ci/claude/plugins/qa/skills/qa-run/SKILL.md` — the exploratory charter. **Privileged**: only you and the orchestrator may change it. A deterministic diff guard hard-stops any dev/rework push that touches it (added after a rework agent walked through a dead deny rule on PR #13 and edited it).
- `scripts/qa_gate.py` and `ci/claude/schemas/qa-verdict.json` — gate rules and evidence format. Also privileged paths; you author changes, the orchestrator applies them.

**Local loop**: `make stack-up && make gateway-dev`, `make seed`, then `make e2e` / `make contract` — run the suites yourself before changing them; the pipeline runs exactly these.

## A ticket from your seat

1. Dev phase opens a PR and labels it `qa-ready`. `phase-qa.yml` first asserts the merge ref is fresh against live `main` — stale trees park `needs-human` before spending anything.
2. Tier-1 runs deterministically: full 8-service stack boots, seed runs, then unit / contract / e2e / webhooks / resilience. Artifacts upload regardless of outcome.
3. Tier-2: one bounded `claude -p` run executes your charter — verifies each `AC-n` against the running app, runs the exploratory pass (console/network messages after every flow, fault injection via WireMock/Toxiproxy, the a11y keyboard pass), triages tier-1 failures as bug/infra/flake.
4. `qa_gate.py` decides, not the agent: tier-1 green AND agent `pass` → `qa-passed`. Any tier-1 red → `qa-failed` regardless of agent opinion (on the stale-tree incident the agent triaged the failure as out-of-scope; the gate still refused the pass — correctly). A `fail` finding without `repro_steps` is downgraded to `blocked` → `needs-human`. No valid structured output → `needs-human`.
5. Your discretionary work starts here. On `qa-passed`: audit the evidence table before anyone merges — "verified" must name what the agent did and saw, not restate the AC. On `qa-failed`: confirm the repro is real before rework burns budget on it. On `needs-human` with `error_max_turns`: **read `permission_denials` first**. Repeated denials = stuck agent, fix the sandbox; zero denials with steady progress = the charter outgrew the cap; propose the raise with the denial data (the dev manager decides, infra lands it — that is how QA went 80 → 120 turns).
6. Compound: promote every real agent-found repro into a permanent tier-1 regression test (the stale-pool 500, the latency-tolerance regression, and the surrogate 500 all live there now). Log the cycle in `docs/learning-log.md`.

## What changes vs. the traditional role

- You stop being the primary test author. Agents draft most tests; you adversarially review them. House example: an agent-written check asserted `"T" not in` the rendered due-date text to prove the raw RFC3339 timestamp was gone — but the correct label ends in "UTC", which contains the banned character. The assertion could never distinguish pass from fail. Agents [over-trust their own work and write tests that pass rather than tests that probe](https://www.epam.com/insights/ai/blogs/ai-agent-failure-modes-enterprise); reviewing for that is now the core skill.
- Your highest-leverage artifact is prose: the charter. Every sentence in `SKILL.md` is executed dozens of times, so charter scope is an economic decision — the a11y keyboard pass costs one MCP call per keystroke, and adding it forced the turn-cap raise. Budget charter growth in turns and dollars, not just coverage.
- You manage a probabilistic instrument. Contract-tier "determinism" is not guaranteed: Hypothesis's local-constants pool varies across processes even under `derandomize=True` — PR #14 failed on a real NUL-byte 500, then passed with byte-identical code. Treat a green contract run as probabilistic evidence; anything it catches once must become a pinned regression test.
- Verdict quality is a thing you calibrate, like a sensor. Evidence formats (repro steps or it downgrades), per-SHA statuses, and freshness asserts exist because agent confidence is not evidence.

## Failure modes to watch

- **Silent false passes.** Agents produce superficially successful runs and [fabricated success reports](https://arxiv.org/pdf/2605.30777) — this is why the exploratory charter mandates reading console messages and network requests after every flow, where three of this lab's real defects surfaced.
- **Trusting perceived confidence.** Experienced developers in METR's RCT were [19% slower with AI while believing they were 20% faster](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/); the same gap applies to an agent's verdict prose. Only the evidence table counts.
- **Misreading `error_max_turns`.** A fully-consumed budget was "stuck agent" on PR #10 (25 denials/run) and "charter outgrew the cap" on PR #13 (zero denials). Same symptom, opposite fixes. Denials first, always.
- **Charter creep.** Every probe you add runs on every ticket forever. Prune the charter like code.
- **Harness-masked bugs.** A test fixture's retry-drain hid a stale-pool 500 from tier-1 for five cycles; the agent found it by auditing the PR's own claims. Fixtures that heal the app are lying to you.

## Metrics you watch

- **Gate false-pass rate**: production/later-found defects per gate-passed merge, [trended over 30/60/90 days](https://daily.dev/blog/defect-density-and-escape-rate-agile-metrics-guide-2024/). The one number that says whether your signal is real. Be precise about the two layers: the verdict layer has never emitted a false pass within a ticket's own QA cycles, but one defect HAS escaped a gate-passed merge (the NUL-in-email 500 shipped in #3, surfaced only when #14's contract run happened to generate the input) — baseline escape rate 1/5, driven by the contract tier's probabilistic generation. Drive it down; never restate it as zero.
- QA↔rework cycles per ticket (loop-guard caps at 3) and verdict distribution (pass/fail/blocked/needs-human).
- Per-run `permission_denials`, `num_turns` vs cap, and cost per QA run (cap $8).
- Tier-1 triage mix: a rising `flake`/`infra` share means the suites are decaying; `bug` share is the suites working.
- Evidence-downgrade rate (fails demoted to blocked) — rising means the charter's evidence discipline is slipping.
- Charter yield: real findings per exploratory pass, against its turn cost.

## Boundaries

**Agents must never**: edit the charter, the tier-1 suites, `qa_gate.py`, schemas, or workflows (deny rules steer; the deterministic diff guard hard-stops and parks `needs-human`); fix code during QA; choose a state transition; leave injected faults in place (unremoved faults = `blocked`); pass with tier-1 red — no agent opinion overrides the deterministic layer. Design-mandated charter changes route through the dev agent's `concerns` output for you to apply by hand.

**You must never delegate**: adversarial review of agent-written tests; charter and gate-rule changes; the evidence audit behind a merge; promotion of agent repros into regression tests; triage of `needs-human` parks. These are the seat. An agent can draft any of them — the judgment that accepts them is yours.
