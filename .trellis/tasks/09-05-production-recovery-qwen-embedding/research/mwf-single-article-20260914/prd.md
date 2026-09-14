# M/W/F single-article Official Account delivery

## Goal

Replace the prospective weekly three-article batch with one independently selected,
generated and delivered article on Monday, Wednesday and Friday at 10:00
Asia/Shanghai. Explain current topic selection honestly. Delivery means unpublished
WeChat draft creation, not subscriber mass-send or publication.

## Background

- The September 14 09:00 batch failed because its frozen V4 validator rejected
  1199 characters against a 1200 minimum; parent-terminal coupling then blocked
  two ready siblings. See `../monday-morning-diagnosis-20260914.md`.
- Live release is application commit 4782064, schema 20260914_0046, with readable
  source presentation and unchanged permanent banners. Root main is unrelated
  mixed WIP; the release-hardening worktree holds the production-shaped code.
- The existing scheduler, input tuple, DAG and automatic draft envelope all assume
  three roles. Merely replacing the cron string would still generate batches.
- Existing independent-delivery work on main is prospective and not deployed.
  Its migration lineage differs; no wholesale merge or activation is implied.

## Requirements

1. Exactly one planned edition per local M/W/F date; zero new weekly three-role
   admissions after activation. Tuesday/Thursday/weekend do not trigger editions.
2. Approved time semantics: prepare ahead of time, begin draft
   delivery at 10:00, not begin all model work at 10:00. Provider delay is visible
   and retried within bounds; exact wall-clock completion is not guaranteed.
3. Each date selects one eligible event from the current governed material pool.
   Preserve source/evidence checks, stored scoring and preference signals; remove
   the requirement to fill all three role categories. Do not add new live-web
   acquisition or silently change score weights.
4. Prevent reuse of an already acknowledged Official Account article/event across
   the new route and known old/manual routes. Lack of three candidates must not
   block one valid candidate. With no eligible source, report no-topic, not invented news.
5. Persist single-edition identity, progress, retry budget and acknowledgement.
   Reuse successful text/images; a failed date must not block a future date.
   Definite transient failures may retry with safe error feedback; ambiguous
   model/draft effects must not be blindly replayed.
6. Preserve author 程岳, Xiaosai-only Chinese-family/school-age visual requirements,
   current relay model, relaxed editorial rule, caption policy, source formatting,
   top introduction banner and bottom marketing banner.
7. Replace the server's active automatic mode only after scoped tests and reviewed
   activation. Preserve history; no incidental replay of today's failed batch,
   deletion of existing drafts, or change to other news-delivery schedules.

## Acceptance

- Boundary tests: Shanghai date, each weekday, before/at/after 10:00, restart,
  concurrency, duplicate ticks and bounded catch-up all preserve one date/one draft.
- A single eligible event completes without creating a three-role batch.
- Mocked end-to-end selection -> generation -> prepared article -> draft receipt
  proves one child, correct author/banners/native source link and no publish calls.
- Failed/retrying dates do not block later dates; no duplicate effects on restart
  or acknowledgement loss; completed text/images are reused.
- Old manifests/receipts remain readable and byte-stable. No unreviewed migration
  branch merge or unscoped release image rebuild replacing live hotfixes.
- Live activation evidence distinguishes healthy services, schedule configuration,
  and actual future draft acknowledgement; no claim of a draft merely from a timer.

## Out of scope

Automatic publishing/mass-send; historical batch recovery; replacement of the news
acquisition pipeline, providers or scoring weights; unrelated WeCom changes;
deleting stored tasks/drafts; broad R32/main-worktree rollout.

## Final-review status

The user approved this proposal with “好的，请你处理”, including the explicit
interpretation of 10:00 as draft-delivery time with earlier preparation.
Implementation and checked prospective server activation are now authorized.
The first prospective scheduled
date after today's already-passed target would be Wednesday, September 16; do not
backfill Monday merely by activating the replacement scheduler.
