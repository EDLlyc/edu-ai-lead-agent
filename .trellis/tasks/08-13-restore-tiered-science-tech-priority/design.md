# Technical design: tiered science and technology news priority

## 1. Design objective

Replace the new-run science/AI-education hard boundary with a deterministic tiered editorial
policy. Education-related science and technology content remains the strongest normal signal;
qualified frontier science and technology advances become valid candidates; authenticated
Ministry education content receives a highest-priority path that may bypass the ordinary numeric
threshold but never a real hard veto.

This remains one backend cross-layer task because acquisition eligibility, event projection,
scoring, historical replay, and explanation must share the same immutable rule identities. The
change does not modify the roadmap PDF, source membership, governance/copy semantics, or delivery
schedule.

## 2. Decision table

| Content/source condition | Acquisition result | Topic-selection result |
|---|---|---|
| Controlled Ministry + science/AI/technology/robotics education or science-talent pathway | Education cohort | Highest group; ordinary threshold not required; every hard veto still applies |
| Other qualified source + science/AI/technology/STEM education or science-talent pathway | Education cohort | Strong normal priority; must meet ordinary threshold and have no veto |
| Robotics/AI/major science item + substantive frontier progress | Frontier cohort | Normal candidate; must meet ordinary threshold and have no veto |
| Product-aligned but content is outside both cohorts | Out of scope | Cannot enter or be rescued by product fit |
| Generic education, financing, marketing, consumer device, ordinary company/AI release | Out of scope | Not a candidate |

“Controlled Ministry” is not inferred from text. It is authenticated only by stored source-version
policy metadata carried through an occurrence. Ministry priority is a composition of this identity
and the education content cohort.

## 3. Versioned data flow

```text
controlled source profile + bounded list snapshot
  -> science-tech-editorial-v2 title evaluation
  -> education title cohort, then frontier title cohort, then neutral probe
  -> product-matrix-fit-v2-science-pathways soft ordering inside each cohort
  -> bounded detail fetch and title + <= 6,000 body re-evaluation
  -> persist only education or qualified frontier candidates
  -> existing factual governance and immutable event projection
  -> science-tech-editorial-v2 + product-matrix-fit-v2-science-pathways event features
  -> genuine hard vetoes (no editorial-scope veto in new config)
  -> authenticated Ministry education priority evaluation
  -> numeric score, deterministic ranking, Top 1 or no_topic
```

The product signal remains editorial metadata. It must not enter normalized evidence, factual
passages, governed claims, or citations.

## 4. Pure editorial policy

### 4.1 New immutable rule

Add `SCIENCE_TECH_EDITORIAL_RULE_VERSION = "science-tech-editorial-v2"` as a new pure domain
policy. Do not change `science-ai-education-v1` semantics. Its typed result contains:

- `is_candidate`;
- `cohort`: `science_technology_education_priority`, `frontier_science_technology`, or
  `out_of_scope`;
- `editorial_priority_score`, `education_relevance_score`, and
  `frontier_significance_score`, each bounded to `[0, 1]`;
- stable reason codes and matched education/topic/progress/exclusion signals split by title/body;
- considered body characters, truncation state, and rule version.

Normalization remains NFKC, case-folded, whitespace-normalized, and safe for untrusted Chinese and
English text. ASCII terms retain word boundaries. Evaluation stays deterministic and never calls a
model.

### 4.2 Education cohort

The education cohort reuses the proven v1 conjunction contract and covers at least:

- science education, technology education, innovation education, STEM/STEAM, science/AI literacy;
- AI/robotics/engineering/science-subject topics with learner, teacher, curriculum, classroom,
  inquiry, experiment, competition, camp, or youth-practice context;
- science and technology talent pathways: Ministry white-list competitions, technology-specialty
  students, Strong Foundation Plan (`强基计划`), and comprehensive evaluation
  (`综评/综合评价`) policy, eligibility, pathway, or substantive implementation news;
- Chinese and English equivalent phrases.

An explicit education compound receives the strongest content score. A topic-plus-context match
receives a slightly lower but still high score. Source identity is not needed for this content
classification.

Exact pathway phrases are strong attention signals, but not unconditional passes. Institution-level
enrollment advertising, tutoring lead generation, guaranteed-admission/pass claims, score-line
aggregation, deadline reminders without policy substance, and keyword-stuffed headlines remain out
of scope. A claim that an event belongs to an official white list must remain evidence-backed; an
unverified publisher assertion is not converted into official status by this classifier.

### 4.3 Frontier cohort

Frontier qualification requires both:

1. a concrete topic family, such as robotics/embodied intelligence, material AI/model methods,
   aerospace/astronomy, quantum, physics, chemistry, biology, materials, or energy; and
