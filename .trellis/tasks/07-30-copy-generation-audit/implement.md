# Implementation Plan: Functional Copy, Audit, and One Repair

- [x] Extract minimal copy/audit/image-prompt rules from supplied brand materials/examples.
- [x] Add strict draft/claim/audit schemas and generator/auditor ports with fake/live adapters.
- [x] Add minimal run/draft/claim/evidence-binding/brand-binding/audit persistence and migration.
- [x] Implement separate evidence/brand retrieval envelopes and bounded delimited prompts.
- [x] Implement critical schema, binding, length, banned-language, privacy, image, and no-publish
      deterministic checks.
- [x] Implement typed brand/risk audit and exactly one versioned automatic repair.
- [x] Add a simple resumable happy path and status/detail APIs.
- [x] Add focused critical negative/replay/provider tests and one real selected-topic demonstration.
- [x] Update specs and run the final full-scope quality gate.
- [ ] Commit and archive the child.

Deferred: exhaustive prompt-injection/provider/chaos matrices, crash-at-every-stage coverage,
advanced cost dashboards, multiple variants, and richer manual editing.
