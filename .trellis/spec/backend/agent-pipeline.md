# Agent Pipeline Contract

## Purpose and status

This guide translates the workflow in [`main.tex`](../../../main.tex) and the generated
[`技术报告-v0.3.pdf`](../../../技术报告-v0.3.pdf) into a testable implementation contract. Three
capabilities now exist: authoritative-source acquisition, versioned factual governance and
auditable event organization, deterministic daily Top 1/`no_topic` selection, private versioned
brand retrieval, preview evidence-bound copy generation/audit, and versioned material-package
delivery. Automated publishing is prohibited. The copy path is functional and has one controlled
live structured draft/audit with manually reviewed bindings, while remaining a preview product
policy pending broader labeled calibration and internal copy review.

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

## Scenario: Nine-source AI evidence acquisition

### 1. Scope / Trigger

This is the implemented boundary for the first stage. It applies to the nine approved government,
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
- Connector contracts cover all nine source fixtures, ordering, article-path restrictions,
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

## Implemented eligibility, scoring, and selection

The executable API, migration, environment, lease, scoring, veto, and test contracts are in
[`topic-selection.md`](./topic-selection.md). The summary below controls the cross-stage handoff.

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

The implemented `scoring-v1-preview.4-science-policy-priority` keeps numeric ranges, weights, penalties, the threshold,
veto version, and tie-break order in an immutable persisted configuration. It has controlled tests
and a real-event demonstration, but remains a preview profile until a later labeled calibration
and explicit product approval create a new production configuration.

Select Top 1 only from eligible candidates with `total >= threshold`. Stable tie-breakers must be
documented (for example source tier, publication time, then stable ID). If none qualifies, persist
`no_topic` and stop before retrieval, copy generation, or image generation.

## Retrieval boundary

The brand half of this boundary is implemented in
[`brand-knowledge-rag.md`](./brand-knowledge-rag.md); the factual retrieval consumed by drafting
remains a later generation-slice integration.

Run two explicit retrieval operations:

1. `retrieve_evidence` returns eligible source passages with snapshot IDs, URLs, tiers, publication
   times, exact text/offsets, and relevance information.
2. `retrieve_brand_context` returns current parent-targeted brand chunks with document/version IDs,
   safety/tone metadata, and relevance information to the internal drafting node. Here `parents`
   describes the generated copy's target audience; it does not expose a parent-facing search flow.

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
manual-publishing boundary. The parent-facing copy must use plain Chinese, explain why learning
science/innovation/AI/robotics is useful without grade or career promises, explain why the learning
experience belongs at Sai Xiansheng using supplied brand context, target at most 300 CJK Chinese
characters and 6-12 emoji in the body excluding the source footer and
trailing hashtag line. The body must contain exactly three natural paragraphs, each represented by
two non-empty lines, separated by one blank line, and end with a separate line of two or three
hashtags whose first tag is always `#赛先生科学`. The opening paragraph must identify the content
as news-derived (for example, `今天看到一条新闻`). Immediately before the final hashtag line,
the system appends `新闻来源：<bound source name>` and
`原文链接：<bound HTTPS evidence URL>` from the first locked evidence item. The footer is
deterministic, is excluded from body counts/format checks, and remains a hard integrity check even
under local preview. Length, paragraph, emoji, and news-framing targets are quality guidance, not
delivery blockers. Under the current recovery rules, ordinary parent-readability, tone/fluency,
brand-fit, learning-value, brand-value, and hashtag-quality findings are also warning-only and may
consume the same single repair. Privacy, prompt-injection echo, automatic publishing, prohibited
marketing, education anxiety, unsafe-image instructions, unbound facts, evidence mismatch, and a
missing or mismatched bound source footer remain hard technical errors.

Only a draft without deterministic errors proceeds to LLM audit; deterministic warnings proceed as
well. The auditor judges parent readability,
learning value, the concrete Sai Xiansheng reason, unsupported implication, exaggeration,
anxiety-inducing language, brand fit, hashtag quality, and image-prompt risk against the supplied
artifacts. It returns a typed verdict such as:

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

The copy-counting helpers are the single source of truth for this contract:

```python
extract_copy_body(text: str) -> str
extract_copy_paragraphs(text: str) -> tuple[str, ...]
has_copy_paragraph_format(text: str) -> bool
has_copy_news_framing(text: str) -> bool
has_copy_news_source_footer(text: str, *, source_name: str, source_url: str) -> bool
append_copy_news_source_footer(text: str, *, source_name: str, source_url: str) -> str
count_hanzi(text: str) -> int
count_emojis(text: str) -> int
```

`extract_copy_body` removes the final hashtag-candidate line and a recognized source footer before
counting. `count_hanzi` counts only CJK Unified Ideographs; punctuation, whitespace, digits, Latin
letters, and emoji do not count. `has_copy_paragraph_format` requires exactly three two-line body
paragraphs separated by one blank line. `count_emojis` counts displayed emoji sequences, treating
variation selectors, skin-tone modifiers, and zero-width-joiner components as part of the preceding
emoji. The body target is at most 300 Hanzi and 6-12 emoji inclusive. Counts outside either target
and missing news framing use `copy_length`, `copy_emoji_count`, or `copy_news_framing` with
`warning` severity under every preview and strict policy; the paragraph check uses
`copy_paragraph_format` with the same warning severity. The source footer check is a hard
`copy_news_source_footer` integrity issue. The count, format, framing, and footer results are
retained in the material package for inspection.

