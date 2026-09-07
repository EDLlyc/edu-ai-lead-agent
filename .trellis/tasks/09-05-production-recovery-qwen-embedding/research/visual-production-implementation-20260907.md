# Prospective strict visual integration: implementation evidence

## Scope and truth boundary

The user's latest approval authorizes R15–R17 implementation for new legitimate tasks only.
Existing three articles and drafts remain protected. No public publishing, old-edition replay,
Qwen migration, alternative model, or additional paid preview call is included.

Implementation is in `.trellis/worktrees/visual-quality-preview`, on the isolated release branch
from `218015e`. Dirty main is not a release input. The accepted preview remains immutable.
Implementation and independent change-relative checking are complete. This is not deployment,
an all-green general release gate, or production acceptance.

## Implementation coordination

Three native implementers own disjoint policy/planner/runtime, durable generation/audit/storage,
and weekly/prepared/consumer modules. Their shared interfaces are the frozen strict policy,
pure upload normalization, and a typed six-subject durable audit/media evidence projection.
Additional snapshot-discriminator and escaped-URL budget decisions are captured in `design.md`.
Main owns task/spec records, isolated test infrastructure, final artifact checks, and release gates.

## Local integration infrastructure

Main created dedicated containers with the task label `edu-ai.task=strict-visual-20260907`:

- `edu-ai-strict-visual-pg-20260907`: existing pgvector/PostgreSQL 16 image, temporary filesystem,
  loopback-only port 44640; `pg_isready` passed.
- `edu-ai-strict-visual-minio-20260907`: existing MinIO image, temporary filesystem,
  loopback-only port 44642; health endpoint passed.

Credentials are local test-only. The repository integration fixture creates a unique database
and bucket per test session. These containers do not mount application data or production files.
At `2026-09-07T05:10:06Z`, after the combined gate, main rechecked both exact container names,
task labels, empty mount lists and tmpfs-only data locations, then removed only these two
containers. Their temporary test databases/buckets were discarded; they are reproducible from
the checked tests, not backed-up user data. No existing project or production container was
changed. Candidate `frontend/node_modules` is absent after the reviewer's exact symlink cleanup;
root dependency packages remain in place.

## Read-only production checkpoint

At `2026-09-07T04:30:46Z` (12:30:46 Asia/Shanghai), all 14 production Compose containers were up.
API, PostgreSQL and MinIO reported healthy; the other daemons do not expose equivalent healthchecks.
A subsequent explicit read-only database transaction confirmed:

- Schema remains `20260901_0042`.
- Exactly three Article runs, all `ready`; all three protected run IDs are unchanged.
- One weekly DAG run remains `terminal_failed`, preserving the original incident record.
- One draft job remains `ready`, exact protected ID `a13a7121-3f3e-57b0-a091-2d55741d55fb`.
- The generated Article visual table contains zero rows: strict production activation has not
  happened. Historical upstream material-package cover generation is a separate table/workflow.

The first diagnostic query used `state` instead of `status` and PostgreSQL rejected it; the
connection closed without mutations. The corrected transaction used actual `status` fields.
No worker stop/start, provider call, enqueue, environment change, migration or deployment occurred.

## Final independent quality checkpoint

See `visual-production-check-20260907.md` for exact commands, findings and baseline reproduction.
The reviewer grants `IMPLEMENTATION_CHECK_PASS` change-relative, explicitly not `SAFE_TO_DEPLOY`.

- All 81 strict policy/worker/prepared/PostgreSQL tests pass, including 16 real PostgreSQL tests
  and a normal material enqueue → real executor/storage → prepared consumer integration.
- Full backend: 2,124 passed, 34 failed, zero setup errors, 80% coverage. Exactly 33 failures
  reproduce on the baseline; the remaining failure is an independently baseline-reproduced
  default-credential test interaction with local integration environment overrides.
- Full integration: 134 passed / 2 known baseline failures. Focused cross-layer: 375 passed /
  6 known missing-private-PNG failures. These are overlapping selections, not additive totals.
- All 52 changed Python files pass Ruff/format; all 31 runtime modules pass strict mypy.
  Full-repository format/type exceptions remain the unchanged baseline ones.
- Frontend API contracts, format, lint, types and production build pass; 243 component tests pass.
  The full frontend command retains one independently reproduced Playwright collection issue.
- Release mock tests: 67 passed / 1 independently reproduced baseline inbox assertion.
- Reviewed runtime-set SHA-256:
  `6ad46cc5924318ba56a33240184b780b970196b6386b8030bbaeea48d2cc1441`.

