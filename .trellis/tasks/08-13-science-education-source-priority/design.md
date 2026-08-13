# Technical design: science-education and product-aligned source priority

## 1. Design objective

Build one versioned editorial policy that makes science education and AI education the actual content boundary across all controlled sources, then use a separate product-matrix fit policy as a dominant but non-blocking ranking signal. Source identity, brand material, and model preference must not substitute for content relevance or factual evidence.

This remains one cross-layer task rather than parent/child tasks because the same rule versions and audit projection must be consistent from discovery through daily selection, and the acceptance result is one end-to-end ranking outcome. Acquisition/source onboarding and topic scoring remain separable implementation checkpoints inside the task.

## 2. Confirmed product decisions

| Decision | Result |
|---|---|
| Editorial boundary | A story must concern science/AI/technology education, learning, teaching, curriculum, youth practice, competition, or study experience to enter the new candidate cohort. |
| Product matrix | High-weight soft fit only; never a hard filter and never factual evidence. |
| Generic AI/technology news | New acquisitions are filtered; historical governed events receive an out-of-scope veto in the new scoring version. |
| Ministry source override | Historical scoring snapshots keep it; the new scoring version removes the absolute source-name override and uses content/source signals. |
| First active source batch | Xinhua Education, CAST science-popularization listing, and EdSurge AI coverage, each subject to its independent activation gate. |
| Conditional/deferred sources | UNESCO requires reference-use compliance sign-off; JYB, NCET, OECD, EU Digital Education, and ISTE remain deferred for the reasons in source research. |

## 3. Data flow

```text
controlled source profile + list snapshot
  -> discover bounded list items
  -> science/AI-education title signal (hard cohort)
  -> product-matrix title signal (soft ordering only)
  -> bounded ordered detail fetch
  -> title + bounded body re-evaluation
  -> freshness + relevance eligibility
  -> candidate/observation with rule versions and match metadata
  -> existing factual governance and event projection
  -> event-level science/AI-education signal
  -> event-level product-matrix fit
  -> hard vetoes, including out-of-scope
  -> versioned weighted score
  -> deterministic Top 1 or no_topic
```

Brand/product-matrix input stops at editorial fit metadata. It never enters normalized factual passages, evidence bindings, factual claims, or external-source citations.

## 4. Domain policy contracts

### 4.1 `science-ai-education-v1`

Create a pure domain policy, owned outside connectors and repositories, with bilingual Chinese/English normalization. It returns a typed result containing:

- `is_eligible`;
- bounded score in `[0, 1]`;
- matched science/AI/technology topic terms;
- matched education/learner/teacher/curriculum/practice context terms;
- named reason codes;
- title/body match separation, considered-character count, and truncation state;
- rule version.

Eligibility requires either an explicit compound such as science education, AI education, STEM/STEAM education, AI literacy, or a conjunction of a science/AI/robotics/engineering topic with an education context. Youth science competitions, camps, inquiry practice, laboratories, and project learning are eligible when the learning/youth context is explicit.

Generic AI model releases, compute/chips, financing, consumer devices, enterprise products, general science discoveries, and broad education stories fail unless the education-and-science/AI conjunction is present. Ambiguous English terms such as `agent`, `model`, `lab`, and `learning` require disambiguating context.

The body remains bounded at 6,000 normalized characters unless focused tests demonstrate a smaller safe bound. The rule does not call a model.

### 4.2 `product-matrix-fit-v1`

Create a second pure domain policy that returns a score in `[0, 1]`, rule version, and zero or more stable direction IDs:

- `science_literacy_inquiry`;
- `subject_transition_math_physics_chemistry_biology`;
- `ai_literacy_project_learning`;
- `ai_theme_robotics_agent_safety_math_3d_hackathon`;
- `competition_innovation_talent_pathway`;
- `study_tour_camp_university_lab_industry`.

The score uses capped named contributions so repeated keywords cannot inflate the result. A direct match receives the strongest contribution; additional distinct directions may add a small capped breadth bonus. No match returns zero and does not change eligibility.

