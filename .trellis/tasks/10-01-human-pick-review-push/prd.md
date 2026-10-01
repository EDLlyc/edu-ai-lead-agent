# 人工加推：审核、修改文案后再推送

## Source (2026-09-30)

Owner: “人工审核，要加上可以修改文案的，功能，还要加上推送的功能。” Decisions (AskUserQuestion):
only human picks (人工加推), not the daily slots; edited copy is re-checked by the deterministic rules
(no model call) and blocked on an error; push goes straight to the formal group after two
confirmations; the UI is the exhibit's PIN review mode; the operator edits only the hook sentence
and the hashtags (heading, headline, source and link stay system-owned); a held pick can be pushed
until 22:30 business time on its day, after that it lapses.

## Production change (this branch, from mainline 3a79c22)

- `content_slot_human_picks`: a pick's run now expires at 22:30 business time (was pick + 3 h);
  picks close at 22:30 (was 23:00). No migration.
- `wecom_delivery`: a human-pick package is never sent automatically. The auto-delivery query
  skips `trigger='human'` packages unless the package is approved, and a formal enqueue for an
  unapproved human pick raises `human pick is held for the operator's review`. Daily slots
  (`trigger` scheduled/manual) are untouched.
- `domain/human_pick_review.revise_headline_hook_copy`: re-renders the operator's hook/tags with
  `render_headline_hook_copy` and runs `validate_material_draft` with the draft's rule version;
  operator-specific errors for an empty/too-long hook, a hook the template would drop, malformed tags.
- `infrastructure/db/human_pick_review`: load the held pick; save a passing edit on the accepted
  draft, its deterministic issues and validation result, and the package copy/validation snapshots
  together (the long image requires draft and package to agree); every edit and the previous text
  are kept in `copy_snapshot.operator_edits` with `llm_audit_repeated: false`.
- API (production loopback): `POST /api/v1/content-slot-human-picks/{run_id}/copy`
  (`hook`, `hashtags`, `reviewer`, `dry_run`) and `POST /api/v1/content-slot-human-picks/{run_id}/push`
  (`reviewer`, `note`). Push approves the package (`material_reviews`) and enqueues the formal
  delivery in the pick's own lane; the long image follows as for any delivered package.
  Errors (409 + code): `human_pick_not_ready`, `human_pick_already_pushed`, `human_pick_rejected`,
  `human_pick_expired`, `human_pick_copy_invalid`.
- Refactor: `load_brand_context_by_chunk_ids` extracted in `infrastructure/db/copy_generation.py`
  (same behaviour) so the review can rebuild the brand context without a job lease.

## Verification

- Unit: `tests/unit/test_human_pick_review.py` (10) with the real validator.
- Integration: `tests/integration/test_human_pick_review.py` (hold, push, second push, deadline,
  rule error, consistent edit + history); `test_content_slot_human_picks.py` updated for 22:30.
  Delivery / long image / copy / content-slot suites: 40 passed.
- `make predeploy-check`: PASS (unit/contract no new failure).
- Not verifiable here: a real push to the formal group (owner checks after deploy).

## Exhibit (feature/daily-wecom-infographic-default-off)

PIN-gated adapter routes forward to the two production endpoints through the existing 18000
tunnel; the news-pool human-pick panel gets a "待审核" stage, an editor for the hook/tags with a
check, save, and a two-step push confirmation.

## Rollout

Owner's word in the deploy window; Python-only overlay FROM the running image; then the exhibit
connector restart (its overlays must include the new adapter files). Human picks in production:
none ever made, so nothing is stranded.
