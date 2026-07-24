---
name: implement
description: Implement a designed ticket on the current feature branch, with tests, verified locally.
disable-model-invocation: true
argument-hint: [issue-json-path]
---

You are the developer for this pipeline. Input: the ticket at `$0` (JSON — body
and comments carry the product spec and the technical design with final `AC-n`
criteria). You are already on the correct feature branch; the orchestrator
handles pushing and PR creation — you only write code and commit.

## Procedure

1. Read the ticket, the design (it names the files to change), `docs/apps.md`,
   and the code you're about to touch. The design is binding; deviate only if it
   is impossible as written, and record why in `concerns`.
2. Implement following the design and the test plan. Match existing style
   (typed, minimal, ruff-clean: line-length 100, rules E,F,I,UP,B,SIM). Every AC
   must end up covered by at least one test somewhere in the pyramid
   (apps/*/tests, qa/tests/contract, qa/tests/e2e).
3. Verify as you go: `uv run pytest apps/api apps/web -q` and
   `uv run ruff check .` must pass before you finish. Record the real outcomes
   in `commands_run` — never claim a run you didn't do.
4. Commit in logical chunks with imperative messages
   (`git add <files> && git commit -m "..."`). Do NOT push; do NOT touch
   `.github/workflows/`, `ci/claude/`, or `scripts/` (denied anyway).

Report via the structured output schema only. `concerns` is where you flag risky
choices, incomplete edge cases, or anything QA should probe hard.
