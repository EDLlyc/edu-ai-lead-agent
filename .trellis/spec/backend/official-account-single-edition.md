# Date-scoped M/W/F single drafts

## 1. Scope and trigger

The prospective single-edition mode replaces automatic Monday three-role batches
for one account. It prepares one article at 09:00 and begins uploading one
**unpublished draft** at 10:00 Asia/Shanghai on Monday, Wednesday and Friday.
Generation/upload duration means 10:00 is an upload start target, not a promised
WeChat acknowledgement time. No subscriber publishing, mass send, historical
batch replay, old draft deletion or unrelated WeCom change is implied.

## 2. Runtime and configuration

`OFFICIAL_ACCOUNT_SINGLE_ENABLED` defaults false. Activation requires an explicit
future M/W/F `OFFICIAL_ACCOUNT_SINGLE_MIN_DATE` and the nonsecret account SHA-256
in `OFFICIAL_ACCOUNT_SINGLE_ACCOUNT_FINGERPRINT`. Defaults are 60 preparation
minutes, six same-day catch-up hours, three attempts and a 60-second retry base.
The September 14 activation plan starts on **2026-09-16**; no September 14 backfill.

The existing weekly scheduler, weekly DAG worker and WeChat draft worker route to
`run_single_runtime` before legacy disabled checks. Single mode requires legacy
weekly scheduler/worker and draft auto-enqueue flags false. It bypasses **both**
legacy admission and legacy draft execution, not just inbox scanning. Only the
draft consumer constructs the WeChat client or receives account credentials.

## 3. Selection and artifact ownership

`due_single_edition` uses the current Shanghai date only; restarting on a later
date does not replay earlier dates. Account/date identity is stable across policy
versions. `select_single_article` admits only governed, veto-free candidates and
excludes reserved events. Prefer the last seven days, otherwise official-source
lookback within fourteen days. Preserve stored applied-priority, score, source
trust and event-time ordering; deterministic event ID breaks ties. Do not create
mandatory role quotas or claim that the model independently chose the topic.

The actual selected role remains an artifact compatibility value. Producer reuses
the persisted article worker, immutable selection/checkpoint storage and canonical
`build_child`/`validate_child`. Preserve existing author, source attribution,
two permanent banners, caption suppression, image provider and factual boundaries.

## 4. Persistence and idempotency

Additive Alembic `20260914_0047`, after `20260914_0046`, creates
`official_account_single_editions` and `official_account_draft_owners` without
rewriting weekly tuples, old manifests, article identities or old delivery rows.
Account/date uniqueness and atomic event reservation prevent competing dates or
workers from admitting the same topic. Claims and saves are lease-token fenced.

Consumer imports validated legacy and private manual-journal article **and event**
ownership before the history barrier allows admission. Missing/ambiguous lineage
is not evidence of non-delivery. Existing canonical `manual-v1` envelopes and
their private acknowledgements remain unchanged. New delivery shares that durable
intent/ACK journal; successful article generation alone never means uploaded.

## 5. Failure and recovery

Bound retryable, proven non-applied failures by persisted attempt counts and the
same-day cutoff. Ambiguous side effects are `outcome_unknown`, not automatically
replayed. HTTP 5xx or a generic retryable flag alone does not prove non-application.
Persisted add ACK must reconcile after expiry/midnight or a database failure
without issuing another add. One date's failure cannot block a later date.

The existing persisted article worker owns model attempts; producer polling is not
a new generation attempt. New runs freeze `execution_retry_policy` in their
`version_bundle` with `max_attempts`, `retry_base_seconds` and `expires_at`.
Enqueue/failure/claim/manual retry enforce that policy. Existing request
fingerprints stay unchanged, old bundles are not backfilled, and a queued/running
run with a mismatched policy is not reused. Preserve safe error codes, never raw provider bodies,
tokens, media IDs, private object paths or signed URLs in public logs/artifacts.

The explicitly authorized September 16 late image compensation is defined in
[`official-account-image-recovery.md`](./official-account-image-recovery.md).
It records the original cutoff and old unknown attempt, binds one new physical
image operation and changes only the target edition's bounded recovery window.
It is not permission for the scheduler or ordinary retry API to reopen unknowns.

## 6. Verification

Cover timezone boundaries, M/W/F eligibility, minimum activation date, no backfill,
single selection and excluded events; use isolated PostgreSQL for date/event races,
leases, history import and populated-downgrade refusal. Exercise prepared-child
validation and intent/ACK crash recovery with fake clients, not live model/WeChat
calls. Validate compose routing, migration metadata and production health checks
against the same `0047` head. Retain legacy weekly and source/layout regressions.

## 7. Deployment and recovery boundary

Capture an under-lock baseline and consistent backup after quiescing writers and
before DDL. Preserve exact live base integrations and banners in an immutable,
committed source overlay. Before consumer startup, new tables must be empty;
after startup, sealed history owners/barrier are expected but editions remain zero
before the activation date. Check these separately from container health.

Once migration may have run, do not automatically restore the old image, downgrade
Alembic or restore the database. Imported history alone can establish the new
ownership boundary. Recovery uses compatible candidate core with **both** old and
new optional admission/consumption disabled. If schema is not verified at `0047`,
leave writers stopped and require a forward fix. Standard release metadata gaps
remain explicit; an offline activation is not proof of a bootstrapped pipeline.
