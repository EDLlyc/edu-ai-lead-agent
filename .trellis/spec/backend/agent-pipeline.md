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
  -> broad-recall deterministic eligible pool
  -> one bounded LLM rerank inside hard priority barriers
  -> automatic deterministic finalization or typed fallback
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

Topic reranking is an ordering stage, not a scoring or governance stage. The deterministic selector
owns eligibility, the 0.59 threshold, Ministry authentication, hard vetoes, seven-day delivered
repeat, slot affinity, same-day exclusion, and item/candidate caps. When the globally disabled-by-
default content-selection pipeline is enabled, its reranker is on by default and sends at most
eight already eligible governed projections to exactly one fake/Zhipu adapter call. Enqueue pins
its independent policy/provider/model config; current `topic-rerank-v4-minimal-order-contract`
accepts only a complete `order` array of frozen candidate IDs, uses JSON-object mode, disabled
thinking/sampling, and direct strict top-level-object parsing with no Markdown/prose envelope.
Ordinals and safe reasons are derived locally. Literal v1/v2/v3 snapshots retain
their exact historical prompt/payload/parser/application behavior.

The v3/v4 automatic finalizer binds an outcome to the exact run request fingerprint, full pool, and
event/version pairs, then rechecks hard veto, eligibility, priority, same-day, final set, and caps.
Any invalid or cross-run mismatch becomes a typed deterministic fallback to the exact base order;
there is no human selection-review stage and no second judge/model pass. Persistence retains
base/final ranks plus a safe typed audit. Invalid completion envelope, JSON envelope, strict schema,
or finalization contract produces bounded content-free diagnostics and the durable fallback while
preserving available usage/latency. No DB session remains open across the provider call.

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

## Scenario: Eleven-active-source tiered science/technology evidence acquisition

### 1. Scope / Trigger

This is the implemented boundary for the first stage. It applies to eleven active government,
education, research, company, and media profiles in
[`source_profiles.py`](../../../backend/app/infrastructure/ingestion/source_profiles.py). It does
not authorize arbitrary URLs, general web search, LangGraph execution, summarization, scoring, or
generation. Xinhua Education passed its production-safe activation smoke. CAST science education
and EdSurge AI education have approved connectors and fixtures but remain in
`PENDING_SOURCE_SEEDS`, outside seeding and scheduling, until each independently passes the same
bounded live gate; the approved target count is thirteen.

### 2. Signatures

- Schedule/default: daily 06:30 `Asia/Shanghai` through `app.scheduler_main`.
- Manual enqueue: `POST /api/v1/acquisition-runs` -> HTTP 202 and a durable run ID.
- Run/job query: `GET /api/v1/acquisition-runs/{run_id}` and `.../{run_id}/jobs`.
- Evidence queue: `GET /api/v1/evidence-candidates`; stored handoff:
  `GET /api/v1/evidence-candidates/{candidate_id}`.
- Active rule: `SCIENCE_TECH_EDITORIAL_RULE_VERSION = "science-tech-editorial-v3-broad"` and
  soft-ordering rule `PRODUCT_MATRIX_FIT_V2_RULE_VERSION =
  "product-matrix-fit-v2-science-pathways"` in
  [`editorial_relevance.py`](../../../backend/app/domain/editorial_relevance.py).
- Worker controls: `ACQUISITION_FIRST_RUN_SCAN_LIMIT`, `ACQUISITION_DAILY_SCAN_LIMIT`,
  `ACQUISITION_FIRST_RUN_ITEM_LIMIT`, and `ACQUISITION_DAILY_ITEM_LIMIT`.

### 3. Contracts

- Parse a bounded raw discovery window and merge duplicate blank-image/text anchors. Evaluate
  bilingual title relevance and product fit without trusting page instructions.
- Education qualification covers science/AI/technology/STEM education plus evidence-substantive
  white-list competition, technology-specialty student, Strong Foundation Plan, and comprehensive
  evaluation pathways. Under v3, a concrete governed hard-technology topic is sufficient for the
  frontier cohort. Completed progress, plans, failures, capital/market activity, events, product
  releases, and general hard-tech coverage are typed signals used for ordering and explanation;
  only completed evidence receives a completed-progress reason. Items without a governed hard-tech
  topic remain out of scope. Explicit consumer/admissions promotions and non-technical aerospace
  homonyms such as sports teams, airlines, or satellite television also remain out; these narrow
  exclusions do not remove a genuine hard-tech product launch, conference, financing event, or
  engineering failure. Evaluation is deterministic, NFKC-normalized, and bounded to 6000 normalized
  body characters.
- Order title matches as education, frontier, then the remaining bounded title-neutral probes.
  Within education/frontier cohorts order by editorial score, product-fit score, publication time,
  original source order, and stable item ID. Product fit never changes eligibility.
- Re-evaluate title plus extracted body and freshness after each bounded detail request. Persist
  only fresh education or qualified-frontier candidates. A zero-match source succeeds with
  `outcome=no_relevant_items`; unrelated detail responses remain auditable filtered observations.
- Accepted candidates persist both rule versions, cohort and education/frontier/editorial scores,
  reason codes, typed content signals, title/body topic/progress/exclusion/signal terms, product direction IDs,
  character-bound/truncation metadata, cleaned text,
  original/canonical URL, publication/fetch time, source/version IDs, immutable snapshot, and
  observations. Historical `ai-title-v1` and `moe-science-v1` source versions remain executable.
- Historical `science-tech-editorial-v2`, `science-ai-education-v1`, `ai-title-v1`, and
  `moe-science-v1` source versions remain
  executable by their stored version strings. Candidate lists expose
  source/title/time/original+canonical URL/candidate ID/rule version. Later
  LangGraph nodes read candidate detail and stored text/snapshot; they do not normally re-crawl the
  original URL.
- China Government policy and yaowen are separate immutable source identities. Yaowen discovery is
  fixed to `/yaowen/liebiao/YAOWENLIEBIAO.json`; discovered details require `www.gov.cn`, the
  `/yaowen/liebiao/` prefix, HTTPS, and no query/fragment. The Tier-A source does not weaken the v3
  relevance gate: unrelated government affairs are filtered like any other out-of-scope item.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Title/body explicitly names science education or AI education | Eligible; record exact rule metadata |
| Science/AI topic also has education, learner, teacher, or practice context | Eligible |
| Generic AI, generic science, or generic education lacks the conjunction | Filter after bounded evaluation |
| Product fit is high while editorial scope is false | Remains ineligible; product signal cannot rescue it |
| Bounded window has only neutral titles and no body match | Successful zero-item job with filtered/probe counts and raw cursor |
| List/detail host, resolved IP, redirect, type, size, or timeout violates policy | Typed failure; no unsafe fallback |
| Fake-IP resolver returns `198.18.0.0/15` | `non_public_address`; fix DNS layer, never weaken SSRF |
| Source HTML changes and required article data disappears | Typed parse failure and connector/parser version update |

### 5. Good / Base / Bad Cases

- Good: eligible science/technology-education titles precede qualified frontier titles, which
  precede neutral probes; product direction breadth orders only inside the same cohort, then body
  evaluation confirms scope before persistence.
- Base: a bounded source window with no eligible title/body completes successfully with zero
  candidates and auditable filter/probe metadata.
- Bad: fetch the first headline per site, treat any HTTP 200 as useful evidence, accept ambiguous
  terms, let product fit override scope, or let a downstream LLM independently browse the link.

### 6. Tests Required

- [`test_editorial_relevance.py`](../../../backend/tests/unit/test_editorial_relevance.py) covers
  bilingual education/pathway/frontier positives, marketing/financing/product-release negatives,
  same-text bounded pathway substance, body bounds, product v1/v2 direction caps, and the
  eligibility/product separation.
