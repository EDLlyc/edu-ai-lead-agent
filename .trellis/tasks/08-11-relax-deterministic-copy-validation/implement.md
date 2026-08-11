# Implementation Plan

1. Read the backend copy-generation, delivery, logging, and pipeline specs plus the current
   validator, executor, settings, repository persistence, and focused tests.
2. Add a new preview policy identifier for the deterministic-warning behavior and preserve old
   v8/v9, strict, and historical explicit-run semantics.
3. Create a version-scoped warning set containing `claim_not_in_copy`, `source_note_unlinked`,
   `unclaimed_external_fact`, `personal_data`, `prompt_injection_echo`, `prohibited_marketing`,
   and `education_anxiety`; include the auditor's existing equivalent marketing/privacy/injection/
   anxiety codes. Keep automatic publishing, unsafe image, unknown IDs, evidence mismatch, source
   footer, schema, provider, storage, and delivery errors hard.
4. Update generator, auditor, and repair prompt contracts to describe the warning/error split and
   state that detection is retained even though the named content issues no longer block delivery.
5. Add focused domain and executor tests for severity, version isolation, retained hard errors,
   one repair, warning-only acceptance, audit normalization, and persisted issue visibility.
   Update the pipeline spec.
6. Run focused tests, Ruff, mypy, full backend checks where practical, Compose rendering, and
   `make doctor`. Confirm no local WeCom sender is enabled.
7. Commit the code and task changes through the Trellis workflow, build the server release, and
   deploy the pinned commit with the existing backup/rollback procedure.
8. Verify server migration head, all service states/restart counts, new redacted version values,
   dispatcher automatic mode, and that no manual test delivery or historical row edit occurred.

## Validation commands

```bash
conda run --name edu-ai pytest backend/tests/unit/test_copy_generation.py -q
make backend-check
make doctor
docker compose config --quiet
git diff --check
```

For deployment verification, use the existing server-local backup, pinned release, Compose profile
startup, health, migration, log, and bounded delivery checks. Do not run an extra provider send.

## Rollback points

- Before code commit: revert only the task branch changes if focused tests fail.
- Before server activation: retain the previous release and leave durable services untouched.
- After activation failure: stop schedulers/workers/dispatcher first, preserve volumes, and restore
  the previous release/configuration; do not downgrade migrations or edit business rows.
