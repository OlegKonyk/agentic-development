#!/usr/bin/env bash
# Single entry point for every Claude agent invocation in the pipeline.
# Usage: run_agent.sh <phase> <prompt...>
#   phase ∈ product | design | dev | qa   (selects plugin, schema, model, limits, tools)
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
CC="$ROOT/ci/claude"
OUT_DIR="${AGENT_OUT_DIR:-$ROOT/agent-out}"
mkdir -p "$OUT_DIR"

MCP_CONFIG=""
DISALLOWED=""
case "$PHASE" in
  product)
    MODEL="${PRODUCT_MODEL:-opus}"; MAX_TURNS=30; SCHEMA="spec-output.json"
    TOOLS="Read,Glob,Grep"
    ;;
  design)
    MODEL="${DESIGN_MODEL:-opus}"; MAX_TURNS=30; SCHEMA="design-output.json"
    TOOLS="Read,Glob,Grep"
    ;;
  dev)
    MODEL="${DEV_MODEL:-sonnet}"; MAX_TURNS=80; SCHEMA="dev-report.json"
    TOOLS="Read,Glob,Grep,Edit,Write,Bash(uv run *),Bash(uv sync *),Bash(git add *),Bash(git commit *),Bash(git status),Bash(git diff *),Bash(git log *),Bash(mkdir *)"
    ;;
  qa)
    MODEL="${QA_MODEL:-sonnet}"; MAX_TURNS=50; SCHEMA="qa-verdict.json"
    TOOLS="Read,Glob,Grep,Bash(curl *),Bash(uv run pytest *),mcp__playwright__*"
    MCP_CONFIG="$CC/mcp/qa.json"
    DISALLOWED="mcp__playwright__browser_run_code_unsafe"
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
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  echo "**Agent phase \`$PHASE\`** — subtype \`$SUBTYPE\`, ${TURNS} turns, ~\$${COST} (client estimate), ${DENIALS} permission denials" >> "$GITHUB_STEP_SUMMARY"
fi

jq -e '.structured_output' "$RESULT" > "$OUT_DIR/$PHASE-output.json" 2>/dev/null || {
  echo "::error::phase $PHASE ended subtype=$SUBTYPE without structured output"
  exit 1
}
if [[ "$IS_ERROR" == "true" || "$SUBTYPE" != "success" ]]; then
  echo "::error::phase $PHASE result subtype=$SUBTYPE is_error=$IS_ERROR"
  exit 1
fi
echo "structured output -> $OUT_DIR/$PHASE-output.json"
