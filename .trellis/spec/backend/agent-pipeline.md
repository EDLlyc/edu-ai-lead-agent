# Agent Pipeline Contract

## Purpose and status

This guide translates the workflow in [`main.tex`](../../../main.tex) and the generated
[`技术报告-v0.3.pdf`](../../../技术报告-v0.3.pdf) into a testable implementation contract. The first
two capabilities now exist: authoritative-source acquisition, followed by versioned factual
governance and auditable event organization. Topic scoring, brand retrieval, generation, product
UI, and publishing remain prospective and must update this document when implemented.

The term “Agent” does not imply one autonomous prompt. The pipeline is an orchestrated sequence of
typed, observable stages with deterministic gates around model calls.

## Stage model

```text
schedule/enqueue
  -> ingest source snapshots
  -> synchronize source occurrences
  -> normalize, segment, and validate factual analysis
  -> exact/semantic duplicate relations and event organization
  -> eligibility vetoes and versioned scoring
  -> select Top 1 or finish no_topic
  -> retrieve evidence and brand context separately
  -> draft typed claims/copy/image prompt
  -> deterministic validation
  -> LLM brand/risk audit
  -> bounded regeneration when allowed
  -> image generation
  -> material package ready for manual use
```

Each stage consumes immutable or versioned artifact references and returns a typed result. Persist
the stage status before and after work. A worker restart must resume from durable state rather than
reconstructing progress from logs or rerunning the whole workflow.

## Source governance and ingestion

Classify sources before they can support a claim:

- Tier A: official/primary government, education authority, school, university, research body,
  international organization, or first-party company release.
- Tier B: reputable secondary science, technology, or education reporting. Prefer and link the
  primary source when it exists.
- Tier C: social posts and unverified aggregators. Discovery only; never final evidence.

Store the fetched snapshot, canonical URL, source identity, publication/fetch timestamps, parser
and normalization versions, and content hash. Apply timeouts, byte limits, content-type allowlists,
redirect limits, and an outbound network policy. Treat all fetched text as untrusted data and
ignore embedded instructions.

Normalize boilerplate, whitespace, timestamps, URLs, and source names. Deduplicate by normalized
SHA-256 first, then use SimHash/embedding similarity and event clustering. Retain links from
duplicates to the canonical article/event so provenance is not lost.

## Scenario: Eight-source AI evidence acquisition

### 1. Scope / Trigger

This is the implemented boundary for the first stage. It applies to the eight approved government,
education, research, company, and media profiles in
[`source_profiles.py`](../../../backend/app/infrastructure/ingestion/source_profiles.py). It does
not authorize arbitrary URLs, general web search, LangGraph execution, summarization, scoring, or
generation.

### 2. Signatures

- Schedule/default: daily 06:30 `Asia/Shanghai` through `app.scheduler_main`.
- Manual enqueue: `POST /api/v1/acquisition-runs` -> HTTP 202 and a durable run ID.
- Run/job query: `GET /api/v1/acquisition-runs/{run_id}` and `.../{run_id}/jobs`.
- Evidence queue: `GET /api/v1/evidence-candidates`; stored handoff:
  `GET /api/v1/evidence-candidates/{candidate_id}`.
- Rule: `AI_TITLE_RELEVANCE_RULE_VERSION = "ai-title-v1"` in
  [`title_relevance.py`](../../../backend/app/domain/title_relevance.py).
- Worker controls: `ACQUISITION_FIRST_RUN_SCAN_LIMIT`, `ACQUISITION_DAILY_SCAN_LIMIT`,
  `ACQUISITION_FIRST_RUN_ITEM_LIMIT`, and `ACQUISITION_DAILY_ITEM_LIMIT`.

### 3. Contracts

- Parse a bounded raw discovery window, merge duplicate blank-image/text anchors, preserve source
  ordering, and apply title relevance before every detail request.
- `ai-title-v1` uses NFKC/case/whitespace/dash normalization and conservative Chinese/English
  terms. AI policy is eligible only when policy wording appears with a direct AI/intelligent-
  technology term. Ambiguous `agent`, `BCI`, `UAS`, generic educational `深度学习`, and compounds
  such as `智能体检` do not pass without the required technical context.
- Accept at most the configured relevant-item limit; never fill the quota with unrelated items.
  A zero-match source succeeds with `outcome=no_relevant_items`, stores `filtered_count`, advances
  the raw-list cursor, and performs no detail request.
- Accepted candidates persist `matched_title_terms` and `relevance_rule_version`, cleaned full
  text, original/canonical URL, publication/fetch time, source/version IDs, immutable snapshot, and
  observations.
