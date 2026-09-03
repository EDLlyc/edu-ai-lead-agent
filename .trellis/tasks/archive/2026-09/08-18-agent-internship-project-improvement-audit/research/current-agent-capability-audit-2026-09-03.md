# Research: Current Agent engineering capability audit

- Query: Audit the current repository's demonstrable Agent engineering capabilities, compare them with the stale internship-project audit, and identify evidence-backed resume highlights and interview risks, with special attention to governed Worker–Reviewer execution, live evaluation, and GLM-5V image calibration.
- Scope: internal
- Date: 2026-09-03

## Findings

### Executive verdict

The repository is now a credible **Agent application engineering / Agent platform backend** portfolio, not merely a business automation project. Its most differentiated capability is the combination of:

1. a typed, bounded, citation-aware Agent Workbench with one canonical tool registry shared by LangGraph and MCP;
2. a durable execution-governance kernel with least-privilege roles, multidimensional budget reservation, causal traces, and immutable artifacts;
3. a fixed, governed Writer–Reviewer workflow whose verdicts and repairs are constrained by code-owned policy;
4. an unusually rigorous, actually executed single-model GLM-5V image evaluation that preserves failures and exposes an important OCR safety weakness.

The evidence is uneven, however. Workbench and Reviewer have strong implementation and deterministic contract evidence, but no successful live-LLM quality result. The enhanced retrieval A/B stopped at a failed first-pair canary and proves no uplift. The GLM-5V run is the only current, complete provider execution from which measured model-quality, latency, usage, and cost observations can honestly be quoted—and even that run is explicitly non-activating and has no human labels.

The strongest interview narrative is therefore **“I built governed, evidence-producing Agent systems and designed experiments that are allowed to say no”**, not “I improved model accuracy in production” and not “I built an autonomous multi-agent swarm.”

### Capability and evidence map

| Capability | Demonstrably implemented now | Strongest checked evidence | Honest current status |
|---|---|---|---|
| Typed Agent Workbench | Four strict read-only tools; bounded model/tool loop; same-run citation binding; conflict refusal; redacted trace; loopback-only API/UI | 42/42 deterministic cases; checked real local API/UI capture with a 3-tool chain, citation projection, refusal, and trace | Strong portfolio implementation. The successful capture uses a deterministic model; the one authorized Zhipu browser attempt failed before typed evidence verification. No live-LLM intelligence claim. |
| Canonical tool registry and MCP | Pydantic input/output schemas, schema hash, validated invocation, timeout/size bounds, safe argument summaries; MCP v2 server delegates to the same registry | Official MCP client contract tests cover list/call, unknown-tool denial, and subprocess stdio | Strong protocol/backend highlight. It is a local read-only MCP server, not a public production MCP service. |
| RAG and evidence retrieval | Query planning, one rewrite, weighted RRF, reranking, process-local single-flight embedding cache, guarded fallback; brand pgvector path and governed evidence FTS | Brand selection fixture: Recall@5 95%, MRR@5 100%, nDCG@5 92.86%; enhanced retrieval live A/B preserves a failed canary | Architecture is implemented. Brand metrics are sanitized deterministic selection-policy metrics, not live embedding/private-corpus effectiveness. Live rewrite/RRF/rerank uplift is unproven. |
| Durable execution governance | Closed capability registry, role/task/artifact scopes, durable pre-call budget reservations, terminal reconciliation, causal trace DAG, immutable artifacts | Unit/integration tests cover concurrent reservation, replay, scope tamper, timeout/cancel, depth and budget limits | High-value Agent platform engineering. It is governance infrastructure, not evidence of user-facing model-quality uplift. |
| Governed Writer–Reviewer | Separate Writer/Reviewer identities and capabilities; one bounded repair; code-owned issue taxonomy, decision projection, repair directives; observe/enforce rollout modes and crash recovery | Provider-free Reviewer canonical suite passes 48/48; integration tests cover observe, enforce, failures, restarts, concurrency, tamper, budget fence and exact lineage | Implementation is substantial and production-shaped, but mode defaults to `off`; `enforce` requires calibration evidence. No successful live Reviewer A/B report exists. |
| GLM-5V image evaluation | Direct Zhipu `glm-5v-turbo` one-shot transport; 48-pair, six-dimension, AB/BA and repeat plan; family-disjoint holdout; hash-bound authorization/journal/report; strict JSON and fail-closed parsing | 120 attempted calls, 119 completed; 80.56% objective pair accuracy, 83.33% holdout; P50 5.39 s, P95 21.20 s; known cost CNY 3.085126; OCR accuracy 0% | Strongest live-model evidence and strongest evaluation-engineering highlight. Single model, six source families, no human/external labels, one provider failure, non-activating. |
| Public portfolio evidence | Public README, architecture write-up, screenshots, checked manifests, reproducible commands, public resume PDF/TeX | `docs/portfolio/agent-workbench.md` and hash-bound run folder | The stale audit's “no public Agent proof” gap is substantially closed. GitHub Actions and a license are still absent; resume bullets do not yet reflect the new Reviewer/GLM-5V work. |

