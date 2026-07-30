# Complete Content Production MVP

## Goal

Complete the remaining four capabilities as one internally usable MVP: select at most one
evidence-backed AI/science-education topic per day, retrieve versioned company brand knowledge,
generate and audit a parent-facing WeChat Moments draft, create one approved image, and deliver an
internal review/copy/download material package without automated social publishing.

## Product Value

The first two capabilities already provide authoritative stored evidence and an auditable event
pool. This program turns that event pool into a daily material package that business staff can
understand, verify, review, copy, and download. Every external fact remains traceable to stored
evidence; brand knowledge changes expression but never becomes factual proof.

## Confirmed Background

- Authoritative acquisition and factual governance/event organization are complete and archived.
- PostgreSQL 16, pgvector, MinIO, LangGraph, Zhipu chat/embedding adapters, durable jobs, internal
  APIs, Compose, and Doctor are available foundations.
- The technical report defines six capability steps; this program owns steps three through six.
- The user requires all remaining functions to work in the MVP. Brand ingestion/RAG, copy
  generation, audit/repair, and image generation are not interface-only placeholders.
- The user approved a functional-first delivery mode on 2026-07-30: complete and run the end-to-end
  business path first, keep explicit upgrade seams, then perform deeper production hardening and
  optimization as follow-up work.
- The product remains internal and human-in-the-loop. It must not store social credentials or
  publish automatically.
- Development should favor visible feature progress, focused checks during each child task, and one
  full integration gate after the last production edit rather than repeatedly running the entire
  suite.

## Program Structure

This parent program will be decomposed into four independently verifiable child tasks:

1. Daily topic eligibility, explainable scoring, seven-day repetition control, Top 1 locking, and
   `no_topic`.
2. Brand document upload, parsing, versioned chunking/metadata, embedding, and separated hybrid
   brand RAG.
3. Evidence-bound Moments draft generation, deterministic validation, brand/risk audit, and one
   bounded automatic repair.
4. Image generation, object-storage persistence, material-package API, and accessible internal
   review/copy/download UI.

The parent owns shared scope, end-to-end acceptance, sequencing, and final integration. Each child
owns its own detailed PRD/design/implementation plan and must be accepted before the next child
depends on its contract.

## Requirements

### R1 — Daily topic selection

- Evaluate governed events, not raw articles and not newly browsed URLs.
- Apply explicit hard vetoes before numeric scoring, including unresolved evidence, privacy/legal/
  safety uncertainty, unsuitable negative incidents, prohibited marketing risk, and a materially
  repeated event within seven days.
- Use a versioned, explainable scoring configuration for source trust, AI/science-education
  relevance, parent relevance, freshness, communication potential, repetition, controversy, and
  marketing risk.
- Persist every input feature, normalized value, weight, penalty, threshold, veto, tie-break, and
  decision version.
- Lock at most one topic for each `Asia/Shanghai` business date. If none qualifies, persist
  `no_topic` and do not invoke brand retrieval, generation, audit, or image stages.

### R2 — Brand document ingestion and RAG

- Provide an internal upload flow for agreed document formats and bounded file sizes.
- Parse and preserve document/version metadata, source filename, checksum, audience, validity,
  status, and ingestion diagnostics.
- Chunk deterministically, embed with the configured provider, and persist versioned vectors in
  PostgreSQL/pgvector. Do not add an external vector database for the MVP.
- Search factual evidence and brand knowledge through separate typed operations. Brand chunks may
  guide tone, audience value, prohibited expressions, examples, and visual direction but cannot
  satisfy an external-fact evidence binding.
- Support activation/deactivation and safe re-indexing without mutating previous versions.

### R3 — Evidence-bound Moments draft

- Generate a structured Chinese result containing Moments copy, parent takeaway, interaction
  suggestion, human-readable source note, image prompt, and typed claims.
- Every external-fact claim must bind to eligible stored event evidence. Brand statements bind to
  retrieved brand chunks where relevant; opinions are explicitly typed.