| Condition | Required result |
| --- | --- |
| Body has 301 or more Hanzi | `copy_length` warning; continue to audit and delivery when no hard issue exists |
| Body has 300 or fewer Hanzi | Length check passes when other checks pass |
| Body has 0-5 or 13+ emoji sequences | `copy_emoji_count` warning; continue to audit and delivery when no hard issue exists |
| Body has 6-12 emoji sequences | Emoji check passes when other checks pass |
| Body does not have exactly three two-line paragraphs with one blank line between | `copy_paragraph_format` warning; continue to audit and delivery when no hard issue exists |
| First paragraph does not identify a news item | `copy_news_framing` warning; continue to audit and delivery when no hard issue exists |
| Footer source name or URL differs from the first locked evidence item | `copy_news_source_footer` error; do not accept or deliver |
| Tags appear only on the final line | Tags are validated separately and excluded from the Hanzi count |

Good: a three-paragraph news-framed body with 300 or fewer Hanzi, 6-12 emoji, the deterministic
source footer, and `#赛先生科学 #科学思维` has no format or source warning. If a body exceeds 300
Hanzi or misses a format target, those characters and layout defects remain visible as warnings;
padding with punctuation, ASCII, emoji, or hashtag text cannot conceal the Hanzi count.

Tests must assert the 300-character upper boundary, exclusion of punctuation/ASCII/emoji/trailing
tags and source footer, common variation-selector and ZWJ sequences, paragraph/newline cases,
news framing, evidence-bound footer replacement, prompt wording, WeCom text preservation, and
continuation through audit for a warning-only draft. `copy_length`, `copy_emoji_count`,
`copy_paragraph_format`, and `copy_news_framing` remain advisory and can consume the existing
single product repair; `copy_news_source_footer` remains hard. A repaired draft with only advisory
warnings remains deliverable, while a missing/mismatched source footer or other hard error ends in
`review_required`. Do not implement a second repair loop or duplicate the counting logic in a
provider adapter.

The auditor is not a retrieval tool and cannot add evidence from model memory. It cannot override
a hard veto or deterministic failure. Regeneration receives structured issues and is bounded by a
configured maximum; exhaustion produces a terminal, reviewable run state.

## Preview quality projection

The redacted preview manifest normalizes validation and audit records through one
`_quality_snapshot(value, default_status)` projection in `backend/app/preview_run.py`. The source
contracts use different verdict fields and must not be conflated:

- deterministic validation uses boolean `passed`, which maps to `passed` or `failed`;
- LLM audit uses boolean `accepted`, which maps to `accepted` or `rejected`;
- an explicit string `status` always wins, including `not_configured`;
- when neither verdict is present, retain the caller's pending/default status.

The normalized payload preserves both `passed` and `accepted` as separate nullable fields. This
keeps the top-level manifest and nested `copy.audit` display consistent with the persisted package
without changing durable state or workflow transitions. The manifest's `copy.copywriting` keeps
normalized line breaks and blank paragraph separators; only intra-line whitespace is collapsed, so
the local viewer displays the same paragraph/source-footer layout that Enterprise WeChat receives.

### Validation & Error Matrix

| Input record | Projected status |
| --- | --- |
| `{"passed": true}` | `passed` |
| `{"passed": false}` | `failed` |
| `{"accepted": true}` | `accepted` |
| `{"accepted": false}` | `rejected` |
| `{"accepted": true, "status": "not_configured"}` | `not_configured` |
| `{}` with `default_status="pending"` | `pending` |

Unit coverage must assert accepted/rejected audit projection at both manifest locations and confirm
that explicit provider statuses are not overwritten.

## Scenario: Preview copy policy and bounded Zhipu structured output

### 1. Scope / Trigger

This contract applies when a locked daily topic is converted into the single parent-facing
Moments draft, including manual API enqueue with a profile that differs from the server default.
It also applies to every Zhipu generator, auditor, and schema-correction request.

### 2. Signatures

- Manual enqueue: `POST /api/v1/copy-generation-runs` with `business_date` and
  `scoring_profile`.
- Version selection: `build_copy_version_bundle(settings, scoring_profile=<effective profile>)`.
- Durable execution identity: `CopyVersionBundle.provider` and `.model` are pinned when the run is
  enqueued and restored by every later claim/retry.
- Preview profiles: `preview`, `preview-v1`, and `preview-v2`; the current local-preview rule
  version is `preview-v8-quality-warning-recovery`. Earlier preview rule versions remain available for
  historical behavior.
- Strict profiles use `COPY_RULE_VERSION`, currently
  `moments-rules-v9-quality-warning-recovery`.
- Current copy versions: generator `moments-generator-v14-quality-warning-recovery`, auditor
  `moments-auditor-v14-quality-warning-recovery`, and pipeline
  `copy-pipeline-v14-quality-warning-recovery`.