### 1. Typed Workbench: a real Agent loop, not a chat wrapper

The Workbench has a strict state and safety boundary:

- Hard limits are part of domain policy: at most four model turns and four tool calls, a 15-second model timeout, 30-second total deadline, and bounded payloads (`backend/app/domain/agent_workbench.py:58-88`).
- Claims and citations are typed. Evidence citations require an eligible public URL, while brand context is prohibited from masquerading as factual public evidence (`backend/app/domain/agent_workbench.py:92-146`).
- Trace objects are allowlisted and bounded rather than raw prompt dumps (`backend/app/domain/agent_workbench.py:149-223`).
- Every tool has strict Pydantic input/output schemas, time and byte bounds, a read-only declaration, and an OpenAI-compatible function schema (`backend/app/application/services/agent_tools.py:58-100`).
- The registry is canonical and deterministically hashed; arguments and results are validated before and after execution, with typed timeout/failure outcomes (`backend/app/application/services/agent_tools.py:103-218`).
- Safe argument summaries retain lengths/hashes rather than raw searches or article drafts (`backend/app/application/services/agent_tools.py:220-258`).
- The exact closed tool set is `get_event`, `retrieve_brand_context`, `search_evidence`, and `validate_copy`. Brand results are never evidence-eligible, and external evidence must remain current, governed, Tier A/B, and safe HTTPS (`backend/app/application/services/agent_tools.py:261-447`).
- The LangGraph runner is a bounded `model -> tools -> model/finalize` state machine (`backend/app/application/services/agent_workbench_graph.py:159-176`). It enforces budgets and validates tool-call IDs/counts (`backend/app/application/services/agent_workbench_graph.py:178-262`). Exact same-run calls may be cached, but cache hits still consume the tool-call budget (`backend/app/application/services/agent_workbench_graph.py:264-390`).
- Final-answer validation binds external factual claims only to successful, current evidence results; brand statements can use only brand citations and opinions cannot cite (`backend/app/application/services/agent_workbench_graph.py:592-638`). Citation objects are projected only from successful same-run tool outputs, and conflicts force refusal (`backend/app/application/services/agent_workbench_graph.py:641-701`).
- The model adapter accepts one strict JSON object and rejects Markdown wrappers, duplicate keys, unknown tools/call IDs, and mixed tool/content output; streaming remains response-bounded (`backend/app/infrastructure/ai/agent_workbench.py:238-400`).

The checked local capture is particularly useful in interviews because it proves a browser-to-API-to-state-machine chain instead of a mocked screenshot. The multi-tool case executed `search_evidence -> get_event -> retrieve_brand_context`, produced two citations and eleven trace steps in four model/three tool calls; the other two captures prove copy validation and refusal (`docs/portfolio/agent-workbench.md:74-113`). The capture is deterministic and expressly does not measure live LLM intelligence. The only authorized live Zhipu Workbench attempt failed during browser capture before typed verification, and the repository correctly makes no provider/model/status/latency claim for it (`docs/portfolio/agent-workbench.md:115-135`).

The canonical Workbench report passes 42/42 cases with 100% tool-set selection, argument validity, citation precision/coverage, terminal-state accuracy and refusal accuracy, plus 0% unsupported external claims. Mean model steps are 2.40 and P95 is four. These are contract/policy fixture metrics, not provider quality (`backend/evals/agent_workbench/canonical-report.json`; `docs/portfolio/agent-workbench.md:137-143`).

### 2. MCP is backed by the same registry, not a second implementation

The MCP server delegates list/call behavior to the Workbench registry (`backend/app/agent_mcp_main.py:29-80`) and rejects production/live mode because it is intentionally local stdio (`backend/app/agent_mcp_main.py:83-98`). It derives exact schemas through the official MCP SDK and advertises read-only/idempotent annotations (`backend/app/agent_mcp_main.py:101-150`). Contract tests use the official MCP v2 client in memory and over a subprocess stdio connection, and verify unknown `shell`-style tools fail safely (`backend/tests/contract/test_agent_mcp.py:22-114`, `backend/tests/contract/test_agent_mcp.py:143-154`).