- Connector contracts cover all eleven active and two pending source fixtures, ordering, exact
  article-path restrictions, duplicate anchor merging, sponsored/API/external/HTTP exclusion,
  parser drift, and source-specific selectors.
- Real PostgreSQL/MinIO tests assert no unrelated detail fetch, zero-match success/cursor behavior,
  body-probe/filter metadata, immutable snapshots, provenance, and no-refetch downstream use.
- Opt-in activation uses production-safe fetching, one entry and at most one detail per proposed
  source, and records only status/count/title/URL results. A failure omits that source from
  `SOURCE_SEEDS`; fixtures do not override the live gate.

### 7. Wrong vs Correct

#### Wrong

```python
items = connector.discover(list_response, profile, limit=1)
detail = await fetcher.fetch(items[0].url, profile)
```

#### Correct

```python
discovered = connector.discover(list_response, profile, limit=scan_limit)
evaluated = [
    (
        item,
        evaluate_science_tech_editorial_relevance(
            item.title,
            rule_version=profile.relevance_rule_version,
        ),
    )
    for item in discovered
]
education = sorted((row for row in evaluated if row[1].cohort == EDUCATION), key=editorial_key)
frontier = sorted((row for row in evaluated if row[1].cohort == FRONTIER), key=editorial_key)
neutral = (row for row in evaluated if not row[1].is_candidate)
window = [*education, *frontier, *neutral][:item_limit]
for item, _title_result in window:
    detail = await fetcher.fetch(item.url, profile)
    result = evaluate_science_tech_editorial_relevance(
        detail.title,
        detail.clean_text,
        rule_version=profile.relevance_rule_version,
    )
    if result.is_candidate:
        await persist(detail, result)
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
privacy/legal/safety uncertainty, prohibited marketing risk, and an audience-visible event repeat
inside the last seven days. For the active v4 policy, that repeat means a prior formal Enterprise WeChat job
with terminal `delivered` status through the typed selection/copy/package lineage; literal `.6`
and older stored policies retain selection-backed replay.

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

The current `scoring-v1-preview.11-qualified-authoritative-priority` gives 0.30 to tiered editorial
priority, 0.25 to product fit, 0.15 to source trust, and 0.10 each to source diversity, freshness,
and communication potential. It keeps genuine hard vetoes but does not add the historical
`outside_science_ai_education_scope` veto. Controlled Ministry education content may bypass the
0.59 numeric threshold only when no hard veto exists and title/summary proves a substantive
science-education policy, teaching practice, talent pathway, or frontier-education action. A
persisted China Government yaowen occurrence joins the same protected priority group only after it
has a current qualified cohort, zero vetoes, and eligibility from the ordinary threshold or the
existing governed hard-tech pool; the source policy never creates a new threshold bypass. The
current broad-recall policy also admits governed
Tier-A/B frontier hard-tech candidates to the LLM pool below 0.59 when no veto exists, while
persisting `passes_threshold=false` and its policy reason. Historical `.8` remains threshold-bound
for ordinary frontier candidates, preserves `.7` delivery-backed repeat provenance, and differs
only by its immutable scoring identity and 0.59 threshold; literal `.7` remains 0.62. `.7` differs from
literal `.6` through its immutable veto identity and delivery-backed repeat provenance. Their
editorial/product rules, Ministry priority/bypass, penalties, and ordering are identical. Historical `.5` configurations
keep their science/AI-education scope veto and disabled source priority, while `.4` keeps its legacy
feature map, policy-action requirement, and Ministry priority semantics on replay.

Select Top 1 only from eligible candidates. Ordinary candidates require `total >= threshold`;
authenticated Ministry education priority under `.6`/`.7`/`.8`/`.9` preserves historical v3
behavior; `.10` applies only its substantive v4 classifier and remains replayable; `.11` composes
that classifier with qualified China Government yaowen priority. Every bypass still requires zero hard
vetoes. Stable tie-breakers must be documented (for example source tier,
publication time, then stable ID). If none qualifies, persist
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

For English evidence, generator and auditor prompts receive both the exact English quote and an
optional Chinese governed fact/summary. The Chinese statement may support deterministic Chinese
copy checks, while the original evidence ID, URL, passage binding, and exact English quote remain
the provenance record. Never label the Chinese statement as an original quote, and never use
product-fit metadata or brand context as factual evidence. This prompt/data change uses
`copy-pipeline-v18-english-evidence`, `moments-generator-v18-xiaosai-insight`, and
`moments-auditor-v18-xiaosai-insight`.

## Validation and audit

Deterministic validation runs first and returns typed issue codes with field/claim locations. It
checks schema, required fields, evidence coverage, source tiers, source URLs, banned phrases,
lengths, date consistency, repeated-topic state, privacy/policy rules, image restrictions, and the
manual-publishing boundary. The parent-facing copy must use plain Chinese, explain why learning
science/innovation/AI/robotics is useful without grade or career promises, explain why the learning
experience belongs at Sai Xiansheng using supplied brand context, target 180-240 CJK Chinese
characters in the body, with a compression warning only above 260, and include 2-5 emoji excluding
the source footer and trailing hashtag line. The body must contain two or three natural paragraphs,
clearly separated for readability without a fixed blank-line count, and end with a separate line of two or three
hashtags whose first tag is always `#赛先生科学`. The copy body must start exactly with
`小赛洞察：` and continue directly with the news fact; generic lead-ins such as
`今天看到一条新闻` are no longer allowed. Immediately before the final hashtag line,
the system appends `新闻来源：<bound source name>` and
`原文链接：<bound HTTPS evidence URL>` from the first locked evidence item. The footer is
deterministic, is excluded from body counts/format checks, and remains a hard integrity check even
under local preview. Length, paragraph, emoji, and news-framing targets are quality guidance, not
delivery blockers. Under the current recovery rules, ordinary parent-readability, tone/fluency,
brand-fit, learning-value, brand-value, and hashtag-quality findings are also warning-only and may
consume the same single repair. Under `preview-v11-compact-content-warning-recovery`, privacy, prompt-injection
echo, prohibited marketing, education anxiety, `claim_not_in_copy`, `source_note_unlinked`, and
`unclaimed_external_fact` are also warning-only; detection and audit records remain persisted.
Automatic publishing, unsafe-image instructions, unknown IDs, truly unbound facts, evidence
mismatch, and a missing or mismatched bound source footer remain hard technical errors.

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
COPY_OPENING_PREFIX = "小赛洞察："
extract_copy_body(text: str) -> str
extract_copy_paragraphs(text: str) -> tuple[str, ...]
has_copy_paragraph_format(text: str) -> bool
has_copy_news_framing(text: str) -> bool
has_copy_news_source_footer(text: str, *, source_name: str, source_url: str) -> bool
append_copy_news_source_footer(text: str, *, source_name: str, source_url: str) -> str
count_hanzi(text: str) -> int
count_emojis(text: str) -> int
```

`COPY_OPENING_PREFIX` is shared by the generator prompt, deterministic fake generator, and
validator. `has_copy_news_framing` retains its historical name and warning code for stored-result
compatibility, but now means an exact prefix check at the first character of the copy body; whitespace,
emoji, or a generic news lead-in before `小赛洞察：` does not pass.

`extract_copy_body` removes the final hashtag-candidate line and a recognized source footer before
counting. `count_hanzi` counts only CJK Unified Ideographs; punctuation, whitespace, digits, Latin
letters, and emoji do not count. `has_copy_paragraph_format` accepts two or three non-empty natural
paragraphs separated for readability without a fixed line or blank-line count. `count_emojis` counts displayed emoji sequences, treating
variation selectors, skin-tone modifiers, and zero-width-joiner components as part of the preceding
emoji. The body target is 180-240 Hanzi and 2-5 emoji inclusive; only more than 260 Hanzi triggers
`copy_length`. Counts outside the emoji range
and missing news framing use `copy_length`, `copy_emoji_count`, or `copy_news_framing` with
`warning` severity under every preview and strict policy; the paragraph check uses
`copy_paragraph_format` with the same warning severity. The source footer check is a hard
`copy_news_source_footer` integrity issue. The count, format, framing, and footer results are
retained in the material package for inspection.

| Condition | Required result |
| --- | --- |
| Body has 261 or more Hanzi | `copy_length` warning; send one compression repair, then continue when no hard issue exists |
| Body has 260 or fewer Hanzi | Length check passes; prompt still targets 180-240 Hanzi |
| Body has fewer than 2 or more than 5 emoji sequences | `copy_emoji_count` warning; continue to audit and delivery when no hard issue exists |
| Body has 2-5 emoji sequences | Emoji check passes when other checks pass |
| Body does not have two or three natural paragraphs | `copy_paragraph_format` warning; continue to audit and delivery when no hard issue exists |
| Copy body does not start exactly with `小赛洞察：` | `copy_news_framing` warning; continue to audit and delivery when no hard issue exists |
| Footer source name or URL differs from the first locked evidence item | `copy_news_source_footer` error; do not accept or deliver |
| Tags appear only on the final line | Tags are validated separately and excluded from the Hanzi count |

Good: a two- or three-paragraph body starting with `小赛洞察：`, with 180-240 Hanzi, 2-5 emoji, the deterministic
source footer, and `#赛先生科学 #科学思维` has no format or source warning. If a body exceeds 260
Hanzi or misses a format target, those characters and layout defects remain visible as warnings;
padding with punctuation, ASCII, emoji, or hashtag text cannot conceal the Hanzi count.

