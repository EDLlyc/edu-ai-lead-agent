# Independent visual-preview quality review — 2026-09-07

## Bounded live verdict

**SAFE-TO-RUN** for one isolated preview from the captured input manifest
`1bae3a88bd68e733e082627a173fef18cf2e783533d505229435bcb7eedecf19`, source run
`1c8a0cc8-b960-4b33-82ff-e7204def40f6`. This permits at most five Comfly
`gpt-image-2` generation POSTs and six direct-Zhipu `glm-5v-turbo` audits in one new private
directory. It is not a production activation, draft replacement, image-quality acceptance,
or human approval. No provider, SSH, production database, or social call was made by this reviewer.

Candidate: `.trellis/worktrees/visual-quality-preview`, based on `218015e`, whose runtime matches
deployed `6154c78`. Main retains operations and spec ownership. The full backend gate is not claimed
green; baseline failures are recorded below.

## Findings fixed

- `backend/app/infrastructure/ai/image_validation.py`: strict audit content parsing alone did not
  reject duplicate keys in the outer completion. A repeated model/choices/content key could hide
  an earlier conflicting identity or rejection. Parse the entire completion with duplicate-key
  and nonfinite-number rejection, preserving one attempt and bounded error output. Five new
  regressions cover duplicate model, choices, nested content, NaN and Infinity.
- `backend/app/application/services/official_account_visual_preview.py`: replay did not bind or
  preserve the root execution intent and ignored unlisted paid-evidence members. The manifest now
  hashes the root intent; zero-call rerender preserves it. Replay/finalization reject extra or
  nested call/transport/raw members and conflicting hash-map keys. Three negative tests exercise
  changed root intent and hidden/unlisted evidence before output creation.
- `backend/app/official_account_visual_preview_main.py`: full-tree mypy rejected the `_env_file`
  constructor argument. A local typed Settings subclass explicitly disables dotenv loading while
  preserving inherited validation and environment configuration. The composition regression
  proves an invalid ambient `.env` is ignored.
- Runner owner applied the preliminary review feedback: existing/forbidden/symlinked output paths
  are checked before constructing Settings or inspecting credentials. A sentinel regression proves
  the existing-directory path makes zero Settings calls.

## Behavior and evidence reviewed

- Complete input member/schema/hash/image validation and the five source block anchors run before
  credentials; the actual captured input passes the public CLI preflight with zero calls.
- Article/source bytes remain unchanged; the acquired context image retains exact bytes,
  1004×620 geometry, section, source/credit/rights, and original source-image identity.
- Only approved reference candidates with both dimensions at least 512 are selected. Selection
  truthfully says deterministic tags with zero embedding calls.
- The request carries native 1536×1024 explicitly, with unchanged historical 1024×1024 default.
  Every adapter result route checks actual decoded geometry without resizing. The preview request
  fingerprint includes native geometry and preserves the base production-plan fingerprint.
- Application and physical transport intents are exclusively created and fsynced before dispatch.
  POST retries are independently prevented by the adapter and transport; downloads and task polls
  are separately journaled and bounded. Cancellation/unknown outcomes cannot reopen the directory.
- A new end-to-end offline composition test uses the real adapters behind MockTransport. It proves
  exactly five generation requests and six audit requests, exact models/routes, disabled thinking
  and sampling, no response-format/temperature fields for vision, normalized reference PNGs, and
  audits of final body JPEGs plus the final cropped cover. Caller Settings remain unchanged.
- Warning, rejected, unavailable, malformed, or identity-mismatched audits cannot pass the preview
  gate. Deterministic resolution/catalog-reuse/exact/perceptual-repeat checks remain separate from
  single-image semantic judgment. No numeric scores, human labels, or durable database rows are
  invented. Production observe remains nonblocking and defaults off.
- Rerender and finalization have zero provider capability; they verify preserved file hashes and
  paid evidence. Final acceptance binds exact 320/430 observations, seven loaded assets, no overflow,
  no external requests and matching article DOM. It still reports human approval and publication
  false. Repeated finalization refuses to overwrite acceptance.
- Read-only capture script uses PostgreSQL `default_transaction_read_only=on`, pins run/package/
  context identities, and constructs no generation or delivery capability.
