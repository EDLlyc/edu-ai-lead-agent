# Current hard-filter and priority seams

## Purpose

This note records the implemented behavior that the new tiered editorial policy must replace for
new runs while preserving for historical replay. It is code-backed planning evidence, not a new
runtime contract.

## Current acquisition boundary

- All ten active source versions use `science-ai-education-v1`; the acquisition pipeline version is
  `acquisition-v4-science-education-fit`.
- `evaluate_science_ai_education_relevance()` accepts an explicit science/AI/technology education
  phrase or a science/AI/robotics/engineering topic combined with an education, learner, teacher,
  or practice context. Without that education context, robotics, AI advances, and scientific
  discoveries are assigned score zero and filtered after the bounded detail probe.
- List discovery orders science/AI-education title matches first, then title-neutral items. Product
  fit is a capped soft ordering signal. Detail qualification repeats the policy over title plus at
  most 6,000 normalized body characters.
- The relevance dispatcher is explicitly versioned. Historical `ai-title-v1`, `moe-science-v1`,
  and `science-ai-education-v1` branches remain installed, so the new tiered policy must be a new
  rule version rather than a semantic edit to v1.
- Source versions, immutable snapshots, candidate extraction metadata, and observations already
  provide storage for a new rule version, cohort, reason codes, matched terms, bounded-character
  state, and filter/defer counters. No schema migration is required for the planned change.

## Current topic-selection boundary

- The default immutable config is `scoring-v1-preview.5-science-education-product-fit`, with a
  0.62 threshold and a 30/25/15/10/10/10 positive feature map.
- `.5` adds `outside_science_ai_education_scope` whenever the current candidate projection is not
  eligible under `science-ai-education-v1`. This is a hard veto, so a non-education robotics or
  scientific breakthrough cannot be selected regardless of its other features.
- `.5` intentionally has no source priority. Historical `.4` snapshots retain
  `science-policy-priority-v2`; that evaluator requires a controlled Ministry occurrence, a
  science/AI/robotics education topic, a policy-action word, no excluded item, no hard veto, and a
  passing numeric score.
- The controlled Ministry identity already propagates from source-version policy metadata through
  article occurrence, event projection, `TopicCandidate`, persisted score explanation, and the API.
  A title merely containing “教育部” cannot create this identity.
- Current scoring sets `eligible = no vetoes AND passes threshold`, even when a priority evaluator
  applies. The new Ministry rule therefore needs an explicit, version-scoped eligibility basis of
  `no vetoes AND (passes threshold OR ministry priority applied)`.
- Config snapshots deserialize by stored feature keys and persist raw/normalized features,
  components, totals, threshold state, priority state, vetoes, and rank. A third feature-map branch
  can support a generic editorial-priority feature without reinterpreting `.4` or `.5` snapshots.

## Confirmed product decisions for the next version

1. Science, AI, technology, STEM, and robotics education are priority content, not the only allowed
   content.
2. Robotics, AI, and major scientific advances may enter when they carry a substantive,
   deterministic frontier-progress signal. A lone broad technology term is insufficient.
3. Generic education, financing, compute-market news, marketing, consumer-device news, and ordinary
   company announcements remain outside the new candidate boundary.
4. Controlled Ministry science/AI/technology/robotics education content is the highest priority.
   It does not need the ordinary numeric threshold, and it no longer requires a policy-action word.
5. Ministry priority cannot override factual/evidence, privacy/legal/safety, prohibited marketing,
   repetition, freshness, or any other genuine hard veto.
6. Product-matrix fit remains a capped soft signal after content qualification. It never creates
   eligibility and never becomes factual evidence.
7. The roadmap PDF, source registry membership, pending-source activation state, schedules, copy
   length, and IP asset work are outside this change.
8. The additional attention terms are `白名单赛/白名单赛事`, `科技教育`, `科技特长生`,
   `强基计划`, `综评/综合评价`, and `人工智能`. Current editorial code already recognizes technology
   education and AI education, but it does not provide a governed pathway contract for the other
   four terms. The current product v1 has a broad competition/talent direction but no explicit
   patterns for them, so compatibility requires product-matrix v2 rather than mutating v1.
9. Pathway terms are strong editorial/product signals, not unconditional admission. Training lead
   generation, guaranteed outcomes, score-line aggregation, and generic enrollment advertising
   remain negative fixtures; official white-list status remains an evidence-backed factual claim.

## Recommended compatibility seam

- Publish a new pure content rule (planned as `science-tech-editorial-v2`) with stable cohorts
  `science_technology_education_priority`, `frontier_science_technology`, and `out_of_scope`.
- Publish a new acquisition version and immutable active source versions using v2. Continue
  dispatching all historical relevance versions by their stored version strings.
- Publish `product-matrix-fit-v2-science-pathways` for the new pathway terms while retaining v1 for
  `.5` and historical replay.
- Publish a new topic config `.6`, a veto rule without the editorial-scope veto, and a Ministry
  priority rule that composes authenticated source policy with the education cohort.
- Preserve the `.5` feature map and hard scope veto exactly. Preserve `.4` policy-action and
  threshold semantics exactly.

## Verification consequences

- Pure bilingual fixtures must separate education priority, science-talent pathways, qualified
  frontier advances, and broad/admissions-marketing false positives with stable reason codes and a
  6,000-character boundary.
- Acquisition tests must prove cohort order, bounded neutral probes, no quota filling, immutable
  source-version replay, metadata counters, and unchanged safe-fetch behavior.
- Topic tests must prove Ministry below-threshold selection, every hard-veto non-bypass case,
  ordinary below-threshold rejection, education-over-frontier ordering, and exact `.4`/`.5` replay.
- PostgreSQL and API tests must prove configuration fingerprints, source-policy authenticity,
  explanation round trips, deterministic rank/replay, and no public contract or migration drift.
