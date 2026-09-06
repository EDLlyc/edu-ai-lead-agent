# Independent no-send canary safety review

## Decision

The task-local diagnostic is suitable for a default zero-call preflight and, only after that
preflight succeeds plus the independent operator identity gates, one bounded live no-send
invocation. This is not permission to replay a terminal job, generate a material package, send a
message, repeat a paid diagnostic automatically, or claim production recovery.

Reviewed against clean deployed commit `5c560da71bcbb61b765d3fe82c742cf2d5e676e1`, not the dirty
workspace application. The full 1,336-line quality guideline was read in bounded chunks because
the native context injection was truncated. PRD, design, execution plan and relevant complete
brand/slot/delivery/database guidance were read. All existing unrelated changes were preserved.

## Verified invariants

- The diagnostic loads the exact requested copy run and typed slot selection, validates the
  selected business date/slot/ordinal, original `review_required/copy_provider_unavailable` state,
  absence of active draft/repair, event-version lineage, succeeded selection run and immutable
  copy-version bundle. It does not construct a lease or use the mutating job loader/executor.
- Deployed `load_locked_topic_origin` and `load_governed_event_evidence` perform SELECTs only.
  Evidence remains limited to 24 validated bindings from accepted analyses and Tier A/B
  occurrences belonging to the selected event at its immutable version cutoff. Brand data remains
  separately typed and filtered by active-ready document, parent audience, validity and the
  exact Zhipu provider/model/dimension identity.
- All database sessions, including the production brand repository's separately opened session,
  use the one diagnostic engine. Startup defaults and every transaction are read-only; SQL
  filtering, NullPool, hidden SQL parameters and bounded statement/lock/idle timeouts add defense
  in depth. The prefix filter is not advertised as a general arbitrary-SQL sandbox; only the
  checksum-bound deployed read paths are executed.
- One shared physical transport charges before forwarding a request. It allows only the current
  configured Zhipu endpoint and model with the stage-specific embeddings/chat path. A timeout,
  HTTP 429/5xx or schema failure cannot cause a second physical request in a stage. The maximum
  is one embedding plus one generation plus one audit; default preflight permits none. Redirects,
  implicit proxy mounts and inner TCP retries are disabled. First safe HTTP status/error class
  remains observable even when the attempted embedding retry is rejected by the budget guard.
- Factory, query construction, prompt, schema, output budget and deterministic-policy reuse match
  the deployed content worker. Its pre-validation transformation is precisely the source-footer
  append; no omitted normalization/binding phase was found. Deterministic errors prevent audit;
  the configured audit policy and repair-code policy determine only the ephemeral first-draft
  result. Neither repairs nor any durable draft/audit persistence run.
- No package/image/MinIO/WeCom/checkpoint executor is constructed. The new Python process does
  not mutate the existing worker's in-memory state. Standard/structured logging is suppressed;
  report values are fixed labels, UUIDs, digests, counts, safe enums and HTTP status numbers.
  Arbitrary issue codes collapse to `other_issue`; issue messages/fields/claim IDs, raw provider
  bodies, prompts, brand/evidence content, vectors, URLs and credentials do not enter output.
- The 253-file application source fingerprint is a genuine code-source check, not a CLI revision
  self-comparison. Main must separately verify the container/image/OCI revision, complete release
  markers, protected environment identity, Alembic head and frozen seven-job cohort before and
  after execution. The script cannot establish those external identities by itself.

## Findings fixed

- Added `test_production_recovery_canary_postgres.py`: unit mocks alone had not executed the real
  PostgreSQL transaction restrictions or actual brand repository SQL. Eight checks now prove
  fresh sessions and post-commit transactions stay read-only, DML/READ WRITE commands are blocked,
  SELECT `nextval` and `FOR UPDATE` fail at the server with SQLSTATE `25006`, fixture data/sequence
  remain unchanged, and production FTS/vector retrieval opens a read-only session.
- Clarified operator outcome interpretation: no-proxy transport, the whole-exercise deadline,
  zero schema correction and omitted repair are conservative diagnostic differences, not evidence
  that the ordinary worker necessarily fails under its own configured policy.
- No runtime/application fix was needed from this safety audit. No production state, SSH,
  provider request, send or release operation was performed by this reviewer.

## Verification

- Provider-free canary suite: 66 passed using the exact deployed application imports.
- Real PostgreSQL suite: 8 passed. Executed only on the main-owned isolated Docker network
  `edu-ai-recovery-check-20260905`, with provider/worker flags disabled and fixed test credentials.
  The disposable base database was upgraded using the exact deployed Alembic graph to
  `20260901_0042`; test-owned scratch tables/sequences were removed by their fixtures. Main owns
  eventual container/network cleanup. Neither production nor the ordinary local Compose database
  was touched.
- Ruff lint/format and strict mypy cover the diagnostic plus reviewer-added typed PostgreSQL
  tests; Ruff also covers the existing unit tests. Tests use local mocked HTTP and contain only
  synthetic inputs. No fixture metric is a live-model or production-delivery result.

## Required interpretation and remaining acceptance

The report's zero write/package/send fields are architectural declarations, not independent
measurements of concurrent services. Reconcile actual durable counters and the protected cohort
outside the script. `first_draft_passed` proves neither durable accepted copy nor image/package
validation nor a message. An expired historical selection remains expired; only a fresh eligible
slot reaching formal terminal `delivered`, followed by a duplicate check, satisfies recovery.

Qwen activation/index migration and unrelated source failures remain outside this canary review.
