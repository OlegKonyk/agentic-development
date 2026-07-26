#!/usr/bin/env bash
# Single entry point for every Claude agent invocation in the pipeline.
# Usage: run_agent.sh <phase> <prompt...>
#   phase ∈ product | design | dev | qa | retro   (selects plugin, schema, model, limits, tools)
# Exit codes: 0 = agent ran and produced schema-valid structured output
#             1 = agent/infrastructure failure (no usable output)
# The *content* of the output (e.g. a QA verdict of "fail") is the caller's business.
#
# Auth: CLAUDE_CODE_OAUTH_TOKEN (subscription) by default. Set CLAUDE_USE_BARE=1
# with ANTHROPIC_API_KEY for the hardened --bare profile (bare mode ignores OAuth).
set -euo pipefail

PHASE="${1:?usage: run_agent.sh <phase> <prompt...>}"
shift
PROMPT="$*"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The Edit/Write deny patterns in ci-settings.json are repo-relative and anchor
# to the claude process cwd — pin it so they hold from any invoker.
cd "$ROOT"
CC="$ROOT/ci/claude"
OUT_DIR="${AGENT_OUT_DIR:-$ROOT/agent-out}"
mkdir -p "$OUT_DIR"

MCP_CONFIG=""
DISALLOWED=""
# Turn/budget caps scale with phase scope. QA grew with the app: verifying auth +
# reminders + webhooks + chaos across ~8 ACs, plus exploration and fault-injection,
# overran a 50-turn budget (error_max_turns on the v2 platform), and the
# accessibility charter (keyboard-only probes cost one MCP call per keystroke)
# overran 80 with zero denials and steady progress (PR #13). --max-budget-usd
# is the hard runaway guard; --max-turns the soft one.
case "$PHASE" in
  product)
    MODEL="${PRODUCT_MODEL:-opus}"; MAX_TURNS=30; MAX_BUDGET="${PRODUCT_BUDGET:-3}"
    SCHEMA="spec-output.json"
    TOOLS="Read,Glob,Grep"
    ;;
  design)
    MODEL="${DESIGN_MODEL:-opus}"; MAX_TURNS=30; MAX_BUDGET="${DESIGN_BUDGET:-3}"
    SCHEMA="design-output.json"
    TOOLS="Read,Glob,Grep"
    ;;
  retro)
    # Advisory analyst: reads the shipped ticket's artifacts, changes nothing.
    MODEL="${RETRO_MODEL:-sonnet}"; MAX_TURNS=30; MAX_BUDGET="${RETRO_BUDGET:-3}"
    SCHEMA="retro-output.json"
    TOOLS="Read,Glob,Grep"
    ;;
  dev)
    MODEL="${DEV_MODEL:-sonnet}"; MAX_TURNS=120; MAX_BUDGET="${DEV_BUDGET:-12}"
    SCHEMA="dev-report.json"
    TOOLS="Read,Glob,Grep,Edit,Write,Bash(uv run *),Bash(uv sync *),Bash(git add *),Bash(git commit *),Bash(git status),Bash(git diff *),Bash(git log *),Bash(mkdir *),Bash(curl *),Bash(docker compose exec *)"
    ;;
  qa)
    MODEL="${QA_MODEL:-sonnet}"; MAX_TURNS="${QA_MAX_TURNS:-120}"; MAX_BUDGET="${QA_BUDGET:-8}"
    SCHEMA="qa-verdict.json"
    # Broad Bash, guarded by the deny-list in ci-settings.json (no push/merge/
    # deploy/rm -rf/sudo, no edits to pipeline files) on a secret-less runner off
    # the main branch. Arg-scoped patterns like `Bash(curl *)` auto-denied every
    # multi-line/var-assignment/piped command the agent naturally writes — it
    # burned 100 turns fighting the sandbox instead of testing (PR #10 cycles 2-3).
    TOOLS="Read,Glob,Grep,Bash,mcp__playwright__*"
    MCP_CONFIG="$CC/mcp/qa.json"
    # QA observes and reports; it must not mutate the repo or the ticket (the
    # deterministic workflow steps own commits and comments). git commit stays
    # allowed globally for the dev phase, so scope these denials to QA here.
    DISALLOWED="mcp__playwright__browser_run_code_unsafe,Bash(git commit *),Bash(git add *),Bash(gh pr comment *),Bash(gh issue comment *),Bash(gh pr edit *),Bash(gh issue edit *)"
    ;;
  *)
    echo "unknown phase: $PHASE" >&2; exit 1 ;;
esac

ARGS=(
  -p "$PROMPT"
  --plugin-dir "$CC/plugins/$PHASE"
  --settings "$CC/settings/ci-settings.json"
  --permission-mode dontAsk
  --allowedTools "$TOOLS"
  --model "$MODEL"
  --max-turns "$MAX_TURNS"
  --max-budget-usd "$MAX_BUDGET"
  --output-format json
  --json-schema "$(cat "$CC/schemas/$SCHEMA")"
  --no-session-persistence
)
[[ -n "$MCP_CONFIG" ]] && ARGS+=(--mcp-config "$MCP_CONFIG" --strict-mcp-config)
[[ -n "$DISALLOWED" ]] && ARGS+=(--disallowedTools "$DISALLOWED")
[[ "${CLAUDE_USE_BARE:-0}" == "1" ]] && ARGS+=(--bare)

RESULT="$OUT_DIR/$PHASE-result.json"
set +e
claude "${ARGS[@]}" > "$RESULT"
CLAUDE_EXIT=$?
set -e

if [[ ! -s "$RESULT" ]]; then
  echo "::error::claude produced no output (exit $CLAUDE_EXIT)"
  exit 1
fi

# NB: jq's // treats false as empty — `.is_error // true` would turn a healthy
# is_error=false into true. Test presence explicitly.
IS_ERROR=$(jq -r 'if has("is_error") then (.is_error | tostring) else "true" end' "$RESULT")
SUBTYPE=$(jq -r '.subtype // "unknown"' "$RESULT")
COST=$(jq -r '.total_cost_usd // 0' "$RESULT")
TURNS=$(jq -r '.num_turns // 0' "$RESULT")
DENIALS=$(jq -r '(.permission_denials // []) | length' "$RESULT")

echo "phase=$PHASE subtype=$SUBTYPE cost_usd=$COST turns=$TURNS permission_denials=$DENIALS exit=$CLAUDE_EXIT"
# The cost line is lab telemetry (scripts/lab_metrics.py parses it from ticket
# comments); phase workflows surface phase-cost.md on the issue/PR.
COST_LINE="**Agent phase \`$PHASE\`** — subtype \`$SUBTYPE\`, ${TURNS} turns, ~\$${COST} (client estimate), ${DENIALS} permission denials"
echo "$COST_LINE" > "$OUT_DIR/phase-cost.md"
[[ -n "${GITHUB_STEP_SUMMARY:-}" ]] && echo "$COST_LINE" >> "$GITHUB_STEP_SUMMARY"

jq -e '.structured_output' "$RESULT" > "$OUT_DIR/$PHASE-output.json" 2>/dev/null || {
  echo "::error::phase $PHASE ended subtype=$SUBTYPE without structured output"
  exit 1
}
if [[ "$IS_ERROR" == "true" || "$SUBTYPE" != "success" ]]; then
  echo "::error::phase $PHASE result subtype=$SUBTYPE is_error=$IS_ERROR"
  exit 1
fi
echo "structured output -> $OUT_DIR/$PHASE-output.json"
