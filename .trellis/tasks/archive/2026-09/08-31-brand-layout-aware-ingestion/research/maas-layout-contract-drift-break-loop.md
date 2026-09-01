## Bug Analysis: MaaS Layout Contract Drift

### 1. Root Cause Category

- **Category**: B — Cross-Layer Contract; E — Implicit Assumption; D — Test Coverage Gap.
- **Specific Cause**: The raw MaaS response included `native_label`, but the public response documentation and
  the open-source formatter exposed only an incomplete view of its values. GLM-OCR merge-mode comments also
  repeated header/footer where the authoritative PP-DocLayoutV3 label list has distinct `header_image` and
  `footer_image` roles. The strict adapter correctly failed closed, but its initial element-extra/native-label
  diagnostics could not distinguish field presence, value class, closed-set membership, or canonical conflict.

### 2. Why Fixes Failed

1. **Generic element-extra diagnosis**: It proved the strict raw contract had drifted, but did not identify the
   added field and encouraged a symptom-level fix.
2. **Formatter-subset allowlist**: Accepting `native_label` against the visualization/output subset omitted
   PP-DocLayoutV3 roles that MaaS could still emit.
3. **Coarse native-label reason**: It preserved privacy but combined invalid type, limit, unknown role, and
   canonical conflict, so the next gate still lacked discriminating evidence.
4. **23-role duplicate assumption**: Merge-mode comments were treated as the schema oracle, incorrectly folding
   header/footer images into header/footer instead of checking the official unique model label list.
5. **Evidence strategy**: Repeated fixes guessed the next representation. The metadata-only probe finally
   supplied discriminating evidence—only the two enum names—without reading provider or corpus content.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
|---|---|---|---|
| P0 | Architecture | Keep raw models explicit and closed; never replace drift handling with `extra="ignore"`. | DONE |
| P0 | Runtime diagnostics | Map envelope/stage failures and native-label type, limit, unknown, and conflict to content-free allowlisted reasons. | DONE |
| P0 | Documentation | Use the official PP-DocLayoutV3 25-label list as the role oracle; treat formatter subsets and comments as non-authoritative. | DONE |
| P0 | Privacy | Use a bounded metadata-only probe for field/enum discrimination; retain no body, content, bbox, path, or raw exception. | DONE |
| P0 | Test coverage | Exhaustively bind all 25 roles to canonical groups and test unknown values, conflicts, sentinels, and empty cause/context. | DONE |
| P0 | Rollout | Gate one document before the second; require exact slices, complete vectors, page-linked retrieval, and retained rollback versions. | DONE |
| P1 | Process | Apply the same raw-contract/probe/closed-expansion checklist to every provider adapter when schema drift appears. | DONE |

### 4. Systematic Expansion

- **Similar Issues**: All adapters that parse provider JSON or multimodal outputs—copy generation, topic rerank,
  image generation/validation, IP recognition, official-account generation, visual embedding, and Agent
  retrieval/workbench—can face documented-envelope versus live-raw-contract drift.
- **Design Improvement**: Separate raw provider DTOs, normalized domain projections, and public schemas. Expand
  only named fields and closed enums; preserve canonical mapping checks and discard provider-only metadata
  before persistence.
- **Process Improvement**: When an unknown-field or unknown-enum failure repeats, stop guessing. Compare the
  raw official contract and SDK/model oracle, then seek the smallest metadata-only observation that separates
  competing hypotheses. Use a one-entity activation gate before a wider rollout.
- **Knowledge Gap**: Formatter mappings, visualization groups, merge comments, and SDK projections are not the
  raw model label contract. Reviews must state which source is authoritative for each layer.

### 5. Knowledge Capture

- [x] Added the durable provider-schema-drift playbook to
  [brand-knowledge-rag.md](../../../spec/backend/brand-knowledge-rag.md).
- [x] Recorded the controlled failures, metadata-only probe, final 25-role oracle, and successful one-then-two
  document gate in the task implementation/result artifacts.
- [x] Checked for a corresponding Trellis template source. None exists for this project-local brand-RAG spec;
  template synchronization is not applicable, and no template was invented.
- [ ] Reuse this playbook during the next actual schema-drift change in another provider adapter; no speculative
  adapter edits are part of this retrospective.
- [ ] Commit remains governed by checklist item 14 and is intentionally not performed in this docs-only step.
