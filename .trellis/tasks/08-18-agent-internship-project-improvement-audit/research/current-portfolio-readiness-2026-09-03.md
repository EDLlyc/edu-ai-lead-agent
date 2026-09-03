# Research: Current GitHub and portfolio readiness for Agent internships

- Query: Review the just-pushed public `main` from recruiter and interviewer perspectives; assess
  README first-screen discoverability, case studies, screenshots/static replay/demo commands, CI,
  licensing/notice, public-safe fixtures, reproducibility, and the visibility of the core Agent and
  image-evaluation stories.
- Scope: mixed (local source inspection plus unauthenticated public GitHub inspection; no model,
  credentials, deployment, push, or repository mutation)
- Date: 2026-09-03

## Findings

### Executive verdict

The project is already technically stronger than a typical Agent internship portfolio. Its best
evidence is not the number of business features; it is the combination of a bounded typed Agent
runtime, one canonical Tool Registry shared with MCP, claim-level grounding, a safe trace surface,
provider-free reproducibility, and a failure-aware live multimodal evaluation. That supports a
primary positioning of **Agent application / AI platform backend**, with **Agent evaluation** as a
credible second axis.

The public translation is only medium-strength. A motivated interviewer can find excellent code
and evidence, but a recruiter scanning for 30 seconds is first shown a broad “multi-agent content
system,” two content images, and a long business-demo manual. The strongest Agent screenshot,
metrics, and the new GLM-5V-Turbo result are not on the first screen. The GitHub repository is
public and current, but has no description, homepage, topics, detected license, GitHub Actions, or
release. Therefore the limiting factor is now **evidence architecture and public trust signals**,
not more Agent features.

### Current public GitHub state

Unauthenticated inspection of the public repository on 2026-09-03 established:

- Repository: <https://github.com/EDLlyc/edu-ai-lead-agent>; visibility `public`, default branch
  `main`, Python primary language, approximately 29,197 KiB repository size.
- Remote `main` resolved to `c472c6e8defc1b0f78f13acd95bf114c26c03b7f`, matching the stated
  just-pushed portfolio head.
- Repository metadata returned `description: null`, `homepage: null`, an empty `topics` array, and
  `license: null`.
- `/.github` returned 404 and the Actions workflows endpoint returned `total_count: 0`; there is no
  public CI result for the remote head. `main` was reported as unprotected.
- The raw public README returned HTTP 200. Workbench sources, screenshots, deterministic run
  evidence, resume sources/PDF, image-panel sources, and the archived GLM-5V evidence note are
  present on remote `main`.

These are current external observations, not permanent facts. They should be rechecked after any
GitHub settings or repository changes.

### What is genuinely strong and interview-defensible

#### 1. Bounded Agent runtime, not an unbounded prompt loop

- `backend/app/domain/agent_workbench.py:58-88` defines hard model-turn, tool-call, timeout,
  recursion, argument/result, model-response, and run-response budgets, with construction-time
  invariants.
- `backend/app/application/services/agent_workbench_graph.py:94-176` compiles a small explicit
  LangGraph state machine: model decision -> tool execution -> finalization.
- `backend/app/application/services/agent_workbench_graph.py:178-262` enforces deadline and model
  budgets and rejects duplicate call IDs or a decision that exceeds the remaining call budget.
- `backend/app/application/services/agent_workbench_graph.py:264-391` validates a canonical
  invocation, scopes exact-result reuse to the current run, bounds tool execution by the remaining
  deadline, and turns failures into typed observations.
- `backend/app/application/services/agent_workbench_graph.py:546-577` makes budget exhaustion and
  model failure explicit terminal states instead of silently continuing.

This is a high-value Agent engineering story because it answers “what happens when the model is
wrong, slow, repetitive, or over-budget?” with executable controls.

#### 2. One typed Tool Registry across Function Calling, MCP, and evaluation

- `backend/app/application/services/agent_tools.py:58-100` binds every tool to Pydantic input/output
  types, timeout and byte budgets, and closed-world/read-only annotations.
