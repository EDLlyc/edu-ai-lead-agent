# Evidence-Bound Copy Generation and Audit

## Goal

Generate one structured parent-facing WeChat Moments draft from a locked topic, factual evidence,
and active brand context; validate and audit it, then allow at most one automatic repair.

## Parent and Dependency

- Parent: `07-30-content-production-mvp`.
- Requires a locked topic/evidence set from `07-30-daily-topic-selection` and active brand context
  from `07-30-brand-knowledge-rag`.
- Produces an accepted draft/image prompt or reviewable failure for `07-30-material-package-ui`.

## Requirements

- Return typed copywriting, parent takeaway, interaction, source note, image prompt, and claims.
- Classify claims as external fact, brand statement, or opinion.
- Bind every external fact to eligible stored evidence and relevant brand statements to supplied
  brand chunks; validate IDs deterministically.
- Delimit untrusted evidence and brand text and version/hash-identify prompts, schemas, models, and
  rules.
- Run deterministic schema/length/evidence/date/source/privacy/banned-language/marketing/image/
  no-publish checks before LLM audit.
- Run typed brand/risk audit for unsupported implication, exaggeration, anxiety, parent value,
  brand fit, and image risk without granting it factual authority.
- Permit exactly one versioned automatic repair and repeat both gates.
- Persist drafts/claims/bindings/validation/audit/issues/usage/attempt lineage and safe failures.

## Acceptance Criteria

- [ ] A controlled valid topic produces a schema-valid Chinese draft with complete bindings.
- [ ] An unbound or hallucinated factual claim fails before audit.
- [ ] The auditor cannot add evidence, override deterministic failure, or expose raw model material.
- [ ] One repair can resolve typed issues; a second failure remains durable and reviewable.
- [ ] Prompt injection, exaggeration, anxiety, privacy, unsafe image, provider, restart, replay, and
      concurrency cases have deterministic coverage.
- [ ] One bounded live Zhipu draft/audit is manually checked against every evidence/brand binding.

## External Input

Approved brand documents plus representative acceptable posts/length rules when not already
specified in the brand corpus.

## Out of Scope

- Multiple drafts/variants, free-form chat editing, more than one repair, unbound creative facts,
  image execution, public publishing, or social-platform integration.