- Zhipu structured payload includes `thinking={"type":"disabled"}` and
  `response_format={"type":"json_object"}` for initial and correction requests.

### 3. Contracts

- The API request profile, not only `CONTENT_SCORING_PROFILE`, determines the enqueued run's
  version fingerprint and durable rule version. Scheduler and worker defaults may continue to use
  the configured profile.
- A generator or auditor result is accepted only when both its `provider` and `model` exactly match
  the claimed run's durable `CopyVersionBundle`. Perform this check before deterministic policy,
  audit-policy transformation, or persistence. A worker restart/configuration change must never
  execute a historical fingerprint under a newly configured model identity.
- Preview-v1 and preview-v2 preserve their historical warning mappings. Under the current
  `preview-v8-quality-warning-recovery` and strict
  `moments-rules-v9-quality-warning-recovery` policies, only the explicit ordinary-quality
  allowlist is warning-only: format, readability, tone, fluency, brand fit, learning-value
  explanation, brand-value explanation, and hashtag quality. Privacy, prompt-injection echo,
  automatic-publishing, prohibited marketing, education anxiety, unsafe-image instructions,
  unbound facts, evidence-text mismatch, source-footer integrity, and unknown evidence/brand IDs
  remain errors. The persisted audit verdict is always the policy-adjusted verdict.
- The copy body target is at most 300 CJK Hanzi, exactly three two-line paragraphs separated by
  one blank line, six to twelve emoji, and an emoji at the first/last boundary of every paragraph.
  The first paragraph must identify a news item. The executor then deterministically replaces or
  appends the source footer immediately before the final hashtag line using the first locked
  evidence item's source name and HTTPS URL; model-provided source links are never trusted. The
  footer is excluded from body counting and is a hard integrity check. Length, emoji-count,
  paragraph-format, and news-framing issues are warnings and may consume at most one bounded
  repair. An imperfect repaired preview draft remains accepted when no technical failure remains.
- GLM-5.2 enables deep thinking by default. Structured copy/audit is a constrained transformation,
  so deep thinking is disabled to reserve the bounded completion budget for JSON. Do not compensate
  for reasoning-token exhaustion by increasing limits without a reviewed version change.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Preview-v1 draft contains only an unverified superlative or incomplete sentence | Persist warning; deterministic gate may continue |
| Preview-v2 draft contains an unlinked claim or source note (with no other blocking issue) | Persist warning; deterministic gate may continue |
| Current preview audit returns ordinary brand/readability/tone/fluency/learning-value/hashtag quality issue | Persist warning; repair at most once, then accept when no hard error remains |
| Current copy policy sees an ordinary format/readability/brand/tone/learning-value/hashtag issue | Persist warning; repair at most once, then continue when no hard issue remains |
| Current copy policy sees privacy, injection, publishing, prohibited marketing, anxiety, unsafe-image, evidence, or source-integrity issue | Keep error; repair once if applicable, otherwise finish `review_required` |
| Strict audit returns `unsupported_implication`, privacy, anxiety, injection, unsafe image, or automatic publishing | Keep error; repair once or finish review-required |
| Deterministic rule detects a prohibited promise such as guaranteed score improvement | Keep `prohibited_marketing` error under every profile |
| Manual API requests `strict` while server default is preview | Persist strict rule version/fingerprint |
| Manual API requests `preview` while server default is strict | Persist preview rule version/fingerprint |
| Generator/auditor returns a different provider or model than the claimed bundle | Fail closed with non-retryable `provider_identity_mismatch`; do not persist the mismatched draft/audit |
| Zhipu initial or correction request omits `thinking.type=disabled` | Contract failure; do not run controlled live acceptance |
| Provider content is invalid JSON/schema | `invalid_provider_output`; preview policy cannot downgrade it |

### 5. Good / Base / Bad Cases

- Good: a current-policy audit flags only brand fit and readability; both become warnings, trigger
  at most one structured repair, and the evidence-bound draft remains deliverable if warnings persist.
- Base: strict mode receives a privacy or evidence mismatch finding and preserves the hard error.
- Bad: classify `unsupported_implication` as marketing style, derive a manual run's rule version
  only from server settings, accept a result from the worker's newly configured provider/model,
  or allow GLM reasoning tokens to consume the structured-output budget.

### 6. Tests Required

- Domain/unit tests assert preview deterministic warning codes, local-preview acceptance, strict
  preservation, warning-only acceptance without repair, and unchanged technical hard failures.
- Version-bundle tests cover configured and explicit manual-profile overrides in both directions.
- Provider-identity tests cover generator and auditor provider drift plus generator and auditor
  model drift. They assert `provider_identity_mismatch` and that the mismatched draft/audit is not
  persisted.
- Provider contract tests inspect every generated request body, including correction requests, and
  assert `thinking == {"type": "disabled"}` plus strict JSON response format.
- Existing provider-envelope, schema, redaction, replay, and PostgreSQL safe-metadata tests remain
  mandatory; no automated test may make a live model request.

### 7. Wrong vs Correct

#### Wrong

```python
bundle = build_copy_version_bundle(settings)  # ignores the manual request profile
provider_payload = {"model": model, "messages": messages, "max_tokens": 2048}
result = await generator.generate(request)  # result identity is persisted without comparison
```

