# Product Manager Playbook

Your job in this pipeline is to own "what done looks like." The spec is not a briefing
document anymore — it is the executable artifact: the product agent drafts it, the design
agent hardens it into numbered acceptance criteria, the dev agent builds to it, and the QA
agent verifies each `AC-n` verbatim against the running app. Every spec-driven tool in
2026 assumes a precise spec exists before any agent runs, which moves the PM role upstream
([spec-driven development](https://dev.to/krlz/spec-driven-development-in-2026-what-it-is-the-tooling-and-how-teams-actually-use-it-2fk2)).
You also hold the pipeline's entry gate: adding `stage:spec` is the human act that starts
agent spend. Nothing runs until you say so, and nothing you say vaguely gets un-vague later.

## Your touchpoints in the pipeline

- **Labels you apply**: `stage:spec` on an issue — the entry gate for **product tickets**.
  (Retro-filed lab proposals enter via the seat that owns the affected area: QA tooling →
  QA engineer, pipeline mechanics → infra, disputes → dev manager.) Re-adding `stage:spec`
  is the retry mechanism after you answer open questions. Other humans also re-add phase
  labels (`qa-ready` etc.) to unpark tickets; forward transitions are the App's alone.
- **Artifacts you review**: the product agent's spec comment (`spec_markdown`, draft
  `AC-n` list, `open_questions`, `estimated_scope`) and — critically — the design
  comment's **final** AC list. Per the QA charter, design's ACs win over the spec's if
  they differ. Your signoff moment is the design comment, not just the spec.
- **Files you own**: the `stage:idea` issue form, `docs/apps.md` product contracts
  (co-owned with QA), and the content of the product agent's charter
  (`ci/claude/plugins/product/skills/spec/SKILL.md`). That path is pipeline-privileged:
  you draft changes, the human orchestrator applies and merges them — agents cannot.

## A ticket from your seat

House example: ticket #5, "make the board scannable" — a deliberately vague ask.

1. An idea lands via the issue form as `stage:idea`. You sharpen the title/body: what
   observable problem, for whom. You do not write ACs yet.
2. You add `stage:spec`. The product agent reads `docs/apps.md` and the app code, then
   posts a proportional spec: problem statement, user stories, **scope IN / scope OUT**,
   draft ACs, and `open_questions`. On #5 it grounded "scannable" in three observable
   problems (unreadable timestamps, no overdue signal, meaningless card order) and
   explicitly cut the implied scope — filter/search/sort controls, priority fields, any
   visual redesign or theming — into scope OUT rather than silently building it.
3. If `open_questions` is non-empty and material: answer in an issue comment, re-add
   `stage:spec`. This is the agent-interviews-PM pattern — the agent surfaces ambiguity,
   you resolve it, and the answers become part of the durable ticket record
   ([Anthropic best practices](https://code.claude.com/docs/en/best-practices)).
4. Design posts the final `AC-1..AC-n`. Read this list line by line. Each AC is a single
   observable behavior; QA will mark it `verified`, `failed`, or `not_testable` with
   evidence. If an AC is wrong here, a wrong feature will pass QA honestly.
5. Dev and QA run unattended. You get involved again only on `needs-human` parks or when
   the QA findings comment shows the ACs themselves were the bug.
6. **Park vs. re-spec**: ambiguity the agent flagged → answer and re-add `stage:spec`.
   Direction fundamentally wrong or the ticket contradicts the product → strip labels
   back to `stage:idea` and rewrite; do not steer a moving pipeline with comments mid-dev.
   `needs-human` after 3 QA↔rework cycles usually means the spec, not the code, is stuck.
7. After deploy, the retro phase files improvement proposals as new `stage:idea` issues.
   They queue at your gate like everything else.

## What changes vs. the traditional role

- Specs are executed, not interpreted. No standup will catch a misunderstanding; the AC
  text is the whole conversation. Precision replaces persuasion.
- The backlog-grooming meeting becomes an async loop: agent drafts, you answer questions
  in comments. Your leverage is editing ACs and scope OUT lines, not writing prose.
- You control spend directly. Each `stage:spec` label triggers real cost (product/design
  ~$0.5–1 each, dev+QA several dollars per cycle). Gate-keeping is now a budget decision.
- "Definition of done" stops being a team norm and becomes a schema: if it is not an
  `AC-n` the QA agent can observe through the UI or API, it does not exist.

## Failure modes to watch

- **Vague AC words.** "Fast", "clean", "intuitive" become `not_testable` or, worse, get
  charitably `verified`. The product charter bans them; enforce the ban when you review.
- **Rubber-stamping the gate.** [MIT NANDA](https://www.forbes.com/sites/jasonsnyder/2025/08/26/mit-finds-95-of-genai-pilots-fail-because-companies-avoid-friction/)
  found 95% of GenAI pilots show no P&L impact; the survivors picked one pain point and
  integrated deeply. Promoting every idea to `stage:spec` recreates the failing 95%.
- **Ambiguity tax shows up as rework.** DORA added Rework Rate as a fifth key metric
  precisely because AI-heavy teams restart more work
  ([DORA 2025](https://dora.dev/research/2025/dora-report/)). Repeated QA↔rework cycles
  on a ticket are usually a spec defect surfacing two phases late.
- **Trusting felt progress.** METR's RCT found experienced devs 19% slower with AI while
  believing they were 20% faster ([arXiv 2507.09089](https://arxiv.org/abs/2507.09089)).
  Judge tickets by pipeline telemetry (labels, verdicts, cost), never by vibes.
- **AC drift.** Design may legitimately refine your ACs — but its list is what QA
  verifies. Skipping the design-comment review means shipping criteria you never read.

## Metrics you watch

Per ticket, straight from GitHub events — no surveys: lead time (`stage:spec` →
`deployed`); rework rate (phase re-entries, QA↔rework loop count); `open_questions`
count per spec (rising = worse idea intake, falling to zero = agent may be under-asking);
AC delta between spec and design (large deltas = your specs are underspecified);
`needs-human` parks caused by ambiguity vs. infra; cost per merged change. Trend beats
level on all of these ([Digital Applied](https://www.digitalapplied.com/blog/agentic-workflow-completion-metrics-pipeline-health-2026)).

## Boundaries

- Agents must never: apply `stage:spec` (entry is human-only by design), invent
  requirements beyond the ticket plus obvious product coherence, silently expand scope
  past a scope OUT line, or edit the issue form / product charter (privileged paths,
  enforced by deny rules and the pre-push diff guard).
- You must never delegate: the entry-gate decision for product tickets, answers to `open_questions`, the
  final-AC review at design time, and the park/kill call on a stuck ticket. An agent can
  draft any of these; the judgment — and the spend — stays yours.
