# Round 0 research — annotated sources

Collected 2026-07-26 by three parallel research agents; every citation in
`docs/lab-charter.md` and `docs/playbooks/` traces to an entry here.

## Metrics frameworks

- [DORA Accelerate State of DevOps Report 2024 (primary)](https://dora.dev/research/2024/dora-report/)
  — First large-scale evidence that AI adoption hurts delivery: a 25% increase in AI adoption correlated with −1.5% throughput and −7.2% delivery stability, while individual productivity, flow, and satisfaction rose — the canonical individual-vs-organizational split.
- [DORA 2025 State of AI-assisted Software Development report (primary)](https://dora.dev/research/2025/dora-report/)
  — AI's primary role is as an amplifier of existing organizational strengths and weaknesses; the report evolved the four keys into five (adding Rework Rate) and shipped the companion DORA AI Capabilities Model (seven capabilities incl. small batches, strong version control, quality internal platforms).
- [DORA 2025: Year in review (primary)](https://dora.dev/insights/dora-2025-year-in-review/)
  — Confirms the five-metric evolution, the AI Capabilities Model release, the finding that 'AI improves throughput, but often at the cost of stability if your foundation isn't solid,' and the trust gap (~90% adoption vs ~25% of tech workers trusting AI output).
- [Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity (METR RCT, arXiv 2507.09089, primary)](https://arxiv.org/abs/2507.09089)
  — Gold-standard RCT: 16 experienced maintainers on 246 real tasks were 19% slower with AI tooling yet self-estimated a 20% speedup — the definitive argument against using perceived productivity to evaluate an agentic pipeline.
- [GitClear: AI Copilot Code Quality 2025 research (primary, 211M LOC)](https://www.gitclear.com/ai_assistant_code_quality_2025_research)
  — AI-era codebases show 8x growth in duplicated code blocks, copy/paste exceeding refactored/moved code for the first time on record, and near-doubling of 2-week churn (3.1%→5.7%) — motivates duplication % and short-window churn as maintainability guardrail metrics.
- [Stack Overflow 2025 Developer Survey — AI section (primary)](https://survey.stackoverflow.co/2025/ai)
  — 84% of developers use or plan to use AI, but only ~29% trust output accuracy (3% high trust), 66% report 'almost right but not quite' answers, and 45% lose significant time debugging AI code — baseline data for trust-calibration and review-burden metrics.
- [DX Core 4 — measuring developer productivity (getdx.com, primary framework doc)](https://getdx.com/research/measuring-developer-productivity-with-the-dx-core-4/)
  — The practical successor/unification of DORA + SPACE + DevEx, co-developed with Forsgren, Storey, and Zimmermann: four balanced dimensions (Speed, Effectiveness, Quality, Impact) with prescribed metrics, designed to prevent single-metric optimization — right-sized for a 6-person team.
- [Faros AI: Key takeaways from the DORA Report 2025 (secondary, adds telemetry numbers)](https://www.faros.ai/blog/key-takeaways-from-the-dora-report-2025)
  — Quantifies the amplifier effect with production telemetry: +21% tasks completed and +98% PRs merged per individual, but PR review time +91%→+441%, bugs per developer +9%→+54%, incidents per merged PR +242.7%, rework restarts +13.8% — the source for review-burden and instability trend numbers.
- [Digital Applied: Agentic Workflow Completion Metrics — Pipeline Health 2026 (practitioner)](https://www.digitalapplied.com/blog/agentic-workflow-completion-metrics-pipeline-health-2026)
  — Defines the human-intervention-rate metric for agent pipelines: workflows with ≥1 human touch / total runs, split planned vs unplanned HITL, with the guidance that week-over-week trend matters more than the absolute rate; also cost-per-completed-work-item as the unit-economics measure.
- [Fly.io: Trust Calibration for AI Software Builders (practitioner)](https://fly.io/blog/trust-calibration-for-ai-software-builders/)
  — Trust calibration = aligning user trust with actual system capability; measure acceptance rates per confidence tier and adapt thresholds from acceptance/rejection outcomes — a concrete recipe for calibrating when agent PRs may skip heavyweight review.
- [CodeRabbit: What percentage of your code should be AI generated? (practitioner, vanity-metric critique)](https://www.coderabbit.ai/blog/ai-code-metrics-what-percentage-of-your-code-should-be-ai-generated)
  — Acceptance rate and %-AI-generated conflate 'not rejected' with 'valuable'; measure cycle time, defect density split by AI vs human authorship, and change failure rate compared across AI/non-AI changes instead.
- [RedMonk: DORA 2025 — Measuring Software Delivery After AI (independent analyst)](https://redmonk.com/rstephens/2025/12/18/dora2025/)
  — Independent read of DORA 2025: volume is the mechanism — AI raises code-generation rate faster than review and deploy infrastructure absorbs it, so teams must instrument the absorption path (review, gates, deploy), not the generation path.
- [daily.dev: Defect Density & Escape Rate — Agile Metrics Guide (practitioner)](https://daily.dev/blog/defect-density-and-escape-rate-agile-metrics-guide-2024/)
  — Defect escape rate = defects found after a gate / total shipped through that gate, trended over 30/60/90 days — the standard construction to adapt into a per-gate false-pass rate for an agentic pipeline's QA gates.

## Role practices

- [Best practices for Claude Code (Anthropic docs)](https://code.claude.com/docs/en/best-practices)
  — Primary Anthropic guidance: verification loops (checks the agent can run, evidence over assertions, Stop hooks, /goal), explore-plan-code-commit with plan mode as a human gate, concise CLAUDE.md, deterministic hooks vs advisory rules, permission allowlists/sandboxing, headless claude -p for CI, parallel writer/reviewer sessions, adversarial review subagents, and named failure patterns (kitchen-sink sessions, trust-then-verify gap, over-specified CLAUDE.md).
- [Building Effective AI Agents (Anthropic engineering)](https://www.anthropic.com/engineering/building-effective-agents)
  — Anthropic's foundational agent guidance: prefer the simplest composable pattern (prompt chaining, routing, parallelization, orchestrator-workers, evaluator-optimizer) over full agents; teams that built elaborate multi-agent architectures often matched results with better prompting of a single agent.
- [How we built our multi-agent research system (Anthropic engineering)](https://www.anthropic.com/engineering/multi-agent-research-system)
  — Orchestrator-worker delegation requires each subagent to have an objective, output format, tool guidance, and task boundaries; multi-agent beat single-agent by 90.2% on their eval but consumed ~15x the tokens — reserve it for heavy parallel work.
- [When to use multi-agent systems (and when not to) (Claude blog)](https://claude.com/blog/building-multi-agent-systems-when-and-how-to-use-them)
  — Use one agent for simple tasks and multi-agent only for heavy parallelizable work; multi-agent systems are frequently applied where a single agent performs better.
- [How Anthropic teams use Claude Code (Claude blog)](https://claude.com/blog/how-anthropic-teams-use-claude-code)
  — Role-by-role internal patterns: most teams keep human review checkpoints rather than full autonomy (tightest for infrastructure, loosest for design's autonomous loops); security engineering uses TDD + pseudocode review for 3x faster incident resolution; strongest pattern is role dissolution — 'anyone who can describe a problem becomes someone who can build a solution' (designers, marketers, legal shipping working tools).
- [How AI Is Transforming Work at Anthropic (Anthropic research)](https://www.anthropic.com/research/how-ai-is-transforming-work-at-anthropic)
  — Quantified role shift from 200k internal transcripts: agent actions without intervention +116%, human turns -33%, task complexity 3.2→3.8, ~50% self-reported productivity gains; engineers shift to reviewer/reviser roles ('70%+ code review'); documented tensions: verification paradox, skill atrophy, weakened junior-senior mentorship, and delegation limited to cheaply-verifiable tasks.
- [How Claude Code is used in practice (Anthropic research)](https://www.anthropic.com/research/claude-code-expertise)
  — In typical sessions humans make most planning decisions (what to do) and Claude makes most execution decisions (how); greater domain expertise correlates with more work delegated per instruction — expertise shifts upstream into specification.
- [Claude Code GitHub Actions (Anthropic docs)](https://code.claude.com/docs/en/github-actions)
  — Documented CI/headless patterns: claude-code-action@v1 (built on the Agent SDK) for @claude-triggered and automation-mode runs; guardrails = least-privilege permissions, --allowedTools, --max-turns, workflow timeouts, concurrency controls for cost, GitHub Secrets/OIDC, and explicit instruction to review Claude's output before merging.
- [DORA 2025: State of AI-assisted Software Development (summary)](https://dora.dev/insights/balancing-ai-tensions/)
  — AI adoption now positively correlates with delivery throughput but continues to correlate with higher instability, change failures, and rework; ~30% of developers report little/no trust in AI code; the 'verification tax' re-spends writing-time savings on auditing; AI amplifies existing organizational strengths and weaknesses.
- [METR: Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/)
  — RCT (16 experienced OSS devs, 246 real tasks): developers were 19% slower with AI tools yet estimated they were 20% faster — the canonical citation for the over-trust/perception gap; METR now labels it historical but it remains the strongest evidence that perceived speedup must be measured, not assumed.
- [AI Agents Are Turning Developers Into Engineering Orchestrators and Moving the Risk to Review (Codacy)](https://blog.codacy.com/ai-agents-are-turning-developers-into-engineering-orchestrators-and-moving-the-risk-to-review)
  — Review capacity is the new bottleneck: reviewers face higher volume in the same time, and 38% find AI-generated code harder to review than human-written code — the risk moves from writing to reviewing.
- [Spec-Driven Development in 2026 (DEV Community overview of Kiro, GitHub Spec Kit, BMAD)](https://dev.to/krlz/spec-driven-development-in-2026-what-it-is-the-tooling-and-how-teams-actually-use-it-2fk2)
  — SDD treats the written spec (requirements → user stories → acceptance criteria) as the primary executable artifact with code as regenerable output — the PM/owner role moves upstream since every SDD tool assumes a precise spec already exists; emerged specifically as the antidote to vibe-coding drift.
- [In 2026, AI Is Merging With Platform Engineering (The New Stack)](https://thenewstack.io/in-2026-ai-is-merging-with-platform-engineering-are-you-ready/)
  — Platform teams own the paved road for agents: templates, modules, and guardrails defining 'correct' infrastructure before generation; mature platforms treat agents as a user persona with RBAC, quotas, and governance policies — compliance by default at generation time, not post-hoc scanning (justified by ~55% AI secure-code generation rates in Veracode 2026 testing).
- [Autonomous Coding Agents Are Rewriting the QA Playbook (DevAssure)](https://www.devassure.io/blog/autonomous-coding-agents-rewriting-qa-playbook-2026/)
  — Agents generate code and tests faster than humans can review, shifting the QA bottleneck from writing coverage to validating confidence; fastest-adapting teams pair dedicated testing agents with human quality strategists doing behavior validation, edge-case thinking, and risk analysis.
- [Why AI Enterprise Solutions Fail: 21+ Agent Failure Modes (EPAM)](https://www.epam.com/insights/ai/blogs/ai-agent-failure-modes-enterprise)
  — Catalog of recurring agent failure modes in long-running and multi-agent systems: context loss, confusing plans with deliverables, agents over-trusting their own work, and induced review fatigue — useful checklist for hardening a pipeline's gates.
- [Agentic fatigue meets vibe coding: the AI developer productivity paradox (explainx)](https://explainx.ai/blog/agentic-fatigue-vibe-coding-ai-developer-productivity-paradox)
  — Names 'agentic fatigue' (cognitive load of constant trust micro-decisions and reviewing code you didn't write); cites a 2026 HackerRank survey where 67% of developers report increased stress from AI-code-validation responsibilities, and context-undisciplined teams spending 4-6x more tokens per feature.
- [Claude Code Review merge gates guide (Whitefox)](https://www.whitefox.cloud/articles/claude-code-review-merge-gates-tools-pricing/)
  — Anthropic's managed Code Review GitHub App completes with a neutral conclusion and never blocks merges by itself — human review and existing CI gates remain authoritative; typical review costs $15-25 and ~20 minutes, a concrete data point for budgeting agent review in CI.

## Comparable cases and pilot design

- [METR: Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/)
  — Gold-standard pilot design: 16 experienced devs, 246 real tasks randomized to AI-allowed/disallowed, screen-recorded. Devs forecast +24% and perceived +20% speedup but measured 19% slower - collect forecast, perception, and objective timing separately because the gap is itself a finding.
- [Answer.AI: Thoughts On A Month With Devin](https://www.answer.ai/posts/2025-01-08-devin)
  — The canonical small-team negative pilot: ~1 month, 20 predefined tasks, outcomes logged as 3 success / 3 inconclusive / 14 fail. Key failure mode was unpredictability - tasks resembling early wins failed in costly ways, and autonomy became a liability when the agent chased impossible solutions for days. Its pre-registered task ledger is directly reusable.
- [Google: How much does AI impact development speed? An enterprise-based RCT (arXiv 2410.12944)](https://arxiv.org/abs/2410.12944)
  — 96 Google engineers randomized on one complex enterprise-grade task: 96 vs 114 minutes, ~21% speedup after controls. Shows a controlled comparison is feasible inside a company, and that heavier daily coders benefited more - segment results by user.
- [HealthEdge: Building an AI-First SDLC - Lessons From Our Claude Pilot Program](https://healthedge.com/resources/blog/building-an-ai-first-sdlc-lessons-from-our-claude-pilot-program)
  — Template for pilot logistics and comms (21 days, 53 contributors, 5 teams, 49 documented use cases, daily sharing rituals, weekly contests) but also the credibility anti-pattern: no control group, savings 'estimated' (680+ hours), and zero failures reported.
- [Cloudflare workers-oauth-provider (GitHub repo)](https://github.com/cloudflare/workers-oauth-provider)
  — The best public 'lab notebook': every prompt and human intervention preserved in commit messages, creating an auditable record of AI-assisted development of security-critical code; the lead engineer's skeptic-to-convert arc is credible because the record is inspectable.
- [Max Mitchell: I Read All Of Cloudflare's Claude-Generated Commits](https://maxemitchell.com/writings/i-read-all-of-cloudflares-claude-generated-commits/)
  — Independent audit of the Cloudflare record (~50 commits, >95% AI-written, manual interventions spiking around commit 40). Concludes the prompt is more valuable and easier to review than the resulting code, and proposes treating prompts as version-controlled source - a concrete narration technique.
- [DORA 2025: State of AI-assisted Software Development](https://dora.dev/dora-report-2025/)
  — Large-N context for any internal writeup: AI now associates with higher throughput but also higher instability; ~30% of devs have little/no trust in AI code; AI amplifies existing team strengths and weaknesses. Pair every speed metric with a stability metric.
- [Anthropic: How AI Is Transforming Work at Anthropic](https://www.anthropic.com/research/how-ai-is-transforming-work-at-anthropic)
  — Method model for evidence at scale: 200k internal Claude Code transcripts analyzed Feb-Aug 2025 (feature-implementation use rose 14.3% to 36.9%) combined with per-team interviews - quantitative trend plus role vignettes.
- [Anthropic: How Anthropic teams use Claude Code](https://claude.com/blog/how-anthropic-teams-use-claude-code)
  — The team-by-team vignette format (security, inference, data science, legal, marketing) is the narrative structure to copy for a 6-person team: one concrete workflow, what changed, and a named practice per person/role.
- [MIT NANDA 'GenAI Divide' coverage (Forbes)](https://www.forbes.com/sites/jasonsnyder/2025/08/26/mit-finds-95-of-genai-pilots-fail-because-companies-avoid-friction/)
  — 95% of enterprise GenAI pilots show no P&L impact; the 5% that succeed pick one pain point, integrate deeply into workflow, and use systems that learn from feedback. This is the skeptical prior an internal case study must explicitly answer.
- [DX Research: Measuring AI code assistants and agents](https://getdx.com/research/measuring-ai-code-assistants-and-agents/)
  — Most-referenced measurement scaffold: track utilization, impact, and cost; avoid acceptance-rate and adoption-count vanity metrics. Validated with Booking.com and Block; gives an internal report a defensible metric taxonomy.
- [Every: Compound Engineering - How Every Codes With Agents](https://every.to/chain-of-thought/compound-engineering-how-every-codes-with-agents)
  — Closest primary writeup to a 6-person agentic team: plan/work/review/compound loop (~80% planning), one owner per feature who supervises the agent and posts async updates, and every cycle writes lessons back into prompts/config so the system improves measurably over time.
- [Atlassian: The AI-native SDLC is paying off](https://www.atlassian.com/blog/ai-at-work/ai-native-sdlc-paying-off-per-developer-per-week)
  — Observational telemetry across 3,400 repos / 2,500 customers: AI-native teams merge 19% more PRs/month and save 2-3 hrs/dev/week. Useful as the external benchmark row in an internal results table.
- [Stanford 100,000-developer productivity study (Denisov-Blanch) - summary](https://proxify.io/articles/stanford-study-of-100000-developers-on-engineering-productivity)
  — At scale, AI gains are partly offset by rework, and can go negative in high-complexity/legacy codebases; measure delivered, surviving functionality rather than commit or line counts - directly shapes which metrics a small team should choose.
- [Real World Data Science: Deploying Agentic AI - What Worked, What Broke, and What We Learned](https://realworlddatascience.net/applied-insights/case-studies/posts/2025/08/12/deploying-agentic-ai.html)
  — Honest deployment postmortem format ('worked / broke / learned' as the report skeleton); found agentic systems impressive-but-brittle and chose a transparent hand-rolled pipeline over frameworks to keep failures diagnosable.
- [arXiv: What Breaks When LLMs Code? Operational Safety Failures of Agentic Code Assistants](https://arxiv.org/pdf/2605.30777)
  — Documents the failure class an internal study must instrument for: agents produce superficially successful runs while silently introducing regressions and maintainability damage that tests do not catch - motivates escaped-defect and churn tracking, not just pass rates.