- `backend/app/application/services/agent_tools.py:103-184` owns stable tool ordering, canonical
  JSON schemas, a registry schema hash, model tool schemas, and a run-scoped invocation key.
- `backend/app/application/services/agent_tools.py:186-218` validates arguments before the handler,
  validates results after the handler, contains exceptions behind safe typed errors, and applies a
  result-size limit.
- `backend/app/agent_mcp_main.py:29-80` exposes that same registry through the official MCP server
  rather than implementing a parallel handler set.
- `backend/app/agent_mcp_main.py:83-98` fail-closes MCP outside local fixture-safe operation and
  serves only over stdio.
- `backend/app/agent_mcp_main.py:101-150` preserves the registry's exact input/output schemas and
  advertises read-only, non-destructive, idempotent, closed-world MCP annotations.

The strongest framing is “schema and behavior have one owner across three adapters,” not merely
“used MCP.” That is an architecture-level differentiator.

#### 3. Grounding is a checked data-flow invariant

- `backend/app/domain/agent_workbench.py:91-146` separates external facts, brand statements and
  opinions, and forbids brand citations from masquerading as eligible factual evidence.
- `backend/app/application/services/agent_workbench_graph.py:592-638` accepts final claims only when
  citation IDs were produced successfully in the current run and have the correct evidence/brand
  kind; unsupported or conflicting citation mappings fail closed.
- `backend/app/agent_workbench_api_main.py:86-143` keeps the portfolio API independent,
  loopback-only, origin-restricted and disabled by default; forwarded/non-loopback requests are
  rejected.

This is much more credible than saying “the Agent supports citations,” because the project can
point to the exact runtime acceptance gate.

#### 4. Reproducible API/UI evidence, not a mocked screenshot

- `docs/portfolio/agent-workbench.md:76-113` documents three browser-to-real-loopback runs and
  links the typed response, screenshot, network record, summary, manifest and hashes.
- `docs/portfolio/runs/agent-workbench/f5cd8de936a5-20260818T063838Z/overview.md:1-16`
  records one multi-tool completion, one deterministic validator call, and one zero-tool safety
  refusal.
- `scripts/capture_agent_workbench.py:400-454` strips credential-like environment variables and
  forces deterministic fixture mode or an explicit isolated live mode.
- `scripts/capture_agent_workbench.py:497-565` starts real Uvicorn and Vite loopback processes and
  cleans both up.
- `scripts/capture_agent_workbench.py:571-665` sends a real typed API request, runs the browser
  capture, and validates the browser response against the generated schema.
- `scripts/capture_agent_workbench.py:767-799` requires exactly one browser POST to the exact
  loopback API and records no route interception plus blocked service workers.
- `scripts/capture_agent_workbench.py:802-890` binds queries, semantic results, screenshots and
  JSON artifacts into a hashed manifest.
- `Makefile:376-390` provides a provider-free portfolio check, capture, and capture-verification
  entry point.

The static evidence package is already strong. It is a better portfolio proof than a screenshot
alone and should be promoted much earlier in the README.

#### 5. Honest deterministic evaluation boundary

- `backend/evals/agent_workbench/canonical-report.md:1-29` reports 42 sanitized cases across six
  categories and explicitly states that 42/42 measures deterministic contracts, grounding and
  safety—not live-model intelligence.
- `docs/portfolio/agent-workbench.md:137-143` repeats the same boundary next to the metrics.
- `backend/evals/brand_retrieval/canonical-report.md:1-20` compares two frozen retrieval policies
  and reports Recall@5 80% -> 95%, nDCG@5 84.37% -> 92.86%, and parent diversity 85% -> 100%, while
  clearly limiting the result to sanitized observations.

The restraint in these claims is a strength. It gives an interviewer less room to dismiss the
entire project as metric inflation.

#### 6. GLM-5V-Turbo evaluation is now the highest-value multimodal story

- `backend/evals/image_quality_panel/README.md:1-28` documents exactly one direct Zhipu
  `glm-5v-turbo` evaluator, six source families, 48 derived pairs, an AB/BA and repeat design,
  exactly 120 planned calls, a first-call four-image capability gate, no retry/fallback, blinded
  image references, a frozen request dialect, and strict safe parsing.