This is resume-worthy because the design prevents schema drift across in-process Agent calls, MCP discovery, and MCP execution. The claim should remain “implemented and contract-tested a local read-only MCP server,” not “operated a public MCP platform.”

### 3. Durable execution governance is the deepest platform-level highlight

The governance layer is more distinctive than a generic LangGraph graph:

- The domain defines orchestrator/planner/worker/reviewer roles, closed event kinds and capabilities, a default delegation depth of one, hard maximum of two, and a 70% delegation utilization threshold (`backend/app/domain/execution_governance.py:9-99`).
- `BudgetLimits` cover multiple resource dimensions rather than only token count, and child allocations are bounded by parent/depth policy (`backend/app/domain/execution_governance.py:108-180`).
- `authorize_capability` applies role, task, artifact, and argument scopes. Orchestrator/planner cannot perform business writes; Reviewer cannot plan or business-write (`backend/app/domain/execution_governance.py:385-462`).
- The gateway durably reserves maximum budget **before** invoking a capability, then reconciles timeout, cancellation, exception, oversize result, and budget-overage paths (`backend/app/application/services/execution_governance.py:205-455`). Unknown provider usage remains unknown rather than being fabricated as zero.
- PostgreSQL persists frozen run limits/fingerprints, allocation used/reserved counters, a safe causal event graph, artifact SHA/size/status, and exact-once reservation/reconciliation ledger entries (`backend/app/infrastructure/db/models.py:6023-6337`).
- Integration tests exercise concurrent child reservations without overselling, root-run replay, cross-run artifact/trace tampering, every budget dimension, hard depth, and non-refundable child count (`backend/tests/integration/test_execution_governance.py:94-568`).

The strongest interview answer is the invariant: **authority and worst-case resource consumption are reserved before a provider or business capability runs; all terminal paths reconcile against a durable ledger**. This demonstrates concurrency control, least privilege, replay safety, and observability in one design.

### 4. Governed Writer–Reviewer: implemented, bounded, and code-owned

The stale audit recommended adding a Reviewer. That recommendation is now materially implemented, but as a deliberately constrained system:

- Reviewer output is confined to six dimensions, a closed issue-code/severity taxonomy, hard-gate mapping, and allowlisted repair operations (`backend/app/domain/official_account_reviewer.py:43-180`).
- Requests bind the exact article SHA, reference identities, versions, and fingerprint (`backend/app/domain/official_account_reviewer.py:235-296`). Verdict identity, locations, severity and hard gates are revalidated; the final decision is computed by code, not trusted from model prose (`backend/app/domain/official_account_reviewer.py:299-361`).
- Repair directives are projected from code-owned mappings. Critical issues are non-repairable and no free-form model instruction is executed (`backend/app/domain/official_account_reviewer.py:543-604`).
- The Zhipu adapter requests schema-guided strict JSON, verifies all returned identity fields, and records safe usage/latency; duplicate JSON keys are rejected (`backend/app/infrastructure/ai/official_account_reviewer.py:26-103`).
- Initial Writer, Reviewer R1, repair Writer, and Reviewer R2 have separate identities and least-privilege capabilities. Reviewer can check only the bound artifact; Writer owns business writes; repair authority exists only in enforce mode (`backend/app/infrastructure/official_account_reviewer_governance.py:90-183`).
- Observe mode records the Reviewer but never blocks legacy behavior. Enforce mode requires an accepted R1 verdict before activation, permits exactly one code-directed repair, re-runs deterministic auditing, and requires an accepted R2 verdict. Unknown/unavailable/denied or exhausted repair becomes manual review, not an infinite reflection loop (`backend/app/application/services/official_account_local.py:1825-2104`).
- The configuration defaults to `off`; observe/enforce require the local worker and exact contract bundle. Enforce additionally requires Zhipu, an explicit acknowledgement, and a frozen calibration-report SHA (`backend/app/core/config.py:295-358`, `backend/app/core/config.py:804-854`).

The provider-free canonical report passes 48/48 deterministic policy cases: critical precision/recall/F1 100%, false accepts 0/48, false rejects 0/48, location and repairability accuracy 100%, with 7/48 manual-review and 12/48 unavailable outcomes retained. This validates code-owned orchestration and failure policy, not live Reviewer intelligence (`backend/evals/official_account_reviewer/canonical-report.json`).

