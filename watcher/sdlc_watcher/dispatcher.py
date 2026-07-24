"""Dispatch phase runs with the Claude Agent SDK, mirroring the CI invocation.

Every phase builds the SAME invocation `scripts/run_agent.sh` builds in CI
(docs/sdlc.md, "Agent invocation profile") — plugin, schema, permission mode,
turn cap — via `claude_agent_sdk.query()` instead of `claude -p`. The QA phase
is implemented for real (fresh git worktree, then the agentic tier); the other
phases are log-only stubs for now.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from .models import PhaseRun, PhaseSpec, Ticket

log = logging.getLogger(__name__)

SCHEMAS_DIR = Path("ci/claude/schemas")
PLUGINS_DIR = Path("ci/claude/plugins")


def build_options(phase: PhaseSpec, checkout: Path, repo_root: Path) -> ClaudeAgentOptions:
    """The SDK twin of the `claude -p` flags in scripts/run_agent.sh."""
    schema = json.loads((repo_root / SCHEMAS_DIR / phase.schema).read_text())
    return ClaudeAgentOptions(
        cwd=str(checkout),
        setting_sources=[],
        permission_mode="acceptEdits",
        max_turns=phase.max_turns,
        output_format={"type": "json_schema", "schema": schema},
        plugins=[{"type": "local", "path": str(repo_root / PLUGINS_DIR / phase.plugin)}],
    )


def build_prompt(ticket: Ticket) -> str:
    kind = "issue" if ticket.kind == "issue" else "PR"
    return f"{ticket.phase.skill} {kind} #{ticket.number}: {ticket.title}\nURL: {ticket.url}"


class Dispatcher:
    def __init__(
        self,
        repo: str,
        repo_root: Path,
        dry_run: bool = True,
        worktree_base: Path | None = None,
    ) -> None:
        self.repo = repo
        self.repo_root = repo_root
        self.dry_run = dry_run
        self.worktree_base = worktree_base or repo_root / ".worktrees"

    async def dispatch(self, ticket: Ticket) -> PhaseRun:
        phase = ticket.phase
        run = PhaseRun(ticket=ticket, phase=phase, dry_run=self.dry_run)
        log.info(
            "dispatch phase=%s %s #%d (label=%s, dry_run=%s)",
            phase.name,
            ticket.kind,
            ticket.number,
            ticket.label,
            self.dry_run,
        )
        try:
            if phase.name == "qa":
                await self._run_qa(ticket, run)
            else:
                self._stub(ticket, run)
        except Exception as exc:  # keep the watch loop alive; CI's analog is needs-human
            log.exception("phase %s failed for #%d", phase.name, ticket.number)
            run.status = "error"
            run.error = str(exc)
        return run

    def _stub(self, ticket: Ticket, run: PhaseRun) -> None:
        """Log-only stub: shows the exact invocation this phase WILL make."""
        phase = ticket.phase
        log.info(
            "[stub] would run query(prompt=%r, options=ClaudeAgentOptions("
            "cwd=<checkout>, setting_sources=[], permission_mode='acceptEdits', "
            "max_turns=%d, output_format={'type': 'json_schema', 'schema': <%s>}, "
            "plugins=[{'type': 'local', 'path': %r}]))",
            build_prompt(ticket),
            phase.max_turns,
            SCHEMAS_DIR / phase.schema,
            str(PLUGINS_DIR / phase.plugin),
        )
        run.status = "stubbed"

    async def _run_qa(self, ticket: Ticket, run: PhaseRun) -> None:
        """QA phase: fresh worktree of the PR head, tier-1 stack (TODO), tier-2 agent."""
        if self.dry_run:
            log.info(
                "[dry-run] qa PR #%d: would `git fetch origin pull/%d/head` + "
                "`git worktree add %s FETCH_HEAD`, boot the stack, then run the QA agent",
                ticket.number,
                ticket.number,
                self.worktree_base / f"qa-pr-{ticket.number}",
            )
            run.status = "dry_run"
            return

        checkout = await asyncio.to_thread(self._make_worktree, ticket.number)

        # TODO(tier-1): mirror phase-qa.yml exactly before the agent runs:
        #   1. docker compose up -d --wait          (api :8000, web :8001, from the worktree)
        #   2. cd gateway && npm ci && npx wrangler dev &   then curl-retry
        #      http://localhost:8787/gw/healthz until healthy
        #   3. uv run python -m app.seed            (deterministic dataset)
        #   4. pytest api unit/integration; Schemathesis v4 (fixed --seed, bounded
        #      --max-examples, phases examples,coverage); pytest-playwright e2e with
        #      --base-url http://localhost:8787
        #   Outcomes must land in files handed to the agent as PATHS, never piped
        #   (10 MB stdin cap). Until then the agent sees only the checkout.
        log.warning("tier-1 stack boot + test run not implemented yet; running tier-2 agent only")

        options = build_options(ticket.phase, checkout=checkout, repo_root=self.repo_root)
        result = await self._query(build_prompt(ticket), options)
        run.output = result
        run.verdict = (result or {}).get("verdict")
        run.status = "completed"
        log.info("qa PR #%d verdict=%s", ticket.number, run.verdict)
        # NOTE: in CI the verdict then drives deterministic label transitions
        # (qa-passed / qa-failed / needs-human) with the App token. Here that
        # transition is the operator's `gh pr edit --add-label` — see README.

    async def _query(self, prompt: str, options: ClaudeAgentOptions) -> dict[str, Any] | None:
        structured: dict[str, Any] | None = None
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                if message.is_error:
                    raise RuntimeError(f"agent run failed: subtype={message.subtype}")
                log.info(
                    "agent done: turns=%s cost_usd=%s session=%s",
                    message.num_turns,
                    message.total_cost_usd,
                    message.session_id,
                )
                structured = getattr(message, "structured_output", None)
                if structured is None and message.result:
                    structured = json.loads(message.result)
        return structured

    def _make_worktree(self, pr_number: int) -> Path:
        """Fresh detached worktree at the PR head — the CI checkout's local twin."""
        path = self.worktree_base / f"qa-pr-{pr_number}"
        self.worktree_base.mkdir(parents=True, exist_ok=True)
        git = ["git", "-C", str(self.repo_root)]
        subprocess.run([*git, "fetch", "origin", f"pull/{pr_number}/head"], check=True)
        if path.exists():
            subprocess.run([*git, "worktree", "remove", "--force", str(path)], check=False)
        subprocess.run([*git, "worktree", "add", "--detach", str(path), "FETCH_HEAD"], check=True)
        return path