Tests must assert the 260-character warning boundary, exclusion of punctuation/ASCII/emoji/trailing
tags and source footer, common variation-selector and ZWJ sequences, paragraph/newline cases,
the branded opening prefix, rejection of the retired generic lead-in, evidence-bound footer replacement, prompt wording, WeCom text preservation, and
continuation through audit for a warning-only draft. `copy_length`, `copy_emoji_count`,
`copy_paragraph_format`, and `copy_news_framing` remain advisory and can consume the existing
single product repair; `copy_news_source_footer` remains hard. A repaired draft with only advisory
warnings remains deliverable, while a missing/mismatched source footer or other hard error ends in
`review_required`. Do not implement a second repair loop or duplicate the counting logic in a
provider adapter.

The auditor is not a retrieval tool and cannot add evidence from model memory. It cannot override
a hard veto or deterministic failure. Regeneration receives structured issues and is bounded by a
configured maximum; exhaustion produces a terminal, reviewable run state.

## Automatic daily copy boundary

The content scheduler and content worker reconcile and claim copy-generation work only for the
current `BUSINESS_TIMEZONE` date. This boundary applies to automatic work, including process
startup and polling: a newly deployed worker must not backfill old selected topics merely because
their current copy-version fingerprint is absent. Historical queued runs remain durable for audit
and explicit, separately authorized recovery; they are not deleted, rewritten, or automatically
claimed. Repository reconciliation filters `DailyTopicSelectionModel.business_date`, and claiming
joins the durable copy run to apply the same date filter. Tests use an injected `now` value only
where a non-current business date must be exercised deterministically.

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
  version is `preview-v11-compact-content-warning-recovery`. Earlier preview rule versions remain available for
  historical behavior.
- Strict profiles use `COPY_RULE_VERSION`, currently
  `moments-rules-v11-compact-warning-recovery`.
- Current copy versions: generator `moments-generator-v18-xiaosai-insight`, auditor
  `moments-auditor-v18-xiaosai-insight`, and pipeline `copy-pipeline-v18-english-evidence`.
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
- Preview-v1, preview-v2, and preview-v8 preserve their historical warning mappings. Under the
  current `preview-v11-compact-content-warning-recovery` policy, the ordinary-quality allowlist remains
  warning-only and privacy, prompt-injection echo, prohibited marketing, education anxiety,
  `claim_not_in_copy`, `source_note_unlinked`, and `unclaimed_external_fact` are warning-only as
  well. Detection and issue persistence remain active, and the existing one-repair budget still
  applies. Under strict `moments-rules-v11-compact-warning-recovery`, those content findings remain
  errors. Automatic-publishing, unsafe-image instructions, truly unbound facts, evidence-text
  mismatch, source-footer integrity, and unknown evidence/brand IDs remain errors in every profile.
  The persisted audit verdict is always the policy-adjusted verdict.
- The copy body target is 180-240 CJK Hanzi, with warning plus one compression repair only above
  260 Hanzi. It has two or three natural paragraphs clearly separated without a fixed blank-line count and two to five
  emoji; it has no fixed line count or forced emoji positions.
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
| Current `preview-v11-compact-content-warning-recovery` policy sees privacy, injection echo, prohibited marketing, anxiety, `claim_not_in_copy`, `source_note_unlinked`, `unclaimed_external_fact`, or `unbound_date` | Persist warning; repair at most once, then continue when no hard error remains |
| Current copy policy sees automatic publishing, unsafe-image, truly unbound facts, evidence mismatch, or source-integrity issue | Keep error; repair once if applicable, otherwise finish `review_required` |
| Strict audit returns `unsupported_implication`, privacy, anxiety, injection, unsafe image, or automatic publishing | Keep error; repair once or finish review-required |
| Deterministic rule detects a prohibited promise such as guaranteed score improvement | Persist `prohibited_marketing` as a warning under `preview-v11-compact-content-warning-recovery`; keep it as an error under strict and historical policies |
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

Controlled v2 artifacts additionally follow
[`visual-diversity.md`](./visual-diversity.md): two plans are reserved before the provider call,
similarity is evaluated only after existing image quality gates, and a safe second near duplicate
is accepted with a warning rather than becoming a hard veto. Historical v1 artifacts retain this
scenario's exact behavior.

### 1. Scope / Trigger

- Trigger: an accepted draft/image prompt must produce exactly one stored image. This is a
  cross-layer contract (AI provider, MinIO storage, DB artifact, controlled download API).
- Only an accepted draft may call the image provider. `no_topic` and failed drafts never reach it.

### 2. Signatures

- Active local provider origin: `https://ai.comfly.org`; the model remains configurable and is
  currently `gpt-image-2`. The old `toapis` adapter remains an explicit rollback mode.
- Comfly generate: `POST /v1/images/generations` with `model`, a validated bounded `prompt`,
  `size=1024x1024`, `response_format=url`, and an optional ordered
  `image=[data:image/png;base64,...]`
  tuple containing approved local references. Each reference carries a role, asset ID, filename,
  checksum, and bytes in the provider-neutral request; private MinIO URLs and provider upload URLs
  are never sent. The default aggregate reference budget is 3 MiB (`IMAGE_REFERENCE_BUDGET_BYTES`),
  which keeps the encoded request within the provider's practical payload envelope while retaining
  real Sai Xiansheng/Xiaosai identity assets.
- The accepted topic/copy produces a bounded `VisualBrief`; the deterministic selector persists its
  catalog/selector versions, ordered reference roles/checksums, selection reasons, and an explicit
  `reference_mode` (`single_reference`, `budgeted_multi_reference`, or `single_fallback`). The raw
  Moments copy is never used as the image text layer.