2. a substantive progress signal, such as a verified breakthrough, first achievement, discovery,
   new research result, successful development, demonstrated capability, milestone, or comparable
   concrete advance.

A lone `AI`, `robot`, `science`, `technology`, `model`, or `innovation` token is insufficient.
Financing, stock/market movement, general compute capacity, sales language, consumer-device
promotion, event promotion, and ordinary company announcements do not become frontier content
without a concrete research or engineering advance. Exclusion reasons are persisted.

`人工智能` is deliberately routed by context: AI education belongs to the education cohort, a
concrete AI research/engineering advance may belong to the frontier cohort, and broad AI business,
funding, compute-market, or marketing news belongs to neither.

### 4.4 Cohort and score precedence

- Education matching is evaluated first and assigns the education cohort even when frontier terms
  are also present.
- Frontier matching is evaluated only for content not already assigned to education.
- Recommended content feature values are deterministic: strong explicit education up to `1.0`,
  topic-plus-education context below that, and qualified frontier content capped below the
  corresponding education content. Exact contributions and caps are locked by focused tests.
- Product fit is evaluated separately with a new immutable
  `product-matrix-fit-v2-science-pathways`; it cannot alter the cohort or candidate eligibility.

### 4.5 Product-matrix v2

Do not mutate `product-matrix-fit-v1`. Publish `product-matrix-fit-v2-science-pathways`, retaining
the six existing direction IDs and capped breadth behavior while expanding the existing
competition/talent direction with stable matches for:

- `白名单赛/白名单赛事` and official nationwide student competition lists;
- `科技特长生` and science/technology specialty development;
- `强基计划` and foundational science talent pathways;
- `综评/综合评价` when used as an education/admissions pathway rather than a generic review phrase.

The result must distinguish stable pathway reason codes from raw matched terms. Repeating these
keywords cannot inflate the capped score, and a v2 product match still cannot make out-of-scope
content eligible.

## 5. Acquisition design

### 5.1 Version rollout

- Bump runtime to `acquisition-v5-tiered-science-tech`.
- Create immutable source versions for the ten active source profiles using
  `science-tech-editorial-v2`. Keep host/path/DNS/robots/response/pacing configuration unchanged.
- Keep all historical relevance branches installed so old jobs and source versions execute with
  their original rules.
- Keep Xinhua Education active and CAST/EdSurge pending. This task neither adds a source nor runs an
  activation decision.

### 5.2 Bounded list ordering and detail qualification

Within the existing scan window:

1. evaluate every title with editorial v2 and product-fit v2;
2. order education-title candidates by editorial score, product fit, publication time, original
   source order, and stable item ID;
3. follow with frontier-title candidates using the same deterministic keys;
4. fill only the remainder of the existing item-limit window with title-neutral items in original
   source order;
5. perform the existing freshness precheck and safe bounded detail fetch;
6. re-evaluate title plus at most 6,000 normalized body characters and persist only the education
   or qualified-frontier cohorts.

Do not backfill the accepted quota with unrelated records. Preserve current scan/item limits,
leases, retries, immutable snapshots, idempotency, rate limits, host/path allowlists, DNS/IP checks,
response bounds, and typed failures. No CAPTCHA, WAF, browser, or proxy bypass is introduced.

### 5.3 Audit metadata

Reuse candidate extraction metadata and observation JSON to persist:

- v2 and product-fit rule versions;
- final cohort and three content scores;
- stable reason codes and title/body matched signals;
- product direction IDs and score;
- character limit/truncation state;
- scanned, education-title, frontier-title, neutral-probe, filtered, stale, and deferred counts.

The candidate detail API already exposes extraction metadata; the list API keeps the immutable
relevance-rule version. No public response shape is added.

## 6. Topic-selection design

### 6.1 Event projection

Evaluate both the old v1 and new v2 policies from stored representative title, governed Chinese
summary/facts, and category projection. `TopicCandidate` retains the existing v1 fields for `.5`
replay and adds internal v2 cohort/scores/reasons for `.6`. Product fit is selected by immutable
config: `.5` keeps product v1 and `.6` uses product v2.
No selection-time browsing or source refetch occurs.

### 6.2 New immutable config

Introduce `scoring-v1-preview.6-tiered-science-tech-priority` with:

| Positive feature | Weight |
|---|---:|
| Editorial priority (education strongest, qualified frontier lower) | 0.30 |
| Product-matrix fit | 0.25 |
| Source trust | 0.15 |
| Source diversity | 0.10 |
| Freshness | 0.10 |
| Communication potential | 0.10 |

