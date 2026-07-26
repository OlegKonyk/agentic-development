# SDLC lab — baseline metrics (OlegKonyk/agentic-development)

| issue | pr | lead_h | rework | needs_human | qa_verdicts | turns | cost_usd | cost_comments | human_label_events |
|---|---|---|---|---|---|---|---|---|---|
| #1 | #2 | 3.36 | 0 | 0 | qa-passed | 53 | 1.64 | 1 | 4 |
| #3 | #10 | — | 6 | 5 | qa-passed, qa-failed, qa-failed, qa-passed | 358 | 11.93 | 6 | 16 |
| #5 | #14 | 1.64 | 3 | 1 | qa-failed, qa-passed, qa-failed, qa-passed | 210 | 5.84 | 4 | 8 |
| #6 | #11 | 0.29 | 0 | 0 | qa-passed | 44 | 1.29 | 1 | 5 |
| #9 | #13 | 1.97 | 3 | 2 | qa-failed, qa-passed | 262 | 6.94 | 3 | 8 |
| **total** | — | 7.26 | 12 | 8 | — | 927 | 27.64 | 15 | 41 |

_Totals sum non-null cells only._

## Notes
- #3: no 'stage:spec' labeled event on the issue

## Provenance and known gaps

Frozen at Round 0 (2026-07-26) by `scripts/lab_metrics.py` from GitHub label
timelines and agent-cost comments; regenerate with
`uv run python scripts/lab_metrics.py`. Known undercount: only QA verdict
comments carry cost footers today — product/design/dev phase spend reaches the
step summary but not a comment, so `cost_usd`/`turns` reflect QA (and any
commented phases) only. Ticket #3 predates the `stage:spec` labeling
convention, so its lead time is unmeasurable. These gaps are themselves
Round 0 findings; fixing the cost-comment coverage is the lab's first
improvement proposal.
