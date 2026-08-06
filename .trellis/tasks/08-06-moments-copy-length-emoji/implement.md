# Implementation plan

## Ordered checklist

1. [x] Add pure copy-body, CJK-count, and emoji-count helpers with bounded Unicode handling and unit
   coverage.
2. [x] Replace the old whole-string copy length check with the 300-500 body Chinese-character target and
   add the 2-5 body emoji target warning while preserving hashtag validation.
3. [x] Update generator and auditor prompts and bump the pipeline, generator, auditor, strict-rule, and
   active preview-policy version identifiers.
4. [x] Make the deterministic fake generator produce a valid 300-500-character body with natural emoji
   so local and integration tests exercise the new contract.
5. [x] Add/adjust tests for boundaries, exclusions, prompt text, advisory continuation through audit,
   and the existing one-time hard-error repair and terminal review behavior.
6. [x] Run targeted copy tests, then Ruff, mypy, and the full backend quality command.
7. [x] Review the diff for secrets, unrelated worktree changes, and accidental delivery calls.

## Validation commands

```bash
cd backend && pytest tests/unit/test_copy_generation.py tests/contract/test_zhipu_copy_provider.py
cd backend && ruff check app tests
cd backend && mypy
make backend-check
```

## Risk points

- `backend/app/schemas/copy_generation.py`: emoji sequence counting and malformed trailing hashtag
  handling.
- `backend/app/domain/copy_generation.py`: length and emoji issues must remain advisory under both
  preview and strict policies, while factual and safety issues remain blocking.
- `backend/app/infrastructure/ai/copy_generation.py`: fake output must satisfy evidence bindings
  and the new count without introducing unsupported facts.
- `backend/app/core/config.py` and the backend agent-pipeline spec: version strings and durable
  contract documentation must stay synchronized.

## Rollback point

The change is isolated to copy validation, prompts, fake output, version metadata, and tests. If
verification fails, revert only this task's files and retain unrelated reports and user worktree
changes.
