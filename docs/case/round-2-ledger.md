# Round 2 ledger — team pilot (DRAFT, pre-flight)

_DRAFT. Must be merged, dates confirmed and forecasts frozen, **before** the
round's first `stage:spec`. Nothing here may be added, removed, or re-forecast
once the window opens; changes go in the brief's failure ledger instead._

## Purpose, and what this round can / cannot prove

Round 1 tested the playbooks with one person in all six seats. Round 2 tests whether
they survive six people, producing what Round 1 could not: handoff friction (PM →
design ACs → dev → QA verdict, across humans who did not write each other's artifacts),
review burden spread over real reviewers, authority conflicts (who kills a ticket, who
merges, who raises a cap), and whether seat boundaries hold when occupants disagree.

**Comparison:** the frozen Round 0 baseline and Round 1's measured results. Round 0's
cost column is a documented undercount — only QA phases posted cost comments then
(`round-0-baseline.md`) — so **cost cannot be trended against it**; lead time, rework
and parks can. There is **no control lane** — no manual-only tickets, no randomization,
no A/B — and the reason is seat load and window length: it means running these tickets
twice, which six part-time seats in 26 days cannot staff. Plainly: this cannot prove
the team is faster, cheaper or better than the same team without agents, and deltas
against Round 1 are confounded by ticket mix and the six-humans change, inseparably.
Round 0's threats hold: small N, the lab owner grades work they helped produce,
public-repo Hawthorne, agent-verified components sharing failure modes with their
authors, and weak per-ticket comparability because tickets differ in size. The failure
ledger has equal prominence; a round where most tickets fail is a publishable result.

## Window

21–30 days. Proposed **2026-08-03 → 2026-08-28** (26 days), owner-confirmed at
pre-flight. The window closes on the date, not the ledger — unfinished tickets are
reported so.

## Ticket ledger (predefined)

Nine tickets, grounded in the Taskboard as it stands. Forecasts are anchored on Round
1's measured spend — **#4 $11.12** (2 environmental parks), **#7 $5.48** and **#8
$4.36** first-pass, mean **$6.99** — where variance came from *which ticket first hit a
latent environment defect*, not feature complexity. Two are softer than they look: #7's
dev phase is recorded unmeasured, so **$5.48 is derived by subtraction** from the $21.72
round total, and #8's $4.36 comes from the brief's totals sentence, not a results row.
Assume that repeats: one ticket will cost about double its band for reasons unrelated to
its content. Each also carries a forecast **wall clock** (`stage:spec`→merge), giving
effort a "before" leg: Round 1 measured 51/31/31 min for #4/#7/#8.

- **R2-1 — "Move back" action on each board row.** (small; developer)
  The board only advances todo→doing→done; a mis-click is undoable only by deleting the
  task. Web-only: `regress-btn`, task-scoped accessible name, filter+page preserved on
  redirect, one e2e case. _$4–6, 0–1 rework, ~40 min, first-pass; the control case._
- **R2-2 — Empty board and empty filtered columns say nothing.** (small; developer B)
  A new user, or `?status=done` with nothing done, gets bare column headings. Needs an
  observable empty state adding no second landmark — the a11y suite asserts exactly one
  `banner` and one `main`. _$3–5, 0 rework, ~30 min. DEV-B's first agent-PR review._
- **R2-3 — Due times typed into `/new` are silently treated as UTC.** (small/medium; bug; PM)
  `to_rfc3339_z` stamps a naive `datetime-local` value with UTC, so a user in another
  zone is reminded at the wrong hour. The board itself reads back honestly —
  `format_due_at` renders "… UTC" — so the gap is at *entry*: the `datetime-local`
  input in `templates/new.html` names no zone. The fix is a product decision first:
  label the field UTC, or convert a client-sent offset. _$5–8, 0–1 rework, ~60 min._
- **R2-4 — Urgency ordering is wrong once the board pages.** (medium/large; product
  decision on a real defect; API contract; PM primary, QA repro)
  No promise is broken: `docs/apps.md` scopes the soonest-`due_at` sort as
  **web-layer-only** and documents `GET /api/tasks` ordering as ascending id, and both
  hold. The defect is emergent — the web layer sorts only the 20 rows it fetched, so
  page 2 can hold a task due before everything on page 1. Contract-reading settles
  nothing; someone must *decide* whether urgency ordering is a promise and pay for it
  server-side (ordering param, OpenAPI + contract-suite change, a default call). _QA the
  repro, PM the decision, dev the build. $8–14, 1–2 rework, ~2 h, one park._
- **R2-5 — Session expiry mid-compose discards the typed task.** (medium; bug; dev manager)
  A 401 during `POST /new` raises `SessionExpired`, clears the cookie and redirects to
  `/login` with no `next` or draft. Genuine scope question: preserve the draft, or only
  fix the redirect? _$6–10, 1 rework, ~75 min. The bug-vs-scope call is the DM's._
- **R2-6 — Edit an existing task from the board.** (large; product-shaped; developer A)
  Title, description and `due_at` are settable only at creation. `PATCH /api/tasks/{id}`
  covers most of it but not all: `update_task` dumps with `exclude_none=True`, so
  `{"due_at": null}` is dropped and a due date cannot be *cleared*, so an edit form
  offering an empty due field is not purely web work. The rest is: route, form, CSRF,
  422 echo (whitespace-only title, past `due_at`), redirect back to the same filter and
  page, accessible names. _$10–16, 1–2 rework, ~2.5 h, largest diff here. PM's job is
  the scope OUT lines — this will try to become inline editing._
- **R2-7 — Find a task by title.** (medium/large; API contract; PM + developer B)
  Twenty tasks per page and no search. Adds a `q` filter to `GET /api/tasks` composing
  with `status`/`limit`/`offset` and preserving the envelope's `total` semantics, plus a
  board input. Substring or prefix, case sensitivity, empty `q`, description included —
  all PM calls. _$8–14, 1–2 rework, ~2 h. Revisits the envelope-vs-header class of
  decision #8 resolved by luck, not by process._
- **R2-8 — "I can't tell whether my reminders are actually going out."** (unsized; vague by design; PM)
  Filed verbatim, un-sharpened: the round's instrument for the PM seat. #7 already
  shipped the obvious reading: `GET /api/reminders/health`, the degraded banner, a
  per-row `reminder-badge` of pending/sent/failed. What is genuinely absent is per-task
  delivery **history** — `ReminderDelivery` rows are written and never read back — but
  the ticket says none of that. Finding the need already met is equally valid: killing
  it at the gate because #7 covered it is a **success** here, and the seat's judgment is
  what is measured. _Either ≤$2/≤20 min (spec written, then killed) or $6–18/~90 min._
- **R2-9 — Make a green contract run reproducible.** (medium; QA infrastructure; QA)
  Hypothesis input generation varies across processes even under `derandomize=True`
  (PR #14 failed on a real NUL-byte 500, then passed on byte-identical code), so a green
  contract tier is only probabilistic evidence — and the obvious lever is not one:
  `derandomize=True` forces `database=None`, and an example database replays only
  recorded failures, so it cannot constrain generation. Desired outcome: the same tree
  re-run reaches the same verdict, and a find once made stays found; how, and at what
  cost to coverage, is the spec's call. _$5–9, 0–1 rework, ~75 min; no product code._

Totals (forecast): **$51–100** — floor $51 if R2-8 is killed at the gate, $55 if not —
≤12 rework cycles, ≤6 unplanned parks, ~12 h wall clock, ≥7 of 9 deployed in-window.

## Seat assignment

| Seat | Owns this round | Playbook |
|---|---|---|
| Product manager | `stage:spec` entry gate on product tickets, `open_questions` answers, final-AC review at design, kill/re-spec calls. Primary: R2-3, R2-4, R2-7, R2-8 | `product-manager.md` |
| Dev manager | Merge authority **and** bypass authority on ticket PRs; triage of environmental, loop-guard and stale-merge-ref parks; cap/budget decisions. Primary: R2-5 | `dev-manager.md` |
| Developer A | Diff + `dev-report.json` review, rework supervision, reproduces a `needs-human` finding before acting; merges in `apps/` but **never their own agent's PR**. Primary: R2-1, R2-6 | `developer.md` |
| Developer B | Same seat, deliberately starting small; the cross-review that lets DEV-A's PRs merge, and vice versa. Primary: R2-2, R2-7 | `developer.md` |
| Infra engineer | Workflows, guards, identities, stack/gateway health; unparks infra causes; lands cap changes as orchestrator PRs; break-glass only on those privileged-path PRs, with the DM's recorded authorization | `infra-engineer.md` |
| QA engineer (lab owner) | Charter and tier-1 suites, evidence audits, gate rules, `stage:spec` on QA tooling; triage of verdict-layer parks (`blocked`, invalid output, disputed evidence). Primary: R2-9, plus the repro and measurement on R2-4 | `qa-engineer.md` |

Three non-delegable lists in `docs/playbooks/` overlap; the table rules on them now, not
mid-ticket: `needs-human` triage is claimed by QA, DM and developer (split by cause);
the merge decision by DM and developer (developers merge, never their own agent's PR);
bypass by DM and infra. Otherwise no seat performs another's non-delegable act, owner
included. An override forced by conflict is a **finding**: who overrode whom, why.

## Operating rules

1. **Serial execution.** One ticket past `stage:design` at a time: one subscription
   token serves every phase, so concurrent tickets contend and can fail mid-phase on
   rate limits, and serial runs keep per-ticket attribution — cost, wall clock, whose
   park — clean. A second may wait at `stage:idea`/`stage:spec`.
2. **Three numbers per ticket.** *Forecast* is above, frozen. *Perceived* is the primary
   seat's comment at close, written **before** telemetry: felt effort (h), felt cost
   ($), felt outcome (clean/churned/stuck), what was hardest. *Measured* comes from
   `lab_metrics.py` and per-phase cost comments. Perceived is never reported alone; the
   three-way gap is a headline metric (METR: 19% slower, feeling 20% faster).
3. **Review minutes self-reported and mandatory**, posted on each agent PR before merge
   — the one self-reported number the lab accepts.
4. **Budget, reconciled.** *Bottom-up*: the ticket bands sum to **$51–100**, assuming no
   environment defect. *Top-down*: Round 1 measured $6.99/ticket ($4.36–$11.12), so nine
   larger-skewed tickets give a ~$65 base, and its one environment defect added $5.6 —
   26% of round spend — on a single operator, so six people and two contract-touching
   tickets take a wider margin. **Plan on $65–85**: inside the bottom-up range, pricing
   in one doubled ticket. **Hard ceiling $110** = bottom-up top plus one over-run past
   it. Per ticket: stop-and-review at $15 (DM decides continue / re-spec / kill), hard
   stop $25; per-phase caps as Round 1 left them (QA $8) absent a DM-approved change.
5. **No mid-flight steering** — comments do not redirect a running pipeline; strip
   labels back to `stage:idea` and re-spec. Parks, bypasses and overrides get a one-line
   reason when they happen, not reconstructed at close.

## Pre-flight — repo-owner-only actions

No teammate and no agent can do these; all are checked off here before the window.

- [ ] **Collaborator invites accepted** by PM, DM, DEV-A, DEV-B, INFRA — accepted, not sent.
- [ ] **Permission per seat:** `write` for all five (`triage` can label but not merge;
  DM/DEV-A/DEV-B need merge). No `admin` beyond the owner and INFRA, who administers
  the ruleset and the App identity.
- [ ] **Break-glass:** DM added as a *named bypass actor* on the `main` ruleset, not
  given admin. Each bypass merge carries a one-line justification; bypass count is a
  reported metric.
- [ ] **Spend acknowledgment in writing from each seat:** repo `write` is the ability
  to spend the owner's Claude subscription by applying a label. Nobody else can read
  `CLAUDE_CODE_OAUTH_TOKEN` or the App key, but every `stage:spec` bills the owner.
- [ ] **Subscription-token contention acknowledged:** one OAuth token serves every
  phase. The owner confirms no other heavy Claude Code use on it during the window, or
  declares that as noise in the brief — the operational reason for the serial rule.
- [ ] **Window dates confirmed** and written into the Window section above.
- [ ] **Deploy path stays owner-only** — deploy secrets and any Cloudflare token out of
  agent jobs and out of teammate reach.
- [ ] **Each seat has read its playbook and `docs/sdlc.md`**, confirmed by name in the
  round-open comment.
- [x] **Readiness items landed** — PR #35 on `main` closed all four before this ledger:
  #26 skip re-verification on repeat-identical infra flake (`scripts/qa_repeat_guard.py`),
  #28 suite-size-aware capacity check (`scripts/e2e_capacity_check.py`), the
  product→design answer-window call (a `blocking` flag per open question in
  `ci/claude/schemas/spec-output.json`; `phase-product.yml` parks `needs-human` instead
  of advancing when any is blocking), and #34 `covering_test`. Nothing deferred.

## Success and failure criteria for the round

**Adopt** — the model goes to normal work — if all hold: ≥7 of 9 tickets reach
`deployed` in-window; spend ≤$110, median ticket ≤$12; **≤6 unplanned parks** for the
round (0.67/ticket — the forecast above, under Round 0's 1.6); **no escaped defect
observed in-window** on gate-passed merges, with the 30/60/90-day trend in a follow-up,
since an escape is by definition found later (the lab's own ran #3's merge → #14's QA)
and per the QA playbook is never restated as zero; median review minutes per agent PR
stable or rising as PR size rises (falling review time on growing diffs is the
rubber-stamp signal); no seat needed the owner for its non-delegable acts more than
once; **felt effort within ±50% of measured `stage:spec`→merge wall clock on ≥6 of 9**.

**Don't adopt** — stop, fix, re-run — if any hold: ≥3 tickets rescued by someone outside
the owning seat; >1 bypass merge; the 3-cycle QA↔rework limit hit on ≥3 tickets; spend
crosses $110 before ticket 7; or the perception gap inverts systematically, the team
calling the round faster and cheaper while telemetry says otherwise — METR reproduced
in-house, a stop signal for uncontrolled rollout, not for the lab.

**Inconclusive**, a legitimate reportable outcome: fewer than 6 tickets closed, the
window slips, or one environment defect dominates the round's cost as in Round 1 — in
which case the round measured the environment, not the team, and says so.
