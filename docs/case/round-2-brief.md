# Round 2 brief — rehearsal (lab owner solo)

_Window 2026-07-28 → closed 2026-07-29 when the ledger was exhausted, ahead of
the 2026-08-28 date. Ledger frozen at the first `stage:spec`; forecasts
committed before any ticket ran._

## Study design, and what this round cannot prove

Eight tickets, predefined in `round-2-ledger.md` with a dollar band, a rework
count and a wall-clock figure each. Comparison: Round 1's measured results and
the Round 0 baseline — **with two stated limits**. Round 0's cost column is a
documented undercount (only QA phases posted cost comments then), so cost is not
trended against it. And **lead time is reported but not compared**: the owner
continued other heavy use of the shared subscription token during the window, so
wall clock is contaminated by work outside the round. Ticket R2-6's 18.35 h is
almost entirely an overnight gap, not pipeline time.

The larger limit is the round's name. **One operator worked all six seats.** A
rehearsal cannot produce handoff friction, review fatigue, or authority conflict
— the three things the lab exists to study. What it can do is find the ledger's
own bugs before five people meet them, and it did.

## Results

| Ticket | Forecast | Measured | Rework | Parks |
|---|---|---|---|---|
| R2-1 move-back | $4–6 | **$11.21** | 2 | 1 |
| R2-2 empty states | $3–5 | **$6.70** | 0 | 0 |
| R2-3 timezone entry | $5–8 | **$16.49** | 1 | 0 |
| R2-4 urgency ordering | $8–14 | **$11.48** | 0 | 0 |
| R2-5 session expiry | $6–10 | **$10.60** | 0 | 0 |
| R2-6 edit a task | $10–16 | **$26.65** | 2 | 1 |
| R2-7 search | $8–14 | **$13.75** | 0 | 0 |
| R2-8 reminder legibility | ≤$2 *or* $6–18 | **$9.29** | 0 | 0 |
| **Round** | **$46–91** | **$106.16** | **5** | **2** |

2,362 agent turns. Every ticket shipped: eight PRs merged, eight issues
`deployed`. Zero product defects escaped to `main`. Under the $150 ceiling,
16% over the forecast band.

**Forecasts were wrong in both directions, which is the useful finding.** The
"control case" (R2-1) cost 2.5× its band; the ticket rated hardest (R2-4) landed
inside its own. Ticket complexity did not predict cost. What predicted cost was
whether a ticket tripped a latent pipeline defect — the same conclusion Round 1
reached, now confirmed on fully-measured data.

The bands themselves were systematically low, and the cause is knowable: they
were derived from Round 1 figures that could not see dev-phase spend at all,
because `phase-dev.yml` granted `issues: read` and every cost comment was a
silent 403. Round 1's "$6.99 per ticket" was measuring roughly two-thirds of a
ticket. **Round 3's forecasts must be re-derived from this round's numbers.**

## Failure ledger

- **The implement charter never required `ruff format --check`** while its
  sibling rework charter did. Third occurrence (PRs #13, #14, #57): QA returns
  `qa-passed`, `ci` fails on formatting, and the merge is blocked with a green
  verdict attached. Fixed in #58. Cost: a human fix, an invalidated per-SHA
  verdict, and a full QA re-run.
- **R2-6 exhausted its turn cap** at 121/120 with **zero** permission denials —
  the documented "scope outgrew the cap" case (+1099 lines). Raising the cap was
  the prescribed response but required editing a privileged script, so the
  decision the rule assigns to the dev manager was gated behind a code change.
  Made operable as a repo variable (#69); the re-run finished at 173 turns.
- **Two agent-written tests were wrong**, both caught by QA and disproven by
  independent reconstruction rather than assertion: a 3-second future margin
  truncated by a minute-granularity input, and a strict-mode locator matching
  two `csrf_token` inputs present on every authenticated page. Rework then fixed
  only the test files — zero product code — which is the charter's rule holding.
- **A runtime dependency arrived unannounced.** R2-3 added `tzdata`; the call
  was correct (the web image ships no IANA database, so the feature would have
  passed locally and failed in the container) but it was absent from `concerns`,
  where a reviewer would look.
- **The blocking-questions gate never fired** — 8 tickets, ~24 open questions,
  zero parks — and missed one genuine case: whether to introduce the first
  client-side JavaScript into a deliberately no-JS app. See below.

## What the round found about the operating model

**Design overruled or refined the PM on every contested call — five for five.**
The envelope-vs-header shape, the no-JS architectural question, the
test-infrastructure seam, the ordering promise, and the corpus-digest reasoning.
On the no-JS call the PM was simply **wrong on the merits**: labelling the field
alone could not satisfy the ticket's own stated outcome. The pattern matters for
Round 3's expectations — **the human gate's value is not producing better
answers than the agents. It is deciding which questions a machine may settle
alone.** Design being right did not make the JavaScript decision design's call.

**The blocking flag is better than its charter.** It never fired, but R2-4
showed why: presented with an API-contract question, the agent reasoned *"either
choice satisfies every AC… unless someone knows of an external consumer relying
on id order"* — the reversibility test, applied correctly, while the charter's
wording describes categories. The round-close fix is to **write down what the
agent already does**, not to change its behaviour. The retro loop reached the
same conclusion independently (#65).

**Seat authority reads differently in practice than in the playbooks.** The
ledger assigns R2-5's bug-vs-scope call to the dev manager; the spec made the
call, with visible reasoning, before that seat saw it. "The DM makes this call"
operates as "the DM ratifies or overturns it." That is arguably better, and it
is not what a person reading the playbook would expect.

**A guard prevented a repeat of its own originating incident, for the first
time.** The merge-ref freshness assert — built after ticket #14 wasted $1.80 on
a stale tree — refused a run in exactly that situation and cost $0.

**Drawing the system found a bug that running it had not.** Extracting the
trigger graph revealed that the interactive `@claude` workflow fired on any
comment containing the mention, on a public repo, with write permissions and the
subscription token — reachable both by any GitHub user and, via App-token phase
comments, by the pipeline itself. No incident produced it; the diagram did
(#72). **Diagramming is a testing technique.**

## What changed because of this round

Merged mid-window: #58 (implement charter formatting), #69 (operable QA cap),
#72 (assistant trigger gate). Landing at close: the charter's blocking-question
wording, and a new rule making explicit what this round had to reason out —
**the apparatus freezes with the ledger.** Changing what an agent *decides*
mid-round invalidates the round's own comparison; repairing an instrument back
to its documented behaviour does not. That distinction was applied twice here
and was previously unwritten.

Queued at the entry gate from seven retro proposals: #59, #62, #63, #65, #67,
#70, #71.

## Recommendation

**Round 3 can proceed, and the ledger is now worth handing to people.** Three
things first: re-derive the forecasts from this round's measured numbers rather
than Round 1's; land #65 and #62 (the blocking-question fix, which the retro and
the operator derived independently); and correct the playbooks so seat authority
reads as *ratify or overturn* where that is what it is.

The access pre-flight remains the gate, and remains entirely the owner's:
collaborator invites accepted, `write` per seat, the `maintain` role plus its
ruleset bypass for the dev manager, spend acknowledgments, and confirmed dates.

## Limitations

One operator in six seats; no control lane; per-ticket comparability is weak
because tickets differ in size; lead time is contaminated by token contention
and is reported, not compared; the operator both ran and graded the round; and
the repo is public, so Hawthorne effects apply. The lab continues to claim
existence proofs and mechanisms — *this ran, at this cost, with these failure
modes* — never generalised productivity numbers.
