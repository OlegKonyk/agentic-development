# sdlc-watcher

The "agent on the lookout" runtime: a long-running process that watches a repo's
phase labels and dispatches Claude agent runs with the
[Claude Agent SDK](https://pypi.org/project/claude-agent-sdk/) — the SDK twin of
the GitHub Actions pipeline defined in `docs/sdlc.md`.

## What it is

The CI pipeline is event-driven: a `labeled` event fires a workflow, the
workflow runs `claude -p` via `scripts/run_agent.sh`, and an App token moves the
label. The watcher performs the same cycle from a shell instead of a runner:

1. **Poll** (`poller.py`): every `--interval` seconds, list open issues with
   `stage:spec` / `stage:design` / `stage:dev` and open PRs with `qa-ready` /
   `qa-failed` via the `gh` CLI. Each `(number, label)` pair is dispatched once
   while the label stays applied; removing and re-adding a label re-dispatches —
   the same retry semantics as the label-guarded workflows.
2. **Dispatch** (`dispatcher.py`): build the *same invocation CI builds* — one
   `claude_agent_sdk.query()` per phase with
   `ClaudeAgentOptions(cwd=<checkout>, setting_sources=[],
   permission_mode="dontAsk", max_turns=<phase cap>,
   output_format={json_schema from ci/claude/schemas/<phase>.json},
   plugins=[{"type": "local", "path": "ci/claude/plugins/<phase>"}])`.
   Turn caps mirror CI: product/design 30, dev/rework 120, QA 120.

## How it mirrors the CI without replacing it

The watcher is a second driver for the same state machine, not a fork of it.
Phase content (plugins, schemas, permission mode, turn caps) is read from the
same `ci/claude/` sources of truth, so a phase behaves identically whichever
driver runs it. The differences are about identity, not behavior:

- CI transitions labels with the **`sdlc-orchestrator` App token**, because
  `GITHUB_TOKEN` events are suppressed and App events chain phases. The watcher
  runs with **your personal `gh` login**: label changes it (or you) makes fire
  the CI workflows too. Run the watcher against a repo with the CI enabled and
  you get double dispatch — use it on a fork/sandbox repo, or filter with
  `--phase`, or keep `--dry-run`.
- CI loop safety (loop guard, `always()` transitions, `needs-human` parking,
  branch-protection contexts) lives in the workflows. The watcher's only
  built-in guard is the in-memory `(number, label)` dedupe; it deliberately does
  **not** write labels yet (see roadmap), so it cannot create label loops.

## Running it

Prereqs: Python >= 3.12, `gh` authenticated (`gh auth login`), and
`CLAUDE_CODE_OAUTH_TOKEN` (or `ANTHROPIC_API_KEY`) exported for execute mode.
Run from the repo root (schemas/plugins are resolved relative to cwd).

```sh
# dry-run (default): log what would be dispatched, touch nothing
uv run sdlc-watcher --repo owner/name

# only watch the QA phase, poll every 30s
uv run sdlc-watcher --repo owner/name --phase qa --interval 30

# actually dispatch agent runs
uv run sdlc-watcher --repo owner/name --execute
```

In execute mode the QA phase prepares a fresh checkout of the PR head under
`.worktrees/qa-pr-<n>` (`git fetch origin pull/<n>/head` +
`git worktree add --detach`) and runs the QA agent against it.

## Roadmap — what is stubbed

- **Product / design / dev / rework phases**: log-only stubs. They print the
  exact `query()` invocation they will make; wiring in issue-body context
  (`gh issue view --json body`, the HTML-marker sections) comes next.
- **QA tier 1**: the deterministic gate is a documented TODO in
  `dispatcher.py::_run_qa` — `docker compose up -d --wait`, `wrangler dev` +
  health-gated curl, `python -m app.seed`, then pytest / Schemathesis /
  Playwright with outcomes written to files and handed to the agent as paths.
  Today only tier 2 (the agent) runs.
- **Label transitions**: the watcher observes but does not write labels or
  commit statuses. Adding opt-in `gh issue edit` / `gh pr edit` transitions
  (with a personal-token loop guard) is the step that makes it a full CI stand-in.
- **Poller transport**: `gh` subprocess today; `httpx` against the REST API
  (already a dependency) for etag-based conditional polling later.
- **Persistence**: the dedupe set is in-memory; restarting the watcher may
  re-dispatch in-flight tickets.
