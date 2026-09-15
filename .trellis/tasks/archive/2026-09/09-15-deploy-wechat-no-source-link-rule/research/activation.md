# WeChat no-source-link production activation

Activated and independently verified on 2026-09-15 at 17:29 Asia/Shanghai.

## Released identities

- Codeup branch: `release/wechat-two-banner-framing-20260914`.
- Application commit: `01ff75eed1ed82f5951580af994b6c5c750e53ae`.
- Release-operator fixes: `d0b9e0a8a81a180fe09a8142676be18d4444b78f`
  and `69a203d`.
- Previous application commit: `d2e709c0b6a5e47d1b91d2ec623de734aa3c0eb2`.
- Previous image: `sha256:baffc27e9dc4ccbd9fed5ab248e4e00784f80ecfb25f966fe8c63ee286601d8d`.
- Activated image: `sha256:febd216660c4fdf3919a8cd2c7da8c233d69d1e53503ff50b27df00c2aa58655`.
- Candidate archive SHA-256:
  `17e59b96cd2e7d929314b17b33b1407d50cb2c8156bf476025332819fdfa1c19`.
- Candidate manifest SHA-256:
  `27c09642594410471f9b9e0acbfcceba41be826180a329fb391d064333f1be18`.
- Final deployment operator SHA-256:
  `0ead97b4d5abdac7b06247d976abc795050241140188768ac182adf228df39a9`.

The OCI validator proved an exact base graph plus one overlay layer containing
only the five reviewed application files. The application image label and both
production revision markers bind the application commit, not the later
operator-only commits.

## Pre-deployment gates

- Focused product suite: 124 passed.
- Release/rollback harness after both production-discovered hardening changes:
  48 passed.
- Changed-scope Ruff formatting/lint and strict mypy: passed.
- Six-profile Compose validation, Trellis task validation and
  `git diff --check`: passed.
- Full `make backend-check` was run once and stopped only on the documented
  unrelated formatting baseline in `official_account_local.py`,
  `topic_selection.py` and `test_title_relevance_ingestion.py`; no task-owned
  file failed.
- Local and production SHA-256 verification and OCI validation passed before
  activation.

## Fail-closed observations

No failed attempt stopped an application service or changed a production
revision marker.

1. The first shell invocation could not enter the root-owned staging directory;
   the operator never started.
2. A preflight observed a transient eighth copy-generation job from the normal
   17:00 content run and rejected before image loading or quiescence. The job
   completed normally and the sealed historical cohort returned to seven.
3. Two formal Enterprise WeChat deliveries were queued for the future
   18:30–19:30 window. The operator was hardened and independently reviewed to
   accept only a bounded frozen set of strictly future, unclaimed, attempt-zero
   rows while rejecting due, running, partial or unknown work.
4. Repeated pre-stop fences exposed that the single-edition scheduler refreshes
   only owner-row `updated_at` heartbeats every few seconds. The owner safety
   digest now validates both timestamps but excludes only valid `updated_at`
   churn; every ownership/control field remains bound. Regression and
   independent review passed before retry.

Two pre-quiescence backup snapshots were preserved at:

- `/opt/edu-ai-release-backups/no-source-links-01ff75eed1ed-prequiesce-failed-1`
- `/opt/edu-ai-release-backups/no-source-links-01ff75eed1ed-prequiesce-failed-2`

They contain protected configuration snapshots and no successful deployment
receipt. The successful backup is
`/opt/edu-ai-release-backups/no-source-links-01ff75eed1ed`.

## Successful activation

The final operator passed these ordered phases:

```text
preflight
load_and_smoke_before_stop
quiesce
start_candidate
completed
```

The operator loaded and smoke-tested the candidate before stopping writers,
rechecked protected files, schema, Compose configuration, candidate identity,
queues and ownership after quiescence, atomically changed only `.release.env`
and the two release markers, recreated only the 12 application services, and
recorded the success receipt.

No Alembic migration, `.env` change, database row update, object-storage write,
model request, WeChat request, image upload, draft operation, publication or
mass-send operation was executed by this release.

## Post-activation verification

- Both revision markers: application commit `01ff75e...`.
- `.release.env`: activated immutable image digest `febd216...`.
- Application services: 12 running on the exact candidate image, restart count
  zero; API health is healthy.
- Dependencies: PostgreSQL and MinIO remained healthy with restart count zero.
- Schema: unchanged at `20260914_0047`.
- `official_account_single_editions`: 0.
- `official_account_draft_owners`: 14, with the frozen safety digest preserved.
- Sealed historical preview copy jobs: 7.
- Active image work: 0.
- Future nonclaimable Enterprise WeChat deliveries: 2, frozen and unchanged;
  their delivery window was not opened or consumed by deployment.
- Network-disabled runtime probe: historical/unversioned and V1 rendering
  preserved; current version is `wechat-source-presentation-v2-no-links`, body
  source attribution contains no URL/link/read-original affordance,
  `content_source_url` is null, and fake `draft/add` omits the field.
- Deployment receipt: `model_calls=0`, `social_calls=0`,
  `migration_executed=false`.
- Standard production health script: `runtime_health=ok`,
  `dependency_count=2`, `service_count=12`, schema/API alignment passed.

Protected evidence hashes:

- `preflight-state.json`:
  `e52b5ed60472c6f78e71178d50b6795f011947e2051dd64dea7e6c2c6651bd81`.
- `result.json`:
  `262b4bc0d98b01f232a69a5fac7b631a28651d1694d81a11bdc3b6e202e762c4`.

The standard release provenance files remain absent, as they were before this
scoped overlay. The health command reports this truthfully as
`standard_release_provenance=incomplete`; it does not affect the successful
runtime, schema or policy verification above.
