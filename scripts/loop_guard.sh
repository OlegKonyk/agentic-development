#!/usr/bin/env bash
# Belt-and-braces runaway protection: GitHub applies NO recursion suppression to
# App-token events, so a mis-wired label graph could loop forever. Counts how
# many times pipeline labels were applied to this ticket and aborts past a cap.
# Usage: loop_guard.sh <number> [label-regex] [max]
#   default regex counts all pipeline labels; pass 'qa-ready' with max 3 to cap
#   QA↔rework cycles.
set -euo pipefail

NUMBER="${1:?issue/pr number}"
LABEL_REGEX="${2:-^(stage:|qa-)}"
MAX="${3:-20}"

COUNT=$(gh api "repos/${GITHUB_REPOSITORY}/issues/${NUMBER}/timeline" --paginate \
  --jq "[.[] | select(.event == \"labeled\") | .label.name | select(test(\"${LABEL_REGEX}\"))] | length")

echo "loop guard: #$NUMBER has $COUNT '$LABEL_REGEX' label events (max $MAX)"
if (( COUNT > MAX )); then
  echo "::error::loop guard tripped on #$NUMBER — $COUNT label events exceed max $MAX. Parking as needs-human."
  exit 1
fi