- `backend/evals/image_quality_panel/execution.py:39-95` proves sequential one-shot execution and
  first-call capability stop in code.
- `backend/evals/image_quality_panel/planning.py:222-252` binds the model identity, complete call
  plan and every attempt to a manifest; `planning.py:255-299` requires an explicit authorization
  artifact before binding requests.
- `.trellis/tasks/archive/2026-09/09-02-image-vlm-human-calibration/research/glm-5v-turbo-live-evidence-2026-09-03.md:3-42`
  records 120 observed attempts, 119 completed, one unretried provider rejection, known cost
  CNY 3.085126, P50/P95 latency, and an incomplete/non-activating result.
- The same evidence at lines 44-67 reports 29/36 objective pair accuracy (80.56%), 15/18 holdout
  accuracy (83.33%), and the critical result that visible-text/OCR accuracy was 0/6 while five
  other tested dimensions were much stronger.
- Lines 69-85 distinguish subjective repeat/position consistency from accuracy and conclude that
  deterministic OCR/hard validation must remain alongside the VLM.

This is a better resume story than a perfect fixture score because it shows experimental design,
cost/risk governance, negative findings, and an engineering decision caused by the failure.

### First-screen and information-architecture gaps

#### The first screen is competent but does not optimize for the target role

- `README.md:1-28` provides a professional logo, English tagline, Chinese explanation, one long IP
  asset paragraph, and navigation.
- `README.md:30-37` lists six strong capabilities, but only one is explicitly labeled Agent
  engineering.
- The first visual proof at `README.md:39-84` is two content-marketing images. The Agent trace
  overview exists at `docs/portfolio/assets/agent-workbench-real-runs-overview.png` but is not shown
  in the root README.
- The actionable Workbench section appears only at `README.md:142-154`; its case study appears even
  later in the navigation table at `README.md:340-353`.
- `README.md:156-318` devotes more than 160 lines to the official-account local handoff and its
  operational details. This is good engineering documentation, but it dilutes the recruiter path.

High-value correction: turn the first 60-90 lines into a recruiter landing page with (1) one precise
title, (2) a five-item tech stack, (3) one Agent trace image, (4) a compact evidence table, and (5)
one no-key reproduction command. Move the official-account operational detail to its existing
dedicated documentation or collapse it under `<details>`.

#### “Multi-agent” is currently an avoidable credibility risk

`README.md:21-24` calls the repository an “evidence-grounded multi-agent content system” and a “多
Agent 系统,” but repository-wide public documentation does not name collaborating Agent roles,
messages, delegation, or a multi-Agent evaluation. The concrete portfolio implementation is one
bounded tool-using Agent plus several governed workflow/model stages. A skeptical interviewer can
read the tagline as trend-word inflation.

Recommended title: **“An evidence-grounded, evaluable Agent system for science-education content
research”** or **“可评测、可追溯的内容研究 Agent（LangGraph + MCP + RAG + Eval）.”** Use
“multi-stage Agent workflow” for the production chain unless actual multi-Agent coordination is
implemented and evaluated.

### Reproducibility and demo gaps

What works now:

- `README.md:126-152` has environment setup and two explicit Workbench launch commands.
- `docs/portfolio/agent-workbench.md:102-113` has the stronger one-command real evidence capture
  and an independent verifier.
- `docs/portfolio/agent-workbench.md:157-171` offers a five-minute review path without a provider
  key or production database.
- `Makefile:372-390` collects the relevant offline checks and capture commands.

What remains weak for a third party:

- The root quick start first asks for full environment creation, database/object-storage startup,
  migrations and source seeding (`README.md:126-132`), even though the fixture Workbench itself
  does not need production infrastructure. There is no top-level “clone -> install -> one command
  -> evidence” path dedicated to the portfolio slice.
- There is no checked static HTML replay, GitHub Pages site, GIF/video, WebM/MP4, or hosted demo.
  The checked screenshots and JSON are useful but require manual navigation.
