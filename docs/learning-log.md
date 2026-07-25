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

## 2026-07-24 — PR #10 QA cycles: the sandbox turn-burn loop (the most instructive failure)

The platform PR needed FOUR QA cycles; each failure was a real, distinct finding
the deterministic gate caught by parking `needs-human` instead of guessing:

1. **Seed step 401** — `qa_helpers.seed()` created tasks on an unauthenticated
   client (v2 needs a bearer). Fix: re-seed via the app's own module in the
   container. *All 5 tier-1 suites passed even here* — first proof the platform
   works in CI.
2. **error_max_turns @ 51/50** — read as "app outgrew the turn budget." Raised
   the cap 50→100. WRONG diagnosis.
3. **error_max_turns @ 101/100** — same wall one turn higher. The pattern
   (always exhausts, never finishes) said *stuck*, not *slow*. Pulled the run
   artifacts: **25 permission denials/run**. Under `--permission-mode dontAsk`,
   `Bash(curl *)` auto-denied every multi-line / piped / VAR=x command the agent
   naturally writes to test a live API. It spent 100 turns fighting the sandbox.
4. **Fix**: broad `Bash` guarded by the deny-list (dangerous verbs, pipeline-file
   edits) on a secret-less runner off main; QA-scoped disallow of repo/ticket
   mutation so it stays observe-and-report. Turns back to 80.

**Lessons**
- *A budget that is always fully consumed is a stuck agent, not a slow one.*
  Raising the ceiling masks it; read the failure mode, don't just extend it.
- Arg-scoped `Bash(...)` allowlists are a determinism trap for agents that write
  real shell (the research warned this). Allow broad Bash + strong deny-list for
  interactive-testing agents; keep tight allowlists for agents that only need a
  fixed command set.
- The pipeline's value showed again: deterministic tier-1 + the no-verdict→
  needs-human rule meant a badly-sandboxed agent never produced a false pass.
- Instrument for this: per-run `permission_denials` count belongs in the phase
  summary (a high count is the tell) — a candidate pipeline improvement.

### Resolved — cycle 4: qa-passed (67 turns, $2.03)

Broad-Bash fix worked. The agent verified all 9 ACs with strong evidence:
drove WireMock 500-injection + Toxiproxy db-latency (with fault removal and
recovery asserts), signed/duplicated webhooks for idempotency, auth matrix in
both curl and browser, cross-user isolation, and audited docs/apps.md against
the running app. This is the reality-grade agentic QA the project set out to
demonstrate. Net: 4 cycles, each failure a distinct real issue the gate caught;
zero false passes; the deterministic layer never wavered.

## 2026-07-24 — Cycle 5: the QA agent finds a real bug the harness was hiding

After the task-counter merge forced a fresh head SHA (per-SHA statuses are
fail-safe: new code must earn a new verdict), cycle 5 returned a decisive
**fail in 26 turns / $0.98**: after a Toxiproxy DB stall clears, the FIRST live
request 500s (asyncpg 'connection is closed' from a stale pooled connection).
Two-step repro, reproduced twice, root-caused from container logs.

What makes this the thesis-proving finding:
1. **The agent audited the PR's own claims** — it flagged that "teardown now
   asserts recovery" was true only in the test fixture, not the application.
   The fixture's retry-loop drain was *masking* the bug from tier-1.
2. **Human review missed it; deterministic suites missed it; the agent's
   exploratory chaos charter caught it.** Exactly the layered-QA argument.
3. Fix: bounded pre-use connection ping (heals stale conns transparently);
   the recovery assert is now strict single-attempt; the agent's repro is a
   permanent regression test.

Also observed: qa-failed auto-triggered rework, whose loop-guard (3) tripped →
needs-human. Guard caps need to distinguish config-iteration cycles from true
rework cycles — raised phase-qa's to 6 earlier; rework's stays tight on purpose.

## 2026-07-24 — Cycles 6-7: the QA↔fix hardening loop converges; PR #10 shipped

Cycle 6 (agent + Schemathesis, both real): (a) my cycle-5 ping fix used a 1s
bound that broke the *documented* 500ms-latency degraded-but-functional
scenario, and the failure was mislabeled as the 8s request deadline — the agent
flagged the on-call-debugging hazard specifically; (b) a lone UTF-16 surrogate
in a password (valid JSON!) crashed argon2 into an unauthenticated 500.
Fixes: ping budget joined the designed timeout set (500ms wire << 3s ping < 8s
deadline); validation exhaustion → honest 503; login rejects un-encodable
passwords as 401. Both became regression tests. Cycle 7: qa-passed, CLEAN,
merged. Deploy closed issue #3 (stage:done + deployed).

**Meta-lesson — this IS the product working.** Across 7 QA cycles the agent
found 3 real defects (stale-pool 500, latency-tolerance regression, surrogate
500) that 131 deterministic tests AND human review both missed; each was caught
by exploratory chaos/fuzz charters, each carried a clean repro, each hardened
the app (not the tests) before merge. The deterministic gate never emitted a
false pass. That is the thesis: predictable orchestration + agent-filled
content + evidence-gated merge = a QA loop that iteratively hardens a
reality-grade system. Timeout budgets are a designed SET, re-derived twice here.

## 2026-07-25 — Calibration #5/#9: rework walks through a dead deny rule

Tickets #5 (PR #14) and #9 (PR #13) were calibration runs; their re-drives
taught pipeline lessons more than app lessons.

1. **The "security boundary" was prompt-deep.** #9's design mandated an edit to
   the QA agent's own charter (`ci/claude/.../qa-run/SKILL.md`). The dev agent
   refused — its skill names the path off-limits — and the first QA cycle read
   like the boundary holding by design. The rework agent, whose skill lacked
   that sentence, simply made the edit (word-for-word the design §5 wording,
   transparently disclosed in its commit message). Root cause: every
   `Edit(//ci/claude/**)`-style deny rule was dead — a `//` prefix means
   absolute-from-filesystem-root, so the patterns matched nothing in the
   checkout. A boundary that exists only in one skill's prose is not a
   boundary. Fixes: repo-relative deny patterns, the same prohibition (plus
   "escalate via `concerns`") in the rework skill, and a deterministic diff
   guard before every dev/rework push — a hard stop no prompt can miss.
2. **Contract "determinism" is a lottery.** #14 qa-failed on a genuine main bug
   (NUL in the login email → asyncpg 500), then qa-passed with byte-identical
   contract/API code: Hypothesis's local-constants pool varies across
   processes even under `derandomize=True`, so generation order is not stable.
   A green contract tier is probabilistic evidence. The bug became PR #15 —
   NUL and lone surrogates now 422 at the model boundary, plus a
   surrogate-safe 422 echo (the naive validator-only fix converts the 500 into
   a *different* 500 in the error renderer; verified empirically). Pinning
   generation (hash seed / explicit database) is open follow-up work.
3. **`error_max_turns` ≠ stuck, this time.** #13's second QA run burned through
   its 80-turn cap (81 logged) with zero permission denials, no loops, and steady forward progress —
   the PR's own a11y charter makes keyboard probes cost one MCP call per
   keystroke. PR #10's lesson was "a consumed budget means a stuck agent —
   read the denials"; the refinement is "read the denials *first*: zero
   denials plus progress means the charter outgrew the cap." QA cap 80 → 120,
   and the triage rule is now in the spec's runaway-controls section.
