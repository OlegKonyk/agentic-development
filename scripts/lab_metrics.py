#!/usr/bin/env python3
"""Baseline metrics for shipped SDLC-lab tickets, computed from GitHub via the gh CLI.

Usage: uv run python scripts/lab_metrics.py [--json] [ISSUE ...]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from typing import Any

REPO = "OlegKonyk/agentic-development"
DEFAULT_ISSUES = (1, 3, 5, 6, 9)
PAGE_SIZE = 100

# Verdict footer: "_Agent run: 64 turns, ~$1.8001 (client estimate)._"
RUN_FOOTER = re.compile(r"Agent run:\s*(\d+)\s+turns,\s*~\$(\d+(?:\.\d+)?)")
# Step-summary style: "Agent phase `dev` ... 38 turns, ~$1.186 ..."
PHASE_LINE = re.compile(r"Agent phase\b[^\n]*?(\d+)\s+turns,\s*~\$(\d+(?:\.\d+)?)")

LINKED_PR_QUERY = """\
query($o: String!, $r: String!, $n: Int!) {
  repository(owner: $o, name: $r) {
    issue(number: $n) {
      closedByPullRequestsReferences(first: 10, includeClosedPrs: true) {
        nodes { number state mergedAt }
      }
    }
  }
}"""


def _gh(args: list[str]) -> str:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"gh {args[0]} failed: {proc.stderr.strip()[:200]}")
    return proc.stdout


def gh_api_paged(path: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        sep = "&" if "?" in path else "?"
        batch = json.loads(_gh(["api", f"{path}{sep}per_page={PAGE_SIZE}&page={page}"]))
        if not isinstance(batch, list):
            raise RuntimeError(f"expected a list from {path}")
        items.extend(batch)
        if len(batch) < PAGE_SIZE:
            return items
        page += 1


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def label_events(timeline: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Chronological (event, label, created_at, actor) rows from a timeline."""
    rows = [
        {
            "event": ev["event"],
            "label": (ev.get("label") or {}).get("name", ""),
            "created_at": ev.get("created_at", ""),
            "actor": (ev.get("actor") or {}).get("login", ""),
        }
        for ev in timeline
        if ev.get("event") in ("labeled", "unlabeled")
    ]
    return sorted(rows, key=lambda r: r["created_at"])


def first_labeled_at(events: list[dict[str, str]], name: str) -> datetime | None:
    for ev in events:
        if ev["event"] == "labeled" and ev["label"] == name:
            return parse_ts(ev["created_at"])
    return None


def linked_merged_pr(issue: int, notes: list[str]) -> int | None:
    owner, repo = REPO.split("/")
    out = _gh(
        [
            "api",
            "graphql",
            "-f",
            f"query={LINKED_PR_QUERY}",
            "-F",
            f"o={owner}",
            "-F",
            f"r={repo}",
            "-F",
            f"n={issue}",
        ]
    )
    nodes = json.loads(out)["data"]["repository"]["issue"]["closedByPullRequestsReferences"][
        "nodes"
    ]
    merged = [n for n in nodes if n.get("state") == "MERGED"]
    if not merged:
        notes.append("no merged linked PR found")
        return None
    if len(merged) > 1:
        notes.append(f"{len(merged)} merged linked PRs; using the last-merged one")
    merged.sort(key=lambda n: n.get("mergedAt") or "")
    return int(merged[-1]["number"])


def parse_cost_comments(numbers: list[int]) -> tuple[float, int, int]:
    """Sum (cost_usd, turns, comments_parsed) from agent-cost lines in comments."""
    cost, turns, parsed = 0.0, 0, 0
    for number in numbers:
        for comment in gh_api_paged(f"repos/{REPO}/issues/{number}/comments"):
            body = comment.get("body") or ""
            matches = set(RUN_FOOTER.findall(body)) | set(PHASE_LINE.findall(body))
            if not matches:
                continue
            parsed += 1
            for t, c in matches:
                turns += int(t)
                cost += float(c)
    return round(cost, 4), turns, parsed


