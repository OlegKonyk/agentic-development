#!/usr/bin/env python3
"""Pre-flight capacity check: does the gateway request budget cover the e2e suite?

The gateway rate-limits per key in a fixed 10 s window (gateway/src/index.ts);
that budget is a constant, the suite is not. PR #24 burned two paid QA cycles
(~$5.70) discovering empirically that a 45-test suite outgrew a 60 req/10 s
budget. This runs before tier-1 e2e, costs one pytest collection, and compares
estimated demand with the configured budget.

The model is anchored on the one measurement we have: 45 tests exhausted a
60 req/10 s budget, i.e. ~1.33 requests per test at the observed breaking point.
REQ_PER_TEST is 1.5 — slightly conservative against that ratio, not a guess — so
"headroom" means "how far the configured budget sits above the point where this
suite actually broke". A 3x-inflated figure would have hard-failed healthy jobs
from ~150 tests, which is how a safety check becomes the outage.

Exit 0 = fine (possibly with a ::warning::), 1 = budget too small.
Anything it cannot measure is a warning, never a failure: this check must not
become its own source of false failures.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REQ_PER_TEST = 1.5
WARN_HEADROOM = 1.5
COUNT_RE = re.compile(r"^(\d+)(?:/\d+)? tests? collected", re.MULTILINE)


def collect_count(tests_path: str) -> int | None:
    proc = subprocess.run(
        ["uv", "run", "pytest", tests_path, "--collect-only", "-q"],
        capture_output=True,
        text=True,
        check=False,
    )
    matches = COUNT_RE.findall(proc.stdout)
    if matches:
        return int(matches[-1])
    if proc.returncode != 0:
        return None
    return sum(1 for line in proc.stdout.splitlines() if "::" in line) or None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate-limit", type=int, required=True, help="gateway RATE_LIMIT per 10s")
    ap.add_argument("--tests", default="qa/tests/e2e")
    ap.add_argument("--req-per-test", type=float, default=REQ_PER_TEST)
    ap.add_argument("--comment", required=True, help="markdown written when the check fails")
    args = ap.parse_args()

    count = collect_count(args.tests)
    if not count:
        print(f"::warning::capacity check skipped: could not count tests in {args.tests}")
        return 0

    required = round(count * args.req_per_test)
    headroom = args.rate_limit / required
    line = (
        f"e2e capacity: {count} tests x {args.req_per_test} req/test = {required} required "
        f"vs RATE_LIMIT {args.rate_limit} (headroom {headroom:.2f}x)"
    )
    print(line)
    if headroom >= WARN_HEADROOM:
        return 0

    remedy = (
        f"Raise the gateway request budget to at least {int(required * WARN_HEADROOM)} "
        "(`GATEWAY_RATE_LIMIT` in `.github/workflows/phase-qa.yml`, the `gateway-dev` "
        "target in `Makefile`, and `docs/apps.md`), or split the e2e suite."
    )
    if headroom >= 1.0:
        print(f"::warning::{line} - thin margin. {remedy}")
        return 0

    Path(args.comment).parent.mkdir(parents=True, exist_ok=True)
    Path(args.comment).write_text(
        "⚠️ QA stopped before tier-1 e2e: the gateway request budget is too small for the "
        f"e2e suite, so 429s would be misread as product bugs.\n\n{line}\n\n{remedy}\n\n"
        "Then re-add `qa-ready`.\n"
    )
    print(f"::error::{line} - below 1.0x. {remedy}")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - this check never fails a healthy job
        print(f"::warning::capacity check skipped: {exc}")
        sys.exit(0)
