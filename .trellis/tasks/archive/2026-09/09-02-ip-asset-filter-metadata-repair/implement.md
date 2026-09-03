# Implementation Plan: IP asset filter and metadata repair

## Ordered checklist

- [x] 1. Load backend/frontend IP asset, error, type-safety and quality specs; snapshot unrelated
      dirty paths and current 41-asset/database distribution.
- [x] 2. Add provenance-preserving text intent, soft hint scoring, candidate-existence outcome and
      closed degraded-reason enum without changing V2/V3 rank weights.
- [x] 3. Regenerate OpenAPI/types and render bounded frontend guidance for every closed reason.
- [x] 4. Add strict metadata repair plan/result domain models, fingerprints, privacy validation and
      exclusive canonical artifact I/O.
- [x] 5. Add exact-approved-41 preflight, verified MinIO recognition orchestration, deterministic
      proposal policy and `glm-5v-turbo` canary/batch CLI.
- [x] 6. Add dimension-aware metadata state and row-locked CAS apply/restore, including canonical
      naming regeneration and non-metadata preservation.
- [x] 7. Add focused unit/API/frontend/PostgreSQL/MinIO/CLI tests for search and repair behavior.
- [x] 8. Run full provider-free quality gates and independent Trellis check; update executable specs.
- [ ] 9. Commit code in isolated batches without unrelated work and without pushing.
- [x] 10. Run the authorized `glm-5v-turbo` canary plus live plan (maximum 41 new calls;
      43 cumulative including both failed historical canaries), validate/privacy-scan the artifact,
      inspect the proposed distribution, then execute local apply only when the plan remains valid.
- [x] 11. Re-apply provider-free to prove idempotency, verify non-metadata invariants and write the
      restore-ready result; do not run the 248-query live retrieval.
- [ ] 12. Record evidence, archive the Trellis task, and create local bookkeeping commits; no deploy
      or remote push.

## Validation commands

```bash
conda run --name edu-ai pytest \
  backend/tests/unit/test_ip_assets.py \
  backend/tests/unit/test_ip_asset_recognition.py \
  backend/tests/unit/test_ip_asset_metadata_repair.py -q --no-cov

conda run --name edu-ai pytest \
  backend/tests/integration/test_ip_assets.py \
  backend/tests/integration/test_ip_asset_metadata_repair.py -q --no-cov

conda run --name edu-ai ruff check <affected-python-paths>
conda run --name edu-ai ruff format --check <affected-python-paths>
conda run --name edu-ai mypy <affected-python-paths>

make api-check
make frontend-check
make ip-asset-grounded-eval-check
make ip-asset-retrieval-eval
make eval-check
git diff --check
```

The final Make/CLI names and explicit acknowledgement token are frozen during implementation. Live
plan targets remain outside `eval-check`; apply/restore require caller-supplied artifact paths and a
fixed acknowledgement.

## Provider compatibility deviation (2026-09-02)

- The first live canary made one call and failed closed. Its legacy safe artifact cannot distinguish
  authentication, rate limiting, request rejection, timeout/network, or 5xx because the repair
  projection collapsed those typed errors; no exact root cause is inferred from it.
- Official Chat Completions documentation reserves `response_format` for text models. The repair
  adapter's corrected visual request removed `response_format`, sent `thinking=disabled` and
  `do_sample=false`, then enforces the requested JSON object with bounded extraction and strict local
  Pydantic validation.
- The then-authorized corrected `glm-4.6v-flash` canary used a new artifact path, reported
  `local_schema_valid` and `provider_json_mode_requested=false`, and preserved only a closed
  body-free provider error category.
  The legacy failure had consumed 1 request; the user explicitly raised the lifecycle cap to 42,
  leaving one corrected canary plus, only on success, the remaining 40 assets.
- Execution evidence: the corrected canary used exactly 1 additional request and failed closed as
  `provider_rate_limited`. Its schema/fingerprint, privacy-key scan and `0700` directory/`0600` file
  permissions passed. At that time cumulative calls were 2 of 42; the remaining 40 batch calls were
  not made, no plan was created, and no database apply/restore command ran. The later user approval
  raises only the current lifetime cap to 43 and does not rewrite this historical execution fact.

## Provider batch fail-closed hardening

- Root category is cross-layer contract plus implicit assumption: canary success proves one request,
  not continued quota/availability, and diagnostic-plan validity is weaker than mutation readiness.
- Batch recognition now uses fingerprinted inter-request pacing: 2 seconds by default, configurable
  only from 0.5 through 60 seconds. The adapter remains one attempt per image with no hidden retry
  multiplication.
- The first rate-limit, timeout or unavailable item trips the batch circuit breaker. Completed
  suggestions remain in canonical order; every remaining asset is materialized as
  `not_processed/not_called_after_transient_failure` without provider calls or invented suggestions.
- Apply now requires zero failures and completed recognition for every item before the first
  repository CAS. A strict diagnostic checkpoint remains readable/valid but cannot create a result
  or partially mutate the successful prefix.
- Provider-free evidence: repair unit tests cover all three transient categories, pacing/default
  bounds, CLI validation and private artifact round-trip; PostgreSQL/MinIO integration proves a
  partial plan leaves the real metadata row unchanged.
