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

## 2026-07-24 — Issue #3 "reality-grade platform" (PR #10, human+agents authored)

- **Shape**: 4 parallel build agents over disjoint paths against a committed
  contract (docs/apps.md v2), then a human-driven integration gauntlet. The
  contract-first split worked: zero merge conflicts, and cross-agent seams
  (webhook HMAC format, gateway x-api-key, seed dataset) were exactly where
  the builders' structured warnings said to look.
- **Integration found 6 real defects** the builders could not have caught
  without running services — notably asyncpg's BEGIN bypassing command_timeout
  (a stalled DB wire hung requests forever; fixed with request-deadline
  middleware) and chaos-poisoned connection pools bleeding into the next test
  (teardown now asserts recovery). Property fuzzing found an int32 overflow 500.
- **Learning**: budgets must be designed as a set (wire latency < command
  timeout < request deadline < stall budget; latency scenarios under the
  deadline) — tuning them one test at a time produced three contradictory
  configurations before the coherent one.
- **Ops**: local Docker disk exhaustion crashed the daemon mid-gauntlet
  (host disk at 100%) — cost ~30 min. CI runners don't have this failure mode;
  another argument for the Actions-hosted execution model.
- Verified: 131 tests / 5 suites green locally; PR #10 sent through agent QA
  with the updated /qa:qa-run skill (fault-injection APIs now documented tools).