- Candidate lists expose source/title/time/original+canonical URL/candidate ID/rule version. Later
  LangGraph nodes read candidate detail and stored text/snapshot; they do not normally re-crawl the
  original URL.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Title directly names AI/model/robotics/intelligent technology | Accept and record matched terms |
| AI regulation/plan/standard title includes direct AI term | Accept as authoritative policy evidence |
| General policy, culture, education, or frontier-science title lacks AI context | Filter before detail fetch |
| Bounded window contains no relevant title | Successful zero-item job with filtered count and raw cursor |
| List/detail host, resolved IP, redirect, type, size, or timeout violates policy | Typed failure; no unsafe fallback |
| Fake-IP resolver returns `198.18.0.0/15` | `non_public_address`; fix DNS layer, never weaken SSRF |
| Source HTML changes and required article data disappears | Typed parse failure and connector/parser version update |

### 5. Good / Base / Bad Cases

- Good: the 2026-07-29 report run `a174ed10-0ef1-4983-b81f-7f8d2bed84d2` completed 8/8 jobs,
  accepted six AI-centered items, and filtered 263 unrelated titles.
- Base: China Government and CAS had no relevant title in their bounded windows; both jobs
  succeeded with zero candidates instead of selecting unrelated policy/research.
- Bad: fetch the first headline per site, treat any HTTP 200 as useful evidence, accept ambiguous
  abbreviations, or let a downstream LLM independently browse the link.

### 6. Tests Required

- [`test_title_relevance.py`](../../../backend/tests/unit/test_title_relevance.py) covers positive,
  negative, Unicode, English-boundary, policy, and ambiguous-compound cases.
- Connector contracts cover all eight source fixtures, ordering, article-path restrictions,
  duplicate anchor merging, parser drift, and source-specific selectors.
- Real PostgreSQL/MinIO tests assert no unrelated detail fetch, zero-match success/cursor behavior,
  filtered counts across retries, immutable snapshots, provenance, and no-refetch downstream use.
- Opt-in live acceptance uses production-safe fetching, one accepted item per source, and records
  run/job/title/URL results; deterministic fixture tests remain authoritative.

### 7. Wrong vs Correct

#### Wrong

```python
items = connector.discover(list_response, profile, limit=1)
detail = await fetcher.fetch(items[0].url, profile)
```

#### Correct

```python
discovered = connector.discover(list_response, profile, limit=scan_limit)
evaluated = [(item, evaluate_title_relevance(item.title)) for item in discovered]
accepted = [(item, result) for item, result in evaluated if result.is_relevant][:item_limit]
for item in accepted:
    detail = await fetcher.fetch(item[0].url, profile)
```

Discovery depth and accepted evidence count are separate contracts.

## Implemented factual-governance handoff

The second capability consumes stored candidates and all of their observations/snapshots without
re-fetching original URLs. It produces immutable normalized passages, evidence-bound factual
analyses, purpose-specific embeddings, duplicate relations, deterministic event assignments, and
versioned event projections. PostgreSQL run/job tables are the operational source of truth;
LangGraph checkpoints contain only resumable IDs, hashes, versions, statuses, and small typed
outputs.

The complete executable signatures, seven-category taxonomy, idempotency bundle, fixed
`embedding-3` 2048-dimensional contract, event thresholds, Zhipu transport rules, error matrix,
tests, and API boundaries live in
[`governance-event-organization.md`](./governance-event-organization.md). That document controls
second-capability implementation details; this file controls the cross-stage handoff.

Downstream topic scoring must consume governed event/fact/category/entity/source-diversity/evidence
projections. It must not re-crawl a source, re-summarize the article, infer provenance from only
`candidate.source_id`, or bypass a durable `review_required` assignment.

## Eligibility, scoring, and selection

Hard vetoes are evaluated independently of the numeric total and cannot be outweighed. Initial
vetoes include unresolved Tier C evidence, unverified rumors, unsuitable negative incidents,
privacy/legal/safety uncertainty, prohibited marketing risk, and an event cluster selected in the
last seven days.

Scoring uses normalized features and a versioned configuration:

```python
class TopicScore(BaseModel):
    scoring_version: str
    feature_values: dict[str, float]
    weights: dict[str, float]
    penalties: dict[str, float]
    total: float
    threshold: float
    eligible: bool
    veto_codes: list[str]
```

Initial features follow the report: source trust, AI/science-education relevance, parent relevance,
freshness, communication potential, historical repetition, and controversy/marketing risk. Store
each component and validate its range. Do not ask an LLM for an unexplained final number.

The report does not supply numeric ranges, weights, penalties, or a threshold. Keep them in a
versioned scoring configuration rather than hard-coding values in this spec. The first scoring
task must document normalization and tie-break rules, evaluate a proposed configuration against a
representative labeled candidate set, and obtain product approval before using it as the
production default.

