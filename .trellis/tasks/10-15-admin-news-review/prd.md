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