Both policies operate on untrusted text and return metadata only. They never copy product-page wording into factual output.

## 5. Acquisition design

### 5.1 Source-version rollout

Keep `ai-title-v1` and `moe-science-v1` installed for old queued jobs and historical source versions. Create new source versions for all existing active sources using `science-ai-education-v1`; keep the Ministry's source-scoped HTTP fallback unchanged. Bump the acquisition pipeline to `acquisition-v4-science-education-fit`.

Add three source seeds/connectors:

| Slug | Tier | Language | Entry and boundary |
|---|---:|---|---|
| `xinhua-education` | B | `zh-CN` | `https://education.news.cn/index.htm`; exact dated `/YYYYMMDD/<id>/c.html` articles only |
| `cast-science-education` | B | `zh-CN` | `https://www.cast.org.cn/kp/`; only fixture-proven same-host article prefixes; Tier B conservatively covers mixed authorship |
| `edsurge-ai-education` | B | `en` | `https://www.edsurge.com/coverage-areas/artificial-intelligence`; `/news/` articles only, excluding visible sponsored content and `/api/` |

The active registry grows from 9 to 12 only if every new seed passes its own activation gate. A failed source is omitted rather than shipped as a permanently failing active job.

### 5.2 Bounded prioritization

Within the existing discovery scan limit:

1. evaluate title science/AI-education relevance;
2. evaluate title product fit without affecting eligibility;
3. order direct eligible title matches first by science relevance, then product fit, publication time, original source order, and stable item ID;
4. fill the remaining existing item-limit detail window with title-neutral items in stable source order so body-only matches remain discoverable;
5. fetch no more than the configured first-run/daily item limit, preserving current pacing, leases, snapshots, response bounds, and freshness checks;
6. re-evaluate title plus bounded body and persist only science/AI-education-eligible, fresh candidates.

This design intentionally does not add an unbounded probe or a second crawler. Product fit changes which equally relevant items are inspected first but cannot exclude a science/AI-education item.

### 5.3 Audit metadata

Persist in existing `extraction_metadata` and source-observation JSON:

- both rule versions;
- science/AI-education eligibility, score, reason codes, and title/body terms;
- product-fit score and direction IDs;
- title match count, body-probe count, filtered count, deferred relevant count, content bound, and truncation state;
- existing freshness and source provenance fields.

No new candidate table columns are required. Candidate detail already exposes extraction metadata; list APIs continue exposing the relevance-rule version.

## 6. Topic-selection design

### 6.1 Event projection

At the immutable topic-run cutoff, calculate both policies from the stored representative title, Chinese governed summary, and factual categories. Extend `TopicCandidate` with explicit science-education score/eligibility, product-fit score, reason codes, and product direction IDs. Do not derive either signal solely from the source profile.

### 6.2 New hard veto

Add `outside_science_ai_education_scope` to the versioned veto explanation for candidates that fail the event-level relevance policy. It joins the existing hard-veto set and cannot be rescued by source tier, product fit, freshness, or another numeric component.

### 6.3 New immutable scoring configuration

Introduce `scoring-v1-preview.5-science-education-product-fit` with `science-ai-education-v1` and `product-matrix-fit-v1` recorded in the config snapshot. Proposed positive weights:

| Feature | Weight |
|---|---:|
| Science/AI-education relevance | 0.30 |
| Product-matrix fit | 0.25 |
| Source trust | 0.15 |
| Source diversity | 0.10 |
| Freshness | 0.10 |
| Communication potential | 0.10 |

The two requested editorial signals therefore own 55% of positive weight. Retain the existing threshold `0.62`, freshness window, repetition behavior, penalties, deterministic tie-break, and `no_topic` behavior for the first preview evaluation. Any later tuning creates another immutable version.

The current misleading `ai_relevance=1.0 if categories else 0.0` and broad `parent_relevance` stay readable only for historical configs. New configs use explicit feature keys. Config deserialization must accept both historical feature maps and the new map without rewriting stored snapshots.

Set no absolute selection-priority rule for the new config. The Ministry occurrence may still carry historical source policy metadata, but it is ignored by the new config. An eligible Ministry science-education policy will naturally gain high content relevance and Tier A trust.

