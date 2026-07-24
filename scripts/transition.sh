#!/usr/bin/env bash
# State-machine transition: remove the inbound label, add the outbound label,
# optionally post a comment. MUST run with GH_TOKEN set to the sdlc-orchestrator
# App installation token — GITHUB_TOKEN label events never trigger the next phase.
# Usage: transition.sh <issue|pr> <number> <remove-label|-> <add-label|-> [comment-file]
set -euo pipefail

KIND="${1:?issue|pr}"; NUMBER="${2:?number}"; REMOVE="${3:?label or -}"; ADD="${4:?label or -}"
COMMENT_FILE="${5:-}"

case "$KIND" in
  issue) CMD=(gh issue edit "$NUMBER") ; COMMENT=(gh issue comment "$NUMBER") ;;
  pr)    CMD=(gh pr edit "$NUMBER")    ; COMMENT=(gh pr comment "$NUMBER") ;;
  *) echo "kind must be issue or pr" >&2; exit 1 ;;
esac

if [[ -n "$COMMENT_FILE" && -s "$COMMENT_FILE" ]]; then
  "${COMMENT[@]}" --body-file "$COMMENT_FILE"
fi
# Remove first so a crash between the two calls leaves the ticket parked, not double-labeled.
if [[ "$REMOVE" != "-" ]]; then
  "${CMD[@]}" --remove-label "$REMOVE" || echo "label '$REMOVE' was not present"
fi
if [[ "$ADD" != "-" ]]; then
  "${CMD[@]}" --add-label "$ADD"
fi
echo "transition: $KIND #$NUMBER  -$REMOVE  +$ADD"
