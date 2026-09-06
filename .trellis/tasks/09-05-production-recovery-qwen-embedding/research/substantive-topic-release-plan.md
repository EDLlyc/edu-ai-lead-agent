# Substantive-topic release: preliminary independent review

Status: path identified; **not a `.12` deployment GO**. Natural `.11` production independently
satisfied delivery recovery AC2/AC3 on September 6; this document does not turn that observation
into authorization for the separate policy rollout.
Source: native Trellis check agent's read-only report, September 5, plus main's allowlisted
protected-environment key-shape verification. No provider requests or production writes.

## Why existing entry points cannot be used unchanged

- `deploy/release/deploy.py` requires a root-owned primary environment and manifest/current state
  inconsistent with this host's audited `0600:1000:1001` environment. It forbids primary-env hash
  changes and does not snapshot/restore that primary environment. Do not bypass those guards.
- Archived brand hotfix artifacts deliberately pin `40e4dec`, legacy marker `7a45a65`, their
  original release ref and exact eight-path runtime diff. Keep them unchanged. This candidate
  starts from deployed `5c560da71bcbb61b765d3fe82c742cf2d5e676e1` and changes a different allowlist.
- The old `primary_env_unchanged=true` result cannot describe this release. Evidence must instead
  prove exactly the approved scoring-version change, with every unrelated byte and file identity
  preserved. No broad dotenv normalization or migration is authorized.

## Candidate and configuration contract

- Clean branch: `release/substantive-news-scope-20260905`.
- Editorial policy: `science-tech-editorial-v4-substantive-topic`.
- Scoring policy: `scoring-v1-preview.12-substantive-topic-scope`.
- The exact protected assignment exists once and is unquoted:
  `CONTENT_SCORING_VERSION=scoring-v1-preview.11-qualified-authoritative-priority`.
  Replace only its value. Reject absence, duplicates, alternative syntax or unexpected old value.
- Preserve `CONTENT_SELECTION_PRIORITY_RULE_VERSION=qualified-authoritative-priority-v1`,
  thresholds, all provider/model/recipient settings and copy/prompt/slot/profile identities.
- Require fetched authoritative Codeup candidate identity, committed builder bytes, exact reviewed
  runtime/audit path sets, full source manifest, image-source parity, OCI revision and final digest.
  Never export dirty main or silently include its unrelated committed or uncommitted WIP.

## Transaction gates

1. Bind the exact current release/image/env/source baseline, known durable counters and seven-job
   frozen SHA. Repeat inside the release lock. Save protected inputs before the first stop.
2. Validate candidate image and no-build Compose behavior before stopping services. Reviewed
   development build metadata is not authorization to run a production build.
3. Quiesce only the reviewed service set, create a fresh backup, then recheck full baseline,
   queues/effects/source/environment immediately before candidate source/config installation.
4. Atomically install the approved single-key environment with exact old mode/UID/GID; validate
   old/new fingerprints at the appropriate stage. Partial source/config/marker/start failures
   restore the exact old source/image/env/markers and verify history again after restart.
5. Finish with at least a 15-minute margin before the actual earliest producer/preparation cutoff.
   A business-date rollover fails closed. Do not stop or extend ordinary schedules to gain time.
6. Require zero new .12 durable runs/jobs throughout the immediate rollback window. Once genuine
   new-policy work exists, unchanged Alembic head alone does not prove old-code snapshot
   compatibility. Later rollback needs separate review; never delete/relabel runs to enable it.
7. Verify all 12 application services share the candidate image, all 14 long-running services are
   healthy, Alembic remains `20260901_0042`, frozen queues/effects remain intact, and active
   settings reflect only the approved scoring transition. Offline probes make no model requests.

## Acceptance after deployment

Release success is only source/image/config/service convergence. Recovery AC2/AC3 were subsequently
met on the unchanged `.11` release by three fresh accepted runs, validated and audit-accepted
packages, formal text+image `delivered` states at 07:30-07:32 CST on September 6, and more than two
hours of normal repeat polling without a duplicate. See
`production-recovery-observation-2026-09-06.json`. That evidence does not prove `.12` behavior,
Qwen migration or official-account publication. No unattended monitor has been installed.
