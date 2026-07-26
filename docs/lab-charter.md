# The SDLC Lab Charter

This repository is an experimentation lab. Its research question:

> **What software development life cycle can a six-person team plus current AI
> tools actually run — and what does each role do in it?**

The apparatus is the label-driven agentic pipeline specified in
`docs/sdlc.md`; the specimen is the Taskboard app (`docs/apps.md`); the raw
record is `docs/learning-log.md`; the team's operating model is
`docs/playbooks/`. This charter defines the method: how experiments run, what
we measure, and what counts as evidence. It is binding the way the SDLC spec
is binding — if practice diverges, change practice or change this file in the
same PR.

## The team and the seats

Product manager, dev manager, two developers, one infrastructure engineer,
one QA engineer (the lab owner). Each seat has a playbook in
`docs/playbooks/` naming its pipeline touchpoints, what changes versus the
traditional role, and its boundaries. Agents fill phase *content*; humans own
entry (`stage:spec`), verification signals, merges, and everything the
privileged-path guard protects.

## Method

**Rounds.** Work happens in named rounds with a fixed window and a ticket
ledger written down *before* results exist — predefined ledgers are what made
the credible pilots citable ([Answer.AI's Devin
month](https://www.answer.ai/posts/2025-01-08-devin): 20 tasks, 3/3/14
success/inconclusive/fail) and their absence is what makes enthusiastic
writeups uncitable.

**Three numbers per ticket.** Before: forecast effort/outcome. After:
perceived effort/outcome. Always: measured actuals from pipeline telemetry.
The gap between them is itself a headline metric —
[METR's RCT](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/)
found developers 19% slower with AI while believing they were 20% faster.
Self-report is never accepted as a result on its own.

**Comparison.** Round 0 establishes a historical baseline from the five
tickets shipped before the lab was named (#1, #3, #5, #6, #9), computed by
`scripts/lab_metrics.py` and frozen in `docs/case/round-0-baseline.md`.
Later rounds compare against it; where a round can afford it, tickets may be
alternated between an agent-driven lane and a manual lane. Every brief states
which comparison it used and what that comparison cannot prove.

**Speed is always paired with stability.** Any throughput claim must appear
next to its counterweight (rework rate, change-failure rate, escaped
defects). [DORA 2025's](https://dora.dev/research/2025/dora-report/) core
finding is that AI raises throughput *and* instability, and that it amplifies
existing organizational strengths and weaknesses rather than fixing them.

**The failure ledger has equal prominence.** Every round's brief reports what
broke, what was inconclusive, and what it cost, with the same care as wins.
The most durable references in this literature are negative results.

**Transcripts are primary evidence.** Every agent run's full JSON payload is
already retained as a CI artifact; retention is a rule, not a habit
(the model: [Cloudflare's
workers-oauth-provider](https://github.com/cloudflare/workers-oauth-provider),
where preserved prompts made the process auditable).

## Metrics

Telemetry-first: lead time, rework, parks, verdicts, human label events, and
agent cost/turns are computed today by `scripts/lab_metrics.py` from GitHub
events (cost currently undercounts — only QA phases post cost comments; see
the baseline's provenance note). Deployment frequency, change-failure rate,
MTTR, gate false-pass rate, and the churn canary are derived per round from
the same event record plus defect attribution; the single self-reported
number in the system is reviewer minutes. Definitions:

| Metric | Definition | Why |
|---|---|---|
| Lead time | first `stage:spec` event → `deployed` event, per ticket | DORA key, pipeline-native |
| Deployment frequency | deploys per week | DORA key |
| Change-failure rate | shipped tickets needing corrective follow-up / shipped tickets | DORA key |
| MTTR | corrective ticket lead time | DORA key |
| Rework rate | `qa-ready` events per PR beyond the first | DORA's 5th key (2025); loop guard already counts it |
| Unplanned human interventions | `needs-human` parks per ticket, by cause | planned gates are the design; unplanned parks are the signal |
| Cost per merged change | Σ agent $ + turns across phases / merged PR | unit economics; run_agent.sh logs it |
| Human review minutes per agent PR | reviewer-reported, per PR | review burden is the documented emerging bottleneck |
| Gate false-pass rate | escaped defects originating in gate-passed merges / gate-passed merges | the gate's integrity; 1/5 at baseline (the NUL-in-email 500 shipped in #3's merge, surfaced in #14's QA) |
| Churn canary | % of agent-written code revised within 2 weeks | maintainability warning ([GitClear](https://www.gitclear.com/coding_on_copilot_data_shows_ais_downward_pressure_on_code_quality)) |

Banned vanity metrics: lines of code, % of code AI-written, suggestion
acceptance rate, raw task/PR counts, and unanchored sentiment — all rise
mechanically with agent volume while saying nothing about delivered value.

## The self-improvement loop

Formalized as the **retro phase** (`docs/sdlc.md`, phase table): every
`deployed` ticket triggers a read-only agent that reconstructs the ticket's
trajectory and drafts the learning-log entry plus ≤3 improvement proposals,
filed as `stage:idea` issues with evidence. A human applies `stage:spec` to
accept one — the identical entry gate features get — and the improvement then
flows through the same spec→design→dev→QA pipeline as product work. The loop
cannot close itself by construction (advisory phase, non-chaining token,
human gate). This is the mechanism behind the one trait the successful 5% of
pilots share: a system that learns from its own feedback
([MIT NANDA](https://www.forbes.com/sites/jasonsnyder/2025/08/26/mit-finds-95-of-genai-pilots-fail-because-companies-avoid-friction/)),
kept inside the governance that has held so far.

## Case outputs

- `docs/learning-log.md` — the raw, public, chronological record. Retro
  drafts land here after human review.
- `docs/case/round-N-brief.md` — one per round, from
  `docs/case/brief-template.md`: study design and limitations *first*, the
  three-number table, the failure ledger, cost, and a recommendation a
  reader can absorb in ten minutes.

## Round plan

- **Round 0 (done when this file merges):** apparatus named, playbooks
  written, retro phase live, baseline frozen from tickets #1/#3/#5/#6/#9.
- **Round 1 (lab owner, in-role):** run the remaining calibration tickets
  (#4 filter, #7 degraded-reminder banner, #8 pagination) exercising each
  seat's playbook touchpoints; first brief; retro proposals begin flowing.
- **Round 2 (team pilot):** 21–30 day window, predefined ledger, each team
  member working their seat per playbook; forecast/perceived/measured per
  ticket; second brief makes the case.

Exit criteria for calling the experiment a result either way: three rounds of
briefs with stable metrics definitions, a failure ledger, and at least one
round of the real team in-role.

## Threats to validity (standing limitations)

Small N; no randomized control (historical baseline + optional manual lane
only); the lab owner grades work they helped produce; public-repo Hawthorne
effects; agent-verified components share failure modes with the agents that
built them (mitigated, not eliminated, by the deterministic tier-1 gate); and
per-ticket comparability is weak because tickets differ in size. Briefs state
these every round; the lab claims *existence proofs and mechanisms* ("this
operating model ran, at this cost, with these failure modes"), not
generalized productivity numbers.

## Standing sources

DORA [2024](https://dora.dev/research/2024/dora-report/) /
[2025](https://dora.dev/research/2025/dora-report/) (individual gains ≠ org
throughput; amplifier, not fixer; the five keys),
[METR 2025](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/)
(perception gap),
[DX Core 4](https://getdx.com/research/) (operationalized SPACE successor),
Anthropic's [agent-building
guidance](https://www.anthropic.com/engineering/building-effective-agents) and
[internal-usage research](https://www.anthropic.com/research/how-ai-is-transforming-work-at-anthropic)
(role shift to reviewer/orchestrator; verification loops),
[Answer.AI](https://www.answer.ai/posts/2025-01-08-devin) and
[Cloudflare](https://github.com/cloudflare/workers-oauth-provider) (pilot and
lab-notebook structure). The full annotated bibliography is committed at
`docs/case/round-0-sources.md`.
