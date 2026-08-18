# Bug Analysis: Live GLM Topic Rerank Rejected as Invalid Output

## 1. Root Cause Category

- **Category B — Cross-Layer Contract**: The adapter requested JSON mode, but the prompt did not
  state the exact provider-facing JSON schema or literal enum values. The local test fixture emitted
  the adapter's ideal internal shape rather than an independently provider-shaped response.
- **Category D — Test Coverage Gap**: Contract tests proved that the parser accepted a hand-built
  perfect object, not that the request followed the complete documented GLM-5.2 structured-output
  contract or that bounded real-world JSON envelopes were accepted.
- **Category E — Implicit Assumption**: Completion-envelope, JSON-envelope, schema, and UUID errors
  were treated as one undifferentiated parse failure. This assumed all invalid output would be
  diagnosable from one public error code, while privacy rules intentionally discarded the body.

The pre-fix live evidence cannot identify one exact malformed field because raw completion content
was correctly not retained. Before the fix, plausible hypotheses were: schema/enum mismatch (45%),
JSON wrapping/prose (35%), and thinking/output-budget interference (20%). The official API contract
and one successful post-fix call strongly validate the combined v2 request/parser contract, but do
not justify claiming which single pre-fix hypothesis occurred.

## 2. Why Earlier Validation Failed

1. **Self-confirming mock**: `_response_content()` was authored from the local Pydantic schema, so it
   could not reveal that the prompt omitted the literal enum/schema contract.
2. **Collapsed diagnostics**: every post-HTTP parse problem became
   `topic_rerank_schema_invalid`; safe usage/latency and stage information were lost.
3. **Unversioned repair risk**: changing the one prompt/parser in place would have reinterpreted
   immutable `topic-rerank-v1` replays.
4. **Privacy blind spot found in review**: generic Pydantic `loc` normalization allowed an unknown
   provider-controlled extra-field name to survive. The safe diagnostic itself therefore needed a
   topic-schema allowlist.

## 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
| --- | --- | --- | --- |
| P0 | Versioned architecture | Couple v1/v2 prompt, payload, and parser to immutable policy identity; reject request/config mismatch before HTTP | DONE |
| P0 | Provider contract | V2 states the exact object, item count, ordinals, seven enum values, priority barrier, and no-prose rule | DONE |
| P0 | Runtime compatibility | Use the existing bounded one-object scanner, followed by unchanged strict Pydantic/domain validation | DONE |
| P0 | Privacy | Project diagnostic locations through stable schema segments; unknown provider keys become `unknown` | DONE |
| P1 | Test coverage | Use independent provider-shaped fixtures and exact v1/v2 payload-key assertions | DONE |
| P1 | Observability | Separate completion, JSON-envelope, and schema failures and retain safe fingerprint/usage/latency | DONE |
| P1 | Live acceptance | After all local gates, make one synthetic `max_attempts=1` call through the production adapter | DONE |

## 4. Systematic Expansion

- **Similar issues**: Any structured-output adapter whose mock is generated from its validation
  model can be self-confirming. Copy generation now shares the same bounded envelope owner and its
  existing tests remain mandatory.
- **Design improvement**: Provider representation compatibility belongs in one shared transport
  helper; domain schema and semantic validation stay feature-owned and strict.
- **Process improvement**: A provider contract test must independently assert request parameters,
  use an independently written response fixture, and prove safe invalid-output diagnostics before a
  bounded live acceptance is considered.
- **Knowledge boundary**: A successful combined fix validates compatibility but does not recreate
  discarded pre-fix raw content. Reports must distinguish verified outcome from inferred root cause.

## 5. Knowledge Capture

- [x] `.trellis/spec/backend/topic-selection.md` records versioned prompt/payload/parser coupling,
  official v2 request shape, strict compatibility, and fallback metrics.
- [x] `.trellis/spec/backend/error-handling.md` records the shared envelope and stable-location
  privacy projection.
- [x] `.trellis/spec/backend/quality-guidelines.md` requires independent v1/v2 provider fixtures,
  malformed-envelope/type/privacy matrices, and no self-confirming live claims.
- [x] `.trellis/spec/backend/logging-guidelines.md` records allowed rerank diagnostics and forbidden
  content.
- [x] Agent-pipeline and content-slot specifications describe the same immutable policy behavior.
- [x] No template sync applies because this repository has no `src/templates/markdown/spec/` tree;
  these are project-owned Trellis specifications.
