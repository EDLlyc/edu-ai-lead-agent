# Data Governance and Event Organization

## Goal

Transform the provenance-bearing AI evidence candidates produced by the completed acquisition
capability into a durable, queryable, and auditable event pool. The capability normalizes stored
article text, preserves every source occurrence, identifies exact and near duplicates, generates
structured factual analysis, and groups multi-source reports about the same event without selecting
a daily topic or generating brand copy.

## Product Value

The acquisition layer answers "which relevant authoritative articles were collected?" This
capability answers "which distinct AI-related events do those articles describe, what verified
facts are available, and which sources support each event?" Its output becomes the governed input
for the later topic-eligibility and scoring capability.

## Background and Key Decisions

- The first capability is complete and exposes candidate IDs, cleaned full text, original and
  canonical URLs, publication/fetch times, source identity/tier, immutable snapshot metadata, and
  observations through PostgreSQL and internal APIs.
- Downstream processing reads stored candidate detail and snapshots; it does not normally re-crawl
  the original website.
- Acquisition may reuse one content-bearing candidate when identical content is observed from
  another source. The additional source remains represented by observations and snapshots, so
  governance must model candidate content and source occurrences separately.
- The approved acquisition frontier remains the existing eight sources. This task does not add a
  ninth source or arbitrary URL ingestion.
- The implemented `ai-title-v1` acquisition keyword rule remains unchanged. Runtime keyword
  customization or a future `ai-title-v2` is a separate first-capability enhancement.
- PostgreSQL 16 with pgvector and MinIO are already part of the runtime. This task does not add an
  external vector database.
- LangGraph is approved for model-oriented, checkpointed workflow orchestration, but does not
  replace the existing acquisition scheduler, worker, database leases, or fetch safety boundary.
- The user can provide Zhipu API access. Credentials are supplied through local environment
  configuration or a deployment secret store, never committed to Git or copied into task
  artifacts, logs, prompts, reports, or API responses.
- The user authorizes bounded live Zhipu calls during implementation and evaluation and delegates
  chat/embedding model selection to the implementation team. Selection must optimize factual
  structured output, embedding quality, compatibility, latency, and observable token/cost use
  within this task's scope rather than choosing a model by size alone.
- This capability remains factual and brand-neutral. Company documents, brand philosophy, tone
  rules, examples, and visual guidance are deferred to the later brand-knowledge capability.
- The first factual taxonomy has seven categories: AI education policy, large/generative models,
  robotics and embodied intelligence, AI compute/chips, youth science education, AI
  industry/application, and AI governance/safety.
- One major workflow milestone is budgeted at roughly one working day including implementation,
  integration, and focused validation. The target for the integrated, quality-checked MVP and
  handoff is Tuesday, 2026-08-04, rather than an under-tested Friday delivery.

## Requirements

### R1 — Stored-evidence and occurrence input boundary

- Consume candidate IDs, stored candidate detail, observations, source snapshots, sources, and
  source versions through an application-owned repository.
- Preserve source, candidate, snapshot, observation, parser, relevance-rule, publication, and fetch
  provenance in every derived record.
- Treat the content-bearing candidate and each stable source occurrence as separate governed
  concepts. Source diversity must be derived from observations/snapshots, not
  `candidate.source_id` alone.
- Do not treat the original URL as a browsing tool or silently refresh source content.
- Process fetched text and model output as untrusted data; embedded page instructions have no
  authority over the workflow.

### R2 — Versioned normalization and derivation

- Normalize Unicode, whitespace, boilerplate, timestamps, canonical entities, and
  language-specific text through an explicit normalization version.
- Segment normalized text into bounded, stable passages with IDs, hashes, and offsets back to the
  stored acquisition text.
- Never overwrite an acquisition candidate or immutable snapshot. Persist versioned derived
  artifacts that can be replayed and compared.
- Reprocessing the same candidate with the same input hash and complete processing-version bundle
  must be idempotent.

### R3 — Exact and near-duplicate relations

- Use normalized text hashes, canonical URLs, source item IDs, content revision signals, and other
  deterministic features for exact-duplicate and revision relations.
