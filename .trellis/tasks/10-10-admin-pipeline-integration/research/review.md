# Independent integration review — 2026-10-10

Reviewer scope: P1–P6 in this task's PRD/design; actual legacy `83a41e41` source and immutable
359-file manifest; no SSH, production actions, provider calls, credential access or commits.
Application changes were reviewed directly, then rollout changes were coordinated with their
owners. Final result: no unresolved code-review blocker; approved to proceed through the
coordinator-owned release gates below. This is not a claim that production has been upgraded.

## Product findings

No remaining product-code defect found in the completed template delta:

- New account choices are normalized only for new editions; an existing supported pin wins.
  Pin version/ID validation is strict, claim validation precedes pin handling, and a malformed
  legacy intent cannot create the new pin or issue a provider write.
- The two bounded first-intent reads correctly cover legacy bodies with and without inline
  media. Old default-colour request/ACK hashes remain valid after expiry and account edits.
  Existing journal objects are create-only and their bytes remain unchanged.
- Account lookup binds the fingerprint as a SQL parameter and imports no admin ORM. The
  disabled-account lookup semantics are preserved deliberately, as documented in research.
- The template page describes saved configuration and first-upload/retry behavior accurately;
  it makes no unsupported live-worker or applied-state claim. Root must pair its deployment
  with the consumer release, as the rollout procedure requires.
- Compose has exactly four optional pipeline image overrides and exactly six explicit model
  encryption-key grants. The draft worker receives neither encryption secret. The narrow
  config port preserves the old defaults/validators and changes only the field/getter.
- The unchanged watcher and entrypoint integration retain environment fallback, verified
  loaded versions/errors, persistent-only registration, and in-flight SIGTERM draining.

## Findings fixed during coordinated rollout review

1. `rollout/common.py`, `preflight.py`, `test_rollout.py`: comparing current journal bytes to
   baseline alone could approve old-code rollback when the baseline itself already had an
   incompatible pin. The owner added baseline-pin rejection and an independent rollback pin
   guard, with coverage for a pin present in both snapshots and a pin added after cutover.
2. `rollout/common.py`: initial idle admission ignored every unleased unknown outcome. The
   owner added active-current-single/new-article-unknown checks against the reviewed research
   cutoff; old expired history remains preserved. Execution allocations are also admitted only
   when not running. No historical row is reset, deleted or made replayable.
3. `rollout/preflight.py`, `postcheck.py`, `common.py`: Python-only comparison was insufficient
   after the candidate manifest expanded to assets/migrations/metadata. The owner now hashes
   and compares the full actual legacy/candidate file scope; postcheck compares
   `expected_file_sha256`, avoiding an erroneous Python-subset versus full-app comparison.
4. `rollout/README.md`: reconciled the distinction between ordinary Docker stop grace expiry
   and this release's explicit `stop --timeout -1`. A local CLI timeout does not authorize
   SIGKILL; recovery rechecks state and leaves the draft stopped on any read/shape error.

## Independent verification completed

- Scoped backend Ruff and configured Mypy: PASS (two changed product modules; lint also covers
  their changed unit/integration tests).
- Scoped frontend ESLint and full TypeScript check: PASS; template component tests: 3 PASS.
- Layout + single-edition + runtime regression files: 74 PASS, zero skips/failures.
- Original pre-template reproduction: now `delivered`, no retry writes and no provider calls.
- `research/check-actual-legacy-ack.py` dynamically loads the actual extracted legacy delivery
  and draft-service modules. Both media/no-media fixtures deliver once with fake clients,
  then reconcile the real old ACK after expiry with the new code: 2 PASS, zero retry/provider
  writes, all old journal JSON bytes preserved. Receipt:
  `/tmp/edu-admin-pipeline-integration/reviewer-actual-legacy-ack.json`.
- Model worker lifecycle + exact Compose mapping + prior strict Compose + model overlay:
  51 PASS, zero skips/failures (`reviewer-model-tests.log` under the same temporary directory).
- Final rollout isolation suite: 13 PASS, zero skips/failures. Includes immutable archive
  validation, backup restore-list failure, pin/state rollback guards, read failure leaving draft
  stopped, current-host/start/fresh/error heartbeat checks, no forced kill, strict render delta,
  and captured-command secret redaction (`reviewer-rollout-tests-final.log`).
- Final helper/changed-test Ruff, helper formatting and `git diff --check`: PASS. Helpers compile
  locally and use only standard-library host dependencies. Application Mypy/TypeScript results
  above cover the typed product boundary; one-off host scripts are outside application Mypy scope.

Executable backend/frontend specs now describe the reviewed pin, bound lookup and saved-state
contracts. Existing six-service diagnostic repair remains accurately identified as already live;
the new four-service connection's live status must be recorded only after root's release evidence.

## Release boundary

Review does not substitute for root-owned final source gate, candidate-image offline smoke,
fresh read-only production admission, verified DB/journal-volume backups, and two current-host
heartbeat observations spanning a poll. Existing six admin/core services must retain their
container identities. Root swaps frontend only after those checks pass. Empty stored-key versions
prove DB reads and environment fallback, not an actual production encrypted-key rotation.
