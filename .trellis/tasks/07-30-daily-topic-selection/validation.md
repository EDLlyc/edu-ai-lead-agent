# Validation: Daily Topic Selection Preview

## Real governed-event demonstration

- Run ID: `e513be83-6318-423c-bda3-91c37e3da601`
- Business date: 2026-07-30 (`Asia/Shanghai`)
- Candidates considered: 2
- Eligible under the original demonstration config: 2
- Selected title: `全球首个端侧驱动本体的具身世界模型！大晓机器人发布Kairos 3.1`
- Selected score: `0.7479107`
- Threshold: `0.62`
- Outcome: one durable selected daily topic; API, worker, score list, and daily result all returned
  the same event/version.

The second-ranked event was from April. Its zero freshness still left a total around `0.704`, which
was too permissive for a daily-news product. The immutable next config `scoring-v1-preview.1` adds
the transparent `stale_event` hard veto for events older than 14 days. The old run and lock remain
preserved as audit history; they were not deleted or rewritten.

## Final checks

- Alembic development database upgrade: `20260730_0005 -> 20260730_0006` passed.
- Post-migration read check preserved the real run, its 2/2 score counts, selected lock, and title.
- Topic-selection repository, API, and migration integration checks: 4 passed.
- Topic-selection unit/delivery checks: 16 passed.
- Full backend suite: 220 passed with 84% aggregate coverage.
- Full Ruff format/lint and strict mypy: passed; mypy checked 86 source files.
- OpenAPI/frontend generated contract drift, Prettier, ESLint, strict TypeScript, 3 component tests,
  and the production Vite build: passed.
- `make doctor`: passed at Alembic `20260730_0006`, including PostgreSQL, pgvector, MinIO,
  governance/checkpoint tables, topic-selection tables, source registry, and bucket health.
- `docker compose config --quiet`: passed.
- `git diff --check`: passed.

Online source crawling and model/provider tests were intentionally not repeated: this stage reads
stored governed projections and makes no provider call.

## Deferred production calibration

- Build a larger labeled recent-event set and measure undesirable Top 1 and excessive `no_topic`.
- Tune a new immutable scoring version rather than editing preview history.
- Add broader contention/crash-recovery testing when production traffic justifies it.
- Keep the current functional path disabled by default until the full content MVP is ready.