- Use SimHash and purpose-specific pgvector embeddings for near-duplicate and rewritten-report
  detection.
- Preserve duplicate membership and all source occurrences rather than deleting evidence.
- Similarity thresholds, embedding model and fixed dimension, input construction, normalization,
  and decision rules must be versioned and observable.

### R4 — Structured factual analysis and evidence binding

- Produce schema-validated structured output for each governed candidate: concise factual Chinese
  summary, individual key facts, entities, event/publication times, categories, and keywords.
- Use the approved seven-category versioned taxonomy. Classification is multi-label with an
  optional primary category so ambiguous evidence is not forced into an unsupported single class.
- Every accepted fact and summary statement must reference valid stored passage IDs. The
  application deterministically validates passage existence and evidence binding.
- The model may summarize and classify stored evidence but may not invent facts or use model memory
  as a factual source.
- Invalid, incomplete, excessive, unsupported, or unevidenced output fails a typed validation gate
  and remains retryable or reviewable without corrupting prior results.

### R5 — Incremental event organization

- Group articles describing the same real-world event while keeping topically similar but distinct
  events separate.
- An event has a stable identity and immutable versions containing a representative title,
  structured summary, time range/precision, entities/categories, member-set hash, source diversity,
  and evidence bindings.
- Daily incremental processing compares new candidates with a bounded recent event window; it does
  not rebuild all historical clusters for every run.
- Candidate-event features include purpose-specific vector similarity, SimHash distance, title
  overlap, entity/category compatibility, and event-time distance.
- High-confidence matches attach, low matches create a new event, and the ambiguity band becomes
  `review_required`. Assignment decisions store features, thresholds, model/rule versions, and the
  outcome so a human can explain the result.

### R6 — Durable LangGraph workflow

- Use LangGraph where stateful model-oriented orchestration adds value: stored-evidence loading,
  occurrence synchronization, normalization, exact-dedup branching, structured analysis,
  deterministic validation, embeddings, semantic relations, event assignment, persistence, retry,
  and review transitions.
- Persist workflow run/job/node state, attempts, idempotency keys, model/prompt/schema versions,
  token/latency metadata, and safe error codes.
- Keep PostgreSQL run/job tables as the operational/API source of truth. LangGraph checkpoints are
  internal orchestration state containing IDs, hashes, versions, statuses, and small typed outputs,
  never full source bodies, prompts, provider responses, or credentials.
- A process restart or transient model failure resumes from durable state instead of repeating
  acquisition or creating duplicate derived artifacts.

### R7 — Zhipu model boundary

- Hide factual-analysis and embedding calls behind two application-owned typed ports so normal
  tests use deterministic fakes and later provider/model changes do not rewrite domain logic.
- Configure provider endpoint, API key, chat model, embedding model/fixed dimension, timeouts,
  concurrency, retries, input/output limits, and token/cost budgets through validated settings.
- Verify and pin LangGraph checkpoint/provider dependencies and any required database driver before
  creating the fixed-dimension vector migration.
- Never log API keys, authorization headers, full prompts/source bodies, hidden raw model output, or
  raw provider exceptions.
- Bounded live Zhipu compatibility and quality evaluation is allowed whenever credentials are
  configured. Normal automated tests remain deterministic and do not require live credentials;
  the formal live smoke/acceptance result is reported separately.

### R8 — Durable runtime and automatic trigger

- Add governance run/job/attempt state with database-enforced business keys, claims, leases,
  heartbeats, retries, and safe recovery.
- A separate governance planner reconciles terminal acquisition runs into one governance run per
  acquisition run and pipeline version. It synchronizes all occurrences even if content analysis
  can be reused.
- A separate governance worker executes LangGraph jobs. Zhipu latency or failure must not delay or
  crash acquisition API/scheduler/worker processes.
- API requests enqueue durable work and return `202`; they never run model analysis inline.

### R9 — Queryable event handoff

- Provide internal APIs for governance run/job state, candidate analysis, individual facts,
  passages/evidence bindings, source occurrences, duplicate relations, event lists/details,
  memberships, assignment features, versions, review state, and typed failures.
