# Design: Relax Deterministic Copy Validation Blockers

## Boundary

The change is limited to the copy-generation policy boundary and its production rollout. The
domain validator remains the source of issue codes and severities. The application executor keeps
the existing one-repair state machine, and the delivery service continues to require a persisted
validated package before it creates a WeCom job.

## Versioned policy

Add a new preview policy version. The new version is selected by the existing `Settings` preview
default and included in `CopyVersionBundle.fingerprint`, generator and auditor request
fingerprints, and persisted run metadata. Existing v8/v9 values remain recognized for historical
records and explicit replay behavior; strict and older preview policies are not changed.

The new preview warning set is the existing quality warning set plus exactly these deterministic
codes:

- `claim_not_in_copy`
- `source_note_unlinked`
- `unclaimed_external_fact`

It also includes the explicitly requested deterministic content codes `personal_data`,
`prompt_injection_echo`, `prohibited_marketing`, and `education_anxiety`. The corresponding audit
allowlist covers the existing semantic aliases emitted by the auditor for privacy, prompt echo,
marketing exaggeration/promotional language, and education anxiety. The sets are version-scoped;
they must not be added to the historical v8 or strict policy. No database migration is needed
because issue severity is already a persisted `warning`/`error` field.

## Data flow

```text
provider draft
  -> deterministic validator
  -> normalize configured consistency/content codes to warning for new preview rule
  -> persist draft/issues/checkpoint
  -> audit (warnings allowed)
  -> at most one quality repair
  -> accepted package when no hard error remains
  -> image/package executor
  -> date-scoped WeCom dispatcher
```

The repair path remains bounded. A warning-only first draft reaches audit, and warning-only audit
results may trigger one repair. A repaired draft with warnings still has `validation_passed=true`
and is accepted when the audit has no error-level issue.

## Hard-boundary compatibility

The new set must not include unknown evidence/brand identifiers, missing evidence/source notes,
evidence-text mismatch, source-footer integrity, automatic publishing, unsafe-image, provider
identity, schema, image, storage, or delivery errors. The prompt text and tests must make this
split explicit. Detection and safe issue persistence remain active for the four downgraded content
categories; only their blocking severity changes.

## Rollout and rollback

Run focused backend tests first, then the normal quality gate. Build the pinned server release,
run the existing migration command as a no-op/head check, and start services in their existing
dependency order. Do not manually enqueue or send a package. If the new worker or dispatcher is
unhealthy, stop write-producing services and restore the previous release/images while preserving
PostgreSQL/MinIO volumes and the existing backup set.
