# Implementation Plan: Durable WeChat Official Account Draft Worker

## 1. Contracts and pure domain

- [x] Update the WeChat draft spec from one-shot development adapter to an independent,
      default-disabled durable draft scheduler/worker while preserving permanent no-publish truth.
- [x] Add domain states, version constants, request/account fingerprinting, typed status/claim/item
      projections, and repository/artifact-store ports.
- [x] Refactor existing draft preparation into a reusable pure owner without changing direct caller
      behavior or provider payloads.

Validation:

```bash
cd backend
uv run pytest tests/unit/test_wechat_official_account_draft.py -q
uv run mypy app/domain app/application/ports app/application/services/wechat_official_account_draft.py
```

## 2. Immutable artifact handoff

- [x] Add a public strict finalized-weekly-aggregate loader that validates live provenance and
      rejects current fixture-only output before enqueue/provider construction.
- [x] Implement content-addressed staging and resolution with full-ref grammar checks, no-clobber
      writes, symlink/path-traversal rejection, and revalidation on resolution.
- [x] Implement bounded finalized-aggregate inbox discovery without adding any WeChat import/call to
      weekly DAG code.
- [x] Cover explicit aggregate enqueue and automatic inbox reconciliation with the same strict
      aggregate/preparation/staging path, including fixture zero-call behavior.

Validation:

```bash
cd backend
uv run pytest tests/unit/test_wechat_official_account_draft_artifacts.py -q
uv run pytest tests/integration/test_official_account_weekly_dag.py -q
```

## 3. PostgreSQL durability

- [x] Add migration `20260901_0042`, ORM models, and repository implementation for jobs/items/
      attempts, idempotent enqueue, claim, heartbeat, fenced transitions, status, and stale recovery.
- [x] Assert migration/metadata parity, clean upgrade/downgrade, concurrent enqueue, claim isolation,
      reclaim-before-side-effect, unknown-after-side-effect, and stale fencing rejection.

Validation:

```bash
cd backend
uv run alembic heads
uv run pytest tests/integration/test_migrations.py \
  tests/integration/test_wechat_official_account_draft_jobs.py -q
```

## 4. Worker, CLI, and settings

- [x] Implement the batch executor with all-three preflight, persisted child progress, heartbeat,
      bounded known retry, terminal unknown semantics, and safe structured logs.
- [x] Add default-disabled bounded settings, `.env.example` placeholders, JSON CLI commands, and an
      optional local Compose profile without enabling or deploying it.
- [x] Add fake-client worker/CLI tests proving three drafts, idempotent replay, partial resume,
      disabled zero-call behavior, error projection, and secret/path/media-ID absence.

Validation:

```bash
cd backend
uv run pytest tests/unit/test_wechat_official_account_draft_worker.py \
  tests/contract/test_wechat_official_account_draft_cli.py -q
```

## 5. Full focused gate and review

- [x] Run Ruff format/check and strict mypy on all touched backend modules.
- [x] Run WeChat adapter, V2 handoff, weekly edition/DAG, WeCom regression, and new PostgreSQL tests.
- [x] Run migration-head checks, Trellis task validation, secret/path leakage searches, and
      `git diff --check`.
- [x] Dispatch Trellis check review; fix every verified finding; update the backend spec with the
      final executable contract.
- [x] Present an exact commit plan and wait for one-shot commit confirmation. Do not deploy and do
      not make a real WeChat provider request during this task.

Suggested final commands:

```bash
cd backend
uv run ruff format --check app tests alembic/versions
uv run ruff check app tests alembic/versions
uv run mypy app
uv run pytest \
  tests/unit/test_wechat_official_account_draft.py \
  tests/unit/test_official_account_weekly_edition.py \
  tests/contract/test_wechat_official_account_client.py \
  tests/integration/test_official_account_weekly_dag.py \
  tests/integration/test_wechat_official_account_draft_jobs.py \
  tests/integration/test_migrations.py -q
cd ..
python3 ./.trellis/scripts/task.py validate 09-01-wechat-official-account-draft-worker
git diff --check
```

## Risky Files and Rollback Points

- `backend/app/infrastructure/db/models.py` and the new Alembic revision: compare metadata with the
  actual single head before and after implementation; never edit an older migration.
- `backend/app/application/services/wechat_official_account_draft.py`: preserve current direct-call
  contract and existing provider tests while extracting preparation.
- `.env.example` and `compose.yaml` are already dirty from unrelated work; edit and later stage only
  exact task hunks.
- Any ambiguity after a provider side effect must roll forward to `outcome_unknown`, never back to a
  retryable state.