- Final hardening gate: `backend/tests/unit/test_ip_asset_metadata_repair.py` passed 22/22 and
  `backend/tests/integration/test_ip_asset_metadata_repair.py` passed 1/1. Focused Ruff, Ruff format,
  mypy, CLI `plan --help`, and diff checks passed. This hardening round made zero provider calls and
  ran no real apply; usage remained 2 calls. The later model-migration approval raises the current
  cap to 43 as recorded below.

## GLM-5V-Turbo contract migration (2026-09-03)

- The user explicitly approved replacing the lower-tier Flash repair model with exact
  `glm-5v-turbo` and raised the lifetime cap from 42 to 43. The two historical failed calls remain
  counted, leaving exactly 41 calls for one new canary and, only if it passes, the remaining 40.
- Canary schema is now `ip-asset-metadata-repair-canary-v2`, plan schema is
  `ip-asset-metadata-repair-plan-v2`, result schema is `ip-asset-metadata-repair-result-v2`, and all
  fingerprint domains are v2. Every artifact requires the exact `glm-5v-turbo` identity, so old
  `glm-4.6v-flash` v1 artifacts fail strict parsing before provider/database setup and cannot be
  reused, planned, applied, or restored through the current CLI.
- The local acknowledgement is `I_ACKNOWLEDGE_LOCAL_IP_METADATA_REPAIR_V2`. The CLI continues to
  force the exact repair model and concurrency one through the generic recognition factory; the
  shared upload-assistant default is unchanged.
- The visual request remains one `image_url`, `thinking=disabled`, `do_sample=false`, no
  `response_format`, and strict unique-object JSON/Pydantic validation. Higher platform/model
  capacity does not authorize local bursting: concurrency one and two-second pacing remain fixed.
- This migration turn is provider-free and mutation-free. No canary, plan, apply, or restore was
  executed; the live call ledger therefore remains 2 used of 43 authorized before a later explicit
  execution turn.
- Provider-free migration gate: recognition plus repair unit tests passed 32/32 and the focused
  PostgreSQL/MinIO integration passed 1/1. Focused Ruff, Ruff format, mypy, CLI help, Make dry-run,
  task-context JSONL validation, and diff checks passed.

## GLM-5V-Turbo live execution evidence (2026-09-03)

- Provider-free preflight selected and verified exactly 41 approved originals. The fresh v2 canary
  used exactly one request, returned exact model identity `glm-5v-turbo`, and passed unique-object
  extraction, strict local Pydantic validation, approved-set/fingerprint validation, privacy scan,
  Git-ignore, and `0700` directory/`0600` artifact checks.
- The passing canary item was reused. The remaining 40 assets ran serially with two-second pacing,
  no fallback and no automatic retry. The completed plan records 41 calls, 41 completed suggestions,
  zero failed/not-called items and no transient circuit-break activation. This live phase therefore
  used exactly 41 new calls and brought the immutable task ledger to 43 of 43 authorized calls.
- Aggregate-only proposal review found the role distribution unchanged at `duo=8`,
  `sai_xiansheng=18`, `xiao_sai=15`. Proposed asset types are `full_body_action=30`,
  `scene_illustration=4`, `transparent_cutout=3`, `identity_reference=2`, `meme_sticker=1`, and
  `portrait_avatar=1`. All controlled values, text lengths, tag bounds and privacy constraints passed.
- Before apply, all 41 rows matched their content commitments and before-metadata fingerprints. The
  first provider-free apply changed all 41 with zero drift/failure/skip; the same plan applied again
  changed zero and returned 41 `already_applied` outcomes. Current metadata matches all 41 proposal
  fingerprints, while the selected non-metadata digest and counts for ten related non-metadata tables
  remain unchanged.
- Both result artifacts pass strict result-fingerprint, privacy, permission and Git-ignore checks.
  The first apply result is restore-ready against the current state. Verification did not fail, so
  restore was intentionally not executed. No deployment, push, commit, image regeneration,
  embedding rebuild, or 248-call retrieval evaluation occurred in this phase.

## Risky files and rollback points

- `backend/app/application/services/ip_assets.py`: inferred hints must never cross into repository
  filters; explicit request fields must remain hard and prior turns semantic-only.
- `backend/app/infrastructure/db/ip_assets.py`: never snapshot `IpAssetRecord.tags` as free tags;
  read dimensions in the transaction and preserve every non-repairable relation/table.
- `backend/app/domain/ip_assets.py` / API schema: reason enum is additive and generated artifacts
  must be regenerated rather than hand-edited.
- `frontend/src/features/ip-assets/IpAssetHub.tsx`: never render internal reason codes or replace the
  existing gallery on a search failure.
- `.env.example` and broad migration/model files are dirty from other tasks; avoid them unless an
  unavoidable generated contract change is explicitly isolated.
- Stop before live apply if the canary, exact-41 mapping, plan identity/privacy, proposed taxonomy
  distribution, or rollback manifest contract fails.

## Execution gate and final ledger

- At execution start, the user had initially authorized 41 Zhipu recognition calls, later raised the
  cumulative maximum to 42 after the legacy failure, and then explicitly raised it to 43 after the
  corrected Flash failure.
  The GLM-5V-Turbo live phase consumed those exact 41 remaining calls and completed successfully;
  the final cumulative ledger is 43 of 43. Apply, validation and idempotency replay were provider-free.
- Final plan selects `glm-5v-turbo`, no database migration, no batch web UI, no deployment/push,
  and no 248-call retrieval rerun.
- The task is already active and its authorized live phase is complete. The 43/43 provider-call
  ledger is exhausted; no further canary or plan execution is authorized by this task.
