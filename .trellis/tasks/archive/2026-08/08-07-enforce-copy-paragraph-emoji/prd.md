# Enforce copy paragraph and emoji formatting

## Goal

Make the daily Moments copy readable in the parent-facing format the user provided: several
natural paragraphs separated by one newline, 2-5 inline emoji in the body, and a final hashtag
line. These are presentation-quality requirements. They must receive one automatic repair attempt
when missing, but must never block an otherwise usable copy, material package, or Enterprise WeChat
delivery.

## Background and confirmed facts

- `MaterialDraft.copywriting` stores the complete body and trailing hashtag line as one string in
  `backend/app/schemas/copy_generation.py`.
- The generator prompt currently describes 2-5 emoji as a target and explicitly allows a missing
  target; it does not specify paragraph structure in
  `backend/app/application/services/copy_generation.py:526-574`.
- Deterministic validation counts body Hanzi and emoji, but the existing `CopyGenerationExecutor`
  only starts the workflow repair when validation or audit has a blocking error. A warning-only
  draft is audited and accepted without repair in
  `backend/app/application/services/copy_generation.py:269-326`.
- The existing repair path is version 2 of the same durable copy run and is already bounded to one
  workflow repair. The provider's JSON-schema correction loop is a separate bounded mechanism.
- Enterprise WeChat receives the copy as Markdown and preserves newlines already present in the
  content; no database migration or webhook payload change is required.
- The user-provided reference uses multiple paragraphs separated by a single newline, no blank
  lines between paragraphs, 2-5 emoji in the body, and 2-3 trailing hashtags with
  `#赛先生科学` first.

## Requirements

### R1. Explicit generation and repair contract

The generator prompt and the same base prompt used for repair must explicitly require:

- the body to be split into at least three natural paragraphs;
- exactly one newline between paragraphs and no empty line between them;
- 2-5 natural emoji in the body, not in the hashtag line and not used as filler;
- the final non-empty line to contain 2-3 space-separated hashtags, with `#赛先生科学` first.

The prompt must also state that paragraph and emoji requirements are quality-format targets: a
missing target is repaired once, but the final draft remains usable if the target is still missed.

### R2. Deterministic advisory validation

Add `copy_paragraph_format` as a deterministic warning when the body does not have at least three
non-empty paragraph lines separated by single newlines, or contains blank lines between them.
Keep `copy_emoji_count` as a warning outside the inclusive 2-5 range. The body excludes the final
hashtag line from both checks. Neither issue may be emitted as an error under preview or strict
copy policies.

Existing evidence, safety, unsupported-claim, hashtag, and provider-integrity errors remain
blocking and retain their current behavior.

### R3. One repair attempt for format warnings

When the initial draft is otherwise eligible but has `copy_paragraph_format`, `copy_emoji_count`,
or an equivalent auditor issue, the executor must perform the existing single workflow repair
attempt. A `copy_length` warning remains advisory and does not trigger this additional repair.
The repair prompt receives bounded issue metadata and the previous draft as today.

The executor must not create a second repair path. A repaired draft with remaining format warnings
is accepted after audit. If the one repair provider call cannot produce a valid replacement and the
initial draft has no blocking validation/audit issue, the durable initial draft is accepted with
the format warning and `repair_count=1`; provider failures unrelated to this advisory-only case
retain their existing retry/review behavior.

### R4. Downstream continuity

An accepted warning-only copy must continue through material-package assembly and the configured
Enterprise WeChat group-webhook dispatcher. Existing idempotency, image safety, source evidence,
brand bindings, and historical-delivery scoping remain unchanged.

### R5. Versioning and compatibility

Bump the copy pipeline, generator prompt, auditor prompt, deterministic rule, and active preview
policy identifiers so new behavior is traceable. Keep the draft and audit JSON schemas compatible;
do not add a migration or rewrite existing drafts.

### R6. Tests and verification

Add focused tests for paragraph extraction/validation, single-newline and blank-line cases, emoji
boundaries, prompt wording, format-warning repair, acceptance after an imperfect repair, and
acceptance when an advisory-only repair provider response is invalid. Preserve tests proving hard
errors still have at most one repair and remain reviewable after a failed repair. Run the backend
quality gate and deployment configuration checks without making a real WeCom call.

## Acceptance Criteria

- [ ] Generator and repair prompts contain explicit paragraph, single-newline, emoji, and
  warning-only instructions.
- [ ] A body with fewer than three paragraphs or any blank line receives only
  `copy_paragraph_format` with severity `warning`.
- [ ] A body with 0-1 or more than 5 emoji receives only `copy_emoji_count` with severity
  `warning`; 2-5 receives no emoji-count issue.
- [ ] The hashtag line remains excluded from body checks and keeps its existing format contract.
- [ ] A warning-only initial draft causes exactly one workflow repair attempt before acceptance.
- [ ] A repaired draft that still has paragraph/emoji warnings is accepted and can proceed to a
  material package and delivery job.
- [ ] An advisory-only repair provider/schema failure accepts the original usable draft rather than
  changing the run to `review_required`.
- [ ] Hard validation or audit errors still use the existing one-repair limit and remain
  `review_required` when unresolved.
- [ ] Existing provider identity, evidence, image, idempotency, and WeCom safety tests remain green.
- [ ] `make backend-check`, `make doctor`, `docker compose config --quiet`, and `git diff --check`
  pass; no real message is sent during verification.

## Out of scope

- Changing news acquisition, Ministry of Education policy ranking, brand retrieval, image prompts,
  image generation, or frontend rendering.
- Adding a new database table or migration.
- Making copy length a blocker; the existing 300-500 Hanzi target remains advisory.
- Automatically publishing to a social platform.

## Risks and deferred items

- A model can still choose awkward paragraph boundaries even after the prompt and one repair. The
  deterministic gate records the warning and preserves delivery rather than attempting endless
  rewrites.
- Existing persisted drafts remain unchanged; only new or re-run drafts use the new prompt/rule
  versions.

## Open questions

None. The user's reference resolves the only product ambiguity: paragraphs use one newline, not a
blank line.