- There is no containerized one-shot portfolio target or devcontainer. Conda, Node, Docker, Make
  and Bash are all listed as prerequisites (`README.md:119-124`), raising the reproduction cost.
- The stored deterministic capture was made from an older source commit
  (`docs/portfolio/agent-workbench.md:85-88`), not the current remote head. The verifier can prove
  its integrity but not that the current head generated identical evidence.

Recommended minimum: add `make portfolio-demo` (or an equivalent script) that installs/checks only
the portfolio dependencies, runs the checked deterministic eval, generates/verifies the three-case
bundle, and prints the local evidence index. A static replay page can load the already-public safe
JSON and screenshots without exposing an Agent API.

### CI and public trust gaps

- There is no `.github/` directory, no Actions workflow, and no check/status badge.
- `Makefile:419-470` already defines Ruff formatting, lint, strict mypy, pytest, Prettier, ESLint,
  TypeScript, Vitest, production build and aggregate checks. The missing work is orchestration and
  caching, not inventing a quality system.
- `Makefile:372-383` already isolates the most relevant provider-free Agent portfolio gate.
- There is no tagged portfolio release that freezes the resume PDF, run evidence, canonical
  reports and source identity.

For recruiter confidence, a small GitHub Action is higher-value than more tests. It should run only
provider-free gates, never load `.env`, and visibly prove `agent-portfolio-check`, frozen eval drift,
backend static checks, and frontend checks. Add a status badge only after the first green remote run.

### License, notice, and public-rights gaps

- No `LICENSE`, `NOTICE`, `SECURITY.md`, or `CONTRIBUTING.md` is present at repository root; GitHub
  reports no detected license.
- The repository contains company-oriented implementation, branded “赛先生/小赛” outputs, reports
  and generated media. `README.md:208` explicitly refers to company-IP body slots, and
  `main.tex:138`, `main.tex:452-453` refers to company platform/storage context.
- `docs/portfolio/content-showcase.md:1-35` says the content is safe public output and records model
  identity and hashes, but it does not state who owns the code, generated media, copy or trademarks,
  or under what terms another person may reuse them.
- `README.md:204-205` responsibly says an unverified publication-rights flag is not authorization,
  but this is an operational rule rather than a repository-wide rights statement.

Do not add MIT mechanically. First confirm that the candidate is authorized to publish and license
the code and branded assets. Then add a root license plus a `NOTICE`/asset-rights table that separates:

1. source code the owner may license;
2. third-party dependencies under their own licenses;
3. company names, trademarks, brand assets and generated showcase media that are not granted for
   reuse unless explicitly authorized;
4. public-source articles/photos that remain attributed and are not relicensed.

Until this is resolved, a recruiter can reasonably ask whether internship work and company IP were
authorized for public release. This is both a portfolio-polish issue and a substantive ownership risk.

### Public-safe fixture assessment

Positive evidence:

- `docs/portfolio/agent-workbench-cases.v1.json:1-43` contains three clearly synthetic/sanitized
  scenarios and no production IDs or arbitrary URLs.
- The checked run directory contains typed responses, summaries, screenshots, exact loopback
  network records, a manifest and a detached SHA-256 record.
- `scripts/capture_agent_workbench.py:265-296` enforces bounded tool use, citation binding and case
  expectations before evidence is accepted.
- `scripts/capture_agent_workbench.py:897-918` scans artifacts for configured credential values,
  private paths and credential-like text; its verifier also checks hashes and PNG metadata.
- `.gitignore:4-7` excludes local environment files while deliberately permitting only
  `.env.example`; `.gitignore:32-36` excludes runtime outputs.
- The public `.env.example` contains placeholders/empty credentials and safe loopback defaults; no
  live secret was observed in the inspected portfolio evidence.

Remaining publication concerns:

