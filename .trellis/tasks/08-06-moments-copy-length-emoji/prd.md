# Enforce Moments copy length and emoji rules

## Goal

Make each generated WeChat Moments body readable to parents, useful for the daily topic, and
consistent with the requested publishing format. The requested body length and emoji range are
quality targets, not blockers for the material-package or delivery path.

## Background and confirmed facts

- The generated `MaterialDraft.copywriting` currently contains the complete Moments body followed by
  a separate trailing hashtag line. The schema and hashtag helpers live in
  `backend/app/schemas/copy_generation.py:10-67`.
- Deterministic validation currently checks the whole copy with an 80-800 character bound and
  validates trailing hashtags in `backend/app/domain/copy_generation.py:308-360`; it does not count
  Chinese characters or enforce an emoji count.
- Generator and auditor prompts already require parent-readable Chinese, learning value, Sai
  Xiansheng brand value, and fixed hashtags in `backend/app/application/services/copy_generation.py:526-610`.
- The executor already sends typed validation/audit issues to one bounded repair attempt and then
  finishes `review_required` when the repaired draft still fails, in
  `backend/app/application/services/copy_generation.py:250-326`.
- Copy version identifiers are persisted with the run bundle and configured in
  `backend/app/core/config.py:138-147`; a rule change must receive new versions for traceability.

## Requirements

### R1. Chinese-character length

For a newly generated draft, the copy body excluding the final hashtag line targets 300-500 Chinese
characters inclusive. Count only CJK unified ideographs. Whitespace, punctuation, digits, Latin
letters, and emoji do not contribute to this count. The hashtag line is validated separately and
never contributes to the body count. A count outside this range records a `copy_length` warning and
must not block the draft.

### R2. Emoji range

The copy body targets 2-5 natural emoji. Emoji are counted independently from Chinese characters;
variation selectors, skin-tone modifiers, and joiner components must not inflate the count of one
displayed emoji sequence. A count outside this range records a `copy_emoji_count` warning and must
not block the draft.

### R3. Existing copy format

Keep the existing format contract: the final non-empty line contains 2-3 whitespace-separated
hashtags, the first is always `#赛先生科学`, and no hashtag-like token appears earlier in the copy.

### R4. Prompt and repair alignment

The generator and auditor prompts must state the exact counting rules, ranges, and advisory behavior.
The auditor must not reject or trigger repair solely because of length or emoji-count issues. Existing
bounded repair remains available only for hard deterministic or audit errors; no second repair path
may be introduced.

### R5. Versioning and compatibility

Bump the copy pipeline, generator prompt, auditor prompt, strict rule, and active preview-policy
versions. Do not add a database migration or rewrite existing persisted drafts. The draft schema
remains structurally compatible.

### R6. Test coverage

Cover boundary counts, punctuation/emoji/tag exclusion, common emoji sequences, hashtag regression,
prompt instructions, advisory continuation through audit, and the existing single-repair terminal
state for hard errors.

## Acceptance Criteria

- [x] A draft with 299 or 501 body Chinese characters receives a `copy_length` warning; 300 and 500
  do not receive that issue when all other rules pass.
- [x] Punctuation, whitespace, digits, Latin letters, emoji, and the valid trailing hashtag line do
  not change the Chinese-character count.
- [x] A body with 0 or 1 emoji, or more than 5 emoji, receives a `copy_emoji_count` warning; 2-5
  do not receive that issue.
- [x] Valid output preserves the required hashtag line and a body in the requested range, and the
  prompts explicitly describe the same contract.
- [x] A length/emoji warning still reaches audit and can become accepted without regeneration; an
  auditor-provided length/emoji error is normalized to a warning as well.
- [x] A hard deterministic or audit failure still has at most one repair and then becomes
  `review_required` when that repair cannot make it acceptable.
- [x] Targeted tests, Ruff, mypy, and the repository backend quality command pass without invoking
  a real Enterprise WeChat delivery.

## Out of scope

- News acquisition, Ministry of Education topic ranking, brand retrieval/chunking, image generation,
  frontend presentation, or Enterprise WeChat transport changes.
- Automatic publishing to any social platform.
- Changing the lengths or emoji policy for `parent_takeaway`, `interaction`, `source_note`, or
  `image_prompt`.

## Risks and deferred items

- Emoji are Unicode sequences rather than single code points. The implementation will use a bounded
  standard-library detector with explicit tests for the emoji forms used by the generator; adding a
  third-party grapheme library is deferred unless future brand requirements need broader coverage.
- Existing persisted artifacts remain unchanged. Only drafts generated or revalidated after this
  version is deployed use the new rule.

## Open questions

None. The product boundaries and failure behavior are resolved by the current request and existing
copy-generation contracts.
