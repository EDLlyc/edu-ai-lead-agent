# Admin console: news review and human pick

## Goal
Move the exhibit's operator-only "news review" (label AI's picks) and "人工加推" (human pick) into the
authenticated admin console (`ops.xiaosaiai.com/admin/`), so operators use it from the public site with their
own account instead of a local adapter + operator PIN + SSH tunnel.

## Decisions (owner, 2026-10-15)
- Scope: review labelling AND human pick (push to the formal WeCom group). Owner chose "with_pick".
- Who: owner and editor roles both.
- Storage: reviews move from a local SQLite file to a new Postgres table (additive migration).

## Current state (found 2026-10-15)
- The review/label code is NOT on `mainline` (production line). It lives in the root working tree / feature
  branches (`feat/human-pick-*`): `visitor_display_review.py`, `visitor_display_human_pick.py`,
  `visitor_review_store.py` (SQLite), `news-label/NewsLabelApp.tsx`, `visitor-display/*`.
  The production side of human pick (service `human_pick_review.py`, `content_slots.py` human-pick routes,
  tables) is already on `mainline`.
- The adapter forwards human picks to the production API over a loopback tunnel; "reviewer" is recorded as a
  fixed string (`展示台审核`).

## Plan (phased; each phase deployable on its own)
1. Bring the needed code from the feature work onto `mainline` cleanly (no unrelated WIP), decide the list of
   files with the owner.
2. Review labelling: Postgres table `news_reviews` (+ Alembic migration, backup first), admin API
   (`/api/v1/admin/news-reviews`, session auth, owner+editor, reviewer = admin username), admin page
   (blind mode, filters, agreement stats), tests, OpenAPI + generated types.
3. Human pick: admin API wrapping the existing production human-pick service (create, edit copy, push, reject),
   reviewer = admin username, same refusal messages. A push sends to the formal WeCom group, so it is the last
   phase and needs its own go-ahead and a dry run first.
4. Deploy: overlay image + migration with backup/rollback (pattern in `10-15-public-hosting`), swap console.

## Open questions
- Which candidate pool does the admin page read: reuse `VisitorDisplayService` news pool (needs the
  exhibit's read-only projection inside the admin API) or a smaller query? Default: reuse.
- Keep the PIN-based exhibit review for local use, or remove it once the admin page works?

## Progress (2026-10-15 evening)
- Done, committed on mainline, NOT deployed: step 1 (visitor-display backend on mainline; exhibit article tests left out because
  mainline lacks `OfficialAccountArticleVersionModel.revision_no`), phase 2 (table `news_reviews` + migration
  `20261015_0062`, `PostgresNewsReviewStore`, `/api/v1/admin/news-reviews` GET/POST for owner+editor with the account as
  reviewer, admin page 新闻审核, tests, OpenAPI + types).
- Deploy needs: backup, run migration 0062 on production (check the production alembic head first), API overlay on the
  running image with the changed files, console swap. Not done yet.
- Phase 3 (human pick from the console) not started; it sends to the formal WeCom group and needs its own go-ahead.
- Known unrelated failures on mainline: `test_migrations.py` head assertion (expects 0059), a Chinese-family downgrade guard.

## Progress (2026-10-15 night): phase 3 built, NOT deployed
- Production already has everything the human pick needs (service, held-pick review, routes, delivery hold); the
  production files `human_pick_review.py`, `db/human_pick_review.py`, `wecom_delivery.py`, `content_slots.py` are
  byte-identical to mainline, so the deploy is the API overlay plus the console, with no migration.
- Admin API (owner + editor, account = reviewer, called in-process, no tunnel and no PIN):
  `POST /api/v1/admin/human-picks` (make copy and picture, held), `GET .../{key}/review`, `POST .../{key}/copy`
  (`dry_run` checks, otherwise saves), `POST .../{key}/push` (the only call that reaches the formal group;
  production refuses a second push). The pool now reports `human_pick_enabled` and `human_pick_review_enabled`
  when content slot mode is on.
- Ported from the root tree's uncommitted work (not the whole WIP): the held-pick stage `awaiting_review`, the review
  loader `load_human_pick_review`, the headline/hook splitter and the new refusal codes.
- Console: in 新闻审核 each item the AI did not select gets 人工加推: 生成文案和配图, progress (auto refresh every
  20 s), then an editor for the hook and hashtags (check / save), and a push that needs two confirmations.
- Tests: integration `test_admin_human_picks.py` (auth, write guard, review, check, save, push, second push refused,
  reviewer = account, disabled slot mode), frontend `HumanPick.test.tsx`; 239 admin frontend tests pass.
- Deployed 2026-10-16 (see runbook). Still to do: first real push by the owner.
- Open: keep or remove the PIN-based exhibit review.