#### Correct

```python
bundle = build_copy_version_bundle(settings, scoring_profile=payload.scoring_profile)
provider_payload = {
    "model": model,
    "messages": messages,
    "thinking": {"type": "disabled"},
    "response_format": {"type": "json_object"},
    "max_tokens": 2048,
}
result = await generator.generate(request)
ensure_provider_identity(
    provider=result.provider,
    model=result.model,
    version_bundle=claimed.version_bundle,
)
```

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

## Scenario: One-image generation through a configured image-provider contract

### 1. Scope / Trigger

- Trigger: an accepted draft/image prompt must produce exactly one stored image. This is a
  cross-layer contract (AI provider, MinIO storage, DB artifact, controlled download API).
- Only an accepted draft may call the image provider. `no_topic` and failed drafts never reach it.

### 2. Signatures

- Active local provider origin: `https://ai.comfly.org`; the model remains configurable and is
  currently `gpt-image-2`. The old `toapis` adapter remains an explicit rollback mode.
- Comfly generate: `POST /v1/images/generations` with `model`, a validated bounded `prompt`,
  `size=1024x1024`, `aspect_ratio=1:1`, and an optional ordered `image=[data:image/png;base64,...]`
  tuple containing approved local references. Each reference carries a role, asset ID, filename,
  checksum, and bytes in the provider-neutral request; private MinIO URLs and provider upload URLs
  are never sent. The default aggregate reference budget is 3 MiB (`IMAGE_REFERENCE_BUDGET_BYTES`),
  which keeps the encoded request within the provider's practical payload envelope while retaining
  real Sai Xiansheng/Xiaosai identity assets.
- The accepted topic/copy produces a bounded `VisualBrief`; the deterministic selector persists its
  catalog/selector versions, ordered reference roles/checksums, selection reasons, and an explicit
  `reference_mode` (`single_reference`, `budgeted_multi_reference`, or `single_fallback`). The raw
  Moments copy is never used as the image text layer.
- Response: accept exactly one synchronous `data[].url` or `data[].b64_json`. If the gateway returns
  a safe task identifier and a pending status, poll `GET /v1/images/tasks/{task_id}` after the
  configured initial delay and interval, bounded by the provider window.
- Download: URL results require HTTPS, no redirects, bounded bytes, and exactly 1024x1024
  dimensions. Every literal or DNS-resolved output address must be globally routable; private,
  loopback, link-local, metadata, reserved, and Fake-IP addresses are rejected before the CDN
  request. A generic or absent CDN media-type header is accepted only after PNG/JPEG/WebP signature
  and dimensions verify; an explicit supported header must agree with the verified bytes.
- Storage: sanitized content-addressed MinIO key, private access, with sha256 checksum.
- DB artifact: `image_artifacts` row with provider/model/prompt version, dimensions, safe provider
  ID, object identity, attempts, status, and request fingerprint.

### 3. Contracts

- One accepted prompt/profile fingerprint maps to at most one successful artifact. Provider calls
  occur outside transactions; persistence re-checks the fingerprint/provider state before retry.
- `COMFLY_API_KEY` is the active credential; `TOAPIS_API_KEY` is retained only for rollback. Any
  generated URL, raw provider response, prompt body, reference contents, and bearer token are
  transient — they must not enter logs, APIs, or durable job metadata. Persist only safe task IDs,
  provider/model/version identity, checksums, attempts, dimensions, status, and typed error codes.
- Validate prompt/rules before the call and returned content type/size/dimensions after the call:
  bounded bytes (`image_max_download_bytes`, default 20 MiB), a verified PNG/JPEG/WebP raster, and
  exactly 1024x1024 before private MinIO storage. `application/octet-stream`,
  `binary/octet-stream`, or absent CDN headers are advisory rather than sufficient proof.
- Config (`Settings`): `image_enabled` (default false, fail-closed), `image_provider_mode`
  (`disabled`/`fake`/`toapis`/`comfly`), `toapis_base_url`, `toapis_api_key`, `comfly_base_url`,
  `comfly_api_key`, `image_model`, `image_prompt_version`,
  `image_pipeline_version`, `image_max_attempts` (default 3, 1-6), `image_poll_initial_seconds`,
  `image_poll_interval_seconds`, `image_provider_timeout_seconds` (default 120s),
  `image_provider_window_seconds` (default 180s, 1-180), `image_max_download_bytes`
  (1 KiB-50 MiB), `image_max_request_bytes`, `image_max_provider_response_bytes`,
  `image_max_reference_images` (default 3), `image_reference_budget_bytes` (default 3 MiB),
  `image_asset_manifest`, `image_selector_version`, and `image_selector_enabled`.
- `image_enabled=True` with `image_provider_mode="disabled"` raises at startup; `toapis` mode
  requires a non-empty `TOAPIS_API_KEY` and pinned HTTPS `toapis_base_url`; `comfly` mode requires
  a non-empty `COMFLY_API_KEY` and an HTTPS `comfly_base_url` without credentials, query, or
  fragment.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Retry/replay/concurrency on same fingerprint | At most one successful image artifact |
