# Independent recovery review — 2026-09-16

Reviewed only the `release-hardening` worktree. No commit, production write,
deployment, compensation, paid model request or WeChat request was performed.
The user subsequently prioritized getting today's article into drafts first;
the main session explicitly paused commit/deployment/compensation. This report
does not authorize resuming those actions or claim a live draft acknowledgement.

## Reviewed scope

- Nine runtime modules in `release-common.py::ALLOWED_FILES`, including the
  adapter → strict/observe executor → image attempt → run attempt/log chain,
  persisted non-applied proof and fenced/bounded slot reclaim.
- `official_account_visual_compensation.py`: exact CLI targets, closed authority,
  accepted article/render bindings, original unknown attempt preservation,
  existing protected journal lock/absence checks, one-shot consumption, a new
  stable physical provider key and unchanged logical source identity, fixed
  same-Shanghai-date recovery cutoff, and idempotent repeated authorization.
- All six `release-*.py` scripts and hash-bound archived builder/validator/deployer:
  committed-object source overlay, nine-module allowlist, exact base/schema,
  protected configuration and complete OA history hashes, old copy-job cohort,
  WeCom safety margin, network-disabled candidate smoke before quiescence,
  unchanged dependencies, and post-quiescence rollback.
- Related focused tests and current recovery specification/operator documents.
  Any separately developed `manual-draft-now` operator is **not** covered here.

## Findings fixed

### Accepted POST followed by a failed GET lost uncertainty

`backend/app/infrastructure/ai/official_account_visual_strict.py` previously
classified some polling/download HTTP4xx responses as terminal authentication,
rejection or invalid-URL failures. A rejected GET cannot establish the outcome of
the earlier accepted, paid POST. This did not cause an automatic repeated POST,
but it misreported the durable result and violated the recovery contract.

The adapter now keeps these later retrieval failures `unknown`, including
invalid polling envelopes. A successful HTTP200 fetch containing invalid raster
bytes still correctly remains a terminal output-integrity error. Safe error
codes/status/kind survive; no raw body or exception is added. Eleven regression
cases cover poll400/401/403/429/500/invalid200 and download400/403/429/500/invalid
pixels200. All require exactly one POST followed by one GET and no retry.

The domain spec now explicitly documents this operation-stage distinction.

## Verification commands

```sh
PYTHONPATH=backend pytest -o addopts='' -q --no-cov --tb=short backend/tests/unit/test_official_account_image_failure.py backend/tests/unit/test_official_account_visual_compensation.py backend/tests/unit/test_official_account_strict_visual_policy.py backend/tests/unit/test_official_account_strict_visual_worker.py backend/tests/unit/test_official_account_native_observe.py backend/tests/unit/test_official_account_worker.py backend/tests/integration/test_official_account_image_failure.py backend/tests/integration/test_official_account_visual_compensation.py backend/tests/integration/test_official_account_strict_visual.py

pytest -q .trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-recovery-20260916/release-test.py .trellis/tasks/archive/2026-09/09-15-deploy-wechat-no-source-link-rule/research/test_no_source_link_release.py -k 'not test_overlay_layer_is_exactly_the_five_reviewed_files'

PYTHONPATH=backend mypy --config-file backend/pyproject.toml backend/app/core/errors.py backend/app/application/ports/official_account_local.py backend/app/application/ports/official_account_strict_visual.py backend/app/application/services/official_account_local.py backend/app/application/services/official_account_strict_visual.py backend/app/infrastructure/ai/official_account_visual_strict.py backend/app/infrastructure/db/official_account_local.py backend/app/infrastructure/db/official_account_strict_visual.py backend/app/infrastructure/db/official_account_visual_compensation.py

git diff --check
```

Ruff `check` and `format --check` cover those nine runtime modules, the seven
changed/new backend test modules, and the six release scripts: **22 files pass**.
Strict mypy passes for **9 runtime modules**. `git diff --check` passes.
Release suite: **75 passed, 1 deselected** in 9.60s. The archived path-dependent
test is executed through the explicit relocation wrapper, without modifying its
archived source. The real checksum-bound base OCI archive was present; its
offline graph/config/history validation ran, not skipped.
The focused image-failure suite after the fix has **59 passing cases**.
The combined product/database run: **222 passed** in 149.76s. PostgreSQL fixtures
create isolated databases, migrate them to the repository head, and remove them
afterward; all generation/WeChat interfaces in this run are fake/offline.

## Evidence and deployment limitations

Synthetic isolated PostgreSQL tests prove authorization/claim/history behavior;
unit Worker tests prove accepted text/render/ready-image reuse and physical-key
forwarding into the successful local draft path. The real single-edition producer
test observes the rearmed original run without creating another article. This is
compositional evidence, not one complete PostgreSQL compensation → prepared → real
WeChat ACK end-to-end run. No live success is claimed and no complete backend
suite was run.

The current code-only release operator intentionally requires the original
unknown edition with no delivery artifacts. If the prioritized manual route
writes a draft first, that frozen precondition will no longer hold. Do not edit
snapshots to conceal the new receipt or replay the compensation. A follow-up
release must explicitly preserve/review the newly delivered state before any
deployment clearance. The September16-only compensation is not valid on a later
Shanghai business date.

## Bug analysis: operation-stage diagnostic loss

1. **Root category — cross-layer contract / implicit assumption:** a generic
   exception class describes the failed HTTP operation, not necessarily the
   earlier paid request's outcome.
2. **Why the initial implementation missed it:** POST error matrix and polling
   connection failure were covered; polling/download deterministic-looking 4xx
   needed separate stage-aware coverage. No repeated trial-and-error fixes.
3. **Prevention — complete:** retain transport operation in classification,
   regress both GET error paths and successful-but-invalid pixels, and document
   the distinction in the image-recovery domain spec.
4. **Expansion:** poll/download failures must never authorize replay of a prior
   POST; output validation after a successful fetch must not lose its terminal
   diagnostic. Existing ordinary non-OA retry behavior remains unchanged.
5. **Knowledge capture — complete locally:** domain spec and this review record
   updated. No generated spec-template copy exists for this application domain;
   no template synchronization is applicable. Commit is intentionally deferred
   under the latest user priority and parent instruction.

## V3 resilient/advisory verification

The prospective policy is `official-account-visual-pipeline-v3-resilient-advisory`.
It owns three durable physical attempts per body slot with separate provider keys,
keeps the transport at one POST per claim, reuses completed slots, and stops without
a fourth request. Provider rejection, invalid output and current-owner ambiguity may
advance; credentials/config/input/result-identity failures, expiry and lease loss do
not. The six vision audits remain durable. Ordinary rejection/unavailability,
composition/relevance findings and duplicate/catalog/reference reuse are advisory;
raster, geometry/count, byte/subject/lineage and audit identity remain blocking.

Independent review fixed three cross-layer gaps before release: a successor could
retry an orphan after lease loss, a stale physical attempt could write into the
current slot, and downstream media/draft/database gates could still reject the V3
duplicate bytes that generation had made advisory. Alembic `20260916_0048` removes
the policy-blind checksum index; V1/V2 keep repository-level duplicate refusal and
downgrade is fenced once V3 data exists.

The combined offline product/database command covering image diagnostics,
compensation, V3 retry/review/prepared consumers and historical strict behavior
passes **245 tests in 146.58 seconds**. The 15 compensation cases also pass alone;
their clock fixture now pins queue availability explicitly instead of depending on
the PostgreSQL wall clock. Ruff check, Ruff format, strict mypy for the changed V3
runtime modules, and `git diff --check` pass. No paid provider, WeChat, publication,
production mutation or September 16 replay occurred during these checks.
