# Recovery no-send canary

## Scope and reuse audit

`production-recovery-canary.py` is task-local diagnostic code, not a runtime patch or a
replacement content worker. Existing `governance_live_smoke.py`, image live smoke and IP metadata
repair canaries do not exercise this copy chain and have different write/provider scopes.
`CopyGenerationExecutor` requires a durable claimed job, can repair, and persists draft/audit
state; it must not be used for this no-send check.

The diagnostic uses the deployed public `load_locked_topic_origin` and
`load_governed_event_evidence` helpers without inventing a lease or claiming a job. It reuses
the production `BrandRagContextRetriever`, brand factory/client selector, copy model factory,
generator/auditor prompts, source-footer binding, deterministic validation, audit policy and
repair-code policy. The original copy run is not changed. Only an explicitly selected
`review_required / copy_provider_unavailable` slot run with no active draft or prior repair is
eligible. Its stored full copy bundle must equal the current consumer bundle.

## Mandatory operator gate

Main owns operational execution; this implementer did not SSH, call providers, change production
or send. Before any execution, independently verify the full content-worker container ID, image
digest and OCI revision, release markers, protected environment identity, database Alembic head,
and protected seven-job cohort. Do not infer a container's identity from the supplied CLI release.
The diagnostic additionally hashes all 253 loaded `app/**/*.py` files and requires the exact
source digest `70105e3d9fcbc4db75a879d1e44af357f3d182b2cbdbcebbddcae6bbbe51ec86` from
deployed commit `5c560da71bcbb61b765d3fe82c742cf2d5e676e1`. This is a code-source gate, not an
image-label, dependency-lock or live-service health check. A different release fails closed.

Use the existing content-worker consumer environment, not API/dispatcher or local workspace
settings. Do not pass any credential, alternate endpoint/account or model. Python must use `-B`
to avoid generating bytecode. Prefer streaming this reviewed script through `docker exec -i`
stdin into the already-verified content-worker container rather than writing a production file.

Exact inner command (script bytes on stdin):

```bash
python -B - \
  --expected-release 5c560da71bcbb61b765d3fe82c742cf2d5e676e1 \
  --copy-run-id 1929a4fa-43f3-4636-816a-7cde3175e24c \
  --selection-id 249c02f0-9389-44ea-b571-2a1676b943a4 \
  --business-date 2026-09-05 --slot evening --ordinal 1
```

Default dry run validates source/config/topic/evidence and counts matching active brand vectors.
It constructs the real factories, checks the generator prompt lower bound (before brand context),
and reaches the brand query construction but stops before embedding. It does **not** claim that
retrieval, generation, audit, image generation or delivery has succeeded.

Only after independent review and a successful dry run may main repeat the same exact selectors
with these additional flags, substituting the two exact digests from that dry-run JSON:

```text
--live-no-send --max-http-calls 3
--expected-config-sha256 <dry-run-config_sha256>
--expected-copy-version <dry-run-copy_version_sha256>
```

The config fingerprint contains allowlisted non-secret consumer settings and an endpoint digest,
not credentials. Main's protected-env identity gate remains necessary. There is no secret override
or reusable success token. Each live invocation consumes a new bounded budget; a timeout or failed
check does not authorize an automatic second invocation. Record each actual invocation externally.

## Isolation and limits

- Every DB connection starts with `default_transaction_read_only=on`; each SQLAlchemy transaction
  explicitly begins read-only. NullPool prevents unreviewed pooled state reuse. All sessions,
  including the brand repository's newly opened session, use the same engine. The statement
  guard admits only SELECT, SHOW and the exact read-only transaction command; PostgreSQL also
  rejects write-producing SELECT functions such as `nextval`. Statement/lock/idle-transaction
  timeouts are bounded. No job repository executor, checkpoint, package/image factory, MinIO or
  WeCom client is constructed; there is no commit or write operation in this tool.
- At most one physical embedding POST, one generation POST and one audit POST, total three.
  The underlying transport has zero retries, no ambient proxy mounts and no redirects. The guard
  pins the existing exact endpoint, stage-specific path and configured model. Calls are charged
  before transport, including failed/unknown outcomes. A retry/correction cannot bypass the guard.
- Copy generation/audit use one attempt and zero JSON corrections; all original input/output
  limits, schemas, deterministic rules and audit policy stay unchanged. Embedding uses the exact
  unchanged production factory, with its attempted second request stopped by the physical guard.
  Its first safe HTTP status or transport-error enum is retained if the cap masks the retry error.
- There is no repair or image generation. Deterministic errors prevent the audit request. If
  ordinary production would repair, output is `repair_needed_not_attempted`, not accepted.
  The whole live exercise has a 180-second deadline.
- Output is one JSON summary containing only IDs, hashes, counts, safe local/provider error enums,
  allowlisted issue-code counts, HTTP status numbers and latency. Unknown issue codes collapse to
  `other_issue`; provider messages, fields, claim IDs, bodies, prompts, private brand/evidence text,
  vectors, URLs and secrets are not emitted. Standard and structured logs are suppressed.

