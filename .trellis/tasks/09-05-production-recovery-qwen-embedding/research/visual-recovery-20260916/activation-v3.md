# Activated: resilient generated visuals with advisory image review

## Outcome at 2026-09-16 19:03 Asia/Shanghai

The checked forward-only release completed successfully. All twelve application
services run the immutable candidate image and the API, PostgreSQL and MinIO are
healthy. No image/review model or WeChat call occurred during deployment.

- Revision: `ee5ff70f7b91fa3da21906ed7dc18c591ff92898`.
- Image: `sha256:2b6d8cca6f58952d632813ad8c8ec280512242bd935190eee4cac68cef16c016`.
- Schema: `20260916_0048`, upgraded from `20260914_0047`.
- Visual policy: `official-account-visual-pipeline-v3-resilient-advisory`.
- Outer adapter attempts: `IMAGE_MAX_ATTEMPTS=1`; V3 owns the durable three-attempt
  per-slot ledger.
- Runtime image provider/model: Comfly `gpt-image-2.5-sunburst`; the configured
  Zhipu audit credential is present without exposing its value.
- PostgreSQL backup SHA-256:
  `168ba57df91027867a2d592f13cd84095cad6df0fee82769e8ac774d9dd04ad7`.
- Protected backup and receipt:
  `/opt/edu-ai-release-backups/visual-recovery-ee5ff70f7b91/`.

The already recovered September 16 external draft was not replayed or replaced.
The original production edition remains `outcome_unknown`, its article remains
`result_unknown`, its generated-visual count remains one, and it still has zero
local drafts. The scheduler reports `due=false`; no same-day admission occurred.

The deployment receipt records `model_calls=0`, `social_calls=0`,
`compensation_executed=false`, the preserved history digest, exact migration byte,
candidate archive digest and all reviewed application hashes. The removed
policy-blind checksum index is absent after migration; V1/V2 duplicate rejection
remains enforced by the repository while future V3 runs treat named duplicate and
quality findings as advisory.

## Verification

- Product/database regression: 245 passed.
- Release operator regression: 34 passed.
- Ruff, format, strict mypy, Python compilation and diff checks passed for their
  scoped files.
- Post-deploy settings readback, schema/index query, service image/state inspection,
  API health and Official Account worker logs were checked independently.

The next natural M/W/F observation is Friday, 2026-09-18. Deployment proves the
new code/config/DB boundary is active; only that future run can prove a real provider
failure followed by an automatic second or third physical attempt.
