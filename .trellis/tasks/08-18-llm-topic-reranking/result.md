# LLM topic reranking implementation result

## Outcome

Implemented the approved default-off shared daily/content-slot topic reranker. Deterministic
scoring, threshold, vetoes, Ministry priority, same-day exclusion, slot affinity, score totals, and
out-of-cap order remain authoritative. The optional fake/Zhipu stage receives at most eight already
eligible governed projections, validates a strict within-group permutation, and otherwise completes
through the exact deterministic order with a typed fallback.

Runs now pin an independent immutable rerank config. Final persistence retains deterministic and
final ranks plus one XOR-bound typed audit record in the same lease-checked transaction. APIs expose
only safe config, outcome, rank, allowlisted reason, fingerprint, usage, and latency projections.
No raw prompt/body, private path, authorization value, or provider exception is persisted or
returned.

No live provider, SSH, deployment, scheduler, Docker production mutation, WeCom send, commit, or
push was performed.

## Files changed

### Domain, application, adapters, worker, and configuration

- `.env.example`
- `compose.yaml`
- `Makefile`
- `backend/app/core/config.py`
- `backend/app/domain/topic_rerank.py`
- `backend/app/domain/topic_selection.py`
- `backend/app/domain/content_slots.py`
- `backend/app/application/ports/topic_rerank.py`
- `backend/app/application/ports/topic_selection.py`
- `backend/app/application/ports/content_slots.py`
- `backend/app/application/services/topic_reranking.py`
- `backend/app/application/services/topic_selection.py`
- `backend/app/application/services/content_slots.py`
- `backend/app/infrastructure/ai/topic_rerank.py`
- `backend/app/content_worker_main.py`

### Persistence, migration, schemas, and APIs

- `backend/alembic/versions/20260818_0022_topic_llm_rerank.py`
- `backend/app/infrastructure/db/models.py`
- `backend/app/infrastructure/db/topic_selection.py`
- `backend/app/infrastructure/db/content_slots.py`
- `backend/app/schemas/topic_rerank.py`
- `backend/app/schemas/topic_selection.py`
- `backend/app/schemas/content_slots.py`
- `backend/app/api/v1/routes/topic_selection_runs.py`
- `backend/app/api/v1/routes/topic_selection_views.py`
- `backend/app/api/v1/routes/content_slots.py`
- `backend/openapi.json`
- `frontend/src/lib/api/generated/schema.d.ts`

### Tests and offline evaluation

- `backend/tests/unit/test_topic_rerank.py`
- `backend/tests/unit/test_topic_selection_delivery.py`
- `backend/tests/unit/test_content_slot_services.py`
- `backend/tests/contract/test_topic_rerank_provider.py`
- `backend/tests/integration/test_topic_selection_repositories.py`
- `backend/tests/integration/test_topic_selection_api.py`
- `backend/tests/integration/test_content_slots_api.py`
- `backend/tests/integration/test_wecom_slot_delivery_concurrency.py`
- `backend/tests/integration/test_migrations.py`
- `backend/tests/integration/test_governance_migrations.py`
- `backend/tests/integration/test_governance_migration_downgrade.py`
- `backend/evals/topic_rerank/__init__.py`
- `backend/evals/topic_rerank/README.md`
- `backend/evals/topic_rerank/cases.v1.jsonl`
- `backend/evals/topic_rerank/runner.py`
- `backend/evals/topic_rerank/canonical-report.json`
- `backend/evals/topic_rerank/canonical-report.md`

### Executable specs and task evidence

- `.trellis/spec/backend/topic-selection.md`
- `.trellis/spec/backend/content-slot-production.md`
- `.trellis/spec/backend/agent-pipeline.md`
- `.trellis/spec/backend/database-guidelines.md`
- `.trellis/spec/backend/quality-guidelines.md`
- `.trellis/tasks/08-18-llm-topic-reranking/implement.md`
- `.trellis/tasks/08-18-llm-topic-reranking/result.md`

The task's existing `task.json`, PRD, design, research, and injected JSONL context remain part of
the untracked task directory but were not rewritten during implementation.

## Verification

- Focused unit/contract/real-PostgreSQL/API/migration slice: `111 passed`.
- Full backend suite (run because migration and shared ORM models changed): `1000 passed`,
  82% aggregate coverage after the independent review regression was added.
- Strict mypy: `Success: no issues found in 168 source files`; eval runner also passes standalone
  strict mypy.
- Ruff: all backend app, migration, tests, and topic-rerank eval files formatted; all checks pass.
- Offline eval: `8/8` synthetic daily/morning/noon/evening/priority/veto/same-day/fallback cases;
  canonical JSON/Markdown drift check passes and claims fixture contract conformance only.
- Alembic: one head, `20260818_0022`; clean-head and SQLAlchemy metadata parity tests pass.
- Production OpenAPI and generated frontend type drift checks pass.
- Agent Workbench OpenAPI/generated type drift checks pass with no Agent Workbench contract diff.
- Frontend TypeScript typecheck and Prettier check pass.
- `docker compose config --quiet` passes.
- `git diff --check` passes.
- Credential-pattern scan found only the repository's pre-existing documented local PostgreSQL
  placeholders; no new real token/private-key/provider credential was found.

## Remaining risks and follow-ups

- Production activation and any live-model editorial-quality evaluation remain intentionally out of
  scope. The flag defaults to false.
- Provider exactly-once is not claimed: a crash after a provider response but before commit may
  cause one bounded durable retry; request fingerprints make this observable.
- Unrelated modified report files and `.trellis/tasks/08-17-agent-workbench-public-portfolio/`
  were preserved and not edited by this task.

## Independent review and self-fixes

- Escaped literal `<` and `>` characters inside the serialized candidate JSON before placing it
  between prompt delimiters. A governed title containing `</candidate_data>` can no longer close
  the data-only block; the regression test exercises that exact injection string.
- Tightened `TopicRerankOutcome` construction so duplicate candidate IDs, reordered skipped or
  fallback outcomes, incomplete/misaligned applied reasons, malformed fingerprints, and negative
  usage/latency cannot become durable audit state.
- Reviewer verification: focused unit/adapter/real-PostgreSQL/API/migration slice `45 passed`;
  full backend `1000 passed` at 82% coverage; frontend `112 passed` plus production build; Ruff,
  strict app/eval mypy, both OpenAPI/generated-client drift checks, Compose render, unique Alembic
  head, 8/8 fixture eval, `git diff --check`, and changed-file credential-pattern scan all pass.