The integration evidence is unusually broad: off mode makes zero calls/rows; observe is nonblocking; provider failure is `result_unknown`; concurrent and restart paths join/recover without duplicate provider calls; tamper and artifact/version scope fail before provider invocation (`backend/tests/integration/test_official_account_reviewer_observe.py:243-1025`). Enforce tests cover the one-repair/R2 terminal path, provider exception, crash recovery, manual/unavailable, and a budget fence that denies repair before provider execution (`backend/tests/integration/test_official_account_reviewer_enforce.py:498-1092`).

This should be called a **fixed governed Worker–Reviewer workflow** or **bounded multi-agent review protocol**. It should not be described as a dynamic swarm, debate system, self-improving reflection loop, or production-proven quality uplift.

### 5. Reviewer live A/B is infrastructure-complete but evidence-incomplete

The repository contains a production-shaped 12-case corpus with eight repairable and four clean-control cases, projected into real article/reviewer contracts and bound to historical version bundles (`backend/evals/official_account_reviewer_live_ab/production_dataset.py:70-139`, `backend/evals/official_account_reviewer_live_ab/production_dataset.py:176-222`). It also contains a model-panel proxy report schema that explicitly fixes `human_labels=0`, `enforce_eligible=false`, `production_mode_changed=false`, up to 36 Reviewer calls and 72 panel calls, and refuses uplift claims unless bootstrap/coverage conditions hold (`backend/evals/official_account_reviewer_live_ab/model_panel_proxy.py:129-225`). The legacy provider-free CLI still fails live closed with `EXECUTOR_NOT_INSTALLED` and `live_model_calls=0`; the application composition root is required for real execution (`backend/evals/official_account_reviewer_live_ab/runner.py:247-288`).

No completed live Reviewer attempts/report were found. The current active live-A/B task still has preflight, first live run, evidence hashes and conclusions unchecked, and its output folder contains only setup artifacts rather than terminal attempts/report. Earlier evidence explicitly recorded `live_model_calls=0`. Therefore:

- do not quote Reviewer quality, latency, tokens, cost, preference, or repair uplift;
- do not claim human agreement—there are zero human labels;
- do not imply the previous heterogeneous three-model panel plan was run. The user later constrained visual model evaluation to direct Zhipu only, and no other-model result is current evidence;
- keep Reviewer `enforce` off until a newly authorized, policy-compatible calibration design has been completed.

The implementation is valuable; the experiment result does not yet exist.

### 6. RAG: good engineering, but fixture and live claims must be separated

The enhanced reader executes the original retrieval path concurrently with a planner, permits one rewrite, combines rankings with weighted RRF, reranks at most ten candidates, and bounds final output (`backend/app/application/services/agent_retrieval.py:45-197`). Planner, rewrite and reranker use timeouts and deterministic fallback; cancellation remains observable rather than swallowed (`backend/app/application/services/agent_retrieval.py:210-313`). Brand embeddings use a bounded process-local TTL/LRU/single-flight cache keyed by namespace, chunk, input and text hash; failed embeddings are not cached (`backend/app/application/services/agent_retrieval.py:316-402`). The Zhipu planner is strict one-shot JSON with semantic-drift checks, while the reranker validates finite scores and unique indices (`backend/app/infrastructure/ai/agent_retrieval.py:73-312`).

The public brand fixture improvement from v2 to v3 is real **within the deterministic selector benchmark**: Recall@5 80% -> 95%, nDCG@5 84.37% -> 92.86%, parent diversity 85% -> 100%, while MRR@5 remains 100% and brand-as-fact violations remain zero (`backend/evals/brand_retrieval/canonical-report.json`). But the benchmark explicitly uses sanitized, hand-authored candidate observations and measures RRF/selection-policy regression only; it excludes live embeddings, private corpus quality, generation quality, and production effectiveness (`backend/evals/brand_retrieval/README.md:3-16`).

The latest paired live retrieval run completed only 2/72 planned matrix attempts. The mandatory first canary failed, so every uplift metric is N/A and the circuit breaker stopped the run. The two arms each had 100% task/tool/citation figures on their single completed attempt, with roughly 15.4 s vs 19.1 s P95 observations, but this is not a valid paired uplift result (`output/evals/agent-retrieval-ab/agent-ab-20260903-v3-compat-canary/paired-report.md:7-71`). Its value is experimental integrity—fail-closed authorization, denominators, provider accounting, and a canary that actually stops—not model improvement.

