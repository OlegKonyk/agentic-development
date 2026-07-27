#!/usr/bin/env python3
"""Deterministic repeat-failure guard for the QA phase.

Builds this run's tier-1 failure signature — the tested tree, the per-suite
outcomes, and the exact set of failing tests from the JUnit XML — and compares it
with the signature embedded in the most recent QA verdict comment on the PR. When
they are identical AND the previous run's agent triage called every one of those
failures `infra` or `flake`, a second full agent pass would pay full price to
rediscover the same fact (PR #24: $3.34 then $2.36 for the identical gateway
rate-limit flake). The guard then tells phase-qa.yml to skip tier 2, and
scripts/qa_gate.py parks the PR at needs-human. It never turns a failure into a
pass: the only direction this can move the gate is toward a human.

Usage:
    qa_repeat_guard.py --tier1 unit=success e2e=failure ... \
        --reports reports --comments context/pr-comments.json \
        --tree <git tree sha> --head-sha <sha> \
        --signature-out agent-out/tier1-signature.json \
        --decision-out agent-out/repeat.json

Writes `repeat` (true/false) and `reason` to $GITHUB_OUTPUT. Exit code is always
0 — the outputs carry the decision.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MARKER = "<!-- sdlc:qa-verdict -->"
JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)
# PR comments are untrusted input (docs/sdlc.md, trust boundaries): only the
# pipeline's own verdict comments may steer this guard.
TRUSTED_AUTHORS = {"github-actions", "github-actions[bot]"}
BENIGN = {"infra", "flake"}


def failing_tests(reports_dir: Path) -> list[str]:
    """Every tier-1 testcase with a <failure>/<error> child, as classname::name.

    pytest records retries as <rerunFailure>, so a test that passed on rerun is
    not counted; a test that failed twice appears once (set semantics).
    """
    found: set[str] = set()
    for xml in sorted(reports_dir.glob("*.xml")):
        try:
            root = ET.parse(xml).getroot()
        except ET.ParseError:
            continue
        for case in root.iter("testcase"):
            if any(child.tag in ("failure", "error") for child in case):
                cls, name = case.get("classname", ""), case.get("name", "")
                found.add(f"{cls}::{name}" if cls else name)
    return sorted(found)


def _author(comment: dict) -> str:
    who = comment.get("author") or comment.get("user") or {}
    return (who.get("login") or "").lower()


def previous_block(comments_path: Path) -> dict | None:
    """Machine-readable block of the most recent pipeline QA verdict comment."""
    try:
        data = json.loads(comments_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    comments = data.get("comments", []) if isinstance(data, dict) else data
    for comment in reversed(comments or []):
        body = comment.get("body") or ""
        if MARKER not in body or _author(comment) not in TRUSTED_AUTHORS:
            continue
        blocks = JSON_BLOCK_RE.findall(body)
        if not blocks:
            return None
        try:
            return json.loads(blocks[-1])
        except json.JSONDecodeError:
            return None
    return None


def _norm(name: str) -> str:
    """Bare test function name: module path and parametrisation stripped.

    The two sides spell the same test differently — JUnit gives
    `qa.tests.e2e.test_board::test_x[chromium]`, while the agent's triage writes
    `qa.tests.e2e.test_board.test_x[chromium]` — so strip the parametrisation
    first, then take the last segment across every separator either side uses.
    """
    bare = re.sub(r"\[.*$", "", name)
    return re.split(r"::|/|\.", bare)[-1].strip().lower()


def triage_class(block: dict, test_id: str) -> str | None:
    """The previous run's classification for a failing test, matched by bare name."""
    target = _norm(test_id)
    for entry in (block.get("verdict") or {}).get("tier1_triage") or []:
        if _norm(entry.get("test", "")) == target:
            return (entry.get("classification") or "").lower()
    return None


def decide(current: dict, block: dict | None) -> tuple[bool, str, dict]:
    """Returns (repeat, reason, previous classification per failing test)."""
    if not current["failed_tests"]:
        return False, "no tier-1 test failures to repeat", {}
    previous = (block or {}).get("signature")
    if not isinstance(previous, dict):
        return False, "no previous verdict signature on this PR", {}
    if previous.get("tree") != current["tree"]:
        return False, "previous verdict tested a different tree", {}
    if previous.get("tier1") != current["tier1"]:
        return False, "tier-1 suite outcomes differ from the previous run", {}
    if sorted(previous.get("failed_tests") or []) != current["failed_tests"]:
        return False, "failing test set differs from the previous run", {}
    classes = {test: triage_class(block or {}, test) for test in current["failed_tests"]}
    if not all(cls in BENIGN for cls in classes.values()):
        return False, "previous triage did not call every failure infra/flake", classes
    return (
        True,
        "identical tier-1 failure on identical code, previously triaged "
        "infra/flake - QA agent skipped, parked for a human",
        classes,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier1", nargs="*", default=[], help="name=outcome pairs")
    ap.add_argument("--reports", default="reports", help="dir of tier-1 JUnit XML")
    ap.add_argument("--comments", required=True, help="gh-fetched PR comments JSON")
    ap.add_argument("--tree", required=True, help="git tree sha of the tested checkout")
    ap.add_argument("--head-sha", default="")
    ap.add_argument("--signature-out", required=True)
    ap.add_argument("--decision-out", required=True)
    args = ap.parse_args()

    current = {
        "tree": args.tree,
        "head_sha": args.head_sha,
        "tier1": dict(pair.split("=", 1) for pair in args.tier1),
        "failed_tests": failing_tests(Path(args.reports)),
    }
    Path(args.signature_out).write_text(json.dumps(current, indent=2))

    block = previous_block(Path(args.comments))
    repeat, reason, classes = decide(current, block)
    Path(args.decision_out).write_text(
        json.dumps(
            {
                "repeat": repeat,
                "reason": reason,
                "signature": current,
                "previous_signature": (block or {}).get("signature"),
                "previous_triage": classes,
            },
            indent=2,
        )
    )

    print(f"repeat={repeat} reason={reason}")
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"repeat={'true' if repeat else 'false'}\nreason={reason}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
