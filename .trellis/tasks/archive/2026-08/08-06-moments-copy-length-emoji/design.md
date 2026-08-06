# Technical design

## Boundaries

The domain validation layer remains the authority for the new copy contract. Pure text helpers will
live beside the existing hashtag helpers in `app.schemas.copy_generation`; the domain layer will use
them from `validate_material_draft`. Provider prompts are updated only to align model output with the
deterministic gate. The executor and persistence contracts remain unchanged.

## Data flow

1. The provider returns a typed `MaterialDraft`.
2. Validation splits the final hashtag candidate line from the body for counting. Hashtag syntax and
   placement are still checked independently using the existing rules.
3. The validator counts CJK ideographs in the body and emoji display sequences in the body.
4. It emits typed `copy_length` and `copy_emoji_count` warnings when the inclusive targets are not
   met.
5. The executor persists those warnings and continues to audit. The audit policy also normalizes
   either code to a warning, so the auditor cannot reject or regenerate a draft solely for either
   target.
6. Existing one-time repair remains for hard validation or audit errors. A repaired draft follows
   the same path; hard failure after repair remains reviewable and cannot proceed to delivery.

## Counting contract

- `copy_body` excludes a final non-empty line made up of hashtag-like tokens, including malformed
  candidates. This prevents tag text from satisfying the body-length rule while the existing
  hashtag validator reports the formatting error separately.
- `hanzi_count` counts only CJK Unified Ideographs in the common and Extension A ranges.
- `emoji_count` counts emoji base sequences from a bounded Unicode range table. Variation selectors,
  skin-tone modifiers, and zero-width-joiner continuation components are ignored as additional emoji;
  adjacent independent emoji count separately.
- The helper behavior is deterministic, dependency-free, and covered by direct boundary tests.

## Prompt and version changes

The generator prompt will state the 300-500 Chinese-character body target, the exclusion rules, the
2-5 emoji target, advisory continuation, and the separate hashtag line. The auditor prompt will
evaluate the same contract without treating either target as a rejection reason.
The configured pipeline, generator, auditor, strict rule, and active preview-policy identifiers will
move to the next versions; the draft and audit schema identifiers do not change because no JSON field
changes. The new preview policy keeps the existing preview-v2 warning allowlist; length and emoji
issues are warnings for both preview and strict rule versions.

## Compatibility and rollback

No migration is required because version identifiers are part of the existing durable version bundle
metadata. Existing records and images are not rewritten. Rollback is a configuration/code rollback
to the prior versions; new drafts created during the rolled-back window retain their recorded bundle
identity and can be reviewed through the existing run state.

## Operational safety

No real provider or Enterprise WeChat call is needed for unit verification. Existing provider identity,
SSRF, delivery, and audit gates remain untouched. The new issues contain counts and safe rule text,
not raw provider responses or secrets.