- The prompt contains clearly delimited factual and brand sections and treats all retrieved text as
  untrusted data.
- Persist only safe prompt/model/version/fingerprint/token/latency metadata; do not expose full
  prompts, hidden reasoning, raw responses, credentials, or full source/brand bodies in logs.

### R4 — Validation, brand/risk audit, and repair

- Run deterministic schema, length, evidence, source, date, banned-expression, privacy, image, and
  no-publish checks before the model audit.
- The model audit returns a typed verdict and issue list covering unsupported implications,
  exaggeration, anxiety-inducing language, parent usefulness, brand fit, and image risk. It is not a
  factual source and cannot override hard failures.
- Allow at most one automatic repair in the initial MVP. Persist every attempt and issue. If the
  repaired draft still fails, keep the artifacts and produce a visible reviewable failure.

### R5 — Image generation

- Only an accepted draft/image prompt may call the configured image provider.
- Generate one image per accepted MVP material package, store it in MinIO/S3-compatible storage,
  and persist request fingerprint, provider/model/prompt version, dimensions, attempt, status, safe
  provider ID, and object identity.
- Retry only typed transient failures without creating duplicate image artifacts.
- Prevent real minor identity, unsafe content, excessive embedded text, infringement-prone marks,
  and any provider credential/output leakage.

### R6 — Material package and internal UI

- Assemble the selected topic, date, copy, parent takeaway, interaction, image, source links,
  machine-readable evidence/brand bindings, and validation/audit status into one versioned package.
- Provide an internal React page for run/package status, topic/scoring explanation, evidence links,
  draft review, issue display, keyboard-accessible copy feedback, and image download.
- The UI and OpenAPI must contain no automatic publish action, social credential field, or
  misleading completed/published status.

### R7 — Durable execution and compatibility

- Preserve acquisition and governance behavior and reuse their event/evidence APIs or repositories.
- Execute scoring, retrieval, generation, audit, repair, image, and package stages through durable,
  idempotent jobs with typed states, bounded retries, leases/heartbeats, and restart recovery.
- Provider calls occur outside database transactions and outside request handlers.
- Feature/provider configuration must fail closed when brand documents or image credentials/models
  are unavailable; earlier capabilities and read-only product views remain healthy.

### R8 — MVP delivery discipline

- Deliver one visible functional slice per working day and connect the complete business path before
  investing in exhaustive failure matrices, performance tuning, or production operations.
- Keep application-owned ports, typed schemas, migrations, version fields, feature flags, and
  provider/repository boundaries so later hardening does not require a rewrite.
- During the fast path, require focused happy-path/critical-negative tests, format/lint/type checks,
  one controlled real-provider example where inputs exist, and one end-to-end integration smoke.
- Do not defer security/evidence basics: secrets stay external, external facts stay evidence-bound,
  brand and factual data stay separated, uploads/providers stay bounded, image generation stays
  idempotent, and no publishing path is introduced.
- Move exhaustive concurrency/restart matrices, large labeled evaluation, retrieval/performance
  tuning, production authentication/monitoring/backups, and broad operational automation to an
  explicit hardening backlog after the business MVP runs.

## Approved Initial MVP Boundary

- One company brand: 赛先生.
- One primary audience: Chinese parents.
- One selected topic or `no_topic` per business date.
- One structured Moments draft per selected topic.
- At most one automatic repair after audit failure.
- One generated image per accepted package.
- One internal reviewer workflow; no multi-role approval chain.
- Manual copy/download/distribution only.

The user confirmed this boundary on 2026-07-30. Expanding any of these dimensions requires a new
scope and schedule review rather than weakening the current acceptance criteria.

## External Inputs Needed

These inputs do not all block child-task planning, but they are required before the related live
acceptance:

- Current company brand documents: positioning, values, parent communication principles, approved
  examples, prohibited expressions, safety/compliance rules, and visual guidance.