| Unsafe prompt or provider output | Typed `review_required`/`failed` state before package readiness |
| Provider returns non-HTTPS URL, redirect, or a non-public DNS/literal address | Reject download, fail the attempt |
| Returned bytes are not PNG/JPEG/WebP, explicit media header disagrees, or size/dimensions are wrong | Reject, do not store |
| Comfly/ToAPIs JSON signals quota or balance exhaustion | Raise non-retryable `ImageProviderQuotaError`; persist only the typed error code, never the response body |
| 401/403 or an explicit invalid-token response | Raise non-retryable provider authentication error; do not retry |
| 429 or bounded transient 5xx | Retry within the configured attempt/window bounds; stop with a typed rate-limit/unavailable error |
| Synchronous response has multiple images, malformed JSON, or unknown task status | Reject the provider result; never choose an arbitrary image |
| 429/503 during polling | Honor `Retry-After`, retry within the configured provider window (180s by default) |
| Provider window exceeded | Stop, classify as transient, retry up to `image_max_attempts` |
| Selected references exceed count/byte bounds | Reject before the paid provider call; preserve the explicit fallback mode if a bounded single reference remains |
| Active provider key missing or URL is not a valid HTTPS origin | Startup fails closed |

### 5. Good / Base / Bad Cases

- Good: one accepted content brief selects approved IP references within 3 MiB, produces one
  1024x1024 PNG in MinIO, one artifact row, and a controlled download.
- Base: `fake` provider returns a deterministic 1024x1024 PNG without network, for offline tests.
- Bad: persist the transient upload/generated URL, store raw provider response, or accept a
  non-1024 image.

### 6. Tests Required

- [`test_image_generation.py`](../../../backend/tests/unit/test_image_generation.py) asserts fake
  determinism (same fingerprint -> same bytes, 1024x1024 PNG), payload shape, fingerprint
  stability, and error classification for malformed provider responses.
- [`test_visual_assets.py`](../../../backend/tests/unit/test_visual_assets.py),
  [`test_visual_brief.py`](../../../backend/tests/unit/test_visual_brief.py), and
  [`test_material_package.py`](../../../backend/tests/unit/test_material_package.py) assert
  deterministic topic selection, bounded reference metadata, prompt/text-layer isolation, and
  explicit provider fallback. The live content-driven smoke must be inspected under
  `output/imagegen/` when a paid acceptance run is performed.
- [`image_live_smoke.py`](../../../backend/app/image_live_smoke.py) runs one bounded call through the
  configured live provider with a locally injected secret; it prints only provider/model/size/
  bytes/output on success. A timeout, authentication, quota, or malformed-output result is a safe
  typed diagnostic and is never presented as a generated image.

### 7. Wrong vs Correct

#### Wrong

```python
payload = {"model": "gpt-image-2", "prompt": prompt, "image": ["https://private-minio/...png"]}
artifact = ImageArtifact(provider_task_url=result_url)  # persist expiring URL
```

#### Correct

```python
payload = {
    "model": "gpt-image-2", "prompt": prompt, "size": "1024x1024", "aspect_ratio": "1:1",
    "image": [bounded_identity_data_url, bounded_action_data_url],
}
image_bytes = await _download(result_url)  # public-address HTTPS only, no redirect
artifact = ImageArtifact(provider_task_id=task_id, sha256=checksum(image_bytes),
                         width=1024, height=1024)  # no URL persisted
```

## Scenario: Private visual catalog annotation with Zhipu vision

### 1. Scope / Trigger

- Trigger: an operator prepares or refreshes the private PNG catalog under
  `private/brand-materials/05-visual-assets/` and wants model-assisted descriptive labels.
- This is a one-shot catalog-preparation operation, not a daily content-worker stage. The daily
  worker reads the already generated manifest and never depends on a remote vision call.
- The source images, sidecar, and manifest remain private, ignored by Git, and outside text RAG.

### 2. Signatures

- Command: `python scripts/annotate_brand_visual_assets.py [--materials-root PATH]
  [--model MODEL] [--base-url HTTPS_URL] [--force] [--max-assets N] [--require-vision]`.
- Default model: `glm-4.1v-thinking-flash`; default endpoint:
  `https://open.bigmodel.cn/api/paas/v4`.
- Environment: `AI_PLATFORM_BASE_URL` and `AI_PLATFORM_API_KEY` select the local Zhipu
  endpoint/credential; `ZHIPU_VISION_MODEL` overrides the default model. Credentials are read
  from local `.env` or deployment secret storage and are never written to the sidecar.
- Output: `private/brand-materials/visual-assets.metadata.json`, followed by
  `python scripts/build_brand_asset_manifest.py` to produce
  `private/brand-materials/visual-assets.manifest.json`.
- Sidecar top-level fields are `schema_version`, `private=true`, `text_rag_eligible=false`,
  `annotation={provider, model, policy_version, generated_at}`, `assets`, and `annotations`.
  Each annotation stores only `status`, bounded `error_code` or `request_fingerprint`, model and
  policy identifiers, `canonical_source`, and optional `suggested_tags` grouped as
  `characters`, `topics`, `poses`, and `scene_tags`.

### 3. Contracts

