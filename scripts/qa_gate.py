#!/usr/bin/env python3
"""Deterministic QA gate: combines tier-1 outcomes with the agent's structured
verdict and decides the pipeline transition. The model never chooses this.

Usage:
    qa_gate.py --tier1 unit=success contract=failure e2e=success \
               --result agent-out/qa-result.json --output agent-out/qa-output.json \
               --comment agent-out/qa-comment.md --repeat agent-out/repeat.json

Writes GitHub Actions outputs (gate, pr_label) to $GITHUB_OUTPUT and a markdown
comment (with an embedded machine-readable verdict block for the rework agent).
Exit code is always 0 — the *gate* output carries the decision.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

MARKER = "<!-- sdlc:qa-verdict -->"


def load_json(path: str) -> dict | None:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def decide(
    tier1: dict[str, str],
    verdict: dict | None,
    result: dict | None,
    repeat: dict | None = None,
) -> tuple[str, str, str]:
    """Returns (gate, pr_label, reason)."""
    tier1_green = all(v == "success" for v in tier1.values())

    # Repeat-identical infra/flake failure on identical code: tier 2 was skipped
    # on purpose (scripts/qa_repeat_guard.py). Escalate — never a pass.
    if repeat and repeat.get("repeat"):
        return "failure", "needs-human", repeat.get("reason", "repeat tier-1 failure")

    if verdict is None:
        subtype = (result or {}).get("subtype", "missing")
        return "failure", "needs-human", f"agent produced no valid verdict (subtype: {subtype})"

    v = verdict.get("verdict")
    findings = verdict.get("findings", [])

    if v == "fail" and not any(f.get("repro_steps", "").strip() for f in findings):
        v = "blocked"  # a fail without evidence is not a fail (spec: evidence over assertion)

    if v == "blocked":
        return "failure", "needs-human", "agent verdict: blocked"
    if not tier1_green:
        failed = [k for k, s in tier1.items() if s != "success"]
        return "failure", "qa-failed", f"tier-1 failures: {', '.join(failed)}"
    if v == "pass":
        return "success", "qa-passed", "tier-1 green and agent verdict: pass"
    return "failure", "qa-failed", "agent verdict: fail"


def render_comment(
    tier1: dict[str, str],
    verdict: dict | None,
    result: dict | None,
    gate: str,
    pr_label: str,
    reason: str,
    repeat: dict | None = None,
) -> str:
    lines = [MARKER, f"## QA verdict: **{pr_label}**", "", f"_{reason}_", ""]
    lines.append("| Tier-1 suite | Outcome |")
    lines.append("|---|---|")
    for name, outcome in tier1.items():
        icon = "✅" if outcome == "success" else "❌"
        lines.append(f"| {name} | {icon} {outcome} |")
    lines.append("")

    if repeat and repeat.get("repeat"):
        sig = repeat.get("signature") or {}
        prior = repeat.get("previous_triage") or {}
        lines.append("### Repeat failure — tier-2 agent skipped")
        lines.append("")
        lines.append(
            "The tier-1 failures below are identical to the previous QA verdict's, on an "
            f"identical tested tree (`{str(sig.get('tree', ''))[:12]}`), and that run's triage "
            "classified every one of them as environment/flake:"
        )
        for test in sig.get("failed_tests", []):
            lines.append(f"- `{test}` → previously **{prior.get(test, '?')}**")
        lines.append("")
        lines.append(
            "A second full agent pass would pay full price to rediscover the same fact, so it "
            "was not run. **This is not a pass** — the gate is red and the PR is parked "
            "`needs-human`. Fix the environment (or the test), then re-add `qa-ready`; any "
            "change to the tested tree — including merging a fixed `main` — re-enables the "
            "full run."
        )
        lines.append("")

    if verdict:
        acs = verdict.get("acceptance_criteria", [])
        if acs:
            lines.append("### Acceptance criteria")
            lines.append("| AC | Status | Evidence |")
            lines.append("|---|---|---|")
            for ac in acs:
                status = ac.get("status", "?")
                icon = {"verified": "✅", "failed": "❌"}.get(status, "⚠️")
                evidence = ac.get("evidence", "").replace("\n", " ")[:200]
                covering = (ac.get("covering_test") or "").strip()
                if covering:
                    evidence += f" — literal case covered by `{covering}`"
                lines.append(f"| {ac.get('id', '?')} | {icon} {status} | {evidence} |")
            lines.append("")
        findings = verdict.get("findings", [])
        if findings:
            lines.append("### Findings")
            for f in findings:
                lines.append(f"- **[{f.get('severity', '?')}] {f.get('title', '')}**")
                repro = f.get("repro_steps", "").strip()
                if repro:
                    lines.append(f"  - Repro: {repro}")
                for a in f.get("artifact_paths", []):
                    lines.append(f"  - Artifact: `{a}`")
            lines.append("")
        triage = verdict.get("tier1_triage", [])
        if triage:
            lines.append("### Tier-1 failure triage")
            for t in triage:
                cls = t.get("classification", "?")
                lines.append(f"- `{t.get('test', '?')}` → **{cls}** — {t.get('reason', '')}")
            lines.append("")
        if verdict.get("summary"):
            lines.append(f"**Summary:** {verdict['summary']}")
            lines.append("")

    if result:
        cost = result.get("total_cost_usd", 0)
        turns = result.get("num_turns", 0)
        lines.append(f"_Agent run: {turns} turns, ~${cost:.4f} (client estimate)._")
        lines.append("")

    lines.append("<details><summary>Machine-readable verdict</summary>")
    lines.append("")
    lines.append("```json")
    lines.append(
        json.dumps(
            {
                "gate": gate,
                "pr_label": pr_label,
                # Read by the NEXT run's scripts/qa_repeat_guard.py. When this
                # run skipped tier 2 there is no verdict to carry triage in, so
                # pass the classifications forward explicitly — without them the
                # guard could only ever fire on every other run.
                "signature": (repeat or {}).get("signature"),
                "carried_triage": (repeat or {}).get("previous_triage") or None,
                "verdict": verdict,
            },
            indent=2,
        )
    )
    lines.append("```")
    lines.append("")
    lines.append("</details>")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier1", nargs="*", default=[], help="name=outcome pairs")
    ap.add_argument("--result", required=True, help="full claude JSON payload path")
    ap.add_argument("--output", required=True, help="structured_output JSON path")
    ap.add_argument("--comment", required=True, help="where to write the markdown comment")
    ap.add_argument("--repeat", help="scripts/qa_repeat_guard.py decision JSON path")
    ap.add_argument("--signature", help="fallback tier-1 signature path (guard wrote it first)")
    args = ap.parse_args()

    tier1 = dict(pair.split("=", 1) for pair in args.tier1)
    result = load_json(args.result)
    verdict = load_json(args.output)
    repeat = load_json(args.repeat) if args.repeat else None
    # The signature must reach the next run even when the guard failed after
    # writing it — otherwise one hiccup disarms the following run too.
    if args.signature:
        fallback = load_json(args.signature)
        if fallback and not (repeat or {}).get("signature"):
            repeat = {**(repeat or {}), "signature": fallback}

    gate, pr_label, reason = decide(tier1, verdict, result, repeat)
    comment = render_comment(tier1, verdict, result, gate, pr_label, reason, repeat)
    Path(args.comment).write_text(comment)

    print(f"gate={gate} pr_label={pr_label} reason={reason}")
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"gate={gate}\npr_label={pr_label}\nreason={reason}\n")


if __name__ == "__main__":
    sys.exit(main())