- Main's `check-visual-preview-mobile.cjs` serves only captured hash-verified HTML/media from a
  loopback resource map, blocks external browser traffic and JavaScript/service workers, verifies
  the exact seven image paths and copy-root DOM, and writes separate fresh screenshots/report.
- Main's new `.trellis/spec/backend/official-account-visual-preview.md` matches these executable
  contracts, including typed native size, immutable paid evidence, final-byte judging, zero-call
  replay, and separate human acceptance/production activation. Root and candidate copies agree.

## Verification

- Combined focused adapter/geometry/runner tests: **166 passed** before the final typed Settings
  adjustment. After that adjustment: **28 runner tests passed**, plus focused Ruff and strict mypy
  of the preview service/CLI and audit adapter passed.
- Full Ruff lint: passed.
- Full format gate: failed on two files unchanged from `218015e`:
  `backend/app/domain/topic_selection.py` and
  `backend/tests/integration/test_title_relevance_ingestion.py`. Unrelated bytes were preserved.
- Final full-tree mypy: **two baseline errors only**, both incompatible string/Literal arguments
  in unchanged `backend/app/local_exact_target_selection.py:158–159`. The new CLI error was fixed.
- Final `make -k backend-check` after the last runtime edit: **2,039 tests passed, 33 failed,
  zero setup errors, 79% coverage**. All 28 new preview service/CLI tests pass. Full-suite failures
  are therefore reported explicitly; this is not a green general release gate.
- All **31 unit failures** independently reproduce on detached exact base `218015e`: 25 unavailable
  ignored/private visual-fixture cases, plus six existing content-slot priority, topic rerank,
  topic-selection default, and IP-evaluation behavior failures.
- The complete base integration suite produces **118 passed, the same two failures**:
  `test_fixture_dag_matches_one_shot_bytes_and_records_zero_social_calls` (fixture DAG cannot
  complete) and `test_v4_rerank_applied_and_finalization_fallback_are_atomic` (suite-order-dependent
  candidate cardinality). The latter passes alone on base but fails in full integration order;
  this was explicitly reproduced rather than dismissed as unrelated by assumption.
- Existing local services had no usable published PostgreSQL/MinIO ports. The initial default-port
  attempt had 120 connection setup errors; these were resolved for the final run with separate
  task-labelled temporary containers from already-present pgvector `0.8.1-pg16` and MinIO
  `RELEASE.2025-04-22T22-12-26Z` images, test-only credentials, tmpfs data and loopback-only ports
  44620/44622. No existing service was started, stopped or reconfigured. Both task-created
  containers and their temporary test data were removed after verification; the temporary base
  checkout was removed. A final label-scoped inventory confirms no task test container remains.
- Machine results are retained locally under `/tmp/edu-ai-visual-preview-check-KNWk9Y/`:
  `final-backend.xml`, `baseline-failures.xml`, `baseline-integration-failures.xml` and
  `baseline-integration.xml`. They are diagnostic files, not provider/live acceptance evidence.
- All 11 changed Python files pass scoped Ruff formatting; full Ruff lint passes. The unrelated
  baseline format/type/runtime defects remain outside this approved preview change.
- `git diff --check`: passed for the product worktree.

## Reviewed runtime SHA-256 identities

| Runtime path | SHA-256 |
|---|---|
| `backend/app/application/ports/image_generation.py` | `5592362086571d13dea0e17adfb0416d483656ab5514aec7e9dddb1561eef4b0` |
| `backend/app/application/services/official_account_visual_preview.py` | `fa925c1a8811b5b92aa2a13e4d35db61fb4d1e82467a6c091ae875be1f41e28c` |
| `backend/app/core/config.py` | `e9fa10e1f89bb71c4613ad67b7958464c4d375c5051ff3a1b21d7630c074fa23` |
| `backend/app/infrastructure/ai/factory.py` | `7f41690fef66197e1bcfbf3d91eb0f454b2582a636b0a7770f4904f47f0ccb11` |
| `backend/app/infrastructure/ai/image_generation.py` | `2df7c7c09343e99120d412a26848244c5507de23d558306997a6b06ed84378d7` |
| `backend/app/infrastructure/ai/image_validation.py` | `c78012d61f68fcaab1b8164f80d502a049adb4744f1254f494ed4cb30211736e` |
| `backend/app/official_account_visual_preview_main.py` | `d0e01ef4f827c942b474924e79e5dbac668b3e4991839d520d28ea3a200287e1` |