- Each approved PNG is sent as one bounded `data:image/png;base64` input to a constrained
  JSON-only request. The prompt treats visible text as untrusted image data and requires values
  from the fixed allowlists; model reasoning, prose, arbitrary keys, and raw provider responses
  are discarded.
- `suggested_tags` are advisory metadata only. The manifest's canonical `asset_kind`, `roles`,
  `approved`, identity characters, topics, poses, and scene tags remain derived from directory,
  filename, and controlled metadata rules. A vision model cannot approve an asset, reclassify an
  identity/action/style role, or turn an action image containing a character into an identity
  reference.
- The annotator writes incrementally through a private temporary file and preserves a per-asset
  rule fallback when the provider is unavailable, rejects a request, returns invalid JSON, or
  exceeds the response/input limit. One bad image does not prevent the remaining catalog from
  being indexed unless `--require-vision` is explicitly requested.
- A fixed image checksum is included in the request fingerprint. The sidecar stores hashes and
  bounded codes only; it does not store image bytes, prompts, private paths/URLs, credentials, or
  model raw output. Rebuilding the manifest revalidates PNG signatures, dimensions, byte limits,
  and SHA-256 values.
- The annotation operation must not be called from material-package execution or from a public
  API handler. It may be repeated after new assets are added; `--force` is required to replace an
  existing accepted model suggestion.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Valid constrained JSON with allowlisted labels | Keep rule metadata as canonical; store bounded `suggested_tags` and `accepted_model_suggestion` |
| Model emits a disallowed tag, extra field, or unknown role | Drop the invalid suggestion; preserve controlled canonical metadata |
| Reasoning tags, markdown fence, or bounded answer wrapper | Extract one JSON object only; never persist reasoning/prose |
| Missing key, timeout, 4xx/5xx, invalid JSON, oversized input/response | Store `fallback_filename_rule` with a typed code and continue catalog generation |
| `--require-vision` and any asset lacks an accepted model suggestion | Exit non-zero after leaving no provider body or secret in the sidecar |
| Symlink, path escape, invalid PNG, invalid HTTPS endpoint, or unsafe model identifier | Reject the operation before the provider call |
| Model suggests a different identity, approval state, or asset kind | Ignore the model's authority; controlled rules remain authoritative |

### 5. Good / Base / Bad Cases

- Good: the provider returns allowlisted labels for each PNG, the sidecar records suggestions and
  fingerprints, and the rebuilt manifest still contains only controlled canonical roles.
- Base: one request times out; that asset keeps its filename/directory labels while the other
  assets continue to annotate, and the daily worker remains usable.
- Bad: pass the whole private directory to a general model prompt, use model output as approval
  or identity truth, persist raw `<think>` content/provider JSON, or make daily image generation
  fail because the optional catalog annotation endpoint is unavailable.

### 6. Tests Required

- `backend/tests/unit/test_visual_asset_annotation.py` must assert reasoning/prose stripping,
  JSON extraction, tag allowlisting, identity-role preservation, provider-failure fallback,
  bounded fingerprints, and absence of raw provider content in the result.
- Manifest tests must assert that sidecar suggestions do not change canonical roles, approval,
  checksum, or identity/action separation, and that the 41-asset private catalog loads with valid
  PNG metadata.
- A command smoke must verify the sidecar has equal asset/annotation coverage, only the expected
  provider/model/policy identifiers, and no API key, prompt, URL, or image bytes. No ordinary
  unit test may call the live Zhipu endpoint.

### 7. Wrong vs Correct

#### Wrong

```python
labels = await vision_model.describe(image)
manifest_asset["asset_kind"] = labels["kind"]
manifest_asset["approved"] = labels["approved"]
```

#### Correct

```python
canonical = build_manifest_from_controlled_rules(asset)
suggested = parse_allowlisted_json(vision_response)
sidecar[asset.relative_path] = {
    "canonical_source": "controlled_rules",
    "suggested_tags": suggested,
}
manifest_asset = canonical
```

## Scenario: Versioned material package reservation and manual reuse

### 1. Scope / Trigger

- Trigger: an accepted copy-generation run is requested as a one-image material package.
- This cross-layer contract covers API reservation, content-worker execution, private MinIO
  storage, package snapshots, frontend polling, and manual reuse.
- `no_topic`, failed, review-required, or otherwise unaccepted copy runs never call the image
  provider and never become a ready package.

### 2. Signatures

- `POST /api/v1/material-packages` with `{copy_generation_run_id, reviewer}` returns HTTP 202 and
  a queued package. The handler calls `enqueue_material_package`; it does not call an image
  provider.
- `GET /api/v1/material-packages` and `GET /api/v1/material-packages/{package_id}` expose status,
  topic, copy, sources, brand bindings, validation, audit, image metadata, and version snapshots.
- `GET /api/v1/material-packages/{package_id}/download` returns an attachment-friendly JSON
  package with `download_kind="material_package_json"`; it never exposes MinIO bucket/object keys.
- `GET /api/v1/material-packages/{package_id}/image` streams only a succeeded image through a
  relative API URL. `POST .../{package_id}/review` records an internal approval/rejection.
