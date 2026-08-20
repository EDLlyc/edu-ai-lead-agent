# Design — hard-tech aerospace recovery coverage

## Decision

Keep the existing ten-source acquisition frontier. Replace the current narrow “topic plus completed progress” eligibility with a new immutable broad hard-tech rule and a new topic-scoring identity rather than adding a crawler or mutating `science-tech-editorial-v2` in place.

## Rule boundary

The new classifier separates recall from prioritization:

1. a governed hard-tech topic is sufficient for acquisition candidacy;
2. progress, plan, failure, capital/market, event and product signals classify the item and affect deterministic rank/explanation;
3. completed substantive progress ranks above otherwise equivalent generic hard-tech content;
4. source/evidence, unverified, stale, delivered-repeat, privacy/legal and prohibited-deception vetoes remain authoritative.

Funding, market, conference and ordinary product-release patterns stop being editorial hard exclusions when a hard-tech topic is present. They remain auditable risk/category signals and cannot claim a breakthrough reason.

The v3 result adds a bounded tuple of stable content-shape signals rather than one mutually exclusive label, because one article may describe both a failed test and the next plan. Supported signals are `completed_progress`, `planned_or_in_progress`, `failure_or_setback`, `capital_or_market`, `event_or_conference`, `product_or_service_release`, and `general_hard_tech`. Persist them in existing JSON audit projections; no schema migration is needed. Completed progress receives the strongest editorial value, while other shapes receive lower deterministic values but remain candidates.

The user's “less strict” requirement also exposes a downstream boundary: current hard-tech candidates can remain ineligible below the global `0.59` threshold because product-matrix fit owns 25% of the score. The new policy is not a global threshold reduction. It is a versioned, audited eligibility path for governed Tier-A/B hard-tech candidates when every remaining hard veto is absent. LLM reranking remains downstream and cannot create source evidence, remove vetoes or rewrite content classes.

Existing deceptive-marketing (`保过/包会/稳赚/零风险/百分百提升`), unverified, stale, repeat, evidence and privacy/legal vetoes remain. The current `unsuitable_negative_incident` safety behavior also remains for actual injury/crime/privacy incidents; an engineering test described only as failed is not one of those terms and therefore can enter without weakening that safety veto.

## Versioning and replay

- Preserve an explicit v2 identity and its exact topic-plus-progress/exclusion behavior.
- Introduce a current v3 broad-hard-tech identity with topic-based candidacy and typed content signals.
- Let the evaluator receive/resolve a supported rule version and fail closed for unknown versions.
- Route acquisition using the source version's stored relevance-rule identity, so historical v2 jobs remain executable and newly seeded source versions use v3.
- Bump the acquisition version because eligibility and source-version fingerprints change.
- Add a new topic-scoring version for v3. Map historical `.6`, `.7`, and `.8` to v2; map the new default to v3. Preserve `.8` threshold and delivered-history behavior in the new version while recording the new bounded milestone-eligibility policy identity.
- Project topic candidates with the editorial rule stored in the run's immutable config snapshot rather than always using the current evaluator identity.

No schema migration is required: source versions and scoring configs are already versioned durable records.

## Source and data flow

```text
Xinhua Tech controlled entry
  -> xinhua_tech_v1 bounded /c.html discovery
  -> title evaluation (hard-tech topic + typed content signals)
  -> bounded detail fetch
  -> body evaluation with the same immutable rule
  -> evidence candidate metadata
  -> governed event
  -> topic selection using the run-pinned editorial rule
```

The connector allowlist, source tier, scan limits, freshness window and ten-source registry remain unchanged.

## Tests

- Domain table tests for the exact Xinhua headline plus completed/planned/failed/capital/event/product hard-tech variants and unrelated negatives.
- Explicit v2/v3 comparison proving v2 retains the old narrow behavior while v3 recalls and truthfully classifies the broader set.
- Xinhua connector fixture shaped like the verified article URL/title/body.
- Acquisition integration showing the milestone moves from neutral to frontier and persists v3 evidence.
- Topic config/repository replay tests showing `.6`/`.7`/`.8` use v2 while the new default uses v3.
- Topic scoring tests proving governed, source-qualified hard-tech variants with no veto reach the LLM pool below `0.59`, while unrelated, unverified and genuine-veto variants do not.
- Existing broad exclusions, source-count and API contract tests remain unchanged.

## Risks and controls

- **Category inflation:** plans, failures, capital and product items are eligible candidates but must never receive a completed-breakthrough reason.
- **Topic keyword noise:** require a governed hard-tech topic; ordinary finance, events and product releases without that topic remain out of scope.
- **Over-broad threshold relaxation:** keep `0.59`; authorize only the versioned hard-tech-pool path and never override a remaining veto.
- **Historical reinterpretation:** dispatch by immutable rule identity and add a scoring version.
- **Source expansion:** none; the verified event is already on the approved Xinhua Tech entry.
