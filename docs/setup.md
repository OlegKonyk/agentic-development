# One-time Setup

Everything the pipeline needs that cannot live in the repo. Order matters.

## 1. Claude auth for CI (subscription token)

```bash
claude setup-token          # mints a long-lived OAuth token from your Pro/Max subscription
gh secret set CLAUDE_CODE_OAUTH_TOKEN   # paste the token
```

This drives every agent phase (`scripts/run_agent.sh`) and the `@claude`
assistant workflow.

**API-key alternative (teams / hardened profile):** set `ANTHROPIC_API_KEY` as
the secret instead, export `CLAUDE_USE_BARE=1` in the workflow env, and
`run_agent.sh` switches to `--bare` — stricter reproducibility (no config
auto-discovery at all), per-run `total_cost_usd` billing against Console
credits. Subscription tokens do NOT work in bare mode.

## 2. The `sdlc-orchestrator` GitHub App (label-transition identity)

Labels added with the default `GITHUB_TOKEN` never trigger the next workflow —
GitHub suppresses Actions-token recursion. Every phase transition therefore uses
a GitHub App installation token.

1. GitHub → Settings → Developer settings → GitHub Apps → **New GitHub App**
   - Name: `sdlc-orchestrator-<yourname>` (must be globally unique)
   - Homepage URL: this repo's URL; **Webhook: uncheck Active**
   - Repository permissions (exactly, per `scripts/github-app-manifest.json`):
     Contents **RW**, Issues **RW**, Pull requests **RW**, Commit statuses **RW**,
     Checks **RW**, Actions **R** (Metadata R is automatic)
2. Create the App → note the **Client ID** → **Generate a private key** (.pem downloads)
3. Install the App: App page → Install App → your account → **Only select
   repositories** → this repo
4. Wire it into Actions:

```bash
gh variable set SDLC_APP_CLIENT_ID --body "<client id>"
gh secret set SDLC_APP_PRIVATE_KEY < ~/Downloads/sdlc-orchestrator*.pem
```

Notes: do not grant `workflows: write` — agents must not be able to edit the
pipeline itself. On an org, register the App at org level and use org secrets.

## 3. Labels and branch protection

```bash
scripts/bootstrap_labels.sh     # idempotent, creates all stage:/qa-/meta labels
scripts/bootstrap_ruleset.sh    # protects main: PR required + checks "ci" and "qa/agent-verdict"
```

Caveat: a required status check must have reported at least once in the last 7
days to appear in the UI; the ruleset works regardless because contexts are
declared by name.

## 4. Optional: real gateway deploys (Cloudflare free tier)

```bash
# Cloudflare dashboard → My Profile → API Tokens → "Edit Cloudflare Workers" template
gh secret set CLOUDFLARE_API_TOKEN
gh secret set CLOUDFLARE_ACCOUNT_ID
```

Without these, `deploy.yml` runs in simulated mode (still closes the ticket
loop). With them, the Worker gateway ships to `agentic-gateway.<your-subdomain>.workers.dev`.
The Python apps stay CI-ephemeral by design in the free-tier setup; the
upgrade path (Cloudflare Containers behind the same Worker, ~$5/mo) is a
documented swap in `gateway/README.md`.

## 5. Optional: @claude assistant

`assistant.yml` uses claude-code-action in tag mode with the same
`CLAUDE_CODE_OAUTH_TOKEN`. For the richest experience (branch pushes from
mentions), also install the official Claude GitHub App via `/install-github-app`
from the Claude Code terminal — not required for the pipeline itself.

## 6. Kick the tires

```bash
# local dev loop
make install && make stack-up && make gateway-dev   # (second terminal)
make seed && make test && make e2e && make contract

# pipeline dry run
gh issue create --template feature.yml    # or use the web form
# then, on the created issue:
gh issue edit <N> --add-label stage:spec  # ← the human entry gate; watch Actions
```

The ticket should flow spec → design → dev (PR appears, `Fixes #N`, labeled
`qa-ready`) → QA (verdict comment + `qa/agent-verdict` status) → you merge →
deploy closes it as `stage:done` + `deployed`.