Also avoid collapsing different retrieval implementations into one slogan: Workbench evidence search is governed PostgreSQL full-text search (`websearch_to_tsquery`) with transaction read-only and a statement timeout (`backend/app/infrastructure/db/agent_workbench.py:60-178`, `backend/app/infrastructure/db/agent_workbench.py:299-306`, `backend/app/infrastructure/db/agent_workbench.py:451-453`); brand knowledge uses pgvector/hybrid selection elsewhere. The Workbench evidence tool is not BM25 or vector search.

### 7. GLM-5V image calibration is the strongest current live-model result

The image panel was actually executed against **only direct Zhipu `glm-5v-turbo`**. No Claude, Gemini, GPT, other GLM identity, gateway, human label, or external label participated (`backend/evals/image_quality_panel/README.md:1-6`). The dataset has 48 derived pairs from six independent source families: 36 deterministic objective recipe anchors and 12 unlabeled subjective cases, split into family-disjoint 24-case calibration and 24-case holdout partitions (`backend/evals/image_quality_panel/README.md:8-16`).

The plan controls position and stability: all 48 cases are shown in AB and BA order, and all 12 subjective cases receive an additional AB/BA repeat, for exactly 120 one-shot calls. The first call probes the four-image batch-diversity capability; there is no retry or fallback. Every image reference is HMAC-blinded, and strict JSON/schema/issue invariants fail closed without retaining raw response text (`backend/evals/image_quality_panel/README.md:18-28`). Objective metrics and subjective self-consistency are reported separately, with unknown usage/cost preserved (`backend/evals/image_quality_panel/README.md:41-47`).

The immutable evidence records:

- 120 observed attempts: 119 completed, one terminal provider rejection, no retry or replacement;
- known usage of 404,154 input and 9,848 output tokens; one failed call remains unknown;
- known native cost CNY 3.085126; unknown failed-call cost is not projected as zero;
- latency P50 5,392.5 ms and P95 21,204.85 ms;
- overall objective pair accuracy 29/36 = 80.56%; eligible order-consistent cases 31/36;
- arm-decision macro-F1 89.54%; critical false-accept rate 2/36 = 5.56%; critical-flag false-negative rate 7/36 = 19.44%;
- family-disjoint holdout accuracy 15/18 = 83.33%, macro-F1 91.40%, critical false-accept rate 11.11%;
- per-dimension pair accuracy: semantic 100%, IP identity 100%, OCR/visible text **0%**, aesthetics 100%, publication layout 83.33%, batch diversity 100%; OCR critical false-accept rate 33.33% and critical-flag false-negative rate 100%;
- subjective self-consistency only: position stability 12/12, repeat consistency 11/12, holdout repeat consistency 5/6.

These figures and artifact hashes are recorded in `.trellis/tasks/archive/2026-09/09-02-image-vlm-human-calibration/research/glm-5v-turbo-live-evidence-2026-09-03.md:3-85`; the machine report is `output/evals/image-panel-glm5v3-live-20260903-v1/image-single-model-report.json`.

The high-value result is not “GLM-5V scored 80.56%.” It is that a blinded, position-controlled, repeated, holdout-aware, cost-bounded live experiment found the model strong on five tested dimensions but unsafe as a standalone OCR/text-integrity gate. The report correctly remains `non_activating=true`, and production mode/model selection did not change. Retaining deterministic OCR and hard validation alongside the VLM is the defensible engineering decision.

### 8. Strongest internship-grade highlights, ranked

#### A. Governed Agent execution and bounded Writer–Reviewer

Why it is high-value: many internship projects stop at prompts and graphs. This repository connects role-based authority, artifact scope, pre-call budget reservation, exact-once reconciliation, causal tracing, crash recovery, code-owned verdicts and a one-repair terminal policy.

Truthful resume bullet:

> 设计受治理的 Writer–Reviewer Agent 流程：以角色/任务/Artifact 最小权限和多维预算预留约束调用，Reviewer 仅输出闭集 issue，最终 verdict 与 repair 指令由代码投影；支持 observe/enforce、最多一次修复、崩溃恢复与不可变版本链路，48/48 条离线策略契约通过。

Required qualifier: “48/48” is provider-free policy/contract validation, not live Reviewer accuracy or production uplift.

#### B. GLM-5V live evaluation and negative-result engineering

Why it is high-value: it demonstrates experiment design, multimodal transport, blinding, order-bias control, holdout separation, failure accounting, cost/latency measurement and a safety decision based on a negative dimension result.

Truthful resume bullet:

> 搭建智谱 GLM-5V-Turbo 单模型图像审校评测：在 6 个独立素材族上构造 48 组六维 AB/BA 样本与固定重测，执行 120 次 hash-bound one-shot 调用；holdout 客观配对准确率 83.33%，并定位 OCR 维度 0/6、关键缺陷误放 33.33%，据此保留确定性 OCR 硬门而未自动上线 VLM 决策。

Required qualifier: only six independent source families, no human/external labels, one provider rejection, and non-activating.

#### C. Typed Tool Registry + MCP + citation-safe bounded loop

Why it is high-value: it is easily demonstrable and connects application engineering with protocol interoperability and safety.

Truthful resume bullet:

> 基于 LangGraph 实现有界 Agent 工具循环，将 4 个只读业务能力收敛为统一 Typed Tool Registry，并由同一 Schema 派生 MCP v2 stdio 服务；加入超时/调用/字节预算、同 run 引用绑定、冲突拒答和脱敏 trace，42/42 条确定性工具与引用契约通过，并留存真实本地 UI→API→Agent 三工具调用证据。

Required qualifier: deterministic Agent model and local MCP; the live Workbench attempt did not produce verified evidence.

#### D. RAG evaluation discipline

Why it is useful: weighted RRF, parent diversity, rerank/fallback and single-flight caching are solid implementation details, while the failed canary shows evidence discipline.

Truthful resume wording should say “sanitized offline selector benchmark Recall@5 95%, nDCG@5 92.86%” and explicitly separate this from live embedding/production quality. Do not claim that query rewrite/rerank improved retrieval: the latest live A/B did not clear its first canary.

### 9. Interview-risk matrix

| Risky claim | Why it is unsafe | Defensible formulation |
|---|---|---|
| “We built a multi-agent swarm.” | The implemented system has fixed Writer/Reviewer identities, closed capabilities, depth bounds and one repair; it is not dynamic delegation or swarm behavior. | “A governed, fixed-role Worker–Reviewer protocol with least privilege and bounded repair.” |
| “Reviewer improved article quality.” | No completed live Reviewer A/B, human labels, preference report, or production-enforce evidence exists. | “Implemented the rollout-safe Reviewer architecture and 48-case policy suite; live efficacy calibration remains pending and enforce defaults off.” |
| “GLM-5V image accuracy is 80.56%.” | 36 objective derived pairs from only six source families; one unresolved/provider failure; does not represent broad image quality. | “80.56% objective pair accuracy on the frozen six-family derived benchmark, 83.33% holdout, with a decisive OCR failure.” |
| “The subjective image score agrees with humans.” | Human/external label counts are zero. Position/repeat results measure only model self-consistency. | “12/12 AB/BA position stability and 11/12 repeat stability; no human-agreement claim.” |
| “RAG achieved 95% production recall.” | The brand benchmark is sanitized and hand-authored; it measures deterministic RRF/selection policy, not live embeddings or private corpus behavior. | “95% Recall@5 on a 36-case sanitized selection-policy regression suite.” |
| “Rewrite + rerank improved retrieval.” | Latest live paired run stopped after 2/72 attempts at a failed canary; uplift metrics are N/A. | “Built a guarded enhancement path and live paired harness; canary failed, so no uplift was claimed.” |
| “The Workbench uses vector/BM25 evidence search.” | Its evidence tool uses PostgreSQL FTS; brand RAG is the pgvector path. | Name each retrieval path precisely. |
| “Workbench was validated live with Zhipu.” | The authorized attempt failed before typed evidence verification. | “Deterministic loopback chain is verified; live Workbench evidence is not available.” |
| “Production AgentOps is complete.” | Safe per-run traces and durable governance events exist, but no checked cross-run metrics dashboard, alerting/SLO evidence, or production incident corpus was found. | “Implemented trace/event primitives and immutable ledgers; aggregate operational dashboarding remains a next step.” |

### 10. Comparison with the stale audit

The existing `.trellis/tasks/08-18-agent-internship-project-improvement-audit/research/project-improvement-audit.md` is directionally useful but stale in several important ways:

| Earlier gap/recommendation | Current repository state | Delta |
|---|---|---|
| Public Agent portfolio and static proof were missing | Public README, architecture explanation, deterministic screenshots, real loopback capture, manifests, resume TeX/PDF, and reproducible checks now exist | Substantially addressed |
| Add a Reviewer / multi-agent story | Governed Writer–Reviewer is integrated with role/capability budgets, observe/enforce modes, exact lineage, one repair and recovery | Implemented architecturally; live efficacy still missing |
| Add live evaluation | GLM-5V image panel has a real 120-attempt direct-Zhipu run with quality/latency/usage/cost; retrieval live A/B stopped at canary; Reviewer live A/B has no terminal report | Partially addressed; image only is strong |
| Add AgentOps/trace | Workbench safe trace and durable execution-governance trace/budget/artifact ledgers exist | Core primitives implemented; aggregate operational UI/SLO evidence absent |
| Add MCP proof | Same-registry MCP v2 implementation and official-client/in-memory/subprocess contract tests exist | Implemented; recruiter-facing real-client video/demo could still improve presentation |
| Resume/demo not ready | Public resume and demo documentation exist | Addressed, but the resume is now stale relative to Reviewer and GLM-5V work |
| Consider memory, open-ended multi-agent, A2A or training | No compelling evidence these are needed for this business workflow | Correctly still out of scope; adding them would dilute the governance story |

### 11. Highest-return remaining improvements

1. **Refresh the public resume and top-level README with the new evidence.** Replace the old image bullet's provider-free 48/48 headline with the GLM-5V live experiment and OCR safety finding. Add the governed Writer–Reviewer as the primary Agent-platform bullet. Preserve the explicit fixture/live qualifiers. The current public resume still highlights provider-free image metrics and omits both the new Reviewer and live GLM-5V evidence (`docs/portfolio/resume/resume-public.tex:31-40`).
2. **Complete a newly authorized Zhipu-only Reviewer live evaluation, or explicitly close it as unavailable.** The current heterogeneous model-panel proxy plan is not completed and cannot become Human Gold. With no human annotation, use deterministic defect anchors and clean controls for objective calibration; label subjective quality as single-model/proxy evidence, keep `enforce_eligible=false`, and never backfill missing calls. A clean negative or inconclusive report is preferable to an implied uplift.
3. **Expose governance evidence as a recruiter-facing run view.** A small checked dashboard/report could show allocation reservation/reconciliation, role/capability decisions, artifact lineage, causal trace and recovery for one Reviewer case. This would make the deepest backend work visible without adding a new architecture.
4. **Add repository trust basics.** No `.github/workflows` files and no license file were found. A minimal public CI quality gate and explicit license would close two remaining stale-audit risks. Do not imply CI is active until the workflow is actually checked and passing.
5. **Keep the retrieval result honest.** Either repair the experimental canary/design and complete the paired matrix under a new authorization, or present the current result as a failure-detection case study. Do not spend effort adding memory, A2A, an autonomous swarm, or model training before the current live evidence gaps are closed.

### Files found