- Response: accept exactly one non-empty synchronous `data[].url` or `data[].b64_json`; the other
  field may be omitted or present as an empty string because Comfly returns both placeholders in
  some successful responses. If the gateway returns a safe task identifier and a pending status,
  poll `GET /v1/images/tasks/{task_id}` after the configured initial delay and interval, bounded by
  the provider window.
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
  `image_poll_interval_seconds`, `image_provider_timeout_seconds` (default 300s, 1-300),
  `image_provider_window_seconds` (default 300s, 2-300), `image_max_download_bytes`
  (1 KiB-50 MiB), `image_max_request_bytes`, `image_max_provider_response_bytes`,
  `image_max_reference_images` (default 3), `image_reference_budget_bytes` (default 3 MiB),
  `image_asset_manifest`, `image_selector_version`, and `image_selector_enabled`.
- A material-package image call may outlive the `content_lease_seconds` value: the executor starts
  its `content_heartbeat_seconds` loop before the provider call and renews the image lease while the
  async request or polling is in progress. The heartbeat must remain shorter than the lease; a lost
  heartbeat fences the result and prevents persistence of an image produced by a stale worker.
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
| Non-empty `b64_json` cannot be decoded strictly | Persist the safe representation reason; queue one unchanged-prompt output recovery, then use the reserved catalog fallback |
| 429/503 during polling | Honor `Retry-After`, retry within the configured provider window (300s by default) |
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
- Image OCR and image quality audit are separate provider capabilities. When controlled OCR is
  enabled with a real image provider and Zhipu AI mode, the worker uses dedicated `glm-ocr`
  `/layout_parsing` with bounded PNG/JPEG Base64 input and strict layout projection. It does not
  send an image to the text-only `AI_CHAT_MODEL`, and it does not change the disabled
  OpenAI-compatible image-quality auditor route.
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

## Scenario: Bounded image-provider output recovery

### 1. Scope / Trigger

- Trigger: an accepted material package receives either typed non-retryable
  `image_provider_rejected` or the exact adapter reason `image_output_representation_invalid`.
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
- The first representation failure uses the same compatibility counter/wire state but persists
  `initial_error_code=image_output_invalid`. It keeps the original controlled prompt, plan, and
  reference order while deriving a distinct replay-stable provider request fingerprint. Its safe
  `provider_output` validation snapshot contains only the allowlisted reason and provider/model.
- A second representation failure uses the reserved catalog fallback without a third provider
  request. URL/address, redirect, media/signature, size, dimensions, provider identity, OCR parser,
  and other security/integrity failures remain terminal and never enter this recovery.
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
| First invalid image representation | One safe warning/snapshot, unchanged prompt/plan, distinct stable fingerprint, and one durable queued retry |
| Second invalid image representation with reserved asset | Private validated catalog fallback with `initial_error_code=image_output_invalid`; no third provider call |
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

- `test_image_fallback.py` asserts neutral prompt isolation, rejection/representation fingerprint
  separation and replay stability, square
  aspect-safe rendering, and invalid asset rejection.
- `test_material_package.py` asserts one scheduled retry, unchanged representation-recovery prompt
  and plan, second-rejection/representation catalog persistence,
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
- A `.7` event formally delivered inside six business-date days and a below-threshold candidate
  both stop before generation; selected-but-undelivered history and the day-seven boundary proceed.
- A draft with an unbound fact fails deterministic validation and never reaches audit.
- Prompt-injection text in a snapshot remains quoted data and cannot alter stage instructions.
- Audit retry exhaustion preserves issues and artifacts for internal review.
- The final OpenAPI contract exposes no automated publishing operation.

## Three-slot independent production

The legacy daily Top 1 pipeline remains the default compatibility path. When the separately gated
slot mode is enabled, each `morning`, `noon`, or `evening` selection is an independent aggregate
with exact acquisition/governance lineage and 0--3 ordered selections. Each selection creates its
own discriminated copy origin, copy run, image artifact and material package; never combine sibling
topics in one prompt, draft or image. Operational slot/ordinal/target/expiry metadata may enter
safe provenance snapshots and fingerprints but may not add factual claims or replace evidence.
The database origin XOR and composite identity foreign keys must reject a copy, selection, or
delivery row cross-wired to another slot event, ordinal, acquisition lineage, or delivery window.

One sibling's `no_topic`, failure, review requirement, image fallback or delivery result must not
cancel, duplicate or retry another sibling. The upper bound is nine distinct package identities per
business date. Fake-provider acceptance must cover 0--3 results, exact replay, sibling isolation and
the existing full-length evidence-bound copy/image policy without external calls.

## Scenario: Local official-account article and simulated draft

### 1. Scope / Trigger

- Trigger: a developer explicitly creates a long-form official-account article from one eligible
  material package, or runs the built-in sanitized fixture.
- This is a local review workflow only. It adds no account credential, token, upload, `draft/add`,
  publish, send, or Enterprise WeChat operation and does not change the existing Moments copy,
  material-package, or WeCom contracts.

### 2. Signatures

- API:
  `GET /api/v1/official-account-local/capabilities`,
  `GET|POST /api/v1/official-account-local/article-runs`,
  `GET /api/v1/official-account-local/article-runs/{run_id}`,
  `POST /api/v1/official-account-local/article-runs/{run_id}/retry`,
  `POST /api/v1/official-account-local/article-runs/{run_id}/manual-review`,
  `GET /api/v1/official-account-local/media/{local_media_id}`, and
  `GET /api/v1/official-account-local/drafts/{local_draft_id}/preview`.
- Worker: `python -m app.official_account_worker_main`.
- Offline demo: `make official-account-local-demo`.
- Explicit live smoke:
  `make official-account-local-live-smoke MATERIAL_PACKAGE_ID=<uuid>`.
- Review export:
  `python -m app.official_account_local_cli export --run-id <uuid> --output-dir <dir> --mode review|copy-ready`.
- Explicit live-local review export (CLI only):
  `python -m app.official_account_local_cli export --run-id <uuid> --output-dir <dir> --mode review --allow-live-local-export`.
  This does not create an HTTP export API and is not a publishing operation.
- Manual-review request is strict JSON
  `{decision: "approved"|"rejected", reviewer_label: string[1..80], note: string[1..2000]|null}`.
  Its response projects `status`, `review_id`, normalized reviewer/note, `reviewed_at`, the immutable
  request fingerprint, `idempotent_replay`, and `editorially_approved`; it never changes the run's
  generated artifacts.
- Migration `20260821_0026` adds `official_account_article_runs`,
  `official_account_article_versions`, `official_account_article_attempts`,
  `official_account_render_versions`, `official_account_local_media`, and
  `official_account_local_drafts`.
- Migration `20260822_0027` adds current Article v2/multi-image support: body ordinals `0..4`,
  cover ordinal `0`, per-run body-checksum uniqueness, and ordered draft/body associations whose
  four-column FK binds `(media_id, run_id, media_role='body', ordinal)` to the exact media row.
- Migration `20260823_0028` adds immutable, run-bound manual editorial decisions and upgrades the
  article-version check to accept frozen v1/v2 plus current v3. A ready local draft is required
  before a decision; exact replays are idempotent, a conflicting final decision is rejected, and
  model/inherited review remains separate from the human decision.
- Migration `20260823_0029` accepts current Article v4 with an immutable multimodal-selection
  snapshot. Migration `20260823_0030` adds immutable Article v5 artifacts for the v8
  structured-output identity. Downgrade refuses while the corresponding v4 or v5 article exists;
  it never discards a selection snapshot or v8 artifact to manufacture an older row.