The summary's zero write/package/send counters describe this tool's construction and enforced
capabilities; they are **not** a claim that other running services made no concurrent changes.
Main must capture/reconcile actual before/after durable counters and the frozen cohort separately.

## Outcome interpretation

`preflight_passed_live_unverified` means zero provider calls and readiness to consider a live
no-send check. `first_draft_passed` means one first draft passed deterministic validation and the
configured audit with no repair-needed findings in this isolated check. Neither means production
recovery, a durable accepted run, image/package readiness or message delivery. Any diagnostic
failure remains a failure; preserve its stage, enum, issue counts, request counts and safe HTTP
status rather than repeating the paid request to obtain raw output.

The no-proxy transport, 180-second whole-exercise deadline, zero JSON corrections and no-repair
policy are intentionally more restrictive than the long-lived worker. A timeout, proxy-dependent
connection failure or first-draft rejection here does not by itself prove that the ordinary worker
cannot finish under its configured retry/repair policy. Confirm the relevant production boundary
before selecting a fix; never relax production quality rules merely to make this diagnostic pass.

The selected September 5 evening window expired at 19:30 CST. This diagnostic does not extend it,
requeue the old run, create a package, or authorize any send. Recovery acceptance still needs a
fresh eligible slot through the normal dispatcher to formal `delivered`, plus a duplicate check.

## Provider-free validation

Run from the main repository, using the clean exact-release app imports:

```bash
PYTHONPATH=/tmp/edu-ai-recovery-release.w7Btpe/backend conda run --name edu-ai \
  pytest .trellis/tasks/09-05-production-recovery-qwen-embedding/research/test_production_recovery_canary.py \
  -q -o asyncio_mode=auto
MYPYPATH=/tmp/edu-ai-recovery-release.w7Btpe/backend conda run --name edu-ai \
  mypy --strict --follow-imports=silent \
  .trellis/tasks/09-05-production-recovery-qwen-embedding/research/production-recovery-canary.py
```

At implementer handoff: 66 provider-free cases pass; scoped Ruff format/lint and strict mypy pass.
The independent reviewer owns separate real-PostgreSQL read-only tests and final gate evidence.
No live outcome is claimed by these fixtures. No product code, configuration, Compose, PRD, spec,
git commit or production state was changed by this implementer.

## Separately reviewed opt-in error observation (v2)

The first v1 live result remains immutable: embedding succeeded with six brand hits, then
generation returned HTTP 400. Its business error body was intentionally not read, so the exact
cause remained unknown. A separate fixed, nonprivate request subsequently succeeded with the same
`glm-5.2` model and parameters. That supports keeping the current model/account/parameters; it
does not establish why the content-bearing request failed.

Main requested one deliberate instrumentation revision, **not** an automatic replay. The revised
canary adds `--capture-provider-error-codes`. The flag is off by default; old invocations retain
their v1 schema/mode and never inspect non-2xx provider bodies. Flagged invocations use
`production-recovery-no-send-v2-error-observation` with `dry_run_error_codes` or
`live_no_send_error_codes`. `capture_provider_error_codes=true` and
`provider_business_error_codes` identify the new observation capability explicitly.

Only with this flag, and only for non-2xx status, the transport reuses the exact deployed bounded
raw/gzip reader to inspect at most 32,768 bytes in memory and then closes/discards the body. It
retains only `error.code` from the same 34 numeric codes independently reviewed in
`zhipu-chat-parameter-probe.py` against [official documentation](https://docs.bigmodel.cn/cn/api/api-code).
Unknown, malformed, ambiguous or non-code values become `other_code`. Messages, request IDs,
field names and private provider content are never emitted. Success responses use the unchanged
processing path. Oversized or malformed compressed responses fail safely; no extra call is granted.
Each stage can contribute at most one code because the existing physical cap remains unchanged.

The standalone stdin packaging repeats only the reviewed small allowlist/projection locally;
an executable parity test prevents it drifting from the independently reviewed parameter probe.
No runtime factory, prompt, model parameter, source/config selector, input limit, deterministic
quality gate, read-only DB restriction, repair limit or sending restriction changed.

Main must obtain a **new** independent review for the revised script hash and record a new
invocation identity. First run the same exact zero-call selectors above plus
`--capture-provider-error-codes`; if approved, the instrumented live invocation adds that flag to
the original `--live-no-send --max-http-calls 3` and exact config/copy-version fingerprints.
The old paid result does not authorize repeat calls, and this phase must not overwrite earlier
result files or review hashes. If the single instrumented call fails, report its code and stop;
do not modify private prompts or bypass a content filter.

V2 implementer gate: 87 provider-free tests pass on exact deployed-source imports, including
unchanged-request bytes, default zero calls/no error-body reads, read-only-loader regressions,
allowlist parity/redaction, raw/chunked/gzip bounds, close-on-failure and physical retry caps.
Independent review, local PostgreSQL rerun and all production invocation authority remain with
main/checker. No paid request or remote operation was performed while implementing v2.