- `POST /api/v1/material-packages/{package_id}/image/retry` returns HTTP 202 only for a failed
  package whose existing image is `failed` or `review_required` and has attempts remaining. It
  requeues that same image artifact and request fingerprint; it never regenerates the topic, copy,
  sources, audit, or an Enterprise WeChat delivery.
- `MaterialPackageExecutor.execute_next(worker_id)` claims one reservation using a lease and
  writes one `ImageArtifactModel` plus one `MaterialPackageModel` result.
- Before claiming image work, `content-worker` calls
  `MaterialPackageExecutor.reconcile_ready_packages(limit=20)`. It scans accepted copy runs with
  an active draft and no package, then creates the same idempotent queued reservation used by the
  API. This closes the handoff if a worker restart or an earlier API path accepted copy without
  creating the image reservation.

### 3. Contracts

- The image request fingerprint includes run, accepted draft, prompt, provider/model, prompt and
  pipeline versions, the ordered reference SHA-256 tuple, visual brief fingerprint, catalog version,
  and selector version. Both image and package tables enforce unique fingerprints; a replay returns
  the durable reservation without a second successful row.
- The package snapshot stores selected topic/explanation, copy and claims, source/evidence
  bindings, brand bindings, validation/audit results, and package/copy/image version metadata.
- A successful image row stores provider/model, dimensions, media type, byte size, SHA-256, safe
  provider IDs, and `{access:"private", immutable:true, content_addressed:true}`. MinIO remains
  private; object keys and signed URLs do not cross the API boundary.
- `content-worker` must receive image provider settings and a read-only brand reference mount.
  `IMAGE_ENABLED=true` with a disabled provider fails closed at settings validation.
- The API and `content-worker` must receive the same `IMAGE_MAX_ATTEMPTS` Compose value. The API
  uses it to decide whether terminal image retry is admissible; the worker uses it to claim and
  exhaust the same image artifact. Divergent values are a deployment defect that can turn an
  accepted retry into an immediate `lease_expired` failure.
- The frontend `features/material` feature polls only queued/running packages and provides copy,
  image download, JSON package download, evidence/audit display, and internal review controls.
  It provides no social publishing operation.
- Reconciliation is best-effort per run: a unique-fingerprint/unique-run conflict means another
  API or worker already won the reservation race and is logged as a skip; malformed local input is
  logged as a safe reconciliation failure without stopping the worker loop. The next poll can retry
  runs that still have no package.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Run is missing, not accepted, or its draft failed validation/audit | Conflict; no reservation/provider call |
| Same fingerprint is submitted again | Return the existing durable package/image reservation |
| API reservation succeeds | Return queued status; provider call remains in content worker |
| Accepted copy has no package when a worker polls | Create one queued reservation before image claiming; do not call the provider twice |
| API and worker reserve the same accepted copy concurrently | Keep the winner's single reservation; treat the losing unique-conflict as an idempotent skip |
| Provider identity/output/dimensions/storage validation fails | Retry only classified transient errors; otherwise image `review_required` or `failed`, package not ready |
| First typed `image_provider_rejected` | Queue exactly one neutralized provider retry; preserve the original provider safety policy |
| Neutralized retry is rejected or cannot pass image quality gates | Render the already-reserved, topic-matched catalog asset and validate/store it privately; do not issue a third provider request |
| Operator requests image retry on a non-terminal package or exhausted artifact | Conflict; do not create another artifact or provider identity |
| Provider-output validation fails | Persist only a bounded issue code and stage in `validation_snapshot`; never store URL, headers, response body, prompt, or credential |
| Worker lease expires | Another worker may reclaim; stale worker cannot persist success |
| Image succeeds | Store one private content-addressed object, mark package `awaiting_manual_use`, expose relative download URLs |
| JSON package is downloaded | Include safe snapshots and metadata; omit bucket, object key, signed URL, credentials, and raw provider response |
| Review is rejected | Mark package rejected; never interpret rejection as an automatic publish action |

### 5. Good / Base / Bad Cases

- Good: an accepted draft creates one queued reservation, the worker writes one 1024x1024 private
  object and package snapshot, and an internal user copies/downloads it after review.
- Good: an accepted copy run survives a worker restart between copy completion and image enqueue;
  reconciliation creates its missing reservation and the normal image worker completes it.
- Base: a fake image provider produces deterministic bytes offline; replaying the same request
  returns the same queued/succeeded artifact.
- Bad: assume the API is the only producer of reservations, generate in the API handler, create a
  package for `review_required`, persist an expiring provider URL, expose MinIO internals, or add
  a “publish now” control.

### 6. Tests Required

- [`test_material_package.py`](../../../backend/tests/unit/test_material_package.py) asserts
  enqueue-only behavior, accepted-draft gating, accepted-run reconciliation, idempotency races,
  provider rejection, lease-safe persistence, safe output-validation diagnostics, terminal
  image-only retry, and safe JSON projections.
- [`test_migrations.py`](../../../backend/tests/integration/test_migrations.py) asserts head
  `20260807_0019`, worker columns, package snapshots, ordered image-reference constraints, and
  unique indexes; MinIO
  integration asserts content-addressed immutable storage.
- Frontend mapper/component tests assert response mapping, queued/failed states, copy/download
  feedback, provenance/audit display, polling termination, and no publishing action.
