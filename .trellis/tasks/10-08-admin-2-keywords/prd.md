# 关键词后台增删改（运营后台第 2 项）

Parent `10-08-admin-console`. Planned 10/14–10/19 (3 d).

## Today (all hard-coded regex/tuples)

- Relevance:
  - `domain/editorial_relevance.py`: about 17 `_*_PATTERNS`, rule version
    `science-tech-editorial-v3-broad`.
  - `domain/education_policy_signal.py`.
  - `domain/science_relevance.py` (`_SCIENCE_TERMS`, `moe-science-v1`).
  - `domain/title_relevance.py` (`ai-title-v1`).
- Priority: `ministry_education_priority.py`, `science_policy_priority.py`.
- Topic safety: `infrastructure/db/topic_selection.py` `_CONTROVERSY` / `_UNVERIFIED` /
  `_NEGATIVE_INCIDENT` / `_PRIVACY_SAFETY` / `_PROHIBITED_MARKETING_TERMS`.
- Copy rules: `domain/copy_generation.py` `_BANNED_MARKETING`, `_ANXIETY` and others.
- Results store versions: `relevance_rule_version` (source versions, evidence candidates, article
  occurrences), `content_scoring_version`, copy `rule_version`.

## Scope (first cut; the hard-coded lists stay as the base)

- Three operator lists, each a versioned set (`keyword_sets` + `keyword_set_versions`, immutable
  versions, one active):
  - **关注词**: a match adds a topic-selection bonus.
  - **屏蔽词**: a match in the title or lead excludes the event from selection.
  - **文案禁用词**: added to the copy rule check as an error.
- Activating a version gives it a new version string (e.g. `ops-kw-v3`). The selection and copy
  records store it next to their existing rule version.
- UI:
  - add, remove and edit words (with a note);
  - "试一下": paste a title and see which words match;
  - list the last 3 days' selections the new version would have changed (replay on stored scores,
    no model call);
  - show the version history.
- Validation:
  - plain words only, no regex for operators; max length;
  - a word that would block more than X% of the last week's events needs a second confirmation.

## Open

- Should blocked words also apply to acquisition (drop articles at fetch time), or only to
  selection? Default: selection only (reversible, and the evidence is kept).
