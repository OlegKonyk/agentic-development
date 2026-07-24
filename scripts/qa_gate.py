#!/usr/bin/env python3
"""Deterministic QA gate: combines tier-1 outcomes with the agent's structured
verdict and decides the pipeline transition. The model never chooses this.

Usage:
    qa_gate.py --tier1 unit=success contract=failure e2e=success \
               --result agent-out/qa-result.json --output agent-out/qa-output.json \
               --comment agent-out/qa-comment.md

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
    tier1: dict[str, str], verdict: dict | None, result: dict | None
) -> tuple[str, str, str]:
    """Returns (gate, pr_label, reason)."""
    tier1_green = all(v == "success" for v in tier1.values())

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
) -> str:
    lines = [MARKER, f"## QA verdict: **{pr_label}**", "", f"_{reason}_", ""]
    lines.append("| Tier-1 suite | Outcome |")
    lines.append("|---|---|")
    for name, outcome in tier1.items():
        icon = "✅" if outcome == "success" else "❌"
        lines.append(f"| {name} | {icon} {outcome} |")
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
    lines.append(json.dumps({"gate": gate, "pr_label": pr_label, "verdict": verdict}, indent=2))
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
    args = ap.parse_args()

    tier1 = dict(pair.split("=", 1) for pair in args.tier1)
    result = load_json(args.result)
    verdict = load_json(args.output)

    gate, pr_label, reason = decide(tier1, verdict, result)
    comment = render_comment(tier1, verdict, result, gate, pr_label, reason)
    Path(args.comment).write_text(comment)

    print(f"gate={gate} pr_label={pr_label} reason={reason}")
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"gate={gate}\npr_label={pr_label}\nreason={reason}\n")


if __name__ == "__main__":
    sys.exit(main())
