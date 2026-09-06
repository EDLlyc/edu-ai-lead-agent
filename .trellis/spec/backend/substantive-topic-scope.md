# Substantive Topic Qualification

## 1. Scope / Trigger

This contract governs the selection-only upgrade to
`scoring-v1-preview.12-substantive-topic-scope` and
`science-tech-editorial-v4-substantive-topic`. It implements the approved substantive technology,
AI or science-education boundary. It is not a provider-safety classifier, a source/person/country
blacklist, or evidence that a provider will accept or deliver any particular story.

## 2. Signatures

- `evaluate_science_tech_editorial_relevance(title, body, *, body_limit, rule_version)` in
  `backend/app/domain/editorial_relevance.py` returns the existing typed cohort/score/reason result.
- `build_topic_scoring_config(Settings(...))` pins the new immutable scoring/editorial pair.
- `load_governed_topic_candidates(...)` authenticates v4 subject from content-bearing stored
  title, summary and facts, not translated taxonomy/category labels.
- `CONTENT_SCORING_VERSION=scoring-v1-preview.12-substantive-topic-scope` activates the policy
  only for new runs; current production settings can explicitly pin an older version.

## 3. Contracts

- Keep `SCIENCE_TECH_EDITORIAL_RULE_VERSION` as literal v3 for acquisition recall and historical
  replay. Never silently route title-only listing acquisition or old source profiles into v4.
  Preserve source IDs, config fingerprints, version IDs and the two-stage title/body contract.
- Freeze literal v2/v3 and scoring .6-.11 outputs, snapshots, canonical fingerprints and ordering.
  .12 changes the scoring identity and editorial identity only: threshold 0.59, weights, genuine
  hard vetoes, governed broad-tech pool and `qualified-authoritative-priority-v1` stay intact.
- Substantive evidence requires actual technology/science-education subject and concrete action
  or meaningful supported technical detail. A nearby generic research/requirement word cannot
  authenticate a whole mixed-topic sentence. Bare keyword lists and exact repetition do not
  manufacture support. Titles cannot override unsupported or predominantly unrelated content.
- Relationship-only predicates such as cooperation, exchange or advocacy remain nontechnical even
  when paired with a generic publication verb. Generic policy verbs such as clarify, support,
  propose or adopt may extend an already established technical subject, but cannot independently
  authenticate technology/AI/science-education subject matter.
- Preserve bounded subject continuity for genuine technical/science-education measurements and
  referents without requiring every clause/fact to repeat the topic. Unrelated subject changes
  reset continuity. Test the actual summary/facts database projection, not only hand-joined prose.
- Bound input before expensive normalization/matching. Keep safe stable reason codes and existing
  body-bound metadata; do not persist new raw article excerpts as explanation payloads.
- V4 excludes taxonomy labels only from subject authentication. Keep separate product/category
  scoring inputs and preserve the complete old editorial projection for historical runs.
- Out-of-scope content stays ineligible before numeric score, broad-pool admission, source priority
  or model reranking. Government ordering applies only to already-qualified eligible candidates;
  it is not an independent threshold bypass. Preserve every hard veto.
- No copy/prompt/rerank/slot-policy/profile identity changes are needed. Existing same-slot ownership
  with a different scoring snapshot must conflict, not replace a run or recreate copy work.
  Automatic preparation/catch-up/expiry gates stay unchanged; manual enqueue is not a recovery
  shortcut around expired windows. Already queued runs execute their pinned old configuration.

## 4. Validation & Error Matrix

| Condition | Required outcome |
|---|---|
| General trade/diplomacy story with incidental AI mention | Out of scope; source/score cannot rescue |
| Nontechnical content labelled AI/education by taxonomy | Labels cannot create v4 qualification |
| Dedicated AI governance, research or science-education practice | May qualify; all ordinary vetoes remain |
| Neutral title followed by technical subject and measurement facts | Evaluate subject continuity from actual stored projection |
| Technology title with no adequate supporting body | No title-only admission |
| Repeated keyword list or predicate overlapping only a topic noun | Does not constitute substantive action |
| Cooperation/exchange initiative merely says it was published | Relationship statement cannot authenticate a technical subject |
| Established technical subject followed by supported policy detail | Generic policy verb may participate only as bounded continuation |
| Stored literal .6-.11 snapshot | Identical prior identity, score, explanation and ordering |
| Existing .11 slot receives a new .12 enqueue | Immutable conflict, not replacement/replay |
| Fresh naturally due slot configured for .12 | Persist new snapshot; no changes to old rows |

## 5. Good / Base / Bad Cases

- Good: dedicated AI assessment standards or classroom science practice remain candidates;
  a generic trade conference mentioning AI does not enter the eligible pool.
- Base: insufficient substantive content produces an explainable out-of-scope result; no model
  or delivery call is needed to evaluate this deterministic boundary.
- Bad: classify a whole long sentence as technical from one nearby keyword, count category labels
  as facts, require redundant topic words in every scientific measurement, or bump copy versions
  just to replay previously failed news.

## 6. Tests Required

- `backend/tests/unit/test_substantive_topic_scope.py`: authored positive/negative/continuity,
  repetition, relationship-only predicates, bounded policy-verb continuation, bounds and
  title/body cases; no high-score/source rescue; exact historical hashes and replay; unchanged
  acquisition/copy/slot/rerank identities.
- Topic/slot repository integration tests: real stored summary/facts/taxonomy boundary, .12-only
  behavior versus .11 replay, immutable existing-slot conflict and fresh natural .12 snapshot.
- Rerank, copy and WeCom regression checks: no priority barrier crossing, copy replay or duplicate
  delivery introduced by scoring-only configuration change.
- Compare broad-suite failures against an exact deployed-source baseline. Report missing private
  demo fixtures and unrelated existing failures explicitly; never describe such a suite as green.
  Synthetic authored cases are not human labels or measured real-world precision/recall.

## 7. Wrong vs Correct

```python
# Wrong: category labels can manufacture subject evidence in a new policy.
subject_body = summary + facts_text + translated_category_labels

# Correct: the run-pinned new policy authenticates only content-bearing evidence;
# historical configurations retain their original projection for replay.
subject_body = (
    project_content_bearing_summary_and_facts(summary, facts)
    if scoring_version == "scoring-v1-preview.12-substantive-topic-scope"
    else historical_editorial_projection(summary, facts, categories)
)
```

The projection names in this example describe responsibilities, not additional public APIs.