- The GLM-5V evidence summary cites hashes for manifest, authorization, pricing, request, journal
  and attempt artifacts, but the safe 10.5 KiB report and 447-byte non-activating artifact remain
  under ignored `output/`. The public repository has the narrative evidence note but not the safe
  machine-readable report needed to verify its detailed metrics. Private attempt journals should
  stay private; the explicitly safe report and non-activating artifact are candidates for a
  reviewed public evidence pack.
- The GLM-5V result is discoverable only through
  `backend/evals/image_quality_panel/README.md` or a `.trellis/tasks/archive/...` path. The root
  README's image-eval link at `README.md:348` points only to the provider-free six-dimensional
  baseline, so a recruiter is unlikely to find the live result.
- The public resume intentionally contains an email address at
  `docs/portfolio/resume/resume-public.tex:11`. That is not a leak if deliberate, but the repository
  should document the intended public-contact policy.

### Resume readiness

The current resume is well aligned to Agent application roles, but it undersells the strongest new
evidence:

- `docs/portfolio/resume/resume-public.tex:33-39` already presents LangGraph, Tool Calling, MCP,
  PostgreSQL/pgvector, Zhipu, Qwen3-VL-Embedding, RAG, typed tools and deterministic fallback.
- The RAG metrics at `resume-public.tex:38` match the frozen provider-free report, but the bullet
  should say “脱敏冻结评测” or equivalent so the boundary remains visible on the resume itself.
- The image bullet at `resume-public.tex:39` still foregrounds the perfect 48/48 provider-free
  policy track. It does not mention the now much more valuable 120-attempt GLM-5V experiment,
  holdout result, repeat control, cost, or OCR failure.
- The resume links only the GitHub profile (`resume-public.tex:11`), not the exact repository or
  an anchored case study. One click should take the interviewer directly to the Agent evidence.

Recommended evidence-bound bullets:

1. **Agent runtime / MCP:** “基于 LangGraph 实现 4-turn/4-tool-call 有界 Agent loop，以同一
   Typed Tool Registry 统一 Function Calling、MCP v2 stdio 与 Eval schema；对参数、返回、超时、
   大小、重复调用和 claim-level citation 做运行时校验，并保留脱敏 Trace。”
2. **Reproducible evaluation:** “构建 42 条六类 provider-free Agent contract cases 和 3 条真实
   loopback API/UI 证据链；多工具案例完成 3 次只读工具调用、2 个绑定引用和 11 步 Trace，安全拒绝
   以 1 次决策、0 次工具调用闭环（不将固定策略结果表述为 live 模型准确率）。”
3. **Multimodal failure-driven engineering:** “为 GLM-5V-Turbo 设计 48 对/6 源族、AB/BA、固定
   重复与源族隔离 holdout 的 120 次图片审校实验；119 次完成、holdout 15/18、已知成本 ¥3.09，
   定位 OCR 0/6 失效并保留确定性文字门禁，实验未自动激活生产模型。”

The third bullet is likely the highest-signal addition for evaluation-oriented interviews because
it communicates a negative result and the resulting system decision, not a vanity score.

### Prioritized improvements

#### P0 — do before the next application batch

| Improvement | Value | Minimum deliverable | Estimated effort |
| --- | --- | --- | ---: |
| Set GitHub metadata | Makes the repo searchable and self-explanatory before README load | Description, homepage/case-study URL, 6-10 topics such as `langgraph`, `mcp`, `agent-evaluation`, `rag`, `fastapi`, `pgvector`, `multimodal` | 15 minutes |
| Resolve license/IP boundary | Removes the largest public-trust and ownership question | Confirm publication authority; add appropriate `LICENSE` plus code/brand/media/source `NOTICE` | 0.5 day plus approval |
| Add provider-free CI | Converts local quality claims into a remote green signal | GitHub Actions for Agent portfolio/eval drift and split backend/frontend checks; cache dependencies; no secrets; README badge | 0.5-1 day |
| Rewrite README recruiter path | Makes the Agent story visible in 30 seconds | Precise non-hype title, Agent trace screenshot, architecture/evidence table, one no-key command; collapse operational handoff prose | 0.5 day |
| Publish the safe GLM-5V result | Turns the just-completed work into verifiable portfolio evidence | `docs/portfolio/evals/` case study, reviewed safe report JSON, non-activating artifact, compact result chart, link from README | 0.5 day |
| Update resume links/bullet | Aligns the application document with current evidence | Direct repo/case-study link and the failure-driven GLM-5V bullet; rebuild PDF | 1-2 hours |

