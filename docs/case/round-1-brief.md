# Round 1 brief — calibration tickets, all seats simulated

_Status: CLOSED 2026-07-26. Ledger and forecasts were committed before any
ticket ran (git history has the timestamp); results below are measured by
`scripts/lab_metrics.py` from pipeline telemetry._

## Study design

Window: opens 2026-07-26, closes when the ledger is exhausted (target ≤4
working days). Ledger: predefined below, no additions mid-round. Comparison:
the frozen Round 0 baseline (`round-0-baseline.md`); no manual lane this
round, so speed claims are trend-vs-baseline only and prove nothing about
human-vs-agent speed. Seats: all six simulated by the lab owner/orchestrator
working each playbook's touchpoints in-role — the stated purpose is testing
the *playbooks*, not the team; team friction data starts in Round 2.

## Ledger and forecasts (predefined)

| Ticket | Lane | Forecast (before running) |
|---|---|---|
| #20 per-phase cost comments | orchestrator (privileged paths — pipeline cannot self-modify) | ~$0 agent spend; <30 min; lands first so the round's tickets get full cost telemetry. Retro's first live run fires on its close |
| #4 filter board by status | full pipeline | control case: 0–1 rework cycles, $4–6 agent spend, ≤1.5 h wall, ships qa-passed |
| #7 degraded-reminder banner | full pipeline | 1 rework cycle, $6–9, ≤2.5 h wall, ships; risk: fault-injection interplay with the resilience tier |
| #8 paginate board + API | full pipeline | hardest: 1–2 rework cycles, $7–11, ≤3 h wall, possibly one needs-human park; risk: OpenAPI/contract changes ripple into e2e counts |

Forecast totals: ≤4 rework cycles, $17–26 agent spend, ≤7 h pipeline wall
clock across the three pipeline tickets.

## Results

| Ticket | Forecast | Perceived | Measured |
|---|---|---|---|
| #20 | ~$0 agent, <30 min | trivial; retro's first live run felt like the real product | ~14 min idea→deployed, $0 pipeline agents, retro $0.76/20t; retro filed 2 valid proposals (#22, #23) incl. auditing the orchestrator's own route choice |
| #4 | 0–1 rework, $4–6, ≤1.5 h, ships | feature trivially clean; ALL friction was environmental | ~51 min stage:spec→merge; ~$11.3 agent total (product 0.47 + design 1.47 + dev + QA 3.34/2.36/2.67 + rework 0.53/≈0.5); 2 rework label cycles (both correct no-op parks), 2 unplanned parks, verdicts failed/failed/passed; 14/14 ACs verified in every run; zero product defects |

| #7 | 1 rework, $6–9, ≤2.5 h, ships | the "risky" fault-injection ticket felt effortless — design pre-answered every trap | 31 min stage:spec→merge; product 0.50 + design 1.50 + dev ? + QA 2.87; 0 rework, 0 parks, first-pass qa-passed; 11/11 ACs incl. live WireMock/Toxiproxy fault-injection; migration + new endpoint + banner in one pass |

_#4 cost ran ~2× forecast entirely on environment: the 45-test e2e suite
outgrew the gateway's fixed 60-req/10s budget (root-caused by the QA agent
twice, fixed on main as #25). The gate refused honestly both times; rework
correctly declined to "fix" a flake in app code both times._

**Round totals (measured):** $21.72 agent spend, 584 turns, 1.88 h pipeline
wall clock, 2 rework label cycles, 2 unplanned parks — inside the forecast
envelope ($17–26, ≤4 rework) and far under the ≤7 h wall-clock bound.
**Headline:** forecast difficulty inverted measured cost (#4 "trivial" cost
$11.12; #8 "hardest" cost $4.36). Variance came from which ticket first hit a
latent environment defect, not from feature complexity — DORA's
amplifier thesis in miniature.

## Failure ledger

- **Gateway rate-limit incident (~$5.6 of #4's spend).** The 45-test e2e
  suite outgrew the gateway's fixed 60-req/10s budget; two QA runs failed on
  an unrelated test, two rework runs correctly no-op'd and parked. The QA
  agent root-caused it identically twice (`RATE_LIMIT=60`); fixed on main
  (#25, env-configurable, test profile 600). The gate refused honestly both
  times — zero false passes — but the pipeline had no way to say "this
  failure class is not rework-fixable," burning ~$1 and two parks to
  rediscover it (proposals #26/#28 address this).
- **PM answer-window race, 3/3 tickets.** Product→design transitions don't
  wait for open-question answers. #4 and #7 aligned anyway; #8 diverged on
  the highest-impact call (envelope vs header) and the documented
  design-wins rule resolved it cleanly — but by luck of reasoning quality,
  not by process guarantee.
- **Retro duplicate proposals.** Three retro runs independently filed the
  same dev-footer idea (#27/#30/#33): retro has no cross-run memory, so the
  human gate absorbed the dedupe — as designed, but it costs attention per
  shipped ticket.

## What changed because of this round

- #25 gateway `RATE_LIMIT` env-configurable (test profile 600) — root-cause
  fix for the round's only systematic failure.
- #21 per-phase cost telemetry (landed at round open, first full use here:
  14 cost comments across the 4 tickets, no undercount).
- Retro proposals #22 (charter names the bypass route) and #23
  (`lab_metrics` marks bypass-lane tickets) accepted and landed at close;
  #30/#33 closed as duplicates of #27.
- Queued for a human entry-gate decision: #26 (skip re-verification on
  repeat-identical infra flake), #27 (dev cost footer on the PR), #28
  (suite-size-aware capacity check), #31 (finer fault-injection lever), #34
  (QA evidence must name coverage when substituting an easier case).

## Recommendation

Proceed to Round 2 (team pilot) without structural changes: the operating
model held for a full round with one person in all six seats, gates refused
honestly under a systematic environment failure, and the retro loop generated
a real, evidence-backed backlog. Before Round 2, consider landing #26 and
#28 (both directly reduce the cost of the failure mode Round 1 actually hit)
and decide whether the product→design transition should wait for PM answers
when a spec marks its open questions material — the answer-race is benign
only while design keeps out-reasoning the PM.

## Limitations

Round 0 threats apply (small N, no control, self-graded). Round-1-specific:
one person plays six seats, so handoff friction, review fatigue, and
authority conflicts — the things Round 2 exists to observe — are invisible
here; forecasts were written by the same person who operates the pipeline.
