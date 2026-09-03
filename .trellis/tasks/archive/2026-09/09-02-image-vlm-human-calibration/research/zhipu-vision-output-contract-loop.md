# Bug Analysis: GLM-5V-Turbo capability output rejected

## 1. Root Cause Category

- **Primary category: B — Cross-layer contract.** The shared OpenAI-compatible transport assumed
  that every model accepting `/chat/completions` also accepted text-model structured-output
  controls. Zhipu documents `response_format` as text-model-only, while GLM-5V-Turbo is a visual
  model.
- **Secondary category: D — Test coverage gap.** Mock HTTP tests validated the generic payload but
  did not assert the exact documented visual-model request dialect or run a real capability gate.
- **Secondary category: E — Implicit assumption.** A successful HTTP envelope was treated as enough
  diagnostic resolution even though model-generated vote framing, schema, invariants, and the
  request-scoped issue allowlist are separate failure stages.

## 2. Why the first fix was insufficient

1. The initial generic request sent `response_format=json_object`. The first live capability call
   ended as generic `invalid_provider_output`, so the remaining 119 calls correctly stopped.
2. The v2 request removed the unsupported field, disabled thinking and sampling, and split provider
   envelope failure from judge-content failure. The second capability call proved the provider
   envelope, exact model identity, token usage, and cost were valid, but the generated vote still
   failed the closed judge-content contract.
3. The remaining failure cannot be safely attributed to Markdown framing, schema mismatch,
   arm-verdict invariants, or an out-of-allowlist issue code because v2 still collapses those stages.
   Repeated prompt guessing would spend calls without producing discriminating evidence.

## 3. Bayesian diagnosis before another call

| Hypothesis | Prior | Evidence needed |
|---|---:|---|
| Exact JSON is wrapped in whitespace or one Markdown fence | 45% | Safe framing-stage error code |
| JSON object has missing/extra/wrongly typed arm-verdict fields | 40% | Safe schema-stage error code |
| Issue code is outside the request-scoped allowlist | 10% | Safe allowlist-stage error code |
| Content was truncated despite a normal provider envelope | 5% | Finish/length stage without raw content |

The second call's known usage (`5408` input, `85` output), valid envelope, exact identity, and
`judge_content_invalid` terminal strongly reduce the probability of endpoint, auth, image transport,
or provider-envelope failure. They do not distinguish the four content hypotheses.

## 4. Prevention mechanisms

| Priority | Mechanism | Specific action | Status |
|---|---|---|---|
| P0 | Architecture | Keep a closed `zhipu-vision-v1` request profile; never accept arbitrary provider options | Done |
| P0 | Runtime evidence | Split provider envelope and judge-content failures without storing raw prompts/responses | Done |
| P0 | Runtime evidence | Split judge framing, schema/invariant, and allowlist failures into safe closed codes | Done |
| P1 | Parsing | Normalize only outer whitespace or one standalone lowercase `json` fence for `zhipu-vision-v1`, then apply the same strict schema | Done |
| P1 | Tests | Assert exact Zhipu visual payload and every safe parse-stage classification | Done |
| P1 | Integration | Keep the first real four-image request as a counted capability gate that stops the plan | Done |

## 5. Systematic expansion

- Production single-image auditing inherited the same text-model payload after its default changed
  to GLM-5V-Turbo; independent review found and fixed that propagation failure.
- OCR and text Reviewer routes legitimately retain JSON structured-output profiles and must not be
  changed by the visual-model workaround.
- Future multimodal providers require an explicit request dialect and a real counted capability
  gate before bulk execution. Endpoint compatibility alone is not model capability evidence.
- Raw provider bodies remain private transient data and are not needed for useful diagnosis when
  failure stages are represented by a closed, non-content-bearing taxonomy.

## 6. Knowledge capture

- Update `.trellis/spec/backend/image-quality-evaluation.md` with visual dialect selection,
  content-stage diagnostics, and the rule against repeated blind probes.
- Add exact tests for framing normalization and for rejecting prose, multiple objects, unknown
  fields, duplicate keys, and disallowed issue codes.
- Sync any shared Trellis template only if this repository has a corresponding managed template.