Select Top 1 only from eligible candidates with `total >= threshold`. Stable tie-breakers must be
documented (for example source tier, publication time, then stable ID). If none qualifies, persist
`no_topic` and stop before retrieval, copy generation, or image generation.

## Retrieval boundary

Run two explicit retrieval operations:

1. `retrieve_evidence` returns eligible source passages with snapshot IDs, URLs, tiers, publication
   times, exact text/offsets, and relevance information.
2. `retrieve_brand_context` returns current parent-audience brand chunks with document/version IDs,
   safety/tone metadata, and relevance information.

Do not place them in an unlabeled combined list. PostgreSQL full-text and pgvector retrieval may be
fused and reranked. `ts_rank` must not be described as BM25; exact BM25 requires an explicitly
selected extension/service.

## Draft schema and claim bindings

The drafting model receives delimited evidence and brand sections plus their IDs. It must return a
Pydantic-validated shape equivalent to:

```python
class DraftClaim(BaseModel):
    id: str
    text: str
    kind: Literal["external_fact", "brand_statement", "opinion"]
    evidence_ids: list[UUID]
    brand_chunk_ids: list[UUID] = Field(default_factory=list)

class MaterialDraft(BaseModel):
    copywriting: str
    parent_takeaway: str
    interaction: str
    source_note: str
    image_prompt: str
    claims: list[DraftClaim]
```

Every `external_fact` claim requires one or more eligible evidence IDs. The binding stored for the
accepted artifact includes source URL, tier, publication time, and exact supporting passage or
offsets. A free-form source note is for readers and does not replace machine-readable bindings.
Brand chunks can support tone or brand statements, not external facts.

## Validation and audit

Deterministic validation runs first and returns typed issue codes with field/claim locations. It
checks schema, required fields, evidence coverage, source tiers, source URLs, banned phrases,
lengths, date consistency, repeated-topic state, privacy/policy rules, image restrictions, and the
manual-publishing boundary.

Only a deterministically valid draft proceeds to LLM audit. The auditor judges unsupported
implication, exaggeration, anxiety-inducing language, parent usefulness, brand fit, and image-prompt
risk against the supplied artifacts. It returns a typed verdict such as:

```python
class AuditIssue(BaseModel):
    code: str
    message: str
    claim_id: str | None = None
    severity: Literal["warning", "error"]

class AuditVerdict(BaseModel):
    accepted: bool
    issues: list[AuditIssue]
```

The auditor is not a retrieval tool and cannot add evidence from model memory. It cannot override
a hard veto or deterministic failure. Regeneration receives structured issues and is bounded by a
configured maximum; exhaustion produces a terminal, reviewable run state.

## Job state and idempotency

Use a unique run key such as `(schedule_date, timezone, pipeline_version)`. Derive a stable stage
idempotency key from the run, stage, and input artifact/version. Persist attempts, leases,
heartbeats, request fingerprints, provider request IDs, prompt/model versions, output artifacts,
and error classifications.

Keep the persisted state machines distinct and expose these canonical `snake_case` API values:

- Pipeline runs: `queued`, `running`, `no_topic`, `awaiting_manual_use`, `completed`, `failed`,
  and `cancelled`.
- Stage jobs: `queued`, `running`, `succeeded`, `retry_scheduled`, `failed`, and `cancelled`.

State transitions must be validated, atomic, and tested. `awaiting_manual_use` means the package
is ready for human review/copy/download. `completed` may represent internal acknowledgement only;
it does not mean that an automated social post occurred.

Retry only classified transient faults with bounded exponential backoff and jitter. Do not retry a
veto, missing evidence, invalid structured output without a bounded repair policy, or failed
deterministic validation as if it were a network timeout.

## Material package boundary

The accepted package contains the selected topic, generated date, copy, parent takeaway,
interaction prompt, image artifact, human-readable source links, machine-readable claim bindings,
and validation/audit metadata. The API may expose copy and download operations or URLs.

There is no automatic social-publishing stage. Do not add social credentials, publishing SDKs,
scheduled posts, or a “publish now” API. Sales staff remain responsible for reviewing and manually
posting the package.

## Verification cases

- Two scheduler replicas produce one run for the same business key.
- A worker crash after an external response does not create a duplicate image/model artifact.
- Tier C content can create a lead but cannot satisfy `external_fact.evidence_ids`.
- A seven-day repeated event and a below-threshold candidate both stop before generation.
- A draft with an unbound fact fails deterministic validation and never reaches audit.
- Prompt-injection text in a snapshot remains quoted data and cannot alter stage instructions.
- Audit retry exhaustion preserves issues and artifacts for internal review.
- The final OpenAPI contract exposes no automated publishing operation.
