# 视觉多样性生产启用与单条验收 — Design

## Boundary

本任务不改业务代码。它使用已经通过完整质量门并部署的 `7d8a914` 镜像，通过隔离的生产形状
验收证明真实 Comfly 图片生成与智谱 OCR 能满足 v2 合同，然后只修改生产 `.env` 中两个布尔
开关。任何代码缺陷都使启用失败关闭，不在运行中打补丁或放宽断言。

## Data Flow

```text
production read-only baseline
  -> fresh protected PostgreSQL dump
  -> temporary acceptance database
  -> choose one accepted copy with no WeCom job
  -> remove only its old v1 package/image in the temporary database
  -> isolated private MinIO acceptance bucket
  -> current material reconciliation (v2 reservations)
  -> Comfly image attempt 1 [optional reserved attempt 2]
  -> exact ordered Zhipu OCR
  -> seven-day similarity decision
  -> machine assertions + local visual inspection
  -> PASS: atomically enable both production flags
       -> recreate API/content worker -> restore scheduler -> restore dispatcher
     FAIL: keep/restore both flags false -> restore services
```

## Isolation Contract

- The temporary database name and bucket use one generated acceptance identifier and never reuse
  the production database or configured production bucket.
- The database is restored from a protected server-local dump. The selected row is identified by
  eligibility predicates, not a hard-coded ID in Git or logs.
- Only the selected clone's old material package and image lineage are removed in the temporary
  database. Production is read-only throughout acceptance.
- The one-off worker receives explicit temporary database/bucket overrides, `WECOM_ENABLED=false`,
  scheduler flags false, `IMAGE_DIVERSITY_ENABLED=true`, `IMAGE_OCR_ENABLED=true`,
  `IMAGE_QUALITY_AUDIT_ENABLED=false`, and `IMAGE_MAX_ATTEMPTS=2`.
- The output image is copied to a protected temporary local path solely for visual inspection; no
  object key, prompt, perceptual hash, provider body, or credential is printed.

## Production Activation

The dispatcher, content scheduler, and content worker stop before the `.env` edit. A timestamped
mode-600 `.env` copy and pre-change checksum form the rollback boundary. Both flags are written in
one atomic replacement. A one-off Settings probe must succeed before acquisition API/content
worker recreation. Only after those services are healthy and their resolved version/flag bundle is
equal does the content scheduler resume. WeCom resumes last after exact delivery counters remain
unchanged.

## Acceptance and Failure Semantics

- `accepted` on attempt 1 is the normal pass.
- `regenerate` on attempt 1 followed by `accepted` or `accepted_with_warning` on attempt 2 is an
  allowed pass and proves the bounded alternate path.
- OCR mismatch, identity/topic/media failure, provider failure, missing audit lineage, more than two
  image attempts, a third reservation, or any WeCom record is a fail.
- Failure before production activation leaves the running API on its prior false-valued environment;
  restoring workers is sufficient. Failure after activation restores the protected `.env` copy and
  recreates the same affected services.
- The additive 0021 schema is never downgraded and no v2 audit rows are deleted from production.

## Cleanup and Evidence

After the result is classified, retain only a sanitized count/status record and the inspected image
until task completion. Drop the temporary database and remove the acceptance bucket only after
proving their exact generated names. Keep the protected `.env` backup through the stability gate.
No production front-end, ACR, Flow, source, copy, or delivery configuration changes are included.