No product code was edited by main after this reviewed digest. Final record/spec synchronization
does not change the verified runtime. Candidate jsonl context omits unavailable historical
`substantive-topic-scope.md` and `production-baseline.md` references; root retains its valid
broader-task references. This prevents importing unrelated branch work just to satisfy context
validation. The current exact visual production checkpoint is recorded above.

## Gates still open

Exact commit-batch confirmation; fresh immutable release/backup/window/rollback review, including
explicit treatment of baseline gate exceptions and three-Article timing; and observation of a
future legitimate run. No commit, push, production activation or extra paid model call has
occurred. Do not report those remaining outcomes as complete before evidence exists.

## Main's independent layout-only check

Ran the actual current `compact_strict_xiaosai_html` against the hash-verified accepted preview
entirely in memory. No preview file was modified and no production artifact identity was fabricated.
The resulting body has 18,495 Unicode characters and SHA-256
`fbe64fd6a9b58c037b09bc6a6423b10a11f2c0c81a5ea754d8f9c8242b121fc5`.

The installed gzh-design validator, fed the actual compact fragment via `--stdin`, reports
134 `span leaf` wrappers, zero errors and zero warnings. Chromium comparison at both 320 and
430 pixels confirms identical text, computed styles and geometry for all 292 descendants,
and byte-identical full-page screenshots versus the original accepted preview. Each version
loads seven images with zero horizontal overflow and zero external requests. Browser JavaScript
and service workers were disabled, and only hash-verified resources were served on loopback.

This establishes lossless layout compaction on the accepted sample. It does **not** yet validate
the assembled new prepared-child format, durable audit lineage, different future articles, actual
WeChat upload responses, or deployment. Provider calls and production writes in this check: zero.

## Main's assembled strict projection diagnostic

After the new strict snapshot guard landed, exercised `build_strict_prepared_projection` and
`validate_strict_prepared_projection` in memory using the entire accepted Article and its exact
generated body/news image bytes. Only the reference-policy marker and dependent Article fingerprint
were changed in an explicitly synthetic in-memory fixture; original sections, title and news
context were asserted equal. Audit IDs/results were synthetic test inputs, not claimed new model
judgments. Neither these synthetic proofs nor a prepared directory were persisted or enqueued.

The complete current projection passed its roundtrip guard and actual installed gzh validator:

- Body 18,441 characters; SHA-256
  `81c01b058809a27cf9129f842989f9139d999de4621a70539a3a0e4fb8b3c1fa`.
- Six inline images with full escaped-URL reserve: 19,866 characters, below 19,999.
- 134 span-leaf wrappers; zero gzh errors and warnings.
- Actual Chromium at 320/430: six loaded inline images, no failures, no overflow, no external
  requests and exact copy-root DOM. Unlike the earlier preview wrapper, this body-only probe does
  not display the independently uploaded thumbnail as an extra header image.
- News original remains byte-identical. The new final thumbnail is 1175×500, 63,621 bytes, SHA
  `1298d39e84ca20bdf15b7187cea72ad90d08eefbc954b8a33855a8c217349a46`.

The 54-character difference from the compact preview body is consistent with the prepared
exporter's deliberate use of immutable Article-block captions; the isolated preview uses generated
scene captions. Main initially suspected a caption-binding failure, then traced the actual
`_build_strict_child` projection and withdrew that finding. The owner added a regression with
different persisted generated captions, proving Article-visible captions remain unchanged.

This is offline projection and mobile evidence, not a real strict thumbnail audit or production
readiness receipt. No model, database, WeChat or other external call was made. The previously
accepted preview files and their historical six audit results remain untouched.

## Timing evidence, not an SLA

A fresh allowlisted read of the running Article worker shows concurrency 1, lease 300 seconds,
heartbeat 60 seconds, weekly Article wait 720 seconds, general image window/timeout 300 seconds,
and text-provider total timeout 150 seconds with configured maximum attempts 3. Settings and
credentials were not changed; only these numeric fields were printed.

Reading existing accepted-preview call ledgers (no new calls) yields generation durations of
35.800, 66.998, 60.429, 41.843 and 37.051 seconds: 242.121 seconds total. Its six audit durations
are 5.724, 8.316, 13.948, 5.703, 8.250 and 4.187 seconds: 46.128 seconds total. Their sum is
288.249 seconds, approximately 4.8 minutes for one Article's visual calls.

One sample is not a latency distribution, future guarantee or stress test. Sequential worst-case
provider windows can exceed weekly waiting/attempt budgets even though this observed sample
does not. Slow-path acceptance requires explicit failed/unknown outcomes and reuse of the same
durable Article identity, not automatic second generations. Do not increase concurrency,
timeouts or weekly versions just to turn an unobserved end-to-end result into a success claim.
