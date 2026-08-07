# Technical Design

## Boundaries

The existing copy schema/domain validation remains the single deterministic authority for format
warnings. The application service owns the decision to spend one workflow repair attempt because
the same warning must be advisory for acceptance while still being actionable for generation. The
provider prompt remains the source of model-facing instructions. Material-package and WeCom code
consume the existing accepted run contract and do not need format-specific branches.

## Data Flow

```text
topic + brand context
  -> generator prompt with paragraph/emoji contract
  -> MaterialDraft
  -> deterministic validation
       -> format warnings (non-blocking) or hard errors
  -> audit
  -> if format warning: one existing v2 repair with bounded issues + previous draft
  -> validate/audit repaired draft
  -> accept either repaired draft or original usable draft
  -> material package -> existing WeCom delivery queue
```

The copy body is the draft after removing a final hashtag candidate line. A paragraph is one
non-empty line in that body. The validator reports a warning when there are fewer than three body
paragraph lines or when any body line is empty, which detects both a single-block copy and the
unwanted blank-line style. Newline normalization remains conservative: `splitlines()` recognizes
CRLF as one line break and does not rewrite persisted text.

## Advisory issue contract

Use a shared constant in the domain/service boundary for the format issues that trigger the one
repair:

```text
copy_emoji_count
copy_paragraph_format
```

These codes are eligible to trigger one format repair. They are always warnings in deterministic
validation and are normalized to warnings in `apply_copy_audit_policy`, including strict mode.
`copy_length` remains an advisory warning but does not trigger this format repair.
The executor decides whether a repair is useful by checking both deterministic and persisted audit
issues, not by changing `validation_passed` semantics.

## Executor State Behavior

1. Generate v1 and persist deterministic issues.
2. If v1 has hard validation errors, retain current behavior: skip audit and generate v2.
3. If v1 has only warnings, audit v1. If it is accepted with no format warning, finish accepted
   immediately. If it has a format warning, proceed to v2 even though `validation_passed` is true.
4. If v2 has only format warnings, audit it and accept it if no hard audit issue remains. Do not
   send it back through repair.
5. If v2 still has a hard validation/audit issue, finish `review_required` as today.
6. If the v2 generation call fails with invalid output/provider rejection while v1 was already
   audited and has only advisory format issues, accept v1 with `repair_count=1`. This preserves a
   usable copy and honors the non-blocking product rule. Other provider failures keep current
   retry/review semantics.

The existing durable version-2 uniqueness and checkpoint state make the repair idempotent across
worker restarts. No second repair is introduced.

## Prompt Contract

The generator prompt and auditor prompt will use the same terms:

- `正文主体分成至少3个自然段`;
- `段间只换一行，不插入空白行`;
- `正文主体包含2到5个自然emoji`;
- format misses are warning-quality signals and cannot alone reject, repair-loop, or block delivery.

The repair prompt is the generator base prompt plus existing bounded `<REPAIR>` and `<PREVIOUS>`
sections, so no separate unbounded prompt or new provider call is required.

## Versioning and Compatibility

Increment the pipeline, generator prompt, auditor prompt, rule, and preview policy identifiers.
The `MaterialDraft` and `AuditVerdict` shapes do not change. Existing database rows retain their
recorded versions. No Alembic migration is needed.

## Rollback and Operations

Rollback is a code/image rollback to the prior release. It does not require database rollback or
deleting durable jobs. Deploy only the backend images after the final quality gate, restart the
content scheduler/worker and any shared backend image consumers as required by the release
procedure, then inspect service health. Do not trigger a paid generation or real WeCom send as part
of unit verification.