- A controlled PostgreSQL/MinIO worker integration should assert concurrent same-fingerprint
  reservations and reclaim after lease expiry; live provider calls remain opt-in only.

### 7. Wrong vs Correct

#### Wrong

```python
image = await image_generator.generate(request)  # inside POST /material-packages
return MaterialPackageResponse(image=save_public_url(image.url))
```

#### Correct

```python
reservation = await enqueue_material_package(session_factory=factory, run_id=run_id)
# content-worker later claims the durable reservation and calls the provider
await material_executor.execute_next(worker_id)
```

## Scenario: Bounded image-provider rejection recovery

### 1. Scope / Trigger

- Trigger: an accepted material package receives the typed non-retryable
  `image_provider_rejected` response from its configured image provider.
- This recovery applies only after an accepted copy and durable image reservation exist. It does
  not weaken provider policy, output-download checks, private MinIO storage, or direct WeCom
  quality predicates.

### 2. Signatures

- Alembic head `20260807_0019` adds `image_artifacts.provider_rejection_retry_count INTEGER NOT
  NULL DEFAULT 0` with `0 <= value <= 1`.
- `MaterialPackageExecutor.execute_next(worker_id)` owns the state transition and its claim budget
  is `IMAGE_MAX_ATTEMPTS + repair_count + provider_rejection_retry_count`.
- `MaterialPackageResponse.image.fallback` is the versioned safe projection with states
  `not_used`, `neutralized_retry`, or `brand_catalog`.

### 3. Contracts

- First rejection sets the independent counter to `1`, persists `fallback.state=neutralized_retry`,
  and schedules exactly one prompt built only from allowlisted `VisualBrief` values and reference
  roles. It never includes raw title, summary, copy, prior prompt, private filename/path, URL, or
  reference bytes.
- A second rejection, failed ordinary raster/text/audit quality gate after the single targeted
  repair, or unavailable quality adapter during that retry uses one pre-reserved catalog reference
  in role order: action, style, identity. Exhausted transient provider attempts use the same
  fallback when a valid reserved reference exists. The renderer aspect-preserves that approved
  asset on a plain 1024x1024 canvas, validates it, and writes it through the normal immutable
  MinIO store. Hard output/security/integrity failures do not use this fallback.
- The fallback provenance stores only version, state, counter, typed initial error, requested
  provider/model, catalog asset ID/basename/checksum/role/reason. It must not store provider
  payloads, prompts, credentials, URLs, object keys, or image bytes. API and JSON-package
  `versions.image.fallback` use the same safe projection.
- Catalog output has deterministic raster validation. Generated-text OCR and generative visual
  audit are `not_applicable`; direct WeCom treats them as unconfigured rather than accepted model
  audit results. The requested provider/model identity remains unchanged on the image artifact;
  provenance identifies the actual catalog source.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| First provider rejection | One warning event with IDs, provider/model, attempt, typed code, and `neutralized_retry`; durable queued retry |
| Second rejection, second ordinary quality failure, or exhausted transient provider attempts with reserved asset | Private validated catalog fallback; package `awaiting_manual_use` |
| No reserved/readable/valid catalog asset or MinIO write fails | Typed `brand_asset_fallback_*`, image `review_required`, package `failed` |
| Replay, race, or expired lease | No duplicate provider call, fallback object, image artifact, or delivery job |
| Unsafe/corrupt fallback snapshot | API omits unsafe asset data and never leaks it through `versions` |

### 5. Good / Base / Bad Cases

- Good: first rejection is followed by one neutralized request that succeeds with a validated
  generated image.
- Base: a second rejection produces a square private image from the current topic's approved action
  reference and exposes its safe basename and selection reason to the internal UI.
- Bad: retry the provider indefinitely, reuse a generated image from another topic, overwrite the
  configured provider/model with `brand_catalog`, or expose a private object path in JSON.

### 6. Tests Required

- `test_image_fallback.py` asserts neutral prompt isolation, retry fingerprint separation, square
  aspect-safe rendering, and invalid asset rejection.
- `test_material_package.py` asserts one scheduled retry, second-rejection catalog persistence,
  unchanged requested provider identity, `not_applicable` audit, safe API/JSON fallback projection,
  and path/URL redaction.
- `test_migrations.py`, `test_governance_migrations.py`, and
  `test_governance_migration_downgrade.py` assert head `20260807_0019` and the new column.

### 7. Wrong vs Correct

#### Wrong

```python
while provider_rejected:
    await image_generator.generate(original_prompt)
```

#### Correct

```python
if provider_rejection_retry_count == 0:
    queue_neutralized_retry()
else:
    await persist_validated_catalog_fallback()
```

When the copy run is already accepted but the reservation is missing, the worker repairs the
handoff before claiming:

```python
await material_executor.reconcile_ready_packages()
await material_executor.execute_next(worker_id)
```

## Material package boundary

The accepted package contains the selected topic, generated date, copy, parent takeaway,
interaction prompt, image artifact, human-readable source links, machine-readable claim bindings,
and validation/audit metadata. The API exposes copy, image, and JSON package download operations
through controlled relative URLs.

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
