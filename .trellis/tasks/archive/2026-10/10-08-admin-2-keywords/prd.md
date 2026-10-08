# 关键词后台增删改（运营后台第 2 项）

Parent `10-08-admin-console`. Planned 10/14–10/19. Started on 10/8 when the owner said "好的，请你处理"
right after item 1.

## Today

- Every term list is a code constant:
  - relevance rules in `domain/editorial_relevance.py` and others;
  - topic-safety terms `_CONTROVERSY/_UNVERIFIED/_NEGATIVE_INCIDENT/_PRIVACY_SAFETY/_PROHIBITED_MARKETING_TERMS`
    in `infrastructure/db/topic_selection.py`;
  - copy rules `_BANNED_MARKETING` and the like in `domain/copy_generation.py`.
- Content-slot runs snapshot their scoring config (`config_snapshot`, fingerprint-checked when the
  decision is persisted). Replays of old runs must stay byte-identical.
- `slot_affinity` is capped at `maximum_affinity` (0.12) and has no effect on eligibility.
- `validate_material_draft(topic=LockedTopicContext, …)` is the shared deterministic copy gate.
  Copy generation, the repair agent's tools and human-pick review all use it. It checks
  `all_output`: the hook, claims, takeaway and the rest, but not the system-rendered headline.
- The exhibit maps unknown veto codes to `other_rule`, so a new veto code is safe there.

## Design

The built-in lists stay as they are. Operators add three lists on top, as one versioned set:

| List | Effect | Where |
|---|---|---|
| 关注词 | an ordering bonus of +0.08 when the title or summary contains one; never makes an ineligible item eligible | `select_slot_topics` (ordering value; recorded in the score explanation) |
| 屏蔽词 | veto `operator_blocked_term` when the title or summary contains one | `_veto_codes` |
| 文案禁用词 | copy error `operator_banned_term` when the generated text contains one | `validate_material_draft`, via `LockedTopicContext.operator_banned_terms` |

- **Storage**
  - `operator_keyword_versions` (migration 0054): immutable rows holding version, the three
    lists, note, author and time.
  - The newest row is the active set. "Restore version N" saves a new version with N's lists.
  - No rows means today's behaviour.
- **Snapshot per run**
  - `content_slot_runs.operator_keyword_version_id` is set once, when the run is created. It is
    not part of the run's identity comparison, so an edit never conflicts with a scheduler retry.
  - A human pick inherits it from its base run.
  - The candidate loader and the copy topic loader read the lists through it.
  - Runs with null keep today's behaviour, so replays stay identical.
- **Matching**: plain, case-insensitive substring match, with no regex.
  - Each term is 1–20 characters; at most 200 per list.
  - A term cannot be both 关注词 and 屏蔽词.
- **Impact check before saving** (`POST /admin/keywords/impact`)
  - Takes the last 7 days of content-slot candidates (title + summary of their event versions).
  - Shows how many each 屏蔽词 would veto, which selected items it would have blocked, and how many
    candidates the 关注词 match.
  - If the 屏蔽词 would veto more than 30 % of the candidates, saving needs `confirm_wide_block`.
- **API** (`require_admin`, write guard, audited with added/removed terms per list)
  - `GET /admin/keywords`: the current set and the history.
  - `GET /admin/keywords/versions/{n}`.
  - `POST /admin/keywords/impact`.
  - `POST /admin/keywords`: a new version.
- **UI 关键词**
  - Three editable lists (chips plus an input), each with a short explanation.
  - "试一下": paste a title or copy and see which terms hit (client-side, same rule).
  - Impact check before saving; history with "恢复这一版".

## Not in scope

- Editing the built-in rule lists or the relevance rules (code-reviewed, version-stamped).
- Telling the copy model about banned terms in its prompt. The validator plus the repair agent
  handle a hit. A prompt change would need a copy-prompt eval run.
- The legacy daily topic-selection path (not used by production slots).

## Acceptance

- Unit tests:
  - term normalisation and conflicts;
  - matching;
  - the block veto and the focus bonus in `select_slot_topics` (old candidates unchanged);
  - the copy validator error.
- Integration tests:
  - versions and restore;
  - the impact report;
  - the wide-block confirmation;
  - a slot run snapshots the active version and its candidates carry the matches;
  - a human pick inherits the version;
  - the copy topic context carries the banned terms;
  - audit;
  - an editor may use the section.
- Frontend tests; a browser smoke on a throwaway database; predeploy gate PASS.