#### P1 — highest-value technical evidence after P0

| Improvement | Why it matters | Minimum deliverable |
| --- | --- | --- |
| Zhipu-only live Agent eval | The current 42/42 track proves policy/contract correctness, while the one public live Agent attempt failed before typed evidence verification (`docs/portfolio/runs/agent-workbench/live-zhipu/attempt-summary.md:1-17`) | Freeze a sanitized objective dataset and use only the authorized Zhipu text model; report task/tool/argument/citation/refusal metrics, repeat variance, latency, tokens/cost and bad-case taxonomy; never use a model judge as sole truth |
| Static replay or 60-90 s demo | Lets a recruiter understand the trace without installing Conda/Docker | Static read-only replay from the existing public response JSON, or a short video/GIF with links to exact evidence; no public API |
| Current-head evidence capture | Removes the gap between the August capture commit and September `main` | Regenerate and verify the deterministic three-case evidence bundle on the portfolio release commit |
| MCP client proof | Turns a source-level MCP claim into interoperability evidence | One fixture-only client session showing `list_tools`, two typed calls and safe results; preserve stdio-only boundary |
| Portfolio release | Gives applications a stable reference | Tag/release with resume PDF, evidence index, safe eval artifacts and SHA-256 manifest |

#### P2 — do not prioritize now

- More tools, Agent roles, Multi-Agent/A2A, Reflection loops or long-term Memory without a measured
  task failure that needs them.
- A public writable/live Agent service; the current loopback-only posture is a sound safety design.
- Training/fine-tuning labels such as SFT, DPO or GRPO without a separate dataset, training run and
  ablation study.
- A large AgentOps product before the public CI, evidence index and one real Agent eval exist.

### Recommended recruiter-facing evidence map

The README should expose one compact mapping near the top:

| Claim | Primary proof | Reproduce |
| --- | --- | --- |
| Bounded Tool-using Agent | `backend/app/application/services/agent_workbench_graph.py` plus the real run overview image | `make agent-portfolio-check` |
| One schema across Function Calling/MCP/Eval | `backend/app/application/services/agent_tools.py`, `backend/app/agent_mcp_main.py` | focused contract tests in `Makefile:376-383` |
| Claim-level grounding and safety refusal | real `multi-tool-research` and `safety-refusal` artifacts | `make agent-portfolio-capture` then verifier |
| Hybrid RAG policy gain | `backend/evals/brand_retrieval/canonical-report.md` | `make brand-retrieval-eval` |
| Failure-aware multimodal evaluation | new public GLM-5V case study and safe report | provider-free panel preflight by default; live run remains opt-in |

This makes the repository readable at three depths: recruiter card, interviewer case study, and
source/test proof.

## Files Found

- `README.md` — public landing page, feature overview, operational quick starts, quality commands,
  resume link and safety boundaries.
- `docs/portfolio/agent-workbench.md` — strongest current Agent case study, architecture, checked
  real-loopback evidence, metrics, limitations and interview script.
- `docs/portfolio/assets/agent-workbench-real-runs-overview.png` — 1800x1396 overview of three real
  deterministic API/UI cases; currently absent from root README.
- `docs/portfolio/runs/agent-workbench/f5cd8de936a5-20260818T063838Z/` — hashed typed JSON,
  screenshots, summaries and exact loopback network observations.
- `docs/portfolio/runs/agent-workbench/live-zhipu/` — honest record of one unretried live Agent
  capture failure; not evidence of live Agent intelligence.
- `scripts/capture_agent_workbench.py` — bounded, credential-stripping real API/UI capture and
  evidence verifier.
- `backend/app/application/services/agent_tools.py` — canonical typed closed-world Tool Registry.
- `backend/app/application/services/agent_workbench_graph.py` — bounded LangGraph runtime and
  claim/citation acceptance gate.
