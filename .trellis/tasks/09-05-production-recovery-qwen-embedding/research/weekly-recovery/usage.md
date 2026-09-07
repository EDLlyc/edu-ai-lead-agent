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