### 3. Contracts

- `OFFICIAL_ACCOUNT_LOCAL_ENABLED=false` and
  `OFFICIAL_ACCOUNT_LOCAL_WORKER_ENABLED=false` are the safe defaults. Fixture execution forces
  `AI_PROVIDER_MODE=disabled` and `CONTENT_LLM_RERANK_ENABLED=false`, constructs no HTTP client,
  uses only bundled sanitized data/image bytes, and makes zero external requests.
- A live create requires `generation_mode=live`, one eligible persisted material-package UUID,
  and a fully configured server-side Zhipu provider. The API enqueues only; one independent worker
  performs generation and audit outside database transactions. The structured provider transport
  uses disabled thinking, JSON-object mode, HTTPS/no redirects, bounded correction, and persists
  only safe request ID/usage/latency metadata.
- Article Package v1/v2/v3 are frozen and `extra="forbid"`; current new runs use
  `official-account-article-schema-v4-multimodal-media`. External facts bind only allowlisted evidence
  IDs, brand statements bind only allowlisted brand-chunk IDs, and opinions bind neither. Model
  output never owns HTML, CSS, URLs, media identities, or platform fields.
- Generator and rule identities are an exact pair. New work uses
  `official-account-generator-v5-structured-output` with `official-account-rules-v4-reader-copy`
  and auditor `official-account-auditor-v2-structured-output`; unknown or mixed pairs fail closed.
  Historical v1--v7 prompt and initial transport bytes remain replayable. Only v8 carries the
  canonical Pydantic output schema in its initial system instruction (and the audit's conditional
  `accepted`/`issue_codes`/`claim_ids` invariant); all initial system and user text count toward
  the input limit, while its one correction remains bounded. The
  current deterministic identities are `official-account-media-plan-v3-multimodal-hybrid`,
  `official-account-visual-query-v1`,
  `official-account-visual-selector-v3-multimodal-hybrid`,
  `wechat-html-renderer-v7-multimodal-media`,
  `wechat-inline-science-field-guide-v7-multimodal-media`,
  `wechat-science-field-guide-template-v7-multimodal-media`, and
  `official-account-local-adapter-v5-multimodal-media`. Renderer v1-v6 and adapter v1-v4
  bytes, fingerprints, media formats, placement, export, and recovery remain immutable.
- A saved third-party editorial page may be inspected offline as untrusted design research. Record
  only measured structural observations and adopt abstract information patterns such as a reading
  map, restrained section rhythm, judgment/action cards, and a bounded conclusion. Never copy its
  prose, HTML, images, mascot, QR code, course promotion, anxiety language, or unsupported claims
  into source, fixtures, prompts, or exports.
- The application, never the article model, owns the media plan. Current v3 accepts one to five
  contiguous body slots, targets three to five when distinct approved candidates exist, distributes
  them after different sections, and never duplicates a checksum. The offline fixture uses three
  immutable publication JPEGs plus a distinct wide cover and never constructs a visual provider
  client. Explicit live multimodal mode may rank only the current manifest-approved 41-item brand
  catalog; the material-package primary image remains the distinct cover. It never searches the
  web, generates a replacement, scans arbitrary files, or lets similarity admit an ineligible item.
- Semantic placement uses the balanced section plan first, then maximizes a bounded one-to-one
  assignment: every normalized tag found in the heading contributes 100, every tag found in the
  first 360 body characters contributes 20, and ties keep candidate order by
  `(publication_priority, sha256, candidate_id)`. The only public reason codes are
  `semantic_heading_match|semantic_body_match|stable_fallback`; fixture placement is exactly after
  section indexes `0, 2, 3`.
- `OFFICIAL_ACCOUNT_LOCAL_VISUAL_SEMANTIC_ENABLED=false` is independent and safe by default. When
  explicitly enabled for live generation, all 2--41 candidates and all at-most-five bounded section
  queries must validate before index preflight or client construction. PostgreSQL proves exact
  catalog/provider/model/dimension/input-policy coverage before the first query and rechecks after
  every result. One request per placement is allowed; there is no correction or retry.
- The v7 selector uses bounded placement-bitmask dynamic programming, maximizing complete cosine
  similarity first, frozen tag score second, then stable priority/checksum/public reference. Any
  unsafe query, incomplete index, provider/result failure, or catalog race discards the entire
  matrix and runs deterministic tag fallback on a freshly validated candidate set. Article v4/v5
  stores only bounded identity, query fingerprints, closed status/reason, similarity bands and
  ordered assignments before render; retry/recovery performs zero embedding queries.
- Runtime media uses immutable MIME-aware publication derivatives, not the large PNG masters. The
  repository fixture is RGB JPEG, quality 82, 4:2:0, non-progressive, non-optimized, with
  EXIF/ICC/text metadata stripped; the original PNG master bytes stay untouched. Body assets are
  1536x1024 and the distinct cover is 1923x818. Export chooses `.jpg` from verified JPEG bytes and
  rejects a declared MIME/signature mismatch.
- Catalog media resolution binds the 16-character public reference, catalog version, immutable PNG
  master checksum and deterministic JPEG publication checksum at the final read. Adapter v5
  regenerates and verifies metadata-free publication bytes without persisting or exposing the
  private filename, path, raw asset ID, query text, vector or raw score. Partial lineage fails
  closed instead of substituting a fixture or cover image.
- The deterministic renderer escapes every data value and produces fixed inline-style HTML with
  exact ordinal body/cover placeholders. Canonical placeholder HTML and resolved local-draft HTML
  have separate stable fingerprints. The worker stages only missing ordinals, replaces every
  expected placeholder exactly once, rejects missing/extra/duplicate media, and records all ordered
  body associations before draft completion. `body_image` remains the ordinal-zero compatibility
  API projection; `body_images` is the authoritative ordered list and `media_selection` is bounded
  safe provenance. Body and cover remain non-interchangeable role-scoped rows/IDs.
- Public status is `queued|running|review_required|ready|failed|result_unknown`; `current_stage`
  retains the detailed stage. Claims use `FOR UPDATE SKIP LOCKED`, leases, heartbeats, and fencing.
  Successful article/render/media artifacts are immutable and reused after a later-stage failure.
  An ambiguous local-draft outcome becomes `result_unknown` and is never retried.
- POST create/retry returns HTTP 202 plus `Location`. Detail omits raw/resolved HTML, prompts,
  provider bodies, private brand text, object paths, and credentials. Preview is the sole HTML
  response and applies no-store, nosniff, no-referrer, and strict CSP headers; the development-only
  UI uses a permissionless sandbox iframe and generated OpenAPI types.
- The fixture and API always project `simulation=true` and `本地模拟，未同步公众号`. The frontend is
  lazy-loaded only when Vite development mode and
  `VITE_OFFICIAL_ACCOUNT_LOCAL_ENABLED=true` are both true.
- Export prose is renderer-versioned alongside HTML. For v4, `article.md` and `sources.json` use
  “家庭实践”, “给家长的三句话”, and “资料来源与适用边界”; historical renderers keep their historical
  labels. The current `official-account-review-bundle-v4-multimodal-media` exports every planned body
  image as MIME-aware `assets/body-00.jpg` through `body-04.jpg`, includes the ordered list in its
  manifest and binds the v7/v8 selection snapshot, and requires an exact, symlink-free tree for
  idempotent reuse. Pending/rejected review
  bundles retain warning chrome. Only an immutable approved manual-review row permits a separate
  copy-ready tree/fingerprint with that warning removed; it never overwrites or reuses a pending
  bundle. The copy-ready manifest, preflight aggregate, and every manual-review preflight record
  must all say approved; the review fingerprint participates in its immutable path and ZIP
  identity. Fixture no-link explanations name the renderer that actually produced the artifact.
