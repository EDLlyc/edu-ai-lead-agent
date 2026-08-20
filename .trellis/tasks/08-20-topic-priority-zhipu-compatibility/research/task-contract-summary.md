# Task contract summary

## Immutable compatibility

- Add new scoring/priority/rerank identities; never reinterpret persisted `.6`–`.9`, Ministry v3 or
  rerank v1/v2/v3 snapshots.
- A stored run snapshot, not current Settings defaults, selects evaluation and parser behavior.
- No migration unless a real schema constraint proves one is required.

## Selection safety

- Hard veto, governed evidence, delivered-repeat, freshness and event/version identity remain
  authoritative before model use.
- Ministry priority requires authenticated policy plus substantive science-education content; a
  source name or conference-only title is insufficient.
- LLM authority is a permutation of at most eight frozen event IDs. It cannot add facts, alter
  scores, remove vetoes or cross priority groups.
- Daily and slot finalizers validate the same frozen pool before existing atomic persistence.

## Provider safety

- Use official Zhipu chat endpoint/configuration already present in the repository.
- V4 uses JSON object mode, thinking disabled, sampling disabled and temperature zero.
- Accept only the exact versioned top-level order schema. Reject prose, markdown, aliases, partial
  results and arbitrary nesting.
- Provider-authored explanations/reason codes do not enter the domain result for v4.
- Raw provider response, secrets and candidate/full article text never enter logs or durable audit.

## Verification

- Focused domain/provider/PG/API tests plus full backend, type, lint, eval, Compose, Doctor,
  migration-head, OpenAPI and diff/security gates.
- One optional isolated real compatibility probe only after deterministic gates: synthetic data,
  max_attempts=1, no repository or business side effects, no retry.
- No news fetch, business replay, copy/image generation, delivery, SSH or deployment.
