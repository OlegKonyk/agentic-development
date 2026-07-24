# Pipeline Learning Log

One entry per pipeline run (or operational incident). Record what the run
revealed about the agents and what we changed because of it. This file is the
"improve" half of run → observe → improve.

Template: **ticket / phase costs / verdict quality / gaps observed / changes made**.

## 2026-07-24 — Ticket #1 "task counter" (maiden voyage, PR #2)

- **Flow**: spec → design → dev → QA passed end-to-end unattended; ~8 spec ACs,
  dev added 12 E2E tests unprompted; QA verified all ACs with evidence.
  Costs: product ~$0.5, design ~$0.6, dev ~$1.9, QA $1.64/53 turns (estimates).
- **Verdict quality**: high — evidence-first, no false findings, sensible
  fallbacks when tools were unavailable; exploratory pass (unicode,
  double-submit, gateway auth) was genuinely useful.
- **Gaps observed**:
  1. Playwright MCP browser missing on the runner (Python vs Node browser
     caches) — the agent adapted with curl-based HTML assertions, valid here
     but not for a JS-heavy UI. **Change**: phase-qa now also runs
     `npx -y playwright install chromium`.
  2. The agent could not exercise "API down" (docker stop denied — sandbox held
     correctly) and fell back to code inspection. **Change**: the platform
     upgrade (issue #3) adds WireMock + Toxiproxy so fault injection is an
     allowed HTTP call, not a denied infra command.
  3. Label-guard runs ("skipped" noise in Actions) are working as designed but
     clutter the run list — acceptable for now; revisit if it impedes triage.
- **Calibration backlog**: issues #4–#9 exercise distinct work shapes (crisp
  feature, ambiguous ask, real bug, resilience feature, multi-layer feature,
  QA-infra change). Promote them one at a time and log each here.