- Fixture export remains the default. A ready simulated `generation_mode=live` run may be exported
  only by the explicit CLI flag `--allow-live-local-export` in review mode. That creates a separate
  `live-local-review-*` tree and deterministic ZIP with relative asset URLs, `LOCAL ONLY · 未同步公众号`,
  `export_scope=live_local`, `copy_ready=false`, and `published=false`; an existing manual-review
  state is recorded but never converted to approval. There is no HTTP export endpoint.
- The API media route and CLI export use the same `OfficialAccountLocalMediaResolver`. Before a byte
  leaves infrastructure it revalidates the persisted fixture/catalog/source-image lineage, MIME,
  byte size and SHA-256, and finishes its database read before filesystem/MinIO I/O. Catalog paths,
  MinIO bucket/object keys and private filenames never enter the exported bundle.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Fixture with blank provider configuration | One complete ready local draft; no network client or external request |
| Live create without a complete Zhipu configuration | Fail closed before enqueue/provider work; fixture remains available |
| Unknown evidence/brand ID, mixed binding type, invalid length/structure, or provider identity drift | Typed validation/review failure; no render or draft |
| Same source/mode/provider/model/version fingerprint is submitted concurrently | Return the one durable run; no duplicate model/artifact call |
| Lease expires before persistence | A new worker may reclaim; the stale lease token cannot write |
| Render/body-media/cover/draft confirmed failure | Bounded retry resumes from the first missing stage and reuses prior artifacts |
| Draft result is ambiguous | Persist `result_unknown`; automatic and explicit retry both refuse |
| Preview contains model text resembling HTML/script/event attributes | Return escaped text only under the fixed CSP document |
| Body and cover use the same source bytes | Persist different role-scoped media IDs and reject role interchange |
| Any generator/rule/schema/media-plan/renderer/style/template/adapter/auditor identity is unknown or crosses a supported version family | Fail closed before provider/export work; never guess a compatible artifact |
| v4 HTML is exported with historical Markdown/source labels | Reject in regression tests; select export labels from the pinned renderer version |
| Saved reference page contains promotional claims, QR codes, or remote assets | Treat as untrusted research; do not ingest or reproduce them in the product artifact |
| Current media plan has a gap, more than five body slots, duplicate checksum, missing placeholder, or extra replacement | Fail closed before local draft completion; preserve already valid per-ordinal artifacts for retry |
| Live package exposes only one approved image | Produce one body slot with an explicit safe-degradation projection; do not duplicate, fetch, or generate images |
| Draft/body association points to another run, cover role, or different ordinal | PostgreSQL four-column FK/check rejects the write |
| Same body checksum is staged twice for one run, even under different renders | PostgreSQL partial unique index on `(run_id, sha256)` rejects the duplicate |
| Manual review targets a missing, non-ready, incomplete, or non-simulated draft lineage | Return 404/409; create no review row |
| Exact normalized manual-review payload is replayed | Return the immutable decision with `idempotent_replay=true` |
| A second manual-review payload conflicts with the final row | Return HTTP 409; never overwrite the original decision |
| Pending/rejected run requests `--mode copy-ready` | Fail closed; preserve the independently exportable warning-bearing review bundle |
| Live run reaches export without `--allow-live-local-export`, requests copy-ready, is not ready/simulated, or uses a root target directory | Fail closed before reading/writing media; fixture default is unchanged |
| Live-local media catalog/source checksum, MIME, size, lineage, or relative-HTML replacement drifts | Fail closed and remove the temporary directory; never substitute an asset or expose private storage data |
| Version family, derivative signature, export tree, or copy-ready preflight state drifts | Refuse recovery/export instead of guessing compatibility or reusing the directory |
| Any candidate or section query is invalid | Zero index preflight/client/embedding calls; deterministic closed fallback only after a fully valid refreshed candidate set exists |
| Complete-index preflight fails or fewer than two eligible candidates remain | Zero embedding calls; record closed unavailable/single-candidate status and use deterministic fallback |
| A later embedding query/result fails | Discard every earlier score; never persist a partial semantic/tag plan |
| Catalog version/master/publication checksum changes after ranking | Fence the result, reload all 41 candidates and fall back, or fail media staging if the persisted lineage changed |
| Retry sees a persisted Article v4 or v5 | Reuse its ordered snapshot; make zero semantic calls |

### 5. Good / Base / Bad Cases

- Good: the fixture creates three distinct, section-distributed body images and an independent
  cover; API, preview, workbench gallery, Markdown, manifest, and ZIP expose the same ordinal order.
- Good: an explicit live run with complete current catalog coverage ranks only approved body-safe
  assets, persists one complete snapshot, and uses the material image only as its separate cover.
- Good: an operator explicitly invokes live-local CLI export for a ready simulated run and receives
  a relative-asset review ZIP that preserves `pending|approved|rejected` history while saying local
  only, never published, and not copy-ready.
- Base: the provider-free fixture creates the same complete durable shape idempotently and is safe
  for tests and local demonstrations with networking unavailable; a one-image live source remains
  valid and explicitly degraded.
- Bad: generate model HTML, call a provider from the API handler, reuse a cover ID as body media,
  recreate a draft after an ambiguous result, expose private storage/provider data, or add a
  WeChat/publish control.
- Bad: copy a reference account's page/module markup or branding, mix prompt/rule versions, or let
  export labels drift from the pinned renderer while the preview displays a newer vocabulary.
- Bad: repeat one attractive picture three times, let the LLM choose image URLs/positions, associate
  ordinal 2 with ordinal 1's row, or scope duplicate detection only to a render instead of the run.
- Bad: add a web export route, treat a live-local archive as manual approval, export a real run by
  default, or duplicate the API's media-read integrity checks in the CLI.

### 6. Tests Required

- Domain/renderer unit tests assert strict schema, stable canonical fingerprints, claim allowlists,
  hard length/structure bounds, escaped text, allowlisted links/tags, and exact media replacement.
- Golden tests assert exact v1/v2/v3 prompt bytes, exact v1-v6 renderer bytes/fingerprints, the
  current v4 prompt/rule pairing, deterministic v7 output, AA color contrast, and fail-closed
  behavior for every mixed/unknown version pair.
- Multimodal tests assert complete fake-41 reordering, 5x41 bounded DP ties, all-query validation
  before preflight/client work, zero-call disabled/incomplete/unsafe cases, whole-matrix fallback,
  refreshed catalog-race fallback, final media-lineage fencing, and recovery without requery.
  Provider tests remain fake/MockTransport and make no live request.
- Export tests assert v4 `article.md`/`sources.json` labels and fixture source policy, while also
  asserting that historical renderer exports retain their original labels. Current tests also
  assert all publication-derivative hashes/dimensions/metadata, MIME-derived filenames, exact
  double-export reuse, pending/rejected warning bundles, approved-only copy-ready identity, and
  consistent approved preflight records.
- CLI/media tests assert default real-run rejection, explicit ready live-local export with body
  derivatives and source cover, relative-only media references, pending-review truth, deterministic
  reuse, no copy-ready/published label, and cleanup on catalog/source integrity mismatch. The
  resolver is tested by both API and CLI consumers without provider or social-service calls.
- MockTransport provider contracts assert success, bounded schema correction, timeout/auth/rate
  classification, identity/usage projection, and absence of raw prompt/response persistence. They
  never contact a live model.