- Logo/brand assets and any rules about whether or where the logo may appear in generated images.
- Desired Moments copy length or representative approved posts if the documents do not define it.
- Zhipu or company-platform image API/model availability and credentials, supplied only through a
  local secret/deployment store.
- The server/private-network access expectation for the internal review page before deployment.

## Delivery Estimate

Assuming the initial MVP boundary is approved and required external inputs arrive before their live
acceptance:

- Topic selection preview and APIs: approximately 1 working day.
- Functional brand upload, parsing, indexing, and RAG: approximately 1 working day.
- Functional draft generation, critical validation, audit, and one repair: approximately 1 working
  day.
- One-image generation and the simple internal package UI: approximately 1 working day.
- Integration, corrections, demonstration, and handoff: approximately 0.5--1 working day.

Expected functional MVP: 4--5 working days, with a first partial end-to-end demonstration targeted
after approximately 2--3 working days. This estimate assumes representative brand documents arrive
by the brand-RAG day and the configured account has a compatible image endpoint.

Deeper production hardening and optimization is a separate follow-up estimate of approximately
2--4 working days after the user has reviewed the functioning product and identified the highest-
value reliability/performance gaps.

## Acceptance Criteria

- [ ] One business date produces at most one locked topic or a durable `no_topic` decision with an
      explainable reason.
- [ ] Every selected topic exposes score components, vetoes, threshold, tie-break, event version,
      and supporting authoritative sources.
- [ ] An internal user can upload a supported brand document, observe its parsed/versioned chunks,
      activate it, and retrieve relevant brand context without mixing it with factual evidence.
- [ ] A selected topic produces a schema-valid Chinese Moments draft whose external facts all bind
      to stored evidence and whose brand statements use versioned brand context.
- [ ] Deterministic validation and typed model audit run in order; one bounded repair can succeed,
      while repeated failure remains visible and reviewable.
- [ ] An accepted draft produces exactly one idempotent stored image and one versioned material
      package.
- [ ] The internal page shows topic, score explanation, copy, image, source links, evidence/audit
      state, copy controls, and image download with accessible feedback.
- [ ] Repeating the same controlled MVP request does not duplicate the selected topic, accepted
      draft, image, or package; exhaustive crash/concurrency recovery is recorded for hardening.
- [ ] No endpoint, UI control, configuration, or data model enables automatic social publishing or
      stores social credentials.
- [ ] Existing acquisition/governance checks and the integrated backend/frontend/Doctor/Compose/
      security/data gate pass after the final production edit.

## Deferred Hardening and Optimization

- Large labeled scoring evaluation and weight/threshold tuning beyond the initial transparent
  preview configuration.
- Exhaustive multi-worker contention, crash-at-every-stage, lease recovery, and chaos coverage for
  the new content stages.
- Advanced OCR, large/complex document archives, sophisticated reranking, ANN indexing, and search
  performance tuning.
- Multiple draft/image variants, richer editing/approval workflows, analytics, and operator tools.
- Production authentication/authorization, external monitoring, backup/retention automation,
  organization secret-manager provisioning, autoscaling, and public-network deployment.

## Out of Scope

- Multiple brands, tenants, audiences, or organization-level role/permission administration.
- Multi-step legal/manager approval workflows and collaborative editing.
- Exact BM25 or a new external search/vector service without a separate architecture decision.
- Multiple image variants, interactive image editing, video, animation, or design-template studio.
- Social-platform authentication, scheduling, posting, engagement analytics, or automatic
  publication.
- Mobile-native applications or public consumer access.

## Approved Scoring Configuration Process

The user approved the following process on 2026-07-30: implementation proposes `scoring-v1`,
evaluates it against controlled and real governed events, presents selected/rejected/vetoed ranks
and reasons, and obtains product confirmation before activating the configuration as the default.
Numeric values are not chosen by an unexplained model score or embedded permanently in code.
