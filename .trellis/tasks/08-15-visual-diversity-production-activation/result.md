# 视觉多样性生产启用与单条验收 — Result

## Result

**FAIL-CLOSED — 未启用生产视觉多样性与图片 OCR。**

唯一的隔离验收条目在一次 Comfly 图片生成后通过了 1024×1024 媒体门，
但紧接着的唯一一次智谱 OCR 逻辑调用以 `provider_request_rejected` 终止。图片在
OCR 前置门失败后未写入验收 bucket，因此没有可下载或人工视觉检查的最终图片。
没有开始第二次图片生成，没有更换新闻，也没有手工 enqueue、retry 或 resend。

## Safe production baseline

- Runtime commit: `7d8a9142d3195ce5d0df8e62252a74d99229a1bc`.
- Runtime application image ID: `sha256:3ce0e573da86726ffb3ba59da7fa16b3e16903649ad6a62213944c698a7b2c64`;
  the existing Compose reference is `edu-ai-lead-agent-backend:local` and was not rebuilt or changed.
- Alembic: `20260815_0021`.
- Pre-quiesce durable counts: image artifacts 31, plan reservations 0, similarity attempts 0,
  material packages 31, WeCom jobs 21, WeCom attempts 41, copy-generation attempts 142.
- Pre-quiesce running content/image/delivery work: 0.
- The three-count increase observed since earlier planning was the ordinary 2026-08-15 evening slot;
  it completed before quiesce and did not overlap acceptance.
- The `.env` rollback copy was mode 600 and checksum-identical. The fresh custom dump was
  9,446,535 bytes, passed `pg_restore --list`, and had SHA-256
  `2c18839f876ed61f3ad7bb7a511f1892510ac49ed022af0bc8a88f7ef3f645b4`.

## Isolation and bounded-call evidence

- The generated acceptance database and private MinIO bucket were distinct from production.
  The bucket was private and empty before the worker started.
- The deterministic target was the newest eligible accepted copy (business date 2026-08-13,
  legacy slot). The clone had exactly one accepted copy without a package and zero other accepted
  copies without a package.
- Actionable copy, topic, slot, brand, image, and package queues were all 0 before the paid call.
  The target had 0 WeCom rows.
- Isolated Settings resolved diversity/OCR enabled, quality audit/scheduler/WeCom disabled,
  `IMAGE_MAX_ATTEMPTS=2`, and `IMAGE_DIVERSITY_MAX_REGENERATIONS=1` against the temporary
  database and bucket. A clone-only check constraint rejected any new image `attempt_count > 2`
  before a provider call.
- Paid image-generation attempts: **1**. Logical OCR calls: **1**. Quality-audit calls: **0**.
  Copy-generation attempt delta: **0**. WeCom job/attempt delta: **0/0**.
- The isolated run created one package and one artifact, plus two plan reservations with two
  distinct plan fingerprints and two distinct reference-set fingerprints.
- Media validation was configured and passed with zero issue codes at 1024×1024. OCR then ended
  with `provider_request_rejected`; the artifact/package ended `failed`, no similarity attempt was
  created, and no image object was stored.
- Because no final object existed, title hierarchy, occlusion, pseudo-text, watermark, QR, identity,
  and topic-fit visual inspection could not be performed. This is an acceptance failure, not a
  waived gate.

## Fail-closed recovery

- `IMAGE_DIVERSITY_ENABLED=false` and `IMAGE_OCR_ENABLED=false` remained unchanged throughout.
- Production content worker and scheduler were restored first. Production counters still matched
  the exact baseline and running work/non-terminal delivery were both 0 before the WeCom dispatcher
  was restored last.
- The 30-second stability sample passed: all eight application services were running with restart
  count 0; PostgreSQL and MinIO were healthy with restart count 0; acquisition API was healthy;
  production counters remained exactly 31/0/0/31/21/41/142.
- The bounded log scan covered four relevant containers with a 300-line cap each and found zero
  secret, raw-prompt, data-URL, or private-object-key patterns.
- The exact temporary database, empty acceptance bucket, one-off worker container, protected dump,
  restore/init logs, target-ID file, and activation state file were removed. The dump is not
  recoverable from the removed transient file; normal production backups remain unaffected.
- The protected `.env` rollback copy remains server-local, mode 600, and checksum-identical to the
  active `.env`.

## Follow-up

Diagnose why the configured Zhipu OpenAI-compatible vision endpoint rejected the bounded OCR
request. Do not enable either production flag until a separately authorized acceptance produces a
stored image, exact ordered three-line OCR evidence, a similarity decision, and a completed manual
visual inspection. This task intentionally did not retry another item or broaden provider scope.

## Independent review

The independent Trellis check passed. It re-confirmed the two production flags were false, all
eight application services were running with restart count zero, production counters matched the
pre-quiesce baseline, no active work or non-terminal delivery remained, and every generated
acceptance resource was absent. The check removed only the `_example` sentinel rows from the two
task JSONL manifests; it made no product or production change.
