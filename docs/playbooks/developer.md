# Developer Playbook

You are no longer the primary typist. In this pipeline the dev agent writes the first draft of
every change (`/dev:implement`) and the first draft of every fix (`/dev:rework`); your job is
direction, verification, and the merge decision. This matches what Anthropic measured internally:
engineers describe their role as "70%+ code reviewer/reviser rather than net-new code writer,"
human turns per session dropped 33%, and planning decisions stayed human while execution moved to
the agent ([Anthropic research](https://www.anthropic.com/research/how-ai-is-transforming-work-at-anthropic)).
The standard you hold: nothing merges that you could not defend line-by-line in an incident review.

## Your touchpoints in the pipeline

- **Labels you apply (by hand, in the GitHub UI):** `qa-ready` on a PR — the retry mechanism after
  you fix a parked branch or update a stale merge base. You remove `needs-human` when you take a
  park. You never script label transitions yourself; automation goes through `scripts/transition.sh`.
- **Artifacts you review:** the agent PR diff; the PR body; `dev-report.json` in the run artifacts —
  especially `commands_run` (real command outcomes, e.g. `uv run pytest apps/api -q: 14 passed`)
  and `concerns`; `qa-verdict.json` findings when a PR comes back `qa-failed`.
- **Files you own:** `apps/api`, `apps/web`, and their tests. `.github/`, `ci/claude/`, and
  `scripts/` are orchestrator-only — you propose changes there as issues, you don't push them.
- **The merge button:** yours, once `ci` and `qa/agent-verdict` are green on the head SHA. Merge is
  the human gate by design (`docs/sdlc.md`); treat it as a review act, not a formality.

## A ticket from your seat

1. A ticket hits `stage:dev`. The workflow boots `db` + `redis` before the agent runs, so the agent
   can execute DB-backed tests itself. This means you get to demand evidence: a `commands_run`
   entry with a pass count, not "tests should pass."
2. The agent opens a PR (`Fixes #N`, labeled `qa-ready`). Skim the dev report first: empty or vague
   `commands_run` is a red flag before you read a single diff line; `concerns` tells you where the
   agent itself is unsure — start your review there.
3. QA runs both tiers. On `qa-failed`, the rework agent triggers automatically. Its skill forces it
   to reproduce each finding before fixing (rework rule 1) and to add a regression test that fails
   without the fix. Watch the next report for exactly that shape.
4. After max 3 QA↔rework cycles the loop guard parks the PR `needs-human`. Now it's yours: check
   out the branch, reproduce the finding from the verdict's `repro_steps` yourself — same rule 1
   applies to you — fix or redirect, push, re-add `qa-ready`.
5. Read `concerns` for escalations. Findings that require touching `.github/`, `ci/claude/`, or
   `scripts/` are routed there deliberately — a deterministic guard fails the push if an agent
   commit touches those paths. Hand these to the orchestrator; do not "quickly fix" them yourself
   in the agent's PR.
6. On `qa-passed`: fresh-eyes review. Audit the PR body's claims against the actual diff — our own
   QA agent has caught a PR body still claiming an edit "was not made" after rework made it
   (PR #13, `docs/learning-log.md`). If the body and the diff disagree, the diff is the truth and
   the discrepancy is a finding.
7. Merge. A push after QA leaves the new SHA without a verdict, so merge re-blocks automatically —
   never look for a way around that; it is the fail-safe working.

## What changes vs. the traditional role

- Writing code is now the minority activity; reviewing, reproducing, and deciding are the majority.
  Your expertise moves upstream (design review, spotting a doomed approach before the agent burns
  budget) and downstream (review quality), per
  [how Claude Code is used in practice](https://www.anthropic.com/research/claude-code-expertise).
- Review is harder, not easier: agent PRs are bigger and reviewers report AI code is harder to
  review than human code ([Codacy](https://blog.codacy.com/ai-agents-are-turning-developers-into-engineering-orchestrators-and-moving-the-risk-to-review)).
  Budget real time for it; a five-minute skim of a 400-line agent PR is not review.
- When you drive an agent locally: context discipline is the biggest quality and cost lever —
  course-correct early, `/clear` after two failed corrections, use subagents for investigation
  ([Claude Code best practices](https://code.claude.com/docs/en/best-practices)).

## Failure modes to watch

- **Over-trust / perception gap.** METR's RCT found experienced devs 19% slower with AI while
  believing they were 20% faster ([METR](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/)).
  Never report "the agent saved me time" from feel; use pipeline timestamps.
- **Rubber-stamping under volume.** Review time per PR is the exploding bottleneck across the
  industry; if you approve faster as PRs get bigger, you've stopped reviewing.
- **Plausible-but-wrong.** The trust-then-verify gap: implementations that look complete but miss
  edge cases. The stale-pool 500 in cycle 5 passed 131 deterministic tests and human review before
  the QA agent's chaos charter caught it (`docs/learning-log.md`). Green is necessary, not sufficient.
- **Copy-paste instead of refactor.** AI-era codebases show 8x growth in duplicated blocks and
  near-doubled 2-week churn ([GitClear](https://www.gitclear.com/ai_assistant_code_quality_2025_research)).
  In review, hunt for the near-duplicate of an existing helper.
- **Fixing the test instead of the code.** If a rework diff touches more test lines than app lines
  for a real defect, verify the regression test fails without the fix.

## Metrics you watch

- Your own review minutes per agent PR, and agent PR size (trend, not level).
- QA↔rework cycles per ticket (loop-guard signal) — rising means dev-phase quality is slipping.
- Escaped defects on gate-passed merges: anything found after `qa-passed` gets a postmortem line in
  the learning log.
- Duplication and 2-week churn in `apps/` — the maintainability canaries for agent-written code.
- Cost per merged PR (`total_cost_usd` is in every run artifact and phase comment).

## Boundaries

- **Agents must never:** edit `.github/`, `ci/claude/`, or `scripts/` (the push guard hard-fails and
  parks the ticket — privileged findings route through `concerns` to the orchestrator); push to
  `main` or push at all (the orchestrator pushes); apply labels; merge; claim a verification they
  didn't run — an assertion without a `commands_run` entry is treated as unverified.
- **You must never delegate:** the merge decision; the fresh-eyes review of an agent diff (an agent
  reviewing its own PR is not review); reproducing a `needs-human` finding before acting on it;
  the call to deviate from a design (that goes back to the ticket, not into a quiet commit).
