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

_TBD per ticket: measured lead time, cost, turns, rework, parks, verdicts;
perceived-difficulty note after each close._

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
