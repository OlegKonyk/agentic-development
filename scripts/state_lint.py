"""Lint the SDLC label state machine (docs/sdlc.md).

Asserts the canonical transition graph stays acyclic outside the single
sanctioned QA rework loop, that needs-human is terminal, and that every label
guarded on in .github/workflows/*.yml exists in the graph.

Run: python scripts/state_lint.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Canonical transition graph. Issue-side stage labels chain idea -> done;
# PR-side labels carry the QA verdict loop.
TRANSITIONS: dict[str, set[str]] = {
    "stage:idea": {"stage:spec"},
    "stage:spec": {"stage:design", "needs-human"},
    "stage:design": {"stage:dev", "needs-human"},
    "stage:dev": {"stage:qa", "needs-human"},
    "stage:qa": {"stage:done", "needs-human"},
    "stage:done": set(),
    "qa-ready": {"qa-passed", "qa-failed", "needs-human"},
    "qa-passed": set(),
    "qa-failed": {"qa-ready", "needs-human"},
    "needs-human": set(),
}

# The ONE sanctioned cycle: qa-failed -> qa-ready (dev rework), bounded by the
# max-attempts guard enforced by scripts/loop_guard.sh in the QA workflow.
SANCTIONED_CYCLE_EDGE: tuple[str, str] = ("qa-failed", "qa-ready")
MAX_QA_REWORK_ATTEMPTS = 3

# Labels that exist but never trigger a phase transition.
NON_TRANSITION_LABELS: set[str] = {"deployed", "bug", "P1", "P2", "P3"}

LABEL_GUARD_RE = re.compile(r"github\.event\.label\.name\s*==\s*['\"]([^'\"]+)['\"]")


def all_nodes() -> set[str]:
    nodes = set(TRANSITIONS)
    for targets in TRANSITIONS.values():
        nodes |= targets
    return nodes


def find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    """Return one cycle as a node path, or None if the graph is acyclic."""
    white, gray, black = set(graph), set(), set()
    parent: dict[str, str] = {}

    def dfs(node: str) -> list[str] | None:
        white.discard(node)
        gray.add(node)
        for nxt in sorted(graph.get(node, ())):
            if nxt in gray:
                path = [nxt, node]
                cur = node
                while cur != nxt and cur in parent:
                    cur = parent[cur]
                    path.append(cur)
                return list(reversed(path))
            if nxt in white:
                parent[nxt] = node
                found = dfs(nxt)
                if found:
                    return found
        gray.discard(node)
        black.add(node)
        return None

    while white:
        found = dfs(sorted(white)[0])
        if found:
            return found
    return None


def check_graph(errors: list[str]) -> None:
    src, dst = SANCTIONED_CYCLE_EDGE
    if dst not in TRANSITIONS.get(src, set()):
        errors.append(f"sanctioned rework edge {src} -> {dst} is missing from the graph")

    if MAX_QA_REWORK_ATTEMPTS != 3:
        errors.append(
            f"MAX_QA_REWORK_ATTEMPTS is {MAX_QA_REWORK_ATTEMPTS}; docs/sdlc.md mandates 3"
        )

    if TRANSITIONS.get("needs-human"):
        errors.append(
            "needs-human must be terminal but has outgoing transitions: "
            f"{sorted(TRANSITIONS['needs-human'])}"
        )

    # Remove the one sanctioned edge; everything left must be a DAG.
    pruned = {node: set(targets) for node, targets in TRANSITIONS.items()}
    pruned[src].discard(dst)
    cycle = find_cycle(pruned)
    if cycle:
        errors.append(
            "unsanctioned cycle in the label graph (only qa-failed -> qa-ready is allowed): "
            + " -> ".join(cycle)
        )


def check_workflow_guards(repo_root: Path, errors: list[str]) -> None:
    workflows_dir = repo_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return  # tolerated: workflows may not exist yet

    known = all_nodes() | NON_TRANSITION_LABELS
    for path in sorted(workflows_dir.glob("*.yml")):
        for label in LABEL_GUARD_RE.findall(path.read_text(encoding="utf-8")):
            if label not in known:
                errors.append(
                    f"{path.relative_to(repo_root)}: guard on unknown label {label!r} "
                    "(not in the docs/sdlc.md transition graph)"
                )


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    errors: list[str] = []
    check_graph(errors)
    check_workflow_guards(repo_root, errors)

    if errors:
        print("state_lint: FAIL", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(
        "state_lint: OK — graph acyclic outside the sanctioned qa-failed -> qa-ready loop "
        f"(max {MAX_QA_REWORK_ATTEMPTS} attempts), needs-human terminal, workflow guards known"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
