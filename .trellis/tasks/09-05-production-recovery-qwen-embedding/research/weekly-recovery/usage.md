# September 7 one-shot draft recovery

This exact-incident operator supports the deployed `5c560da` runtime and the prospective source
preflight fix. Run inside the existing weekly DAG worker container with its existing settings,
database access and persistent weekly artifact/inbox mounts. It constructs no model or WeChat
client; one ordinary article enqueue authorizes the existing local worker to generate the missing
article. Final atomic inbox aggregation authorizes the existing draft worker to stage three drafts.

## Commands

```bash
python -B /reviewed/weekly_recovery.py plan
python -B /reviewed/weekly_recovery.py execute --plan-file /reviewed/plan.json --plan-sha256 SHA_FROM_PLAN
```

`plan` prints one canonical safe JSON plan. Capture stdout through the operator's normal secured
transport into a mode-0600 local plan file; the command itself performs only database/file reads.
`-B` prevents import bytecode writes. The database sessions explicitly use
repeatable-read/read-only transactions and roll back. Review
the fixed original run, cutoff, two retained articles, replacement material/event, source and
article-request fingerprints, selected-input fingerprint, original root/node/attempt/artifact
hashes and successful article/media/draft row hashes. Use the exact printed `plan_sha256` on execute.
Do not redirect logs into the JSON plan file; a malformed plan fails closed.

`execute` rechecks the entire plan, exclusively creates a mode-0600 incident audit in the existing
weekly artifact root, writes and fsyncs the full safe plan intent, checks again, and enqueues only
package `198969a7-056d-482b-81f4-8219cbd2106b`. A short `FOR SHARE` transaction locks only that
material and its image, verifies the sealed source/request fingerprints, and keeps the source
stable through the ordinary repository's enqueue commit. These locks permit the enqueue's foreign-key
checks and block source updates; the lock-only transaction always rolls back. Lock waits, statements,
and the enqueue are bounded. It waits at most 720 seconds for the ordinary worker.
It then builds/validates the existing two exact children and one new child through the existing
prepared artifact owner, rechecks unchanged history and absence of draft jobs/items/attempts or
staged inbox aggregates, writes an aggregate intent, and atomically exposes the validated batch.

Each phase appends a timestamped SHA-256 chained receipt and fsyncs it. The audit never overwrites
original DAG nodes, attempts, inputs or root state. The original DAG remains `terminal_failed`.
An `inbox_ready` result means a validated recovery handoff exists, not that WeChat accepted drafts.
Main must observe the ordinary draft job and all three role items and verify nonduplication.

The durable exclusive intent makes every repeat execute fail closed, including after process
failure, cancellation, timeout, or a successful aggregate. Never delete the audit to retry. Inspect
its last phase and the exact article request/run or aggregate before designing a separately
reviewed continuation; preserve any unknown external outcome. No broad retry/reset or new identity
is provided. Ordinary repository/artifact owners retain their own idempotency as defense in depth.

## Verification

```bash
PYTHONPATH=backend conda run --name edu-ai pytest .trellis/tasks/09-05-production-recovery-qwen-embedding/research/weekly-recovery/test_weekly_recovery.py -q
```

Tests are provider-free and use temporary local audit directories. Main additionally performs the
real read-only plan against deployed state before any execute. Production status and credentials
are never embedded in fixtures; stdout/errors contain only fixed codes, IDs, counts and hashes.

## Prepared batch discovery and existing daemon handoff

The September 7 recovery produced aggregate
`4d25b6c7c81055c101101100d18682d3aedf61d52228d662710b397b422248c5`
and batch `abb680a1b8e52df9395a033199c1844b6cb2d919eaeef72a9fe196b9e8864bea`.
The producer writes `weekly-inbox` relative to the shared weekly named volume. Its consumer
mounts that volume read-only at `/app/input/official-account-weekly-editions`, so its process-local
inbox must be `/app/input/official-account-weekly-editions/weekly-inbox`. The previous
`/app/input/weekly-inbox` path is outside that mount. The Compose fix changes only this consumer
environment field and retains the read-only mount, existing credentials and draft-only mode.

The empty writable staging volume also requires installation-time ownership matching the existing
worker UID/GID. The observed initial root was `root:root`, mode `0755`, empty, while the worker ran
as UID/GID `999:999`. Before initializing that exact root, bind its named-volume identity and
destination from the captured worker mounts; use `O_DIRECTORY|O_NOFOLLOW`, verify the descriptor
and path inode, require mode `0755`, ownership `0:0` and an empty directory, then `fchown` only that
descriptor to the verified worker UID/GID. Preserve the mode and read-only weekly source volume.
Reject a nonempty root, symlink, identity drift or unexpected ownership. Never recursively chown
an existing staging tree. Main owns this independently reviewed installation repair and its receipt.

After verifying the exact prepared batch, zero draft jobs/items/attempts, the matching staging
mount and writable root, main may run the existing CLI once in the captured running draft-worker
container, with only its discovery path overridden:

```text
docker exec -e WECHAT_MP_DRAFT_WEEKLY_INBOX_ROOT=/app/input/official-account-weekly-editions/weekly-inbox CAPTURED_DRAFT_CONTAINER_ID python -m app.wechat_official_account_draft_main reconcile --once --maximum 1
```

Reconciliation uses the prepared loader, stages all three children immutably in the shared draft
artifact volume, and enqueues one three-item job. It constructs no WeChat client. The existing
daemon resolves claimed items from that staging volume independently of its discovery inbox;
therefore it can finish all three drafts without a stop/restart, an extra worker or further model
generation. `enqueue-weekly` is not interchangeable here: its manual path still invokes the
legacy finalized-weekly loader after staging and cannot accept this prepared aggregate end to end.

Observe the existing database/CLI status until one job is `ready` and the canonical three items
are `succeeded` with draft receipt fingerprints, no running/unknown attempts, then observe a repeat
pass for nonduplication. Preserve the original terminal DAG and successful article identities.
CLI exit zero or reconciliation enqueue alone is not success evidence. If the outcome is unknown,
do not enqueue again, start another worker or reset rows; retain the actual durable state for
inspection. The permanent Compose fix makes future automatic discovery read the correct inbox.
