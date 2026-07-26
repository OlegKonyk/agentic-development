# Dev Manager Playbook

Your job is no longer allocating coding work — agents do the coding. Your job is
placing the gates, holding merge authority over machine-verified state, and
keeping the humans' oversight capacity from becoming the silent bottleneck. The
pipeline produces evidence; you decide whether evidence becomes shipped code.
Every number here derives from labels and statuses, so your decisions are
auditable — keep them that way.

## Your touchpoints in the pipeline

- **The merge button.** The `main` ruleset requires the `ci` and
  `qa/agent-verdict` status contexts, so a mergeable PR is already
  machine-verified. Your merge is the human gate over that state (`docs/sdlc.md`
  principle 4). A push after QA leaves the new SHA statusless — merge re-blocks
  by construction; never ask for that to be "fixed."
- **Admin bypass** on the ruleset. Break-glass only: orchestrator-authored
  pipeline maintenance and urgent main fixes, which by definition carry no
  `qa/agent-verdict`. Every bypass merge gets a one-line justification in the PR.
- **Labels you apply:** re-adding a phase label is the retry mechanism (the
  spec's loop-safety rule). You resolve `needs-human` parks: read the parking
  comment, fix the cause (e.g. update a stale branch), re-add the label
  (`qa-ready`, `stage:dev`, ...) to resume, or pull the ticket out of the
  pipeline entirely.
- **Artifacts you review:** the QA verdict comment (AC-by-AC evidence,
  findings with repro steps), the diff, the per-phase cost echoes, dev-report
  concerns.
- **Numbers you own:** per-phase `--max-turns` / `--max-budget-usd` caps, job
  timeouts, `MAX_PHASE_EVENTS`, and the 3-cycle QA↔rework limit. They live in
  privileged paths (`.github/workflows/`, `scripts/`), so changes land as
  orchestrator PRs — you set the values, you don't hand-edit in place.

## A ticket from your seat

1. PM gates a `stage:idea` issue in with `stage:spec`. Spec → design → dev run
   without you; you see a PR appear labeled `qa-ready`.
2. QA posts its verdict. On `qa-passed`: read the verdict comment *before* the
   diff — check each AC's evidence is specific (artifact paths, not
   assertions), spot-check one AC yourself, skim the diff for scope creep,
   glance at cost. Then merge. Deploy and `stage:done` follow automatically.
3. On `qa-failed`: do nothing — rework triggers itself. Watch the cycle count.
4. On `needs-human` (stale merge ref, `blocked` verdict, loop guard, tripped
   privileged-path guard): triage the parking comment. Environmental cause →
   fix and re-add the label. Substantive cause → decide human fix vs. re-drive.
5. On `error_max_turns`: read `permission_denials` first. Zero denials with
   steady progress means the phase outgrew its cap (raise it, via PR); repeated
   denials mean a stuck agent (fix the sandbox, not the ceiling).

**Routing a fix.** Behavior changes in `apps/` go through the full pipeline:
file `stage:idea`, gate with `stage:spec`. Pipeline maintenance goes
orchestrator PR + CI + bypass — agents cannot author it (no `workflows:
write`, deny rules, diff guard) and it can't earn a QA verdict. Precedents:
PR #12 (dev phase boots db+redis), PRs #16–#18 (privileged-path layers, QA
freshness assert). PR #15 is the edge case: an app bug, but one QA had already
characterized with repro evidence — a human fix verified by the same tests
shipped via bypass, because a full re-drive would add cost, not information.
That's the test: does the pipeline add *verification*, or only spend?

## What changes vs. the traditional role

You stop reviewing effort and start reviewing evidence. Anthropic's internal
data shows engineers shifting to a "70%+ code reviewer/reviser" role
([Anthropic](https://www.anthropic.com/research/how-ai-is-transforming-work-at-anthropic));
your team's throughput ceiling is now review capacity, not typing capacity —
DORA-aligned telemetry shows PR review time up 91% then 441% while PR size grew
154% ([Faros AI](https://www.faros.ai/blog/key-takeaways-from-the-dora-report-2025)).
So you manage oversight like you used to manage sprint capacity: who reviews
what, how deep, and reward quality of oversight, not volume of merges. Standups
shift from "what did you build" to "what did you verify and what did you park."

## Failure modes to watch

- **Rubber-stamping under volume.** 38% of reviewers find AI code harder to
  review than human code ([Codacy](https://blog.codacy.com/ai-agents-are-turning-developers-into-engineering-orchestrators-and-moving-the-risk-to-review));
  fatigue turns your gate into a formality. If review minutes per PR trend
  down while PR size trends up, quality of oversight is eroding.
- **Trusting felt speed.** METR's RCT: experienced devs were 19% slower with AI
  while believing they were 20% faster
  ([METR](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/)).
  Never accept "this is faster" without pipeline telemetry.
- **Volume without stability.** DORA 2024 found more AI adoption correlated
  with −1.5% throughput and −7.2% stability
  ([DORA 2024](https://dora.dev/research/2024/dora-report/)); 2025 added Rework
  Rate as a key metric because AI amplifies weaknesses
  ([DORA 2025](https://dora.dev/research/2025/dora-report/)). Merged-PR count
  alone is a vanity metric here.
- **Mentorship gap and skill atrophy.** Juniors ask seniors fewer questions
  when the agent answers first, and supervising agents requires the very
  skills that atrophy under delegation
  ([Anthropic](https://www.anthropic.com/research/how-ai-is-transforming-work-at-anthropic)).
  Assign your two devs real, non-agent design work on purpose.
- **Bypass creep.** Every "just this once" bypass of the QA gate weakens the
  precedent. If bypass frequency rises, the pipeline is failing — fix it,
  don't route around it.

## Metrics you watch

Weekly, from label/status telemetry, trends over levels: human review minutes
per agent PR and median PR size (the bottleneck pair); unplanned `needs-human`
rate; QA↔rework cycles per ticket; $ per merged PR (phase cost echoes); gate
false-pass rate (defects escaping `qa-passed`); bypass merges per month, with
reasons. Calibrate trust per person: who merges fast, and do their merges hold?

## Boundaries

Agents never merge, never bypass, never apply the entry label, never touch
`.github/workflows/`, `ci/claude/`, `scripts/`, or the budget caps — they hold
no identity that can, and that stays true. You, in turn, do not delegate: the
merge decision, the bypass decision, `needs-human` verdicts, cap changes, or
reading the QA evidence before merging. If you can't verify it, don't ship it.
