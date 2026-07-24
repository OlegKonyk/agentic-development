#!/usr/bin/env bash
# Deterministically resolve the single open PR linked to an issue (via closing
# keywords / Development links). Prints JSON {number, headRefName, headRefOid,
# isCrossRepository} on stdout.
# Exit codes: 0 = exactly one open linked PR; 2 = zero or multiple (caller parks
# the ticket as needs-human); 1 = API failure.
# Note: closedByPullRequestsReferences also returns MERGED PRs regardless of
# includeClosedPrs — filtering state == OPEN client-side is load-bearing.
set -euo pipefail

NUMBER="${1:?issue number}"
OWNER="${GITHUB_REPOSITORY%%/*}"
REPO="${GITHUB_REPOSITORY##*/}"

RESULT=$(gh api graphql \
  -f query='query($o: String!, $r: String!, $n: Int!) {
    repository(owner: $o, name: $r) {
      issue(number: $n) {
        closedByPullRequestsReferences(first: 10) {
          nodes { number state headRefName headRefOid isCrossRepository }
        }
      }
    }
  }' -F o="$OWNER" -F r="$REPO" -F n="$NUMBER")

OPEN=$(echo "$RESULT" | jq '[.data.repository.issue.closedByPullRequestsReferences.nodes[] | select(.state == "OPEN")]')
COUNT=$(echo "$OPEN" | jq 'length')

if [[ "$COUNT" -ne 1 ]]; then
  echo "expected exactly one open linked PR for issue #$NUMBER, found $COUNT" >&2
  exit 2
fi
echo "$OPEN" | jq '.[0]'
