# Round 2 ledger — team pilot (DRAFT, pre-flight)

_DRAFT. Must be merged, dates confirmed and forecasts frozen, **before** the
round's first `stage:spec`. Nothing here may be added, removed, or re-forecast
once the window opens; changes go in the brief's failure ledger instead._

## Purpose, and what this round can / cannot prove

Round 1 tested the playbooks with one person in all six seats. Round 2 tests
whether they survive contact with six people, and exists to produce what Round 1
structurally could not: handoff friction (PM → design ACs → dev → QA verdict,
across humans who did not write each other's artifacts), review burden spread over
real reviewers, authority conflicts (who kills a ticket, who merges, who raises a
cap), and whether a seat's boundaries hold when its occupant disagrees with them.

**Comparison:** the frozen Round 0 baseline and Round 1's measured results. There
is **no control lane** — no manual-only tickets, no randomization, no A/B. Plainly:
this cannot prove the team is faster, cheaper or better than the same team without
agents. Deltas against Round 1 are confounded by ticket mix (Round 2 is larger and
more ambiguous by design) and by the six-humans change itself, inseparably. It
proves existence and mechanism only. Round 0's threats hold: small N, the lab owner
grades work they helped produce, public-repo Hawthorne, agent-verified components
sharing failure modes with their authors. The failure ledger gets equal prominence
in the brief; a round where most tickets fail is a publishable result.

## Window

21–30 days. Proposed **2026-08-03 → 2026-08-28** (26 days), confirmed by the repo
owner at pre-flight and written here before ticket one. The window closes on the
date, not on the ledger — unfinished tickets are reported as unfinished.

## Ticket ledger (predefined)

Nine tickets, grounded in the Taskboard as it stands. Forecasts are anchored on
Round 1's measured spend — **#4 $11.12** (2 unplanned parks, all environmental),
**#7 $5.48** and **#8 $4.36** first-pass, mean $7.02 — where variance came from
*which ticket first hit a latent environment defect*, not feature complexity.
Assume that repeats: one ticket below will cost about double its band for reasons
unrelated to its content.

- **R2-1 — "Move back" action on each board row.** (small; developer)
  The board only advances todo→doing→done, so a mis-click is unrecoverable short of
  deleting the task. Web-only: `regress-btn`, task-scoped accessible name,
  filter+page preserved on redirect, new testids in `docs/apps.md`, one e2e case.
  _$4–6, 0–1 rework, first-pass — the round's control case._
- **R2-2 — Empty board and empty filtered columns say nothing.** (small; developer B)
  A new user, or `?status=done` with nothing done, gets bare column headings. Needs
  an observable empty state adding no second landmark — the a11y suite asserts
  exactly one `banner` and one `main`.
  _$3–5, 0 rework. Deliberately the second developer's first agent-PR review._
- **R2-3 — Due times typed into `/new` are silently treated as UTC.** (small/medium; bug; PM)
  `to_rfc3339_z` stamps a naive `datetime-local` value with UTC, so a user in
  another zone is reminded at the wrong hour with no indication. The fix is a
  product decision first: label the field UTC, or convert a client-sent offset.
  _$5–8, 0–1 rework; the risk is spec churn, not code._
- **R2-4 — Ordering promise breaks across pages.** (medium/large; bug; API contract)
  `docs/apps.md` promises rows ordered soonest-`due_at` first, but that sort runs in
  the web layer over one 20-item page while the API pages by ascending id — page 2
  can hold a task due before everything on page 1. Fixing it moves ordering
  server-side: new `GET /api/tasks` ordering param, OpenAPI + contract-suite change,
  a call on the default. _QA owns the repro, PM the default, dev the build. $8–14,
  1–2 rework, one park plausible — the likeliest over-run._
- **R2-5 — Session expiry mid-compose discards the typed task.** (medium; bug; dev manager)
  A 401 during `POST /new` raises `SessionExpired`, clears the cookie and redirects
  to `/login` with no `next` and no draft. Genuine scope question: preserve the
  draft, or only fix the redirect target?
  _$6–10, 1 rework. The bug-vs-scope call is the DM's, not the agent's._
- **R2-6 — Edit an existing task from the board.** (large; product-shaped; developer A)
  Title, description and `due_at` are settable only at creation; `PATCH
  /api/tasks/{id}` already supports the change, so this is web work: route, form,
  CSRF, 422 echo (whitespace-only title, past `due_at`), redirect back to the same
  filter and page, accessible names. _$10–16, 1–2 rework, largest diff here. PM's
  job is the scope OUT lines — this will try to become inline editing._
- **R2-7 — Find a task by title.** (medium/large; API contract; PM + developer B)
  Twenty tasks per page and no search. Adds a `q` filter to `GET /api/tasks`
  composing with `status`/`limit`/`offset` and preserving the envelope's `total`
  semantics, plus a board input. Substring or prefix, case sensitivity, empty `q`,
  description included — all PM calls. _$8–14, 1–2 rework. Revisits the
  envelope-vs-header class of decision #8 resolved by luck, not by process._
- **R2-8 — "I can't tell whether my reminders are actually going out."** (unsized; vague by design; PM)
  Filed verbatim and un-sharpened, as the round's instrument for the PM seat. Could
  mean per-task delivery history (`ReminderDelivery` rows exist, never exposed), a
  banner change, a manual retry, or nothing. _Unbounded by design: either ≤$2 (spec
  written, returned to `stage:idea` or killed at the gate — that counts as a
  **success**) or $6–18 if it proceeds. Recorded either way._
- **R2-9 — Make a green contract run reproducible.** (medium; QA infrastructure; QA)
  Hypothesis input generation varies across processes even under `derandomize=True`
  (PR #14 failed on a real NUL-byte 500, then passed on byte-identical code), so a
  green contract tier is only probabilistic evidence. Pin the example database,
  commit historical finds as replayed regressions, make inputs recoverable from
  artifacts. _$5–9, 0–1 rework; touches no product behavior._

Totals (forecast): **$55–100 spend**, ≤12 rework cycles, ≤6 unplanned parks, ≥7 of
9 reaching `deployed` in-window.

## Seat assignment

| Seat | Owns this round | Playbook |
|---|---|---|
| Product manager | `stage:spec` entry gate on product tickets, `open_questions` answers, final-AC review at design, kill/re-spec calls. Primary: R2-3, R2-7, R2-8 | `product-manager.md` |
| Dev manager | Merge authority, `needs-human` triage, cap/budget decisions, break-glass justifications. Primary: R2-5 | `dev-manager.md` |
| Developer A | Diff + `dev-report.json` review, rework supervision, merges in `apps/`. Primary: R2-1, R2-6 | `developer.md` |
| Developer B | Same seat, deliberately starting small. Primary: R2-2, R2-7 | `developer.md` |
| Infra engineer | Workflows, guards, identities, stack/gateway health; unparks infra causes; lands cap changes as orchestrator PRs | `infra-engineer.md` |
| QA engineer (lab owner) | Charter and tier-1 suites, evidence audits, gate rules, `stage:spec` on QA tooling. Primary: R2-4, R2-9; runs measurement | `qa-engineer.md` |

No seat acts outside its playbook's "you must never delegate" list, and no seat
performs another's non-delegable act — the lab owner included. A conflict forcing
an override is a **finding**, recorded with who overrode whom and why.

## Operating rules

1. **Serial execution.** One ticket past `stage:design` at a time. Parallel work in
   Round 1 produced `docs/apps.md` conflicts (every seat edits that file), and all
   phases share one subscription token — concurrent runs contend and can fail
   mid-phase on rate limits. A second ticket may wait at `stage:idea`/`stage:spec`.
2. **Three numbers per ticket.** *Forecast* is above, frozen. *Perceived* is a
   comment on the issue at close by the primary seat, written **before** anyone
   looks at telemetry: felt effort (h), felt cost ($), felt outcome (clean /
   churned / stuck), one sentence on what was hardest. *Measured* comes from
   `scripts/lab_metrics.py` plus per-phase cost comments. Perceived is never
   reported alone; the three-way gap is a headline metric (METR: 19% slower while
   believing 20% faster).
3. **Review minutes self-reported and mandatory**, posted on each agent PR before
   merge — the one self-reported number the lab accepts.
4. **Budget ceiling.** Round 1 measured $7.02/ticket ($4.36–$11.12); nine tickets
   skewed larger gives a $65 base. Its one environment defect added $5.6 — 26% of
   round spend — with a single operator, so six people and two contract-touching
   tickets take a wider margin: **expected $65–85, hard ceiling $110.** Per ticket:
   stop-and-review at $15 (DM decides continue / re-spec / kill), hard stop $25.
   Per-phase caps stay as Round 1 left them (QA $8) absent a DM-approved change.
5. **No mid-flight steering** — comments do not redirect a running pipeline; strip
   labels back to `stage:idea` and re-spec. Parks, bypasses and overrides get a
   one-line reason when they happen, not reconstructed at close.

## Pre-flight — repo-owner-only actions

No teammate and no agent can do these; all are checked off here before the window.

- [ ] **Collaborator invites accepted** by PM, DM, DEV-A, DEV-B, INFRA — accepted, not sent.
- [ ] **Permission per seat:** `write` for all five (`triage` can label but not
  merge; DM/DEV-A/DEV-B need merge). No `admin` beyond the owner and INFRA, who
  administers the ruleset and the App identity.
- [ ] **Break-glass:** DM added as a *named bypass actor* on the `main` ruleset
  rather than given admin. Each bypass merge carries a one-line justification and
  bypass count is a reported metric.
- [ ] **Spend acknowledgment in writing from each seat:** repo `write` is the
  ability to spend the owner's Claude subscription by applying a label. Nobody else
  can read `CLAUDE_CODE_OAUTH_TOKEN` or the App key, but every `stage:spec` bills
  the owner.
- [ ] **Subscription-token contention acknowledged:** one OAuth token serves every
  phase. The owner confirms no other heavy Claude Code use on it during the window,
  or declares that as noise in the brief. This is the operational reason for the
  serial rule, not a preference.
- [ ] **Window dates confirmed** and written into the Window section above.
- [ ] **Deploy path stays owner-only** — deploy secrets and any Cloudflare token out
  of agent jobs and out of teammate reach.
- [ ] **Each seat has read its playbook and `docs/sdlc.md`**, confirmed by name in
  the round-open comment.
- [ ] **Readiness items landed or explicitly deferred:** #26 (skip re-verification
  on repeat-identical infra flake), #28 (suite-size-aware capacity check), and the
  product→design answer-window call — does a spec with material open questions block
  the transition? Deferring is fine; deciding silently is not.

## Success and failure criteria for the round

**Adopt** — the model goes to normal work — if all hold: ≥7 of 9 tickets reach
`deployed` in-window; spend ≤$110, median ticket ≤$12; unplanned parks ≤1.5/ticket;
zero new escaped defects on gate-passed merges; median review minutes per agent PR
stable or rising as PR size rises (falling review time on growing diffs is the
rubber-stamp signal and fails this criterion even if everything shipped); no seat
needed the lab owner to perform its non-delegable acts more than once; perceived
effort within ±50% of measured on ≥6 tickets.

**Don't adopt** — stop, fix, re-run — if any hold: ≥3 tickets rescued by someone
outside the owning seat; >1 bypass merge; the 3-cycle QA↔rework limit hit on ≥3
tickets; spend crosses $110 before ticket 7; or the perception gap inverts
systematically, the team calling the round faster and cheaper while telemetry says
otherwise — METR reproduced in-house, a stop signal for uncontrolled rollout, not
for the lab.

**Inconclusive**, a legitimate reportable outcome: fewer than 6 tickets closed, the
window slips, or one environment defect dominates the round's cost as in Round 1 —
in which case the round measured the environment, not the team, and says so.
