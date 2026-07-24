#!/usr/bin/env bash
# Idempotently create every label the SDLC state machine uses (docs/sdlc.md).
# Usage: [REPO=owner/name] scripts/bootstrap_labels.sh
set -euo pipefail

REPO="${REPO:-}"
repo_args=()
if [[ -n "$REPO" ]]; then
  repo_args=(--repo "$REPO")
fi

label() {
  local name="$1" color="$2" description="$3"
  gh label create "$name" --force --color "$color" --description "$description" "${repo_args[@]}"
  echo "ok: $name"
}

# Stage labels (issue-side pipeline phases)
label "stage:idea"   "ededed" "Filed via issue form, not yet approved for the pipeline"
label "stage:spec"   "1d76db" "Product agent is on it"
label "stage:design" "5319e7" "Design agent is on it"
label "stage:dev"    "0e8a16" "Dev agent is on it"
label "stage:qa"     "fbca04" "Mirror: linked PR is in QA"
label "stage:done"   "0052cc" "Merged and deployed"

# PR-side QA labels
label "qa-ready"  "fbca04" "QA agent should run"
label "qa-passed" "0e8a16" "QA verdict: pass"
label "qa-failed" "d93f0b" "QA verdict: fail"

# Escape hatch and deploy marker
label "needs-human" "b60205" "Pipeline parked; a human must look"
label "deployed"    "006b75" "Deploy workflow finished"

# Triage labels
label "bug" "d73a4a" "Something is broken"
label "P1"  "b60205" "Priority: urgent"
label "P2"  "fbca04" "Priority: normal"
label "P3"  "c2e0c6" "Priority: low"

echo "All labels bootstrapped."
