# Focused implementation and review contract

This task-local summary prevents context truncation of the large cross-pipeline and quality specs. The owning specs remain authoritative.

## Selection invariants

- Consume governed event/fact/category/entity/source-diversity/evidence projections at the immutable run cutoff. Never recrawl or resummarize sources for reranking.
- Current scoring is `.8` with threshold 0.59. Hard vetoes are independent of numeric score and cannot be outweighed. Only controlled Ministry education content may bypass the numeric threshold, and only with zero hard vetoes.
- Daily selection remains Top 1 from eligible candidates. `no_topic` stops before retrieval/generation. Slot mode preserves its exact lineage, same-day exclusion, affinity, 1--3 limit and sibling isolation.
- An LLM may order only already-eligible candidates inside the existing priority barriers. It cannot generate an unexplained replacement score, invent evidence, rescue a veto, or act as the only safety check.
- Model text and source summaries are untrusted data. Delimit and bound them; embedded instructions never become prompt instructions.

## Persistence and provider invariants

- Persist scoring, rerank policy/model versions, input/output fingerprints, base/final ranks, safe reasons, usage and outcome. Logs do not replace durable audit state.
- Keep transactions short and do not hold a database session across provider I/O.
- Use bounded concurrency, timeouts, retries, input/output sizes and strict provider-neutral schemas. Do not let untyped provider dictionaries cross the adapter boundary.
- A provider/model/output failure produces a typed deterministic fallback, never `except Exception: pass` or an unbounded retry.
- Do not claim exactly-once across an external call and DB commit. Preserve request fingerprints and bounded job retry semantics.

## Logging and privacy

- Safe log fields: run/job/event IDs, provider capability/model, prompt/policy version, duration, token counts, request fingerprint, counts and typed outcome/failure code.
- Never log prompts, candidate titles/summaries, raw model responses, fetched content, Authorization/API keys, database URLs, signed URLs, private paths or PII.
- Candidate text must not become an event name or terminal-control output.

## Required checks

- Pure unit coverage for threshold/veto/priority invariants, permutation validation, pool cap, no-call 0/1 cases and exact fallback parity.
- MockTransport/provider tests for strict JSON, timeouts, limits, redaction and typed usage.
- Real PostgreSQL tests for migration, immutable config pinning, lease/conflict behavior and atomic decision/audit persistence; mock-only DB tests are insufficient.
- API/OpenAPI generated-client drift and Compose configuration checks for additive settings/contracts.
- Eval fake must not consume expected answers; reports must say fixture contract conformance, not live editorial accuracy.
- Ruff, strict mypy, focused/full-risk-proportionate pytest, migration head, diff check and secret scan.