- `backend/app/agent_mcp_main.py` — MCP v2 stdio projection over the same registry.
- `backend/app/agent_workbench_api_main.py` — separate loopback-only portfolio ASGI boundary.
- `backend/evals/agent_workbench/canonical-report.md` — 42-case deterministic Agent contract
  baseline with honest scope statement.
- `backend/evals/brand_retrieval/canonical-report.md` — frozen RAG policy comparison used by the
  current resume.
- `backend/evals/image_quality_panel/` — exact single-model GLM-5V-Turbo experiment planner,
  executor, metrics and provider-free preflight.
- `.trellis/tasks/archive/2026-09/09-02-image-vlm-human-calibration/research/glm-5v-turbo-live-evidence-2026-09-03.md`
  — current live image-evaluation result, currently buried outside the portfolio navigation.
- `output/evals/image-panel-glm5v3-live-20260903-v1/image-single-model-report.json` — locally present
  safe machine-readable report, ignored and absent from public `main`.
- `docs/portfolio/resume/resume-public.tex` and `resume-public.pdf` — public resume source/artifact;
  currently predates the live GLM-5V result.
- `Makefile` — mature local quality and portfolio command surface, but not wired to public CI.
- `.env.example` and `.gitignore` — safe defaults/placeholders and credential/runtime-output ignore
  rules.

## External References

- Public repository: <https://github.com/EDLlyc/edu-ai-lead-agent>
- GitHub repository metadata endpoint used for the time-bound observations:
  <https://api.github.com/repos/EDLlyc/edu-ai-lead-agent>
- Public raw README used to confirm unauthenticated access:
  <https://raw.githubusercontent.com/EDLlyc/edu-ai-lead-agent/main/README.md>
- GitHub Actions workflow inventory endpoint (observed zero workflows at audit time):
  <https://api.github.com/repos/EDLlyc/edu-ai-lead-agent/actions/workflows>

## Related Specs

- `.trellis/spec/backend/agent-workbench.md` — one canonical read-only registry, bounded runtime,
  grounding, MCP, evaluation and portfolio evidence rules.
- `.trellis/spec/frontend/agent-workbench.md` — development-only UI, generated contract, safe trace
  rendering, accessibility and real browser evidence requirements.
- `.trellis/spec/backend/agent-pipeline.md` — production multi-stage workflow and deterministic
  gates around model calls.
- `.trellis/spec/backend/execution-governance.md` — durable execution, fallback and observable
  governance expectations.
- `.trellis/spec/backend/image-quality-evaluation.md` — provider-free and live single-model image
  evaluation claim boundaries.
- `.trellis/spec/backend/quality-guidelines.md` — layered local validation and final-gate policy.
- `.trellis/spec/guides/cross-layer-thinking-guide.md` — contract ownership and end-to-end evidence
  projection guidance.

## Caveats / Not Found

- No tests or build commands were run because this research role may write only under the task's
  `research/` directory; many test/build commands create cache or generated files. Existing report
  contents and source contracts were inspected, but current-head green status cannot be claimed.
- No model, database, business API, deployment, credential, git command, commit or push was used.
- Public GitHub API observations are time-bound. The unauthenticated shared IP reached its API rate
  limit near the end of inspection, after the repository metadata, root tree, remote head,
  `.github` absence and zero-workflow result had already been captured.
- No LICENSE/NOTICE/CI/static replay/video was found locally or on remote `main` at audit time.
- The presence of company-branded materials is not proof that publication or relicensing is
  unauthorized; it is proof that the repository currently does not document the authority or
  rights boundary. Obtain the owner's answer instead of guessing.
- The GLM-5V-Turbo experiment evaluates an image judge, not the Agent's live tool-selection or
  multi-turn planning quality. It strengthens the evaluation-engineering story but does not close
  the separate live Agent-eval gap.
- The 48 image pairs derive from six independent source families, include no human/external labels,
  and must not be presented as 48 independent real images, Human Gold or broad population accuracy.
