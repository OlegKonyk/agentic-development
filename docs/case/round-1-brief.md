# Round 1 brief — calibration tickets, all seats simulated

_Status: IN PROGRESS. Ledger and forecasts committed before any ticket ran
(see git history for the timestamp); results filled as tickets close._

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

## Failure ledger

_TBD._

## What changed because of this round

_TBD (retro proposals accepted, playbook edits)._

## Recommendation

_TBD._

## Limitations

Round 0 threats apply (small N, no control, self-graded). Round-1-specific:
one person plays six seats, so handoff friction, review fatigue, and
authority conflicts — the things Round 2 exists to observe — are invisible
here; forecasts were written by the same person who operates the pipeline.
