# Bug Analysis: Ministry priority overreach and brittle rerank output

### 1. Root Cause Category

- **Category**: B — Cross-Layer Contract, E — Implicit Assumption, D — Test Coverage Gap.
- **Specific cause — priority**: authenticated source policy was composed with a broad editorial
  cohort as if that proved substantive science-education content. The rule did not inspect the
  candidate's actual policy/practice shape, so a general education meeting received a threshold
  bypass.
- **Specific cause — rerank**: the model was asked to author ordering plus ordinals, reason codes and
  explanations even though only ordering affected the decision. JSON mode was implicitly treated
  as stronger field-shape enforcement than the provider contract guarantees.
- **Specific cause — review gaps**: initial v4 reused the historical JSON-envelope extractor and
  globally widened reason-code validity. Focused implementation tests covered the built-in adapter
  but did not initially close the domain boundary for custom results or reject fenced/prose output.

### 2. Why earlier behavior failed

1. **Source-level shortcut**: authenticating Ministry metadata correctly proved provenance, but not
   editorial substance. Reusing the broad cohort converted a source preference into blanket
   priority.
2. **Over-specified provider output**: making the model emit local audit fields multiplied schema
   failure points without granting useful model authority.
3. **Surface compatibility risk**: loosening a generic JSON extractor would have hidden the symptom
   while accepting more ambiguous output. The successful fix instead reduced the wire contract.
4. **First v4 review finding**: parser and reason-code helpers were shared too broadly. Independent
   review caught the cross-version behavior before completion.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
|---|---|---|---|
| P0 | Architecture | Give each semantic change a new immutable scoring/priority/rerank identity | DONE |
| P0 | Architecture | Limit LLM authority to a complete frozen event-ID permutation; derive audit fields locally | DONE |
| P0 | Runtime | Validate exact top-level v4 JSON, complete permutation, priority barrier and finalizer bindings | DONE |
| P0 | Test | Lock `.9` config and v1/v2/v3 prompt fingerprints; retain literal historical parser tests | DONE |
| P0 | Test | Keep the real Tibet meeting as a negative regression and substantive policy/practice cases as positives | DONE |
| P1 | Review | Require version-specific diagnostics and reject cross-policy result construction | DONE |
| P1 | Documentation | Record the narrow priority and minimal provider wire in backend topic-selection specs | DONE |

### 4. Systematic Expansion

- **Similar issues**: any source-specific boost must distinguish provenance from content substance;
  provider adapters should not ask models to generate values the application can derive safely.
- **Design improvement**: immutable policy dispatch plus narrow authority objects prevents current
  defaults from rewriting historical audit meaning.
- **Process improvement**: future provider compatibility fixes must begin with an observed typed
  failure and reduce the contract before considering aliases or permissive parsing.
- **Knowledge gap closed**: `json_object` guarantees JSON syntax, while the prompt and local schema
  still own field structure and semantic validation.

### 5. Knowledge Capture

- [x] Updated `.trellis/spec/backend/topic-selection.md`.
- [x] Updated `.trellis/spec/backend/agent-pipeline.md`.
- [x] Updated `.trellis/spec/backend/content-slot-production.md`.
- [x] Added immutable replay, exact parser and real-regression tests.
- [x] Recorded the one-call compatibility result without raw provider output.
- [x] Confirmed this repository has no `src/templates/markdown/spec/` mirror to synchronize.