- Real PostgreSQL integration asserts migration/metadata parity, concurrent idempotency, lease
  reclaim/fencing, body/cover role isolation, body ordinal/checksum constraints, strict four-column
  draft/body lineage, v1 backfill, partial per-ordinal resume, explicit failed-run retry, and
  `result_unknown` non-retry. It also asserts the ready-only manual-review gate, exact replay,
  four-way concurrency, immutable conflict, and downgrade refusal after v3/review or v4 selection artifacts.
  Migration tests inspect semantic columns/SQL, not truncated generated constraint names.
- API/frontend tests assert HTTP 202/Location, safe detail projection, media and preview headers,
  ordered `body_images`, compatibility `body_image`, bounded selection provenance, accessible
  gallery, polling stop, permanent simulation boundary, permissionless iframe,
  generated-contract use, and absence of unsafe HTML or publishing/credential controls.
- Runtime acceptance asserts the Compose profile builds, the offline fixture reaches `ready`, the
  worker reports live provider unavailable, and non-default host ports are reflected in the safe
  browser URL.

### 7. Wrong vs Correct

#### Wrong

```python
@router.post("/official-account-runs")
async def create_run(payload):
    html = await model.generate(payload)
    return await wechat.draft_add(html)
```

This performs unversioned external work in the API process, trusts model markup, and crosses the
prohibited social-platform boundary.

#### Correct

```python
run, created = await repository.enqueue_material_package(
    material_package_id=payload.material_package_id,
    identity=version_identity,
)
# The independent worker later claims the durable run and executes typed stages.
return AcceptedRun(id=run.id, created=created, status=run.status)
```

The correct form returns durable state immediately; the worker validates a structured Article
Package and creates only a local simulated draft through typed adapters.

For multi-image resolution, passing an untyped list or replacing every placeholder with the first
URL is wrong. The correct form claims the pinned media plan, stages each missing `(role, ordinal)`
under its own fingerprint, persists strict draft/body lineage, then resolves an exact
`slot_key -> controlled media URL` map and refuses gaps, extras, or duplicate bytes.

For reference-driven presentation work, copying a saved page into the renderer or fixture is also
wrong. The correct form records bounded observations in task research, implements an original
versioned renderer using only governed Article Package fields, and freezes both historical HTML
goldens and renderer-specific export vocabulary.

## Scenario: Automated approved-IP body visuals (official-account-local v2)

### 1. Scope / Trigger

- Trigger: an approved local-only follow-up turns the prior manual IP-reference supplement into an
  additive official-account worker stage. It produces original per-section **body** illustrations;
  it is never a publish, WeChat, or WeCom capability.
- The current article's existing manual editorial review and approved-only copy-ready behavior do
  not review, approve, or block an individual image. There is deliberately no image-review gate.

### 2. Signatures

- DB: `official_account_local_generated_visuals` is immutable by
  `(render_version_id, ordinal)` and `request_fingerprint`; local body media may reference it via
  `official_account_local_media.generated_visual_id`. The database shape constraint binds the
  complete version tuple: historical plan v1 requires prompt v1 and nullable v2-only fields;
  block-anchor plan v2 requires prompt v2 plus every anchor/input/output-profile field. Never
  validate `plan_version` without its matching `prompt_version`.
- Worker: `OfficialAccountLocalExecutor(..., generated_visuals_enabled, image_generator,
  generated_visual_store, generated_visual_provider, generated_visual_model)` may generate only
  after the persisted Article v8 media-selection snapshot exists.
- API detail: `generated_visuals[]` exposes ordinal, section, safe public reference, selection
  method/band, bounded block position/kind, plan/output-profile identity, provider/model, status and
  output metadata. While `generating_body_visuals` has not staged media yet, the safe planned total
  comes from the persisted media-selection snapshot assignments rather than the current media row
  count. It has no create, approve, publish, provider-body, or prompt endpoint.

### 3. Contracts

- `OFFICIAL_ACCOUNT_LOCAL_GENERATED_VISUALS_ENABLED=false` is the default. Enabling it requires
  the local worker, `IMAGE_ENABLED=true`, `IMAGE_PROVIDER_MODE in {fake,toapis,comfly}`, and
  `IMAGE_MAX_ATTEMPTS=1`; current plan/prompt settings must equal the v2 block-anchor literals.
  Historical v1 dispatch retains its original request fingerprint, section-first-360 prompt,
  PNG provider request bytes, and raw result bytes.
- For each selected body placement, use only its revalidated public reference from the exact,
  complete 41-item Qwen3-VL approved-catalog snapshot. If semantic selection/index capability is
  absent, use its persisted deterministic-selector snapshot; never search or read arbitrary files.
- Persist the intent before calling the image port. Build prompt text only in memory. Store only
  safe reference/checksum/version/fingerprint/provider/result metadata plus bounded block
  index/kind/fingerprint; never persist or expose block text, a prompt, raw catalog ID, vector,
  private path/object key, reference bytes, or provider body.
- Select one eligible semantic block inside the assigned section and construct the transient v2
  scene brief from that exact block, heading, and topic. Bind the anchor, reference-input
  normalization identity/checksum, prompt hash, and output profile to the request fingerprint.
- Preserve exact valid PNG provider bytes. For v2 catalog JPEG references, verify the publication
  checksum and deterministically normalize to metadata-free PNG before ToApis/Comfly request
  construction. Persist the generated v2 publication artifact itself as metadata-free
  `image/jpeg` at exactly 1536×1024; local media, HTML, and export resolve those same bytes.
- The image port and MinIO write execute outside DB transactions. Fixture/default execution must
  not instantiate an image client and makes zero external requests. No WeChat or WeCom adapter is
  introduced or called.
- A paid live acceptance is an explicit operator-only action, never part of fixture/default tests.
  It must pass an offline `--preflight-only` run, force Comfly plus `image_max_attempts=1`, reserve
  a new output directory with an exclusive paid-call intent before network I/O, and allow exactly
  one generation attempt. Validate provider/model/request identity and the complete 3:2 artifact
  before writing the success bundle. The safe bundle may contain checksums, version identities,
  dimensions and call counters, but never a credential, Authorization header, provider URL/body,
  raw prompt, or private storage path.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Disabled or fixture run | Existing selected-catalog media path; zero image client/provider calls |
| Feature identity/configuration drifts | Fail closed before image I/O |
| Persisted plan/prompt versions form a mixed v1/v2 tuple | Reject at the application and database boundaries |
| Incomplete semantic capability | Reuse deterministic selection snapshot; never broaden the catalog |
| Existing `generating` intent after a worker interruption | Mark `result_unknown`; do not issue a second image request |
| Provider timeout after durable intent | Persist `result_unknown` immediately; recovery must issue zero image requests |
| Paid live-acceptance output directory or intent already exists | Refuse replay before provider I/O |
| Paid live-acceptance credential appears in terminal/tool output | Treat it as exposed and rotate it immediately; never copy it into artifacts or reports |
| Existing `failed` intent is recovered | Preserve deterministic `failed`; do not relabel it `result_unknown` and do not call the provider |
| Image/output/provider identity validation fails | Persist safe non-retryable `failed`; no hidden image retry |
| Stored state shape is inconsistent | Reject it: `generating` has no completion/error/output; failed/unknown require error and completion; ready requires the full output tuple |
| Ready output is staged | Require the generated-visual FK plus the same run/render/ordinal, MIME, size and checksum before local media resolution |

### 5. Good / Base / Bad Cases

- Good: a live v8 run uses one already-selected approved public reference per body section, stages
  validated generated bytes, then still waits for the normal article manual-review event before
  copy-ready export.