def collect_issue(issue: int) -> dict[str, Any]:
    notes: list[str] = []
    row: dict[str, Any] = {
        "issue": issue,
        "pr": None,
        "lead_time_hours": None,
        "rework_cycles": None,
        "needs_human_count": None,
        "qa_verdicts": None,
        "agent_turns": None,
        "agent_cost_usd": None,
        "cost_comments_parsed": None,
        "human_touch_events": None,
        "notes": notes,
    }

    issue_events: list[dict[str, str]] = []
    timeline_ok = True
    try:
        issue_events = label_events(gh_api_paged(f"repos/{REPO}/issues/{issue}/timeline"))
    except (RuntimeError, json.JSONDecodeError, KeyError) as exc:
        timeline_ok = False
        notes.append(f"issue timeline unavailable: {exc}")

    spec_at = first_labeled_at(issue_events, "stage:spec")
    deployed_at = first_labeled_at(issue_events, "deployed")
    if spec_at and deployed_at:
        row["lead_time_hours"] = round((deployed_at - spec_at).total_seconds() / 3600, 2)
    elif timeline_ok:
        if not spec_at:
            notes.append("no 'stage:spec' labeled event on the issue")
        if not deployed_at:
            notes.append("no 'deployed' labeled event on the issue")

    pr: int | None = None
    try:
        pr = linked_merged_pr(issue, notes)
        row["pr"] = pr
    except (RuntimeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        notes.append(f"linked-PR lookup failed: {exc}")

    pr_events: list[dict[str, str]] = []
    if pr is not None:
        try:
            pr_events = label_events(gh_api_paged(f"repos/{REPO}/issues/{pr}/timeline"))
            qa_ready = sum(
                1 for e in pr_events if e["event"] == "labeled" and e["label"] == "qa-ready"
            )
            row["rework_cycles"] = max(qa_ready - 1, 0)
            row["qa_verdicts"] = [
                e["label"]
                for e in pr_events
                if e["event"] == "labeled" and e["label"] in ("qa-passed", "qa-failed")
            ]
        except (RuntimeError, json.JSONDecodeError, KeyError) as exc:
            notes.append(f"PR timeline unavailable: {exc}")

    combined = issue_events + pr_events
    if combined:
        row["needs_human_count"] = sum(
            1 for e in combined if e["event"] == "labeled" and e["label"] == "needs-human"
        )
        row["human_touch_events"] = sum(
            1 for e in combined if e["actor"] and not e["actor"].endswith("[bot]")
        )

    try:
        targets = [issue] + ([pr] if pr is not None else [])
        cost, turns, parsed = parse_cost_comments(targets)
        row["cost_comments_parsed"] = parsed
        if parsed:
            row["agent_cost_usd"], row["agent_turns"] = cost, turns
        else:
            notes.append("no agent-cost comments matched either known format")
    except (RuntimeError, json.JSONDecodeError) as exc:
        notes.append(f"cost-comment parsing failed: {exc}")

    if row["lead_time_hours"] is None and not row["qa_verdicts"] and row["pr"] is not None:
        notes.append("orchestrator-bypass lane (no pipeline phases)")

    return row


def fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, list):
        return ", ".join(value) if value else "—"
    return str(value)


def render_markdown(rows: list[dict[str, Any]]) -> str:
    header = (
        "| issue | pr | lead_h | rework | needs_human | qa_verdicts "
        "| turns | cost_usd | cost_comments | human_label_events |"
    )
    lines = [
        f"# SDLC lab — baseline metrics ({REPO})",
        "",
        header,
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        pr_cell = f"#{r['pr']}" if r["pr"] is not None else None
        lines.append(
            f"| #{r['issue']} | {fmt(pr_cell)} | {fmt(r['lead_time_hours'])} "
            f"| {fmt(r['rework_cycles'])} | {fmt(r['needs_human_count'])} "
            f"| {fmt(r['qa_verdicts'])} | {fmt(r['agent_turns'])} | {fmt(r['agent_cost_usd'])} "
            f"| {fmt(r['cost_comments_parsed'])} | {fmt(r['human_touch_events'])} |"
        )

    def total(key: str) -> Any:
        vals = [r[key] for r in rows if r[key] is not None]
        if not vals:
            return None
        s = sum(vals)
        return round(s, 4) if isinstance(s, float) else s

    lines.append(
        f"| **total** | — | {fmt(total('lead_time_hours'))} | {fmt(total('rework_cycles'))} "
        f"| {fmt(total('needs_human_count'))} | — | {fmt(total('agent_turns'))} "
        f"| {fmt(total('agent_cost_usd'))} | {fmt(total('cost_comments_parsed'))} "
        f"| {fmt(total('human_touch_events'))} |"
    )

    numeric = ("lead_time_hours", "rework_cycles", "needs_human_count", "agent_turns")
    if any(r[k] is None for r in rows for k in numeric):
        lines += ["", "_Totals sum non-null cells only._"]

    noted = [r for r in rows if r["notes"]]
    if noted:
        lines += ["", "## Notes"]
        for r in noted:
            for note in r["notes"]:
                lines.append(f"- #{r['issue']}: {note}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="SDLC lab baseline metrics")
    parser.add_argument("--json", action="store_true", help="emit raw JSON instead of markdown")
    parser.add_argument("issues", nargs="*", type=int, default=list(DEFAULT_ISSUES))
    args = parser.parse_args()

    rows = [collect_issue(n) for n in args.issues]
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print(render_markdown(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