- `.trellis/tasks/08-18-agent-internship-project-improvement-audit/research/project-improvement-audit.md` — earlier audit whose public-proof, Reviewer, trace and live-eval recommendations were compared with current code.
- `README.md` — current public positioning, Workbench commands, evaluation caveats, portfolio links and safety boundary.
- `docs/portfolio/agent-workbench.md` — architecture, checked real loopback capture, deterministic metrics and failed live-attempt truth boundary.
- `docs/portfolio/runs/agent-workbench/f5cd8de936a5-20260818T063838Z/` — checked API/UI run artifacts, screenshots, semantic probes and hashes.
- `docs/portfolio/resume/resume-public.tex` — current public resume; useful but stale relative to Reviewer and GLM-5V results.
- `backend/app/domain/agent_workbench.py` — Workbench state, limits, claims, citations and safe trace contracts.
- `backend/app/application/services/agent_tools.py` — canonical typed read-only tool registry and invocation boundary.
- `backend/app/application/services/agent_workbench_graph.py` — bounded LangGraph loop, tool execution and citation projection.
- `backend/app/infrastructure/ai/agent_workbench.py` — strict OpenAI-compatible model adapter.
- `backend/app/agent_mcp_main.py` — same-registry MCP v2 stdio server.
- `backend/app/infrastructure/db/agent_workbench.py` — governed PostgreSQL readers and read-only transaction fence.
- `backend/evals/agent_workbench/canonical-report.json` — 42-case deterministic Workbench policy report.
- `backend/app/domain/execution_governance.py` — roles, capabilities, scopes, budgets and delegation policy.
- `backend/app/application/services/execution_governance.py` — durable reservation/call/reconciliation gateway.
- `backend/app/infrastructure/db/models.py` — governed run/allocation/event/artifact/ledger tables.
- `backend/app/domain/official_account_reviewer.py` — Reviewer request, issue, verdict and repair contracts.
- `backend/app/infrastructure/ai/official_account_reviewer.py` — strict Zhipu Reviewer adapter.
- `backend/app/infrastructure/official_account_reviewer_governance.py` — separate agent identities, capabilities and budgets.
- `backend/app/application/services/official_account_local.py` — observe/enforce Writer–Reviewer orchestration and recovery.
- `backend/evals/official_account_reviewer/canonical-report.json` — 48-case provider-free Reviewer contract report.
- `backend/evals/official_account_reviewer_live_ab/` — production-shaped corpus and incomplete live/model-proxy harness.
- `output/evals/reviewer-v2-provider-free-smoke-20260903/` — setup-only Reviewer evaluation output; no attempts/report found.
- `backend/app/application/services/agent_retrieval.py` — rewrite/RRF/rerank/fallback/cache implementation.
- `backend/app/infrastructure/ai/agent_retrieval.py` — strict Zhipu planner and reranker adapters.
- `backend/evals/brand_retrieval/canonical-report.json` — deterministic brand selector metrics.
- `output/evals/agent-retrieval-ab/agent-ab-20260903-v3-compat-canary/paired-report.md` — failed-canary live retrieval evidence with no uplift conclusion.
- `backend/evals/model_panel/` — provider-neutral authorization, budget, one-shot transport, strict parsing, consensus, journal and evidence-hash primitives.
- `backend/evals/image_quality_panel/` — direct GLM-5V image calibration plan, transport composition, metrics and evidence contracts.
- `output/evals/image-panel-glm5v3-live-20260903-v1/image-single-model-report.json` — machine-readable live GLM-5V report.
- `.trellis/tasks/archive/2026-09/09-02-image-vlm-human-calibration/research/glm-5v-turbo-live-evidence-2026-09-03.md` — checked human-readable GLM-5V evidence summary and hashes.
- `Makefile` — provider-free/live preflights, evaluation gates, capture checks, lint/type/test/build entrypoints.
- `backend/pyproject.toml` — pinned Python/LangGraph/MCP dependencies and strict Ruff/mypy/pytest configuration.

### External references and versions

- No external browsing, credential access, provider call or model call was performed for this audit.
- Repository-pinned versions inspected: Python 3.11+, LangGraph 1.2.10, LangGraph PostgreSQL checkpoint 3.1.0, MCP 2.0, FastAPI and pgvector (`backend/pyproject.toml:9-47`).
- Direct live evidence already present in the repository identifies Zhipu `glm-5v-turbo` and adapter `image-panel-zhipu-glm-5v-turbo-one-shot-v3`; this audit did not re-contact the provider.

### Related specs

- `.trellis/spec/backend/agent-workbench.md` — Workbench loop, tools, citations, trace and local safety contract.
- `.trellis/spec/frontend/agent-workbench.md` — local development UI and loopback boundary.
- `.trellis/spec/backend/execution-governance.md` — roles, capabilities, budget accounting, events and artifacts.
- `.trellis/spec/backend/official-account-reviewer.md` — Reviewer policy, rollout modes, recovery and calibration boundary.
- `.trellis/spec/backend/brand-knowledge-rag.md` — parent/child chunks, hybrid selection and fixture-metric truth boundary.
- `.trellis/spec/backend/image-quality-evaluation.md` — image validation/audit gates and evaluation semantics.
- `.trellis/spec/backend/topic-selection.md` — governed evidence and deterministic selection boundary.

## Caveats / Not Found

- No successful live Workbench run with typed response evidence was found; the checked live attempt failed before verification.
- No completed live Reviewer A/B attempts, proxy report, human labels, quality uplift, cost or latency evidence was found. Existing provider-free Reviewer metrics are contract/policy results only.
- No human or external labels exist for the GLM-5V subjective cases. Stability is self-consistency, not accuracy or human agreement.
- The GLM-5V dataset has 48 derived pairs but only six independent source families; broad population generalization and narrow statistical confidence are not supported.
- The enhanced retrieval live A/B completed only 2/72 planned cells and failed its canary; no uplift metric is available.
- No persistent Workbench memory/run-history feature was found. Durable governance history belongs to the production execution subsystem, not the local Workbench.
- No GitHub Actions workflow or license file was found. No hosted public deployment was verified.
- Current working-tree test status was not established: this was a read-only source/evidence audit and no test suite was run. Historical/canonical reports were inspected as repository artifacts, not regenerated.
- The resume's Plan-and-Execute/Replan and memory claims appear to belong to the separate 12306 project section; they should not be attributed to this repository without separate evidence.