- The downstream projection must support later topic scoring without another source fetch or
  another summarization call.
- Lists are bounded and cursor-paginated. APIs expose no signed object URLs, full prompts, raw
  provider output, secrets, or arbitrary fetch surface.
- Regenerate and commit OpenAPI and frontend contract types; a product frontend is out of scope.

### R10 — Evaluation, security, observability, and delivery

- Controlled fixtures cover exact duplicates, two sources sharing one candidate, same-event
  paraphrases, similar-but-distinct events, conflicting dates/entities, ambiguous review,
  prompt-injection text, invalid model output, provider failures, checkpoint restart, concurrency,
  and idempotent replay.
- Evaluate extraction and event organization against a labeled dataset combining controlled
  fixtures with accumulated live candidates; the initial six accepted live articles alone are not
  sufficient for clustering evaluation.
- Expose per-stage success/failure, latency, retries, token usage, duplicate/cluster/review counts,
  and complete version metadata without leaking source bodies, credentials, or personal data.
- Implement milestones in order with focused checks, then run the complete backend/frontend/doctor
  gate once after the final production edit.
- Tuesday, 2026-08-04 is the target for the integrated, quality-checked MVP and handoff. Expanding
  into scoring, brand knowledge, generation, product UI, keyword customization, or new sources
  requires a schedule re-baseline instead of weakening final validation.

## Acceptance Criteria

- [ ] A candidate and all of its source occurrences are processed from stored data without an
      outbound request to the original URL.
- [ ] Repeating the same request with identical inputs and versions produces no duplicate analysis,
      passage, embedding, relation, membership, invocation artifact, or workflow record.
- [ ] Exact copies and controlled paraphrases retain all provenance while resolving to the expected
      duplicate relation and event.
- [ ] When identical content is observed from two approved sources, the event exposes two source
      occurrences even if acquisition reused one content-bearing candidate row.
- [ ] Controlled articles about similar technology but different events remain separate.
- [ ] Every accepted structured factual statement returned through the API has a valid stored
      passage plus candidate/snapshot/source-occurrence provenance.
- [ ] Invalid, excessive, or unsupported model output is rejected by deterministic
      schema/taxonomy/evidence validation and records a typed, retry-safe outcome.
- [ ] A transient Zhipu or checkpoint failure resumes from durable workflow state without re-running
      acquisition or duplicating completed derivations.
- [ ] Model, prompt, schema, taxonomy, normalization, embedding, similarity, assignment, and event
      versions are visible in persisted records and API projections.
- [ ] Labeled fixtures produce documented extraction and event-organization results, and an opt-in
      live Zhipu run demonstrates the bounded workflow on accumulated real candidates.
- [ ] PostgreSQL/pgvector migrations, backend checks, integration tests, OpenAPI/frontend contract
      checks, Compose/Doctor, diff checks, and credential scanning pass.
- [ ] No topic score, Top-1 selection, brand RAG, copy/image generation, product page, arbitrary
      browsing, automatic publishing, acquisition keyword change, or ninth source is introduced.

## External Input Needed Before Live Acceptance

- Zhipu API base URL and API key, configured in local `.env` or the deployment secret store.
- Allowed chat and embedding model identifiers. The implementation selects and verifies the fixed
  embedding dimension before the migration and records only safe model/version metadata.

No company or brand document is needed for this capability.

## Out of Scope

- Topic eligibility vetoes, weighted scoring, seven-day repeat policy, Top-1 locking, and
  `no_topic`; these belong to the third capability.
- Company/brand document ingestion, brand embeddings/retrieval, tone/visual rules, or parent-facing
  messaging; these belong to later capabilities.
- Claim composition for copy, brand/risk audit, image prompts, image generation, material-package
  delivery, and product frontend pages.
- Adding acquisition sources, changing/customizing the existing title-relevance rule, or refreshing
  websites from LangGraph nodes.
- Production server provisioning, public authentication, external monitoring, and organization
  secret-manager provisioning.
