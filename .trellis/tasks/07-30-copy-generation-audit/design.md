# Design: Evidence-Bound Copy Generation and Audit

## Boundary

Transform one locked topic plus separately retrieved evidence and brand context into one immutable
structured Moments draft. Deterministic validation precedes a typed brand/risk audit; at most one
repair is allowed. This task does not call an image provider or build the final product page.

## Workflow

```text
locked topic/version
  -> retrieve evidence context + brand context separately
  -> generate structured draft/claims
  -> validate schema and bindings
  -> deterministic content/image/no-publish rules
  -> typed LLM audit
       accepted -> accepted draft
       rejected + repair available -> one repaired draft -> both gates
       rejected/exhausted -> reviewable failure
```

## Ports and Schemas

- Add application-owned `MaterialDraftGenerator` and `MaterialDraftAuditor` ports; deterministic
  fakes are the default automated-test providers.
- Strict schemas contain copywriting, parent takeaway, interaction, source note, image prompt,
  typed claims, validation issues, audit verdict/issues, and safe usage metadata.
- Existing Zhipu transport/bounds/retry/redaction patterns are reused, while generation/audit prompt
  templates and response schemas have independent versions/fingerprints.

## Binding and Authority

- `external_fact` requires governance evidence IDs and persists relational source/passage/
  occurrence provenance.
- `brand_statement` may bind active supplied brand chunk IDs; brand evidence cannot replace factual
  evidence.
- `opinion` is explicitly non-factual and cannot smuggle a verifiable claim without evidence.
- The model can select only IDs included in its bounded input. The application verifies every ID.

## Persistence and Checkpointing

Use durable content run/job/attempt state and immutable draft versions. Persist claims, evidence/
brand bindings, validation results, audit attempts/issues, repair parentage, provider/model/prompt/
schema/rule versions, fingerprints, and safe token/latency counts. LangGraph checkpoint state keeps
IDs/status/issues only and resumes without repeating successful provider calls.

## Failure Policy

Transient provider/checkpoint/database errors receive bounded job retry. Invalid structured output
may receive the configured bounded correction inside a provider call, distinct from the one product
repair. Deterministic failure never reaches audit. Audit rejection is not an infrastructure retry.
Repair exhaustion remains visible with all artifacts/issues.

## Rollout

Deploy disabled, prove fake flow, run controlled negative cases, configure brand corpus and Zhipu,
then execute one live selected topic. Manually verify every factual and brand binding before
acceptance. Rollback disables generation/audit and preserves drafts/issues.