Keep the ordinary threshold at `0.62`, current penalties, freshness window, repetition window,
stable tie-break, and `no_topic` behavior. The feature map records
`science-tech-editorial-v2` and `product-matrix-fit-v2-science-pathways`. Later tuning requires another immutable
version.

Config serialization/deserialization branches on stored feature keys:

- historical feature map for `.4`;
- `science_education_relevance` map for `.5`;
- `editorial_priority` map for `.6`.

No historical field is silently reinterpreted.

### 6.3 Veto boundary

Publish `topic-veto-v3-governed-content` for `.6`. It retains all genuine vetoes:

- unresolved governance or ineligible/Tier-C-only evidence;
- unverified or unsuitable negative incident;
- privacy, legal, or safety uncertainty;
- prohibited marketing risk;
- recent repetition and stale event.

It does not add `outside_science_ai_education_scope`; acquisition/v2 cohort qualification and the
new editorial feature own scope for new runs. `topic-veto-v2-science-ai-education` remains unchanged
for `.5` replay.

### 6.4 Ministry highest-priority rule

Add `ministry-education-priority-v3` without changing `science-policy-priority-v2`.

The new rule applies only when:

- an event occurrence carries the controlled Ministry topic-priority policy; and
- v2 assigns the education cohort based on title plus governed content; and
- no hard veto exists.

It covers science education, AI education, technology/innovation education, STEM, science/AI
literacy, robotics education, official white-list competitions, technology-specialty students,
Strong Foundation Plan, and comprehensive-evaluation science-talent pathways. It does not require
`通知/方案/行动/规划` or another policy-action word and does not reject an otherwise substantive
related story merely because it is a report, curriculum item, practice story, result, or
conference coverage.

For `.6` only:

```text
eligible = no_hard_veto AND (passes_ordinary_threshold OR ministry_priority_applied)
```

This makes an authenticated Ministry education event eligible and places it in rank group 0 even
when `passes_threshold=false`. Ordinary candidates remain eligible only at or above threshold.
Historical `.4` keeps its action-word and threshold requirements; `.5` keeps priority disabled.

### 6.5 Ranking and explanation

Stable groups are:

1. applied Ministry education priority;
2. ordinary eligible candidates;
3. below-threshold candidates without a hard veto;
4. hard-vetoed candidates.

Within a group, retain total, source trust, event time, and UUID ordering. Persist the v2 rule,
cohort/scores/reasons, product directions, all feature components, total, threshold,
`passes_threshold`, `eligible`, priority rule/policy/reason, `threshold_bypass_applied`, vetoes, and
rank in existing score/config/explanation JSON. This intentionally allows the inspectable state
`passes_threshold=false`, `eligible=true`, `priority_applied=true` for Ministry bypass cases.

## 7. Compatibility, storage, and rollback

- No Alembic migration or public API schema change is planned. Existing JSON metadata, config
  snapshots, feature maps, and explanation fields carry the new data.
- Old source versions keep `ai-title-v1`, `moe-science-v1`, or
  `science-ai-education-v1`. Old acquisition runs keep their stored pipeline/source versions.
- `.4` retains its legacy features and `science-policy-priority-v2`; `.5` retains v1 relevance,
  the outside-scope veto, and disabled source priority. `.6` alone uses v2, veto v3, and Ministry
  threshold bypass.
- Acquisition rollback activates the prior v4 source versions for future runs without deleting new
  snapshots/candidates. Ranking rollback configures future runs back to `.5`; existing `.6` scores
  and daily decisions remain immutable.
- If implementation discovers a required database or public API shape change, stop and revise the
  design, migration/rollback plan, and user review before making it.

## 8. Verification strategy

- Domain: bilingual education/frontier/out-of-scope fixtures, pathway keyword positives and
  admissions/marketing negatives, ambiguous `综评` and ASCII terms, progress conjunction, cohort
  precedence, stable reasons/scores, product-v2 caps, and the 6,000-character boundary.
- Acquisition: exact three-part list ordering, bounded neutral probe, body-only matches, zero-match
  success, no quota fill, metadata counters, historical rule dispatch, source-version fingerprints,
  retries/leases/freshness/idempotency, and unchanged ten-active/two-pending registry.
- Topic unit: exact `.6` weights, education-over-frontier behavior, ordinary threshold, Ministry
  below-threshold eligibility, each hard-veto non-bypass case, `.4`/`.5` replay, tie-break, and all
  `no_topic` branches.
- Persistence/API: real PostgreSQL config fingerprint and score/explanation round trips, Ministry
  source authenticity, deterministic replay/rank, and no schema/contract drift.
- Final gates: backend format/lint/strict types/full tests, frontend check/build, API contract,
  Compose render, doctor, migration-head assertion, and `git diff --check`.