### 6.4 Explanation and persistence

Continue using existing JSON score columns and explanation. Persist:

- raw/normalized science-education and product-fit scores;
- weights/components and total;
- both editorial rule versions;
- relevance reason codes and product direction IDs;
- the out-of-scope veto when applicable;
- a reason indicating the historical source override is not active for this config.

The current API already exposes numeric feature maps and arbitrary explanation JSON, so no response-shape or database migration is intended. OpenAPI/frontend contract checks must still prove there is no drift.

## 7. English evidence boundary

EdSurge articles retain `language="en"`. The current governance prompt already receives source language and requires Chinese summary/facts with passage IDs. Add an English fixture/provider case that proves:

- English normalization and passage offsets remain stable;
- the Chinese summary/facts bind to original English passage IDs;
- original URL, source language, exact quote, and evidence binding remain available downstream;
- product fit is editorial metadata and never appears as evidence.

No change to the `zh-CN`-only private brand-document contract is required.

## 8. Compatibility and storage

- No Alembic migration is planned: source/version rows, candidate extraction metadata, score maps, config snapshots, and explanation JSON already carry the necessary data.
- Old source versions retain old relevance policies; queued/replayed work remains executable.
- Historical topic runs deserialize their existing six positive features and Ministry priority semantics exactly.
- New runs use the new six-feature map and no absolute source priority.
- Existing hard vetoes, threshold, daily revisions, current-run uniqueness, leases, and downstream reconciliation remain unchanged.
- Source count references, smoke matrices, fixtures, specs, README/operator docs, and any count assertions change from 9 to 12 only after the three new active profiles pass.

## 9. Operational safety and activation

For each new source, require fixed fixtures first and a bounded live entry + one-detail smoke second. Live failure remains a typed source failure; never add proxy rotation, browser challenge automation, CAPTCHA handling, WAF bypass, or relaxed SSRF/DNS policy.

Special rules:

- Xinhua: reject HTTP/external/app/topic/image links; do not inherit permissions from the existing Xinhua Technology profile without a fresh robots snapshot.
- CAST: missing robots is `manual_review`, not permission; use conservative pacing and Tier B for the mixed page.
- EdSurge: reject `/api/` and visible sponsored/advertorial records; do not use its API.
- UNESCO: do not activate until reference-use compliance is explicitly accepted; never use for training or bulk reproduction.

## 10. Rollback

- Acquisition rollback: activate the prior `acquisition-v3-freshness-pacing` source versions for future runs; keep new snapshots/candidates immutable.
- Source rollback: omit or deactivate only the failing new source version; do not weaken fetch policy or remove history.
- Ranking rollback: configure new runs with `scoring-v1-preview.4-science-policy-priority`; never edit or delete `.5` runs.
- Policy correction: publish `science-ai-education-v2`, `product-matrix-fit-v2`, or a later scoring version. Do not mutate v1 semantics.
- A production-code rollback does not delete already governed evidence, scores, or daily decisions.

## 11. Verification strategy

- Pure domain tests: bilingual positives, conjunction rules, ambiguous terms, product direction matches/caps, and negative generic AI/science/education cases.
- Connector contracts: three list/detail fixture pairs, exact path restrictions, dates/language, sponsor exclusion, canonical URLs, parser drift, and cross-host/HTTP rejection.
- Acquisition unit/integration: deterministic title ordering, product soft ordering, bounded body probe, zero-match success, metadata, source-version round trip, English candidate, freshness, retry/idempotency, and 12-source enqueue.
- Topic unit/integration: new weights sum to one, out-of-scope veto, product fit cannot override veto, threshold/no-topic, historical config round trip, Ministry no longer absolute in `.5`, deterministic replay, persistence/API explanation.
- Governance/copy boundary: English evidence -> Chinese governed summary/copy with valid bindings and unchanged brand separation.
- Final gates: backend, frontend, API contract, Compose, doctor, diff check, and opt-in bounded live smoke for each newly activated source.
