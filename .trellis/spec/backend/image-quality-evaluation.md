# Image-Quality Evaluation and Final-Publication Observation

## 1. Scope / Trigger

Use this contract when changing the provider-free image-quality harness, the optional official-
account final-publication observer, generated-visual persistence, or editor-handoff visibility
claims. The observer evaluates the publication artifact produced after center crop and JPEG
encoding. It is evidence only: `observe` must not become a release gate or regeneration policy.

## 2. Signatures

- Shared domain: `app.domain.image_quality_eval`
  - `build_image_eval_issue(...) -> ImageEvalIssue`
  - `build_image_eval_observation(...) -> ImageEvalObservation`
  - `decide_image_eval(...) -> ImageEvalDecision`
  - `decide_image_eval_batch(...) -> ImageEvalBatchDecision`
  - `active_image_eval_rubric() -> ImageEvalRubric`
- Provider port: `ImageQualityAuditor.audit(ImageQualityAuditRequest) -> ImageQualityAuditResult`.
  `ImageQualityAuditRequest` carries final bytes, media type, a SHA-256 request fingerprint,
  bounded per-image criteria, prompt/rubric versions, and typed reference images.
- Repository completion:
  `persist_generated_visual(claimed, plan, result, eval_result=None)` must mark the visual ready and
  insert the optional immutable eval row in one fenced transaction.
- Repository projection:
  `list_generated_visual_evals(run_id=...)` performs one bounded batch query; ORM relationships and
  per-visual lazy loads are not used.
- Alembic `20260901_0041` adds `official_account_generated_visual_evals` and the parent composite
  unique key `(id, run_id, sha256)` used by the child final-hash foreign key.

## 3. Contracts

- `IMAGE_QUALITY_EVAL_MODE` is `off|observe` and defaults to `off`.
- `off` performs no quality-provider call and creates no eval row. Existing ready behavior remains
  unchanged.
- `observe` audits the exact final `image/jpeg`, `1536x1024` bytes. It records `accepted`,
  `manual_review`, `rejected`, or `unavailable` but does not change readiness or release gates.
- A single-image provider record covers exactly semantic faithfulness, IP identity, OCR/text,
  aesthetics/artifacts, and publication layout. Batch diversity remains a separately reported
  offline/future batch-evaluator dimension and must not be claimed from one image.
- The approved reference is normalized with the plan's frozen image-input version and its PNG
  checksum must equal `plan.reference_input_checksum` before it is sent to the auditor.
- Each child row is immutable and unique per generated visual. Its composite foreign key binds
  `generated_visual_id`, `run_id`, and `publication_sha256` to the ready parent result. The record
  stores only bounded versions, fingerprints, decisions, normalized observations, safe issue
  codes, and optional provider/model identity.
- `record_fingerprint` covers the visual/run IDs, final SHA-256, request fingerprint, versions,
  provider/model, normalized observations, and aggregate decision. It excludes completion time.
- Never persist image bytes, scene criteria, raw prompts, provider bodies, vectors, private paths,
  bucket keys, or free-form provider explanations in an eval row.
- Handoff emits `durable_image_audit_accepted` only for a recomputed, current-version accepted
  record whose request fingerprint, record fingerprint, run/visual identity, and final SHA-256 all
  match. Every absent, unavailable, warning/review, rejected, stale-version, or mismatched record
  projects `passed_local_visual_inspection`; it does not make a ready visual undeliverable.
- A ready historical row without an eval child is never backfilled by a paid call during recovery.

## 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Mode is not `off|observe` | Settings/executor construction rejects it |
| `observe` with no usable adapter or credentials | Five unavailable observations; ready still commits |
| Provider timeout or typed transport failure | `unavailable/provider_unavailable`; no raw error persisted |
| Invalid provider schema | `unavailable/invalid_output` |
| Provider/model/request fingerprint mismatch | `unavailable/identity_mismatch` |
| Unknown provider issue code | Stable `provider_audit_unclassified` warning and manual review |
| Critical closed issue | Aggregate `rejected`; aesthetic scores cannot offset it |
| Warning without critical issue | Aggregate `manual_review` |
| Final SHA or normalized reference checksum mismatch | Reject the attempted binding; never claim accepted |
| Lease/fencing loss before completion | No ready transition and no eval child |
| Stored observation/decision/record fingerprint drift | Repository treats the row as invalid |

## 5. Good / Base / Bad Cases

- Good: `observe` audits the prepared JPEG, MinIO content-addressed storage succeeds, and one
  fenced commit writes both ready metadata and an accepted, hash-bound child. Handoff may claim
  `durable_image_audit_accepted`.
- Base: mode is `off`, or a historical visual is already ready without a child. It remains
  deliverable and handoff says `passed_local_visual_inspection`.
- Good degraded case: the adapter is unavailable or returns a typed failure. The same completion
  transaction writes ready plus an unavailable child; release behavior is unchanged.
- Bad: persist ready first and insert eval in a second transaction. A crash creates a ready row
  with missing evidence and recovery skips the paid provider call.
- Bad: audit raw provider output before publication crop/compression, or send JPEG reference bytes
  under a PNG media type. Neither result is evidence about the delivered artifact.

## 6. Tests Required

- Domain/runner: strict schema, closed taxonomy, five-dimension batch aggregation, six-dimension
  fixture coverage, duplicate/malformed/hash/canonical drift, critical false-pass, and manual
  review metrics.
- Provider adapter: criteria, prompt/rubric version, closed single-image issue codes, final JPEG,
  typed normalized PNG reference, and strict structured output.
- Worker service: default off makes no auditor call; observe uses final bytes; accepted, warning,
  critical, empty rejection, and unavailable branches; storage/lease failure; ready recovery makes
  no audit call.
- Repository/PostgreSQL: ready+eval atomicity, exact replay behavior, composite hash/run FK,
  one-record uniqueness, JSON/decision constraints, old ready rows without children, record
  fingerprint validation, empty downgrade success, and populated downgrade refusal.
- Handoff: exact current accepted record yields durable status; no record and every other decision,
  hash/version/fingerprint mismatch yield local-inspection status without failing the ready gate.
- Canonical command: `make image-quality-eval` must remain provider-free and use `--check` in CI.

## 7. Wrong vs Correct

### Wrong

```python
stored = await repository.persist_generated_visual(claimed=claim, plan=plan, result=result)
await repository.insert_eval(stored.id, provider_observation)  # second transaction
```

This permits `ready` without its claimed evidence after a crash and invites recovery-time duplicate
provider calls.

### Correct

```python
eval_result = await observe_final_publication(prepared.image_bytes) if mode == "observe" else None
stored = await repository.persist_generated_visual(
    claimed=claim,
    plan=plan,
    result=prepared.result,
    eval_result=eval_result,
)
```

The provider call stays outside the transaction, while ready metadata and the optional immutable
record share one fenced commit.
