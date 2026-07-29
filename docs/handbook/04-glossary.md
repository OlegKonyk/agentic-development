# Glossary — the terminology, and where each term actually appears

A crash course in the vocabulary this project runs on, in four layers from the
model outward. Every concept is followed by *where it shows up in this repo*, so
the term and the code stay attached to each other. Documentation links are to
Anthropic's own docs and were verified live on 2026-07-29.

Read this alongside [`02-system-map.pdf`](02-system-map.pdf), which explains the
machine; this file explains the words.

---

## Layer 1 — the model

These are properties of Claude itself, independent of any harness.

**Token.** The unit of both billing and context. Roughly ¾ of an English word,
but code and non-English text tokenize less efficiently. Never estimate with
OpenAI's `tiktoken` — it undercounts Claude by 15–20%. Use the
[token counting endpoint](https://platform.claude.com/docs/en/build-with-claude/token-counting).

**Context window.** The total tokens a single request may contain — prompt,
conversation history, tool results, and the response together. The current
Claude 5 family holds 1M tokens; Haiku 4.5 holds 200K. Exceeding it is a
distinct stop reason (`model_context_window_exceeded`), not the same as hitting
your output cap.

**Model tier and model ID.** Three tiers trade capability against cost:

| Tier | Model ID | Input / output per million tokens |
|---|---|---|
| Opus | `claude-opus-5` | $5 / $25 |
| Sonnet | `claude-sonnet-5` | $3 / $15 |
| Haiku | `claude-haiku-4-5` | $1 / $5 |

Claude Code also accepts the bare aliases `opus`, `sonnet`, `haiku`, which is
what this pipeline uses. *In this repo:* `scripts/run_agent.sh` sets
`PRODUCT_MODEL`/`DESIGN_MODEL` to `opus` and `DEV_MODEL`/`QA_MODEL`/`RETRO_MODEL`
to `sonnet` — spec and design work get the stronger tier because a bad
specification is expensive to discover downstream; implementation and testing are
verified by gates, so they run cheaper.
[Model overview](https://platform.claude.com/docs/en/about-claude/models/overview)

**Adaptive thinking.** The model decides for itself when to reason before
answering and how deeply. It replaces the older fixed `budget_tokens` setting,
which is now rejected outright on the Claude 5 models. *You will meet this if you
move from the CLI to the API;* the CLI manages it for you.
[Adaptive thinking](https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking)

**Effort.** A five-step dial — `low`, `medium`, `high`, `xhigh`, `max` — that
controls how much thinking and how many tool calls the model spends on a task.
It is the main cost/quality lever above model choice. `xhigh` is the recommended
setting for coding and agentic work.
[Effort](https://platform.claude.com/docs/en/build-with-claude/effort)

**Prompt caching.** Cached prompt prefixes are re-read at about one tenth the
input price; writing the cache costs 1.25×. The catch is that it is a **prefix
match** — one changed byte anywhere invalidates everything after it, so a
`datetime.now()` in a system prompt silently disables caching for the whole
request. This is why long agent sessions are far cheaper than the raw token
counts suggest.
[Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

**Tool use.** The model does not execute anything. It emits a `tool_use` block
naming a tool and its arguments; *your* harness runs it and returns a
`tool_result`. Everything an agent does — reading a file, running a test — is
this loop repeating. Anthropic-hosted "server tools" (web search, code
execution) are the exception: those run on Anthropic's infrastructure.
[Tool use overview](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)

**Structured output.** Constrains the response to a JSON Schema, so the caller
gets validated data instead of prose it has to parse. *In this repo this is the
single most load-bearing model feature:* every phase is invoked with
`--json-schema` against a file in `ci/claude/schemas/`, and
`scripts/run_agent.sh` treats a missing `.structured_output` as an
infrastructure failure. No pipeline decision is ever made by reading an agent's
free text.
[Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)

**MCP — Model Context Protocol.** An open standard for exposing tools and data
to a model over a documented wire protocol, so a capability is written once and
works in any MCP-speaking client. *In this repo:* `ci/claude/mcp/qa.json`
attaches the Playwright MCP server to the QA phase, which is how a QA agent
drives a real browser. `--strict-mcp-config` ensures only that file's servers
load, ignoring anything a developer has configured locally.
[MCP in Claude Code](https://code.claude.com/docs/en/mcp) ·
[the protocol itself](https://modelcontextprotocol.io/docs/getting-started/intro)

---

## Layer 2 — the agent harness

A **harness** is the code that runs the tool-use loop: it sends the request,
executes the tools the model asks for, feeds results back, and decides when to
stop. Three Anthropic products supply one, and confusing them is the most common
vocabulary mistake:

| | What it is | Who deploys it |
|---|---|---|
| **Claude Code** | The harness as a CLI and app, with built-in file/bash/search tools | You run it — locally or in CI |
| **Claude Agent SDK** | The same harness as a library you embed | You host it |
| **Managed Agents** | Anthropic runs both the loop *and* a per-session sandbox | Anthropic |

This project uses **Claude Code in CI**. The concepts below are its vocabulary.
[Claude Code docs](https://code.claude.com/docs/en/overview) ·
[Agent SDK](https://code.claude.com/docs/en/agent-sdk) ·
[Managed Agents](https://platform.claude.com/docs/en/managed-agents/overview)

**Headless mode.** Running Claude Code non-interactively with `-p "<prompt>"`
and `--output-format json`, so it can be driven from a script with no terminal
attached. This is the mechanism that makes an agent a CI job.
[Headless mode](https://code.claude.com/docs/en/headless) ·
[CLI reference](https://code.claude.com/docs/en/cli-reference)

**Turn.** One model response plus the tool calls it triggers. The unit that
`--max-turns` counts. A turn is not a user message — an agent working alone can
burn a hundred turns without a human saying anything.

**Permission mode.** How the harness handles a tool call that isn't
pre-approved: prompt the user, accept edits, plan only, or `dontAsk`. *In this
repo:* every phase runs `--permission-mode dontAsk`, because there is no human
at the terminal to answer a prompt.
[Permissions](https://code.claude.com/docs/en/iam)

**Allowlist and deny-list.** `--allowedTools` names what a phase may use;
`--disallowedTools` and the `deny` block in a settings file name what it may
never use. **The hardest-won lesson in this repo is about the shape of these
rules.** Argument-scoped patterns like `Bash(curl *)` look tighter but auto-deny
every `cd x && ...`, `VAR=1 uv run ...`, piped, or backgrounded command an agent
naturally writes. Ticket #36 burned 121 turns and $6.25 on 13 such denials trying
to boot the app it was asked to build against; the same ticket after the fix took
101 turns, $4.52, and zero denials. The pipeline now grants broad `Bash` and
relies on a deny-list plus a credential-less checkout plus a deterministic
pre-push guard.

**Settings file.** Repo- or user-level JSON configuring permissions, hooks, and
model defaults. *In this repo:* `ci/claude/settings/ci-settings.json` holds the
deny rules that keep an agent out of the pipeline's own files. Note that its
`Edit(...)`/`Write(...)` patterns are **repo-relative and anchor to the process
working directory** — which is why `run_agent.sh` does a `cd "$ROOT"` before
invoking anything. A deny rule anchored to the wrong directory is not a weak
rule; it is no rule at all.
[Settings](https://code.claude.com/docs/en/settings)

**Skill.** A folder containing a `SKILL.md` of task-specific instructions that
the model loads only when relevant — progressive disclosure, so the instructions
don't sit in context on every request. *In this repo:* each phase's charter (what
a product agent must produce, what a QA agent must verify) is a skill.
[Skills in Claude Code](https://code.claude.com/docs/en/skills) ·
[Agent Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) ·
[the design rationale](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)

**Plugin.** A packaged bundle of skills, commands, agents, and hooks, loaded
with `--plugin-dir`. *In this repo:* `ci/claude/plugins/<phase>/` — one plugin
per SDLC phase, which is how a single binary becomes five different specialists.
[Plugins](https://code.claude.com/docs/en/plugins)

**Subagent.** A nested agent with its own context window, spawned to do a
scoped piece of work and report back. Keeps the parent's context clean at the
cost of re-establishing context in the child. *Not used inside our phases* — the
phases themselves are the decomposition — but it is how the multi-agent research
patterns in the literature work.
[Subagents](https://code.claude.com/docs/en/sub-agents)

**Hook.** A shell command the harness runs at a lifecycle point (before a tool
call, after an edit, at session end) — deterministic code in the agent's loop,
which is the natural place to put a rule you refuse to leave to prose.
[Hooks](https://code.claude.com/docs/en/hooks-guide)

**Turn and budget caps.** `--max-turns` is the soft runaway guard;
`--max-budget-usd` is the hard one. *In this repo:* per-phase in
`run_agent.sh` — 30 turns for product/design/retro, 120 for dev and QA. The QA
cap is overridable at runtime through the `QA_MAX_TURNS` repo variable so the
dev manager can raise it without a code change.

**`--no-session-persistence`.** Don't write session state to disk. Correct for
CI, where every run is fresh and the runner is discarded.

**The result envelope.** Headless JSON output carries `subtype`, `is_error`,
`total_cost_usd`, `num_turns`, `permission_denials`, and `structured_output`.
*In this repo* `run_agent.sh` parses all six: the first two decide pass/fail, the
next three become the cost telemetry the lab measures, and the last is the actual
work product.

> **Read the cost field carefully.** These phases authenticate with a Claude
> subscription token (`CLAUDE_CODE_OAUTH_TOKEN`), not a metered API key. So
> `total_cost_usd` is the client's *estimate of what the same work would have
> cost on the API* — it is not an invoice. Every dollar figure this lab reports
> is that estimate. It is a good comparative instrument and a bad accounting
> record.
> [Cost tracking](https://code.claude.com/docs/en/costs)

---

## Layer 3 — the orchestration (this project's own vocabulary)

**Label-driven state machine.** The pipeline has no scheduler, queue, or
orchestrator process. State lives entirely in GitHub issue and PR labels, and
every transition is a label change made by `scripts/transition.sh`. The spec is
[`docs/sdlc.md`](../sdlc.md).

**The token asymmetry.** GitHub deliberately suppresses workflow events caused
by the built-in `GITHUB_TOKEN`, to stop CI from triggering itself forever. A
**GitHub App token** does not carry that suppression. This pipeline turns that
into its central design tool: *anything that should advance the machine is
written with the App token; anything that must not is written with
`GITHUB_TOKEN`.* Commit statuses, cost comments, QA verdicts and retro proposals
all use the CI token precisely so they land without chaining.
[GitHub Actions integration](https://code.claude.com/docs/en/github-actions) ·
[the action](https://github.com/anthropics/claude-code-action)

**Phase.** One agent invocation with its own plugin, schema, model, tool
profile, and caps: product, design, dev, QA, retro. Adding a phase means adding a
schema *and* a plugin — the two are a pair.

**Entry gate.** The human decision that starts agent spend: moving a ticket from
`stage:idea` to `stage:spec`. Deliberately the one thing no agent may do.

**Tier 1 and tier 2.** Tier 1 is the deterministic suite — pytest, Playwright
E2E, contract replay. Tier 2 is the agentic QA pass: an agent boots the stack and
verifies acceptance criteria in a browser. `scripts/qa_gate.py` combines them,
and **tier-1 red refuses the merge even when the tier-2 agent argues the failure
is out of scope.** That has fired for real.

**Verdict and evidence rule.** The QA agent returns `pass`, `fail`, or
`blocked`. A `fail` without reproduction steps is auto-downgraded to `blocked`
and parked for a human — agent confidence is not evidence.

**Park / `needs-human`.** The pipeline's way of stopping rather than guessing.
A parked ticket waits for a person; it does not retry.

**Rework.** The loop back from `qa-failed` to the dev phase. Counted, because
rework rate is one of the five DORA keys.

**Escaped defect.** A defect that reaches `main`. The count across 20 shipped
tickets is zero, and that number is the headline claim of the whole lab.

**Loop guard and concurrency group.** `scripts/loop_guard.sh` plus per-ticket
concurrency groups stop a phase from re-triggering itself or racing a second
copy of itself.

**Privileged path.** Files that define the pipeline's own behavior —
`.github/workflows/`, `ci/claude/`, `scripts/`. An agent may not modify them. The
rule is enforced in three layers: the phase prompt says so, the settings
deny-list blocks the edit tools, and a deterministic merge-base diff plus a
dirty-tree check runs before every push. **Only the third layer actually holds** —
which is the general lesson below.

**Break-glass.** A human bypassing the pipeline to push directly. Permitted for
the operator, tracked separately in the cost ledger, and never used for docs.

**Instrument freeze.** A methodological rule: the apparatus freezes when a
measurement round's ledger is fixed. Changing *what a phase decides* mid-round
invalidates the comparison; *repairing an instrument to its documented behavior*
does not.

---

## Layer 4 — the measurement vocabulary

**DORA metrics.** The industry-standard delivery measures — deployment
frequency, lead time for changes, change failure rate, failed deployment
recovery time, and (added in the 2024/25 reports) **rework rate**. This lab
reports cycle time, rework, and escaped defects against them.

**Forecast band and ceiling.** Before a round, each ticket gets a predicted cost
range; the round gets a hard spend ceiling. Round 2 measured $106.16 against a
$46–91 band and a $150 ceiling — and the *direction* of the error was not
uniform, which is the finding.

**Cost is not predicted by complexity.** The single most useful measured result
here: ticket cost tracked whether the ticket happened to trip a latent *pipeline*
defect, not how hard the feature was. The "easy control case" ran 2.5× over band;
the ticket rated hardest landed inside its own.

---

## The three ideas worth carrying elsewhere

1. **Deterministic orchestration, AI-filled content.** The model never chooses a
   state transition. It produces schema-validated JSON; free text is never parsed
   for control flow. This is Anthropic's own "workflows over agents" guidance
   applied literally.
   [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
2. **Prose is not a boundary.** Every rule that lived only in an agent's
   instructions was eventually walked through — not maliciously, just by an agent
   doing its job under different wording. A rule that matters needs a
   deterministic step that fails the build.
3. **The gate outranks the agent.** When the deterministic suite and the agent's
   judgment disagree, the suite wins, and the merge does not happen.

---

## Reading list

**Claude Code** — [overview](https://code.claude.com/docs/en/overview) ·
[quickstart](https://code.claude.com/docs/en/quickstart) ·
[common workflows](https://code.claude.com/docs/en/common-workflows) ·
[CLI reference](https://code.claude.com/docs/en/cli-reference) ·
[headless](https://code.claude.com/docs/en/headless) ·
[settings](https://code.claude.com/docs/en/settings) ·
[permissions](https://code.claude.com/docs/en/iam) ·
[skills](https://code.claude.com/docs/en/skills) ·
[plugins](https://code.claude.com/docs/en/plugins) ·
[subagents](https://code.claude.com/docs/en/sub-agents) ·
[hooks](https://code.claude.com/docs/en/hooks-guide) ·
[MCP](https://code.claude.com/docs/en/mcp) ·
[GitHub Actions](https://code.claude.com/docs/en/github-actions) ·
[security](https://code.claude.com/docs/en/security) ·
[costs](https://code.claude.com/docs/en/costs) ·
[analytics](https://code.claude.com/docs/en/analytics) ·
[data usage](https://code.claude.com/docs/en/data-usage)

**The API underneath** —
[models](https://platform.claude.com/docs/en/about-claude/models/overview) ·
[tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview) ·
[structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) ·
[prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) ·
[effort](https://platform.claude.com/docs/en/build-with-claude/effort) ·
[adaptive thinking](https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking) ·
[token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting) ·
[agent skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) ·
[MCP connector](https://platform.claude.com/docs/en/agents-and-tools/mcp-connector) ·
[managed agents](https://platform.claude.com/docs/en/managed-agents/overview)

**Anthropic engineering, in the order I'd read them** —
[Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) (start here — the workflows-over-agents argument this project is built on) ·
[Claude Code best practices](https://www.anthropic.com/engineering/claude-code-best-practices) ·
[Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) ·
[Writing tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents) ·
[Equipping agents with Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills) ·
[How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)

**Protocol** — [Model Context Protocol](https://modelcontextprotocol.io/docs/getting-started/intro)
