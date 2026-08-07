# Implementation Plan

## Ordered Checklist

1. [ ] Add shared paragraph-format helpers/issue classification beside the existing copy body,
   hashtag, Hanzi, and emoji helpers.
2. [ ] Make `copy_paragraph_format` and `copy_emoji_count` warning-only in deterministic and LLM
   audit policy paths; preserve hard safety/evidence/claim failures.
3. [ ] Update generator and auditor prompts to require at least three natural paragraphs separated
   by one newline, no blank lines, and 2-5 body emoji, while explicitly preserving warning-only
   continuation semantics.
4. [ ] Update `CopyGenerationExecutor` to trigger exactly one v2 repair for format warnings and to
   accept the original draft when an advisory-only repair provider failure occurs.
5. [ ] Bump copy version identifiers and update backend agent-pipeline documentation with the new
   format/repair contract.
6. [ ] Add focused unit tests for the new validator, prompt, repair, imperfect-repair acceptance,
   and advisory-provider-failure paths; retain hard-error terminal-state coverage.
7. [ ] Run targeted tests, backend lint/type/format checks, then the full backend and operational
   checks.
8. [ ] Review diff for scope, secrets, unrelated worktree changes, and real external side effects;
   build and deploy the backend release to the production server only after the planning approval
   and quality gate.

## Validation Commands

```bash
conda run --name edu-ai pytest backend/tests/unit/test_copy_generation.py -q
make backend-format-check backend-lint backend-typecheck
make backend-check
make doctor
docker compose config --quiet
git diff --check
```

Production verification after deployment:

```bash
docker compose --profile governance --profile content --profile wecom ps --all
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT version_num FROM alembic_version;"'
```

Do not invoke a real paid copy/image generation or WeCom delivery in the automated test suite.

## Risk Points

- `backend/app/application/services/copy_generation.py`: warning-only format issues must still
  initiate one repair without altering hard-error terminal behavior.
- `backend/app/schemas/copy_generation.py` and `backend/app/domain/copy_generation.py`: paragraph
  counting must exclude the hashtag line and never make format failure blocking.
- `backend/app/infrastructure/ai/copy_generation.py`: the deterministic fake must exercise the new
  single-newline and emoji contract without weakening evidence binding.
- `backend/app/core/config.py` and `.trellis/spec/backend/agent-pipeline.md`: versions and durable
  documentation must match the implementation.
- Existing reports and `.agents` edits are unrelated user work and must remain untouched.

## Rollback Point

Before deployment, the prior commit is the rollback point. If focused or full checks fail, keep the
task in progress and fix the affected code. If production deployment fails, restore the previous
backend image/configuration without deleting PostgreSQL/MinIO volumes or durable jobs.
