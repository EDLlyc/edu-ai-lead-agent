# Implementation plan

## Preconditions

- Do not execute the operational change until the user approves the final planning summary and
  `task.py start` moves this task to `in_progress`.
- Preserve the existing dirty worktree, especially `.agents/skills/trellis-break-loop/SKILL.md`
  and all untracked `reports/` files.
- Do not print proxy subscriptions, tokens, credentials, signed URLs, or full source bodies.

## Checklist

1. [x] Re-read the current task and backend source/network specs; verify the active Clash profile,
       merge-template association, target template, current DNS answers, and 10/2 source registry.
2. [x] Create a timestamped sibling backup of `moQE0hDIEMse.yaml`, record checksums, and add exactly
       `+.cast.org.cn` and `+.edsurge.com` idempotently.
3. [x] Validate YAML shape and the two-line diff; reload only `clash_verge_service`.
       YAML and diff validation passed. The user completed the reviewed administrator reload;
       independent post-reload verification reports `clash_verge_service` as `Running`.
4. [x] Validate both target domains and public controls from WSL, Compose, and the application
       public-resolution path. Confirm no target answer is non-global or in `198.18.0.0/15`.
       CAST, EdSurge, `www.gov.cn`, and `education.news.cn` returned only globally routable
       answers in WSL, PostgreSQL, MinIO, and `validate_public_resolution`.
5. [x] Run focused SafeHttpFetcher/live-smoke/connector tests, including non-global rejection.
6. [x] Run bounded pending-source live gates: one CAST entry + at most one detail, then one EdSurge
       entry + at most one detail. Stop on typed policy/access/parser failure; do not bypass.
       Each source returned HTTP 200 for its single entry request, then deterministic discovery
       raised typed `parse_failure` with zero approved items. No detail request or retry was made.
7. [x] Confirm database/source registry still reports 10 active and 2 pending and no pending source
       was seeded or scheduled.
8. [x] Run `make doctor`, `git diff --check`, and a final secret/unrelated-change audit. Record the
       result and exact rollback instructions.

## Validation commands

```bash
conda run --name edu-ai pytest -q \
  backend/tests/contract/test_safe_fetcher.py \
  backend/tests/contract/test_fetch_policy.py \
  backend/tests/contract/test_live_smoke.py \
  backend/tests/contract/test_source_connectors.py

make doctor
git diff --check
```

Live checks use the pending profiles directly through the existing safe fetcher/connector
interfaces; `make source-smoke` is not sufficient because it intentionally includes only active
profiles.

## Rollback point

Before the service reload, compare the edited template against its backup and abort if the diff is
anything other than the two domain lines. After reload, any DNS regression restores the backup and
reloads the same service before further checks.
