"""Invariants over the agent invocation profiles in scripts/run_agent.sh.

The same defect has now cost two phases a full run: an arg-scoped `Bash(...)`
allowlist auto-denies the compound, env-prefixed, piped and backgrounded
commands agents naturally write, so the agent spends its budget rephrasing
instead of working (PR #10 cycles 2-3 in QA; ticket #36 in dev — 121 turns,
$6.25, 13 denials). Both times it was found reactively, by a phase hitting its
first ticket that needed a live stack. These tests make the trust model an
asserted invariant instead of a lesson someone has to remember.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RUN_AGENT = Path(__file__).resolve().parents[1] / "run_agent.sh"
SOURCE = RUN_AGENT.read_text()

# `TOOLS="..."` is the allowlist; `DISALLOWED="..."` is the deny-list, where
# arg-scoped patterns are correct — a denial names an exact thing to refuse.
TOOLS_RE = re.compile(r'^\s*TOOLS="([^"]*)"', re.MULTILINE)
PHASE_RE = re.compile(r"^\s{2}(\w+)\)$", re.MULTILINE)

ANALYSIS_PHASES = {"product", "design", "retro"}
BUILD_PHASES = {"dev", "qa"}


def profiles() -> dict[str, str]:
    """Phase name -> its TOOLS string, in `case` order."""
    phases = PHASE_RE.findall(SOURCE)
    tools = TOOLS_RE.findall(SOURCE)
    assert len(phases) == len(tools), f"{len(phases)} phases but {len(tools)} TOOLS lines"
    return dict(zip(phases, tools, strict=True))


def test_every_phase_has_a_profile() -> None:
    assert set(profiles()) == ANALYSIS_PHASES | BUILD_PHASES


@pytest.mark.parametrize("phase", sorted(BUILD_PHASES | ANALYSIS_PHASES))
def test_no_phase_uses_an_arg_scoped_bash_allowlist(phase: str) -> None:
    """`Bash(uv run *)` does not match `VAR=1 uv run ...` or `cd x && uv run ...`.

    Boundaries belong in the deny-list, the credential-less checkout, and the
    pre-push privileged-path guard — not in an allowlist that quietly refuses
    ordinary shell.
    """
    tools = profiles()[phase]
    scoped = re.findall(r"Bash\([^)]*\)", tools)
    assert not scoped, f"{phase} re-introduced arg-scoped Bash: {scoped}"


@pytest.mark.parametrize("phase", sorted(ANALYSIS_PHASES))
def test_analysis_phases_get_no_shell_at_all(phase: str) -> None:
    """Product, design and retro read and reason; they never execute."""
    assert "Bash" not in profiles()[phase]


@pytest.mark.parametrize("phase", sorted(BUILD_PHASES))
def test_build_phases_get_broad_bash(phase: str) -> None:
    """Dev and QA must be able to run the stack they are asked to build/verify."""
    assert re.search(r"(^|,)Bash(,|$)", profiles()[phase]), f"{phase} lost broad Bash"


def test_qa_cannot_mutate_the_repo_or_the_ticket() -> None:
    """QA observes and reports; the deterministic steps own commits and comments."""
    qa_block = SOURCE.split("  qa)")[1]
    disallowed = re.search(r'DISALLOWED="([^"]*)"', qa_block).group(1)
    for denied in ("git commit", "git add", "gh pr comment", "gh issue comment"):
        assert denied in disallowed, f"QA may now {denied}"


def test_dev_keeps_commit_rights_but_cannot_mutate_the_ticket() -> None:
    dev_block = SOURCE.split("  dev)")[1].split("  qa)")[0]
    disallowed = re.search(r'DISALLOWED="([^"]*)"', dev_block).group(1)
    assert "git commit" not in disallowed, "dev must commit; the workflow pushes"
    for denied in ("gh pr comment", "gh issue comment", "gh pr merge"):
        assert denied in disallowed, f"dev may now {denied}"