- Base: fixture, disabled mode, or unavailable multimodal index never creates an image provider;
  the deterministic catalog snapshot remains the bounded source.
- Bad: let an LLM select a path/URL, retain its prompt/provider response, call the provider inside
  a transaction, retry an uncertain paid call, add an image approve/reject state, or add WeChat
  publishing.

### 6. Tests Required

- Unit-test deterministic block anchoring, transient prompt construction, safe plan projection,
  fake-image validation, provider/model fingerprint drift, exact 3:2 metadata-free output, and a
  fixed historical v1 request fingerprint.
- No-network provider-builder tests prove PNG byte identity and deterministic JPEG-to-PNG inputs
  for ToApis/Comfly.
- Test setting validation and fixture behavior, including when the live feature flag is enabled,
  prove no image client/request is made.
- Repository/migration tests cover immutable intent/recovery, exact state shapes, ready-only
  generated-media FK, same-run/render lineage, complete plan/prompt version tuples and no leakage
  through API/media/export; API/OpenAPI tests expose only safe result fields and prove the planned
  total is non-zero before the first generated media row exists.
- Worker tests distinguish deterministic `failed` from uncertain `result_unknown`, make both
  recovery paths perform zero provider/storage/catalog reads, and keep deterministic catalog
  selection labeled `stable_fallback` rather than `multimodal_similarity`.
- Live-acceptance harness tests remain fully offline and assert provider/attempt/version preflight,
  exclusive-intent replay refusal, JPEG-to-PNG reference identity, timeout-to-unknown with one call,
  success-bundle redaction and validation-before-write ordering. A completed live acceptance records
  attempted/succeeded call counts and the zero-call article/embedding/WeChat/WeCom/publish boundary.

### 7. Wrong vs Correct

#### Wrong

```python
image = await provider.generate(prompt)  # no durable intent, then retry on timeout
article.body_images.append(image.url)
```

This loses idempotency, leaks a provider-controlled URL, and can double-charge after an uncertain
request.

#### Correct

```python
reference = normalize_v2_provider_reference(revalidated_selected_reference)
plan = plan_generated_body_visual(..., reference=reference, block_anchor=selected_block)
intent = await repository.create_generated_visual_intent(claimed=claimed, plan=plan)
# Call image port outside the transaction only for the newly-created intent.
result = await image_generator.generate(request)
publication = prepare_generated_visual_result(result=result, plan=plan)  # exact 1536×1024 JPEG
await store.put_immutable(publication.image_bytes, media_type=publication.result.media_type)
await repository.persist_generated_visual(
    claimed=claimed, plan=plan, result=publication.result
)
```

The plan pins a safe public-reference lineage. Recovery treats an unconfirmed external request as
unknown rather than repeating it, and the usual article-level local/manual-review boundary remains
in force.

Treating every non-ready recovery as unknown, or resolving a generated image by FK/hash alone, is
also wrong. Preserve a known `failed` outcome as failed; use `result_unknown` only for an abandoned
`generating` intent. Before returning stored bytes, bind the ready output to the same run, render
and ordinal as the local-media row, then revalidate MIME, size and SHA-256.

## Scenario: News-backed visible-IP official-account demo (v3)

### 1. Scope / Trigger

- Use this operator-only additive flow when an official-account demonstration must bind current
  authoritative news to newly generated body images with a clearly visible approved company IP.
- It never replaces historical runs or v1/v2 identities and never enables WeChat, WeCom, or publish.

### 2. Signatures

- Plan/prompt pair: `official-account-generated-visual-plan-v3-visible-ip` and
  `official-account-generated-visual-prompt-v3-visible-ip-block-scene`.
- Migration: `20260824_0034`, with `down_revision=20260824_0033`.
- Command: `python -m app.official_account_news_ip_live_demo --output-dir <new-dir>
  --news-html <verified-news-cache> --plan-html <verified-plan-cache>`.
- Output ledgers: `intents/body-N.intent.json`, `intents/body-N.result.json`, `run.json`,
  `evidence.json`, `visual-map.json`, relative `assets/body-NN.jpg`, HTML, manifest and ZIP.

### 3. Contracts

- Generated-visual v1/v2 builders are immutable. Tests freeze both v1 and v2 request
  fingerprints and the v2 prompt SHA-256; v3 retains the v2 block/reference/output shape while
  requiring a manifest-approved 小赛／赛先生 character as a clearly visible protagonist.
- `0034` admits only a complete paired v3 plan/prompt row and applies the existing metadata-free
  1536×1024 JPEG constraint to ready v2/v3 outputs.
- Only the two pinned Ministry of Education sources and the exact approved 41-item company-IP
  catalog are accepted. Facts retain evidence ID, canonical URL, date and bounded quote; family
  practice copy is labeled interpretation rather than evidence or policy.
- Exactly three ToApis single-reference calls are possible. Every call requires an exclusive,
  fsynced intent first, `attempts=1`, and a corresponding terminal result ledger. Comfly, article
  model, embedding, WeChat, WeCom and publish clients are not constructed.
- Safe bundles expose checksums, public refs, block anchors, relative images and bounded status;
  they exclude prompts, provider bodies/task IDs/URLs, credentials, raw paths and object locations.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| News source identity/date or required fact differs | Fail in offline preflight; zero paid calls |
| Approved catalog is incomplete or reference count is not exactly three | Fail before provider I/O |
| Existing output directory or any prior intent exists | Refuse replay; never resume a paid call |
| Provider reports attempts other than one | Reject the result and stop |
| Provider timeout after `body-N.intent.json` | Write `body-N.result.json` and `run.json` as `result_unknown`; stop without creating the next intent |
| Three attempts have been created | Structurally prohibit a fourth call |
| Output is not validated 1536×1024 metadata-free JPEG | Do not publish it into the success bundle |
| Safe artifact contains a secret, provider URL/body, prompt or private path | Fail the bundle scan |

### 5. Good / Base / Bad Cases

- Good: two verified official sources bind the article claims; three one-shot ToApis calls each
  yield a 3:2 image with a visible approved IP protagonist; the local bundle has zero external
  image references and records `3 attempted / 3 succeeded / 0 retry`.
- Base: offline preflight and tests validate the complete flow with mock generators and zero
  network calls.
- Bad: edit v2 prompt text under the v2 version, use a generic mascot without an approved
  reference, retry a timeout, create a fourth intent, or treat local visual inspection as an
  implemented automatic multimodal output-quality gate.

### 6. Tests Required

- Freeze v1/v2 golden request fingerprints and v2 prompt SHA-256; assert v3 prompt requires the
  visible IP protagonist and produces a distinct request identity.
- Test source identity/fact binding, catalog completeness, ToApis JPEG-to-PNG single-reference
  construction, exactly-three call cap, exclusive replay refusal, safe artifact redaction and
  manifest/ZIP equality without network.
- Mock a timeout and assert one provider invocation, one intent, a terminal result ledger and run
  both marked `result_unknown`, with no second intent.
- PostgreSQL tests assert clean upgrade and `0033 -> 0034`, exact plan/prompt pairing, current/head
  parity and historical v1/v2 row validity.

### 7. Wrong vs Correct

#### Wrong

```python
for visual in visuals:
    image = await provider.generate(request)  # retries may be hidden
    write_success(image)
```

#### Correct

```python
write_exclusive_intent(ordinal, request_fingerprint)
try:
    image = await one_attempt_toapis.generate(request)
except ImageProviderTimeoutError:
    write_terminal_result(ordinal, status="result_unknown")
    write_run(status="result_unknown")
    raise
validated = prepare_generated_visual_result(image, plan=v3_plan)
write_success_after_validation(validated)
```
