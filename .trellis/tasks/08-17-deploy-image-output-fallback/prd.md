# 部署图片供应商格式容错修复

## Goal

将已经通过 live URL smoke 和完整质量门的图片输出容错提交 `cbc27b2` 安全部署到生产，使后续内容任务使用 URL 主输出、一次格式恢复和审核品牌素材兜底，同时保持当前业务数据、评分 `.7`、OCR/多样性开关和企业微信状态不变。

## Confirmed Baseline

- Authoritative application commit to release: `cbc27b2` (`fix(image): recover invalid provider representations`).
- Current production: commit `7ba25d3eeb290d3f784ae449a5b6ad360a8def58`, image
  `sha256:7627186cf1650a63bbe2e5e136e2364970a9383f756a62ed7db8c6e5cb50b21c`.
- All eight application services are running on the same image with restart count zero; API is
  healthy. Effective scoring is `scoring-v1-preview.7-delivered-repeat-history`; OCR/diversity are
  `true:true`.
- Runtime diff is exactly three application modules: image provider adapter, fallback domain
  helper, and material-package executor. There is no dependency/lock, Alembic, Compose, Settings,
  OpenAPI, or environment change.
- A separately authorized live smoke already made exactly one `gpt-image-2` generation with the
  new URL contract and validated a 1024×1024 PNG. This release must not repeat that paid smoke.
- The standard registry/digest baseline remains unavailable; `make release-prod` is not a valid
  activation path. The previous successful production release used a checksum-bound offline image
  and source-overlay operator.

## Requirements

### R1 — Authoritative source and Codeup

- Push the current clean local `main` fast-forward to Codeup `origin/main`; never force-push.
- Before build, fetch again and require `origin/main` contains `cbc27b2` with no remote divergence.
- Build application artifacts only from a clean detached worktree at exact `cbc27b2`; task/operator
  commits may be newer on Codeup but must not enter the application release identity.
- Verify the runtime diff from `7ba25d3` is exactly the three reviewed application modules and that
  runtime lock, Dockerfile, pyproject production dependencies, Compose and Alembic head are unchanged.

### R2 — Immutable offline artifacts

- Reuse the verified dependency base and current offline overlay semantics; build with no network,
  no dependency installation, and exact linux/amd64 identity.
- Produce source archive/manifest, image-source manifest, compressed image bundle, safe provenance,
  checksums, validator and a task-local operator in a mode-0700/0600 protected stage.
- Exact source/image path counts remain 321/179; only three file hashes differ from the production
  7ba source/image manifests.
- Candidate gates include non-root identity, dependency-layer prefix, `pip check`, all eight service
  imports, URL payload contract, both valid URL/Base64 parsing, material fallback focused tests,
  OpenAPI equality and Alembic `20260815_0021`.

### R3 — Safe production window and backup

- Before first stop, require a fresh stable read-only sample with no running/actionable content,
  no nonterminal/unknown WeCom delivery, no existing release operator, and no provider/WeCom delta.
- Acquire the backup lock before stopping anything. Stop all eight application services in reverse
  dependency order, dispatcher first.
- Create a fresh verified PostgreSQL dump/catalog plus exact source, env/release-env, markers,
  previous container IDs, shared/service tags, source manifest and protected-input hashes. Object
  storage is not mutated by this release; record a read-only MinIO inventory instead of invoking
  `minio-init` or restoring objects.

### R4 — One-shot activation

- Load and validate the candidate before retagging. Arm recovery before the first tag/source change.
- Retag the shared and nine service tags to the candidate, atomically install the exact 321-file
  source archive while preserving reviewed destination modes/owners, and update full/short markers
  to `cbc27b2`.
- Run only Alembic `upgrade head` with an explicit no-seed override; require no schema/source/business
  counter drift and head `20260815_0021`. Do not run `minio-init` or `seed_sources`.
- Recreate all eight application services one at a time with `--no-build --no-deps`; API first,
  dispatcher last. Check image identity, restart zero, health and stable business/provider vectors
  between dependency groups.
- Invoke the reviewed operator once. No second deploy attempt in the same authorization.

### R5 — Rollback and fail-closed behavior

- Before mutation, create immutable rollback tags bound to the exact 7ba image and capture old
  container IDs.
- Any failure after first stop triggers one automatic application rollback: restore exact source,
  markers and tags, then restore all eight 7ba services in dependency order with dispatcher last.
- Do not restore PostgreSQL/MinIO or downgrade Alembic automatically because this release has no
  migration/data write. If prior identity or stable zero-work state cannot be proven after rollback,
  stop all application writers and report an incident instead of retrying.

## Acceptance Criteria

- [ ] Codeup `origin/main` contains `cbc27b2`; push is fast-forward and committed secret scan passes.
- [ ] Candidate is built from exact clean `cbc27b2`, offline, with exact source/image manifests and
      no dependency/Compose/migration drift.
- [ ] Preflight and backup gates pass before mutation; all provider/WeCom deltas remain zero.
- [ ] Production markers become exact `cbc27b2`/`cbc27b2`; all eight services run one candidate
      image with restart count zero and API healthy.
- [ ] Runtime reports URL output contract, `IMAGE_MAX_ATTEMPTS` unchanged, scoring `.7`, OCR/diversity
      `true:true`, and Alembic `20260815_0021`.
- [ ] Bounded postcheck shows no running/actionable work, no nonterminal/unknown delivery, no release-
      caused provider/WeCom attempt, safe logs, and no old-image running container.
- [ ] Stage/temporary containers are removed; backup/result evidence is checksum-bound and retained.
- [ ] On any failure, exact 7ba source/image/services are restored once or all eight writers remain
      stopped with a clear incident report.

## Out of Scope

- No replay, resend, manual enqueue, historical noon repair, test WeCom message or business fixture.
- No second live image-provider call; the URL contract acceptance call already passed.
- No database migration, configuration/flag change, source seeding, MinIO initialization or object
  restoration.
- No production Agent Workbench route or frontend deployment.
- No standard registry/digest bootstrap; that remains a separate release-infrastructure task.
