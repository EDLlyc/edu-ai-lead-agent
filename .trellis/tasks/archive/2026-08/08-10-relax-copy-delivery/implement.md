# Implementation Plan

1. Read the backend copy-generation, logging, error-handling, and quality specifications plus the existing unit/contract tests.
2. Add the new local-preview policy/version identifiers without changing the server or database.
3. Update copy body parsing and deterministic format checks for `<=300` Hanzi, exactly three two-line paragraphs, one blank separator, 6--12 emoji, and paragraph boundary emoji.
4. Add local-preview warning normalization for the requested deterministic issue codes, including `evidence_text_mismatch`; keep schema, binding-ID, database, image-file, provider, request-bound, and WeCom transport failures hard.
5. Update generator, auditor, and bounded-repair prompts to state the new copy contract and warning-only local-preview behavior.
6. Update focused unit/contract tests for versioning, format boundaries, deterministic warning severity, audit normalization, retained technical failures, and executor acceptance.
7. Run local targeted tests, lint, and type checks. Verify local WeCom settings remain false and dispatcher remains stopped.
8. Run one local preview generation using local dependencies/output only, then report the generated copy, image path, issue warnings, and material-package status. Do not deploy, push, SSH, rebuild server containers, or send WeCom messages.

## Validation Commands

```bash
cd backend && pytest tests/unit/test_copy_generation.py tests/unit/test_wecom_delivery.py
cd backend && ruff check app tests
cd backend && mypy app
docker compose --profile content ps
```

The final local smoke test must not use production credentials or the remote server. If a local provider call is needed, retain the existing provider request bounds and write generated assets only under the project-local output directory.

## Rollback Points

- Before implementation: planning artifacts only; no runtime behavior changed.
- After policy/validator edits: unit tests must pass before prompt or executor edits continue.
- Before smoke test: verify local WeCom remains disabled and no dispatcher is running.
- No server rollback or database migration is permitted in this task.
