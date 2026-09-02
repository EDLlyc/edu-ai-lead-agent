# Design: Production Weekly Scheduler and Draft Handoff

## 1. Architecture boundary

```text
official-account-weekly-scheduler
  -> due policy (Monday 09:00 Asia/Shanghai, 24h catch-up)
  -> production weekly input planner (PostgreSQL, immutable fingerprint)
  -> existing weekly DAG repository/governance

official-account-weekly-dag-worker --handler-mode production
  -> select three real governed roles
  -> enqueue/observe three official-account local generation runs (Zhipu)
  -> validate persisted Article/render/media/draft lineage
  -> assemble one immutable production draft-source batch

wechat-official-account-draft-worker
  -> discover complete eligible batch
  -> preflight all three items
  -> upload images/thumb and create three independent unpublished drafts
```

The existing fixture handlers remain unchanged and network-free. Production construction must be a separate explicit mode and must refuse fixture handlers.

## 2. Schedule and idempotency

- Add a scheduler entrypoint following the existing `content_scheduler_main.py` lifecycle and signal handling.
- Use `CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="Asia/Shanghai")` only as the wake-up mechanism. The authoritative eligibility decision still calls `due_weekly_edition_week_start(WeeklyEditionSchedule())`.
- Add an interval reconcile so a container restart inside the 24-hour window catches up. It checks the durable business key before computing a new input.
- The first successful planner snapshot freezes the input fingerprint for that week. Later reconciles reuse the stored run and never conflict merely because more news arrived.
- A production minimum-week gate is applied before planner query, artifact creation, or provider construction.

## 3. Production input planner

- Introduce an application port that returns a path-free, typed weekly input snapshot from PostgreSQL.
- Its infrastructure repository joins the existing authoritative lineage rather than title matching: governed event/version, stored topic score and veto state, content-slot selection/copy/material package, and formal delivered business result where required by the current quality policy.
- Convert those rows into the existing `WeeklyGovernedCandidate` contract and call `select_weekly_articles`; do not duplicate role scoring.
- Freeze the selected event IDs, version IDs, material-package IDs, source authority metadata and version fingerprints in the run input artifact. The opaque artifact owner stores details; DAG rows retain hashes and safe refs only.

## 4. Production DAG handlers

- Add `ProductionWeeklyDagHandlers` behind the existing static registry protocol.
- `schedule` validates the frozen planner snapshot and schedule identity.
- `select_roles` emits the canonical three-role mapping.
- Each `build_article` node idempotently enqueues one existing official-account local run for its material package using the configured Zhipu identity.
- `plan_media`, `render_handoff`, and `validate_child` observe and validate the persisted official-account run stages rather than reimplementing the generator. A not-yet-ready upstream run is a bounded retryable state; an immutable quality rejection is terminal.
- Automatic quality mode is required. No synthetic manual-review record is created.
- `aggregate` writes a versioned prepared-draft batch only after all three validated children succeed. `finalize` publishes only its opaque batch metadata into the shared inbox volume.

## 5. Prepared draft artifact contract

The current draft worker accepts strict finalized weekly directories. Production DB-backed articles need an additive prepared-source representation rather than pretending to be the development V2 bundle.

- Add a versioned `wechat-draft-prepared-batch-v1` artifact under the existing content-addressed weekly output volume.
- The artifact contains safe article request fields, rewritten-local HTML before WeChat upload, ordered immutable body media, one cover, role/order, and exact hashes. It contains no credentials, access token, provider media ID, database DSN or MinIO object path.
- Extend the artifact-store/preparer boundary so both current finalized-weekly artifacts and the new prepared batch resolve to the same `WeChatPreparedDraft` tuple.
- Existing finalized-weekly behavior and fingerprints remain backward compatible. Production discovery accepts only the new version when production handler mode is selected.
- All three prepared drafts are loaded and verified before item 1 marks a side effect.

## 6. Runtime configuration

Add default-false settings for the production scheduler and production handler acknowledgement, plus bounded poll/catch-up controls only where not already code-owned. Compose adds:

- `official-account-weekly-scheduler`
- `official-account-weekly-dag-worker` with explicit production handler mode
- `official-account-local-worker` only if production handlers rely on the independent existing executor

All are portless, depend on migration completion, share the immutable application image, and mount only the minimum required read-only/writable volumes. The ordinary release service list remains unchanged until an explicit reviewed operator enables these profiles.

## 7. Compatibility and data migration

- Prefer no schema migration: `0040` already owns durable DAG state, `0042` owns draft jobs, and official-account local tables already exist.
- If the production planner cannot freeze its safe input identity in existing execution artifacts, add one additive table/revision only; no existing table or row is rewritten.
- Current development CLI/fixture tests and morning/noon/evening behavior remain byte- and contract-compatible.

## 8. Rollout and rollback

- Implement on an isolated branch/worktree derived from the reviewed production runtime so the current dirty `main` tree is not accidentally shipped.
- Build an immutable linux/amd64 image and compare the runtime diff against the production baseline.
- Preflight with provider networking disabled, snapshot PostgreSQL and both weekly/draft volumes, then enable processes before the first eligible Monday.
- Deployment acceptance requires `due=false`, zero weekly runs, zero draft jobs/items/attempts, zero provider writes, stable containers and healthy existing services.
- If an idle process is unstable, disable only the new flags/profiles and restore the prior runtime. If any external side effect has started, stop writers and preserve audit state instead of replaying or destructively rolling back.

## 9. Key trade-offs

- A Compose scheduler is preferred over host Cron/Systemd because it shares versioned code, settings validation, logs and release identity with the workers.
- Production handlers reuse existing generation and weekly selection services instead of copying their rules.
- A truthful prepared-draft artifact is preferred over forging the development V2 live-provenance format.
- The first release prioritizes exactly-once, no-partial-write safety over forcing a weekly batch when fewer than three valid inputs exist.
