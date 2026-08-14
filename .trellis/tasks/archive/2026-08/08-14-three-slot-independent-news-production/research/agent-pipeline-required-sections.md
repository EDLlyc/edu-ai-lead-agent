# Agent-pipeline contracts required during implementation and check

The source of truth is `.trellis/spec/backend/agent-pipeline.md`. It exceeds Trellis's direct
context-injection byte limit, so implement/check agents must read the following sections from the
repository before changing the corresponding stage; this routing note is not a replacement for the
spec.

- Lines 179--240: factual-governance handoff and implemented eligibility/scoring/selection. Preserve
  stored-evidence use, hard vetoes, exact version dispatch and `no_topic` provider stop.
- Lines 241--392: retrieval, draft schema, evidence/brand claim bindings, deterministic validation,
  audit and current short-copy policy. Every slot item remains one evidence-bound complete draft.
- Lines 393--559: automatic daily copy boundary, preview quality projection and structured provider
  repair rules. Generalize the origin/reconciliation identity without claiming old jobs or changing
  warning/error semantics.
- Lines 560--710: job idempotency and one-image provider contract. Every selected item has its own
  durable request; preserve lease/heartbeat, one-success identity, SSRF/output validation and paid
  call bounds.
- Lines 818--938: versioned material-package reservation/manual reuse. Reconciliation may create one
  package per accepted slot copy but must preserve fingerprint, private storage and API boundaries.
- Lines 939--1033: bounded provider rejection recovery and catalog fallback. Sibling slot items do
  not share retry/fallback identities or results.
- Lines 1034--1054: material package boundary and verification cases. New slot metadata is a safe
  additive projection and never exposes prompts, object keys, private URLs or image bytes.

Implementation and check must also search the current spec for every occurrence of `daily`,
`business_date`, `one`, `automatic`, `reconcile`, `material package`, `image`, and `historical`
after edits, then update the spec to distinguish the legacy daily contract from the new slot
contract without deleting historical guarantees.
