# September 14 Monday batch: read-only diagnosis

User asked why this morning's articles did not complete. No retry, generation,
upload, publication, configuration change or production write was authorized or
performed. Queries used explicit PostgreSQL read-only transactions; checkpoint
reads used the running weekly worker's content-addressed artifact owner.

## Observed batch

- Weekly run `82acb89f-1349-546e-9cba-c2964282ea9c` started at 09:00:00
  Asia/Shanghai on 2026-09-14. Schedule and role selection succeeded.
- Official-anchor article `8fe5f048-b68e-475e-ba4b-6743dd267afb`, titled
  `当孩子问“为什么”，家长如何接住科学教育的信号`, generated successfully but
  failed the sole validation issue `article_length_out_of_bounds` at 09:02:53.
  The actual domain character counter returns **1199**, versus frozen minimum
  **1200**, target 1800–2600, maximum 4000. Audit stayed pending; no image stage.
- Its frozen identity is `official-account-rules-v4-reader-copy`. The article
  became `review_required`, and the weekly build translated it into misleading
  `provider_terminal`, `retryable=False`. Only one of three allowed node attempts
  was used; this was not an observed provider outage.
- Industry-trend build reused ready article
  `75c5b5cb-c379-4a19-9e43-e6655ef50fc1` from September 10, titled
  `机器学习帮科学家造新材料，孩子学科学也该学“找规律”`, with five ready generated images.
  This is proven by the successful build checkpoint, not inferred from its short
  duration. It is not a missing third selection.
- Application-case article `faf7f290-fcd8-481d-88ce-f6c4c410acba`, titled
  `从真实工程难题到家庭科学对话：家长如何引导孩子学会解题`, completed at 09:11:36.
  Its 1609 characters produced only a target-length warning; audit, rendering,
  five Comfly `gpt-image-2` visuals and local draft creation all succeeded.
- Weekly run ended `terminal_failed` at 09:11:37. All downstream plan-media,
  render-handoff, validate-child, aggregate and finalize nodes remain pending.
  No automatic `wechat_mp_draft_jobs` were created today. This SQL result does
  not deny the separately journaled manual sample upload earlier today.

## Code explanation, verified against running image

`ProductionWeeklyDagHandlers._build_article` maps `review_required`, `failed` and
`result_unknown` to the same nonretryable provider-terminal error.
`derive_weekly_dag_run_status` marks the parent terminal if any node is terminal;
`PostgresOfficialAccountWeeklyDagRepository.claim_ready` excludes terminal parent
runs. Hence even the ready siblings' downstream work cannot advance. Automatic
weekly preparation remains complete-batch-dependent, not independently delivered
per completed article.

Running hashes match the inspected release worktree exactly:

- `application/services/official_account_weekly_production.py`:
  `25637035fcaf512e98107f691a25abf68e2fdd7df0fce57a4f7ccffd383804b1`.
- `infrastructure/db/official_account_weekly_dag.py`:
  `e071e32fea34e6aeeb39618a01a867bc182e7c46f27abf9da837bd0d622bb40b`.
- `domain/official_account_weekly_dag.py`:
  `6fae4a3e0ebccdc57f80afd82a0aa17b0ae519c282a92c236fc8cf609b9443b5`.
- `domain/official_account_local.py`:
  `8394d46e47e950a76dc4ffd05e0b927769055f11f30eca9c7b0cdb6318550c2f`.

Current effective weekly-worker settings select relaxed
`official-account-rules-v5-editorial-advisory`, but the morning frozen input still
binds V4 and is not automatically rewritten/replayed by deployment. Service
health after the 13:11 source-format release is not historical article completion.
The separate 12:19 manual-sample run's ambiguous image result is not the cause of
the 09:00 batch failure.

## Proposed follow-up, not executed

Recover the exact batch with explicit authority, preserving immutable historical
receipts and checking any existing draft acknowledgements before writing. Reuse
successful text/images. Separately fix accurate failure classification and sibling
progress/per-article handoff so a nonfatal editorial issue cannot block ready
siblings. Do not reset ambiguous image or draft outcomes as an incidental repair.
