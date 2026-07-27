"""Tests for the deterministic QA guards.

The repeat guard can park a PR, so its two dangerous directions are pinned here:
it must never turn a failure into a pass, and it must never silently fail to
fire. Both bugs actually happened in review — a payload-shape mismatch made the
guard a no-op, and a normalizer collapsed parametrised cases so one test's
`flake` could answer for another's `bug`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from qa_gate import decide as gate_decide
from qa_repeat_guard import decide, failing_tests, previous_block, triage_class

FAILING = "qa.tests.e2e.test_taskboard::test_due_date_renders_human_readable[chromium]"
TRIAGE_ID = "qa.tests.e2e.test_taskboard.test_due_date_renders_human_readable[chromium]"
SIGNATURE = {
    "tree": "TREE1",
    "head_sha": "S1",
    "tier1": {"unit": "success", "e2e": "failure"},
    "failed_tests": [FAILING],
}


def block(classification: str = "infra", signature: dict | None = SIGNATURE) -> dict:
    return {
        "signature": signature,
        "verdict": {
            "tier1_triage": [{"test": TRIAGE_ID, "classification": classification}],
        },
    }


def current(tree: str = "TREE1", failed: list[str] | None = None) -> dict:
    return {**SIGNATURE, "tree": tree, "failed_tests": FAILING if failed is None else failed}


def test_fires_on_identical_tree_and_benign_triage() -> None:
    repeat, _, classes = decide({**SIGNATURE}, block("flake"))
    assert repeat is True
    assert classes == {FAILING: "flake"}


@pytest.mark.parametrize(
    ("case", "cur", "blk"),
    [
        ("real bug last time", SIGNATURE, block("bug")),
        ("tree changed", {**SIGNATURE, "tree": "TREE2"}, block()),
        ("different failing set", {**SIGNATURE, "failed_tests": ["other::test_x"]}, block()),
        ("different suite outcomes", {**SIGNATURE, "tier1": {"e2e": "success"}}, block()),
        ("no previous signature", SIGNATURE, {"verdict": {}}),
        ("no failures at all", {**SIGNATURE, "failed_tests": []}, block()),
    ],
)
def test_does_not_fire(case: str, cur: dict, blk: dict) -> None:
    repeat, reason, _ = decide(cur, blk)
    assert repeat is False, f"{case} must not skip tier 2 (reason was {reason})"


def test_conflicting_classifications_resolve_non_benign() -> None:
    """One parametrised case called `bug` must not be laundered by another's `flake`."""
    a = "qa.tests.e2e.test_filter::test_active_filter_is_indicated[chromium-doing]"
    b = "qa.tests.e2e.test_filter::test_active_filter_is_indicated[chromium-done]"
    blk = {
        "signature": {**SIGNATURE, "failed_tests": [a, b]},
        "verdict": {
            "tier1_triage": [
                {"test": a.replace("::", "."), "classification": "flake"},
                {"test": b.replace("::", "."), "classification": "bug"},
            ]
        },
    }
    repeat, _, _ = decide({**SIGNATURE, "failed_tests": sorted([a, b])}, blk)
    assert repeat is False


def test_carried_triage_keeps_the_chain_alive() -> None:
    """A park comment has no verdict, so the classifications ride in carried_triage."""
    assert triage_class({"carried_triage": {FAILING: "infra"}}, FAILING) == "infra"


@pytest.mark.parametrize("slurped", [True, False])
def test_previous_block_accepts_both_gh_payload_shapes(tmp_path: Path, slurped: bool) -> None:
    """`gh api --paginate --slurp` yields pages; plain --paginate yields comments."""
    body = "<!-- sdlc:qa-verdict -->\n\n```json\n" + json.dumps(block()) + "\n```\n"
    comments = [{"user": {"login": "github-actions[bot]"}, "body": body}]
    payload = [comments] if slurped else comments
    path = tmp_path / "comments.json"
    path.write_text(json.dumps(payload))
    assert (previous_block(path) or {}).get("signature") == SIGNATURE


def test_untrusted_comment_authors_are_ignored(tmp_path: Path) -> None:
    body = "<!-- sdlc:qa-verdict -->\n\n```json\n" + json.dumps(block()) + "\n```\n"
    path = tmp_path / "comments.json"
    path.write_text(json.dumps([{"user": {"login": "drive-by"}, "body": body}]))
    assert previous_block(path) is None


def test_failing_tests_ignores_a_test_that_passed_on_rerun(tmp_path: Path) -> None:
    (tmp_path / "e2e.xml").write_text(
        '<?xml version="1.0"?><testsuites><testsuite name="pytest">'
        '<testcase classname="q.test_a" name="test_flaky[chromium]">'
        '<rerunFailure message="timeout"/></testcase>'
        '<testcase classname="q.test_a" name="test_real[chromium]">'
        '<failure message="boom"/></testcase>'
        "</testsuite></testsuites>"
    )
    assert failing_tests(tmp_path) == ["q.test_a::test_real[chromium]"]


@pytest.mark.parametrize("tier1", [{"e2e": "failure"}, {"e2e": "success"}, {}])
@pytest.mark.parametrize("verdict", [None, {"verdict": "pass", "findings": []}])
def test_repeat_is_never_a_pass(tier1: dict, verdict: dict | None) -> None:
    gate, label, _ = gate_decide(tier1, verdict, {}, {"repeat": True, "reason": "r"})
    assert (gate, label) == ("failure", "needs-human")


def test_absent_repeat_leaves_the_gate_unchanged() -> None:
    assert gate_decide({"e2e": "success"}, {"verdict": "pass", "findings": []}, {}, None) == (
        "success",
        "qa-passed",
        "tier-1 green and agent verdict: pass",
    )
