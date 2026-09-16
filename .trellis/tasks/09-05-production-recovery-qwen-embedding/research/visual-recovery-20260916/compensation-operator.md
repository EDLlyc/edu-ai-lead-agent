# September 16 exact-target compensation operator

## Runtime and authority

This operator may rearm only the frozen September 16 edition/run/article/first-image
IDs in `SEPTEMBER_16_TARGET`. It is not a general retry API. It retains the unknown
first paid request, records the user's one-time compensation authority, and does
not claim that the old request failed. No provider/model change, schedule change,
database migration, public publishing, mass send, or draft deletion is performed.

Use the independently checked immutable release, with the **same production
database, configuration and actual persistent `wechat_mp_draft_artifact_root`
mount used by the single-edition draft consumer**. The existing account journal
directory is required; a missing mount is an error, not an empty replacement.
The operator holds the existing account journal lock throughout the SQL transaction.
Stop/quiesce the affected single producer, official-account generator and draft
consumer during the final plan/apply; do not run a second copy of the consumer.

Default is a plan (no database updates, no model/WeChat calls):

```sh
python -m app.infrastructure.db.official_account_visual_compensation
```

The approved apply is explicit, once the reviewed candidate is deployed and the
final target/volume preflight succeeds:

```sh
python -m app.infrastructure.db.official_account_visual_compensation --apply
```

Do not call these commands against the developer database to emulate production.
They intentionally fail if the exact target is absent. Console output is only the
closed authorization schema (IDs, hashes, attempts and deadlines); arbitrary
exception text and provider responses are never printed.

## Durable transitions and recovery

1. Lock the exact edition, run, visual and account/event owner. Require no active
   leases, prepared artifact, receipt, local draft/media, foreign draft ownership
   or target journal write/claim. Require accepted, validated original text/render,
   original unknown visual attempt and no recoverable provider request handle.
2. Write a create-only protected snapshot to the existing private account journal.
   It includes complete pre-change edition/run/visual/original-attempt/owner plus
   accepted article/render. Never copy that private receipt into this repository.
3. Append `visual_compensation_authorized` workflow attempt containing only the
   closed schema and snapshot hash. Atomically requeue this run and restore this
   edition to generating plus its event owner to reserved. No old attempt changes.
   Old attempt remains 1 of 3; authorized successor is attempt 2 of 3.
4. Freeze the only new cutoff at authorization time: at most two hours later and
   before the end of the same Shanghai business date. Both original and new cutoff
   are audited. Only the exact run/edition execution windows change; not `.env`.
5. Resume the normal services. The regular fenced image claim consumes this
   authorization exactly once, records `visual_compensation_consumed`, then moves
   only the logical visual-slot projection to generating. The new physical
   `provider_request_fingerprint` goes to the existing provider Idempotency-Key;
   logical plan/result fingerprints and accepted article/render remain unchanged.
6. An acknowledged non-applied transient retry can consume the remaining frozen
   attempt with the same **new** physical key, never the original unknown key.
   Unknown successor/crash/orphan does not obtain another compensation. Repeated
   operator apply returns the old authorization without requeueing or refreshing
   its deadline. All ordinary unknown retry paths remain disabled.

## Acceptance

Record original/new auth fingerprints and deadline, image attempt lineage and
ready image count, prepared artifact identity, same original article/render IDs,
and the final actual single-edition draft receipt fingerprint. Confirm another
consumer pass adds no WeChat write. Healthy containers or an image alone are not
proof of complete draft delivery. If the compensating request is unknown, report
that and stop; no automatic third paid identity is authorized.

## Local checks

New unit and isolated PostgreSQL tests use synthetic data and frozen clocks;
no paid provider or WeChat writes are used. They cover closed schema, midnight/
two-hour cutoff, exact ownership/lease/receipt/journal guards, immutable input
rechecks, one-time/concurrent consumption, preserved text/render/attempts,
safe retry physical key and frozen budget, orphan/no-replay, and producer resume.
