"""Data model: phase specs mirroring the docs/sdlc.md state machine, plus runtime records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class PhaseSpec:
    """One phase of the pipeline: which label triggers it and how the agent is invoked.

    Mirrors the phase table in docs/sdlc.md; schema/plugin paths are relative to
    the repo root (`ci/claude/schemas/`, `ci/claude/plugins/`).
    """

    name: str
    label: str
    kind: str  # "issue" | "pr"
    skill: str
    plugin: str
    schema: str
    max_turns: int


# Same caps as the CI workflows: QA 50, dev 80, product/design 30.
PHASES: tuple[PhaseSpec, ...] = (
    PhaseSpec("product", "stage:spec", "issue", "/product:spec", "product", "spec-output.json", 30),
    PhaseSpec(
        "design", "stage:design", "issue", "/design:design", "design", "design-output.json", 30
    ),
    PhaseSpec("dev", "stage:dev", "issue", "/dev:implement", "dev", "dev-report.json", 80),
    PhaseSpec("qa", "qa-ready", "pr", "/qa:qa-run", "qa", "qa-verdict.json", 50),
    PhaseSpec("rework", "qa-failed", "pr", "/dev:rework", "dev", "dev-report.json", 80),
)

PHASES_BY_LABEL: dict[str, PhaseSpec] = {p.label: p for p in PHASES}
PHASES_BY_NAME: dict[str, PhaseSpec] = {p.name: p for p in PHASES}


@dataclass(frozen=True)
class Ticket:
    """An open issue or PR currently carrying a phase label."""

    number: int
    kind: str  # "issue" | "pr"
    title: str
    label: str
    url: str

    @property
    def phase(self) -> PhaseSpec:
        return PHASES_BY_LABEL[self.label]

    @property
    def key(self) -> tuple[int, str]:
        # Issues and PRs share one number sequence on GitHub, so this is unambiguous.
        return (self.number, self.label)


@dataclass
class PhaseRun:
    """Record of one dispatch attempt for a ticket."""

    ticket: Ticket
    phase: PhaseSpec
    dry_run: bool
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: str = "pending"  # pending | stubbed | dry_run | completed | error
    verdict: str | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
