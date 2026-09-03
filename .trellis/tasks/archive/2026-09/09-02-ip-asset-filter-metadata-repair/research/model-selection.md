# Research: Recognition model selection

- Updated: 2026-09-03
- Scope: official Zhipu documentation and recorded safe local execution evidence

## Current decision

Use exact model `glm-5v-turbo` for the one-time 41-asset repair plan. It is the selected higher-tier
flagship multimodal model, accepts image input, and supports an explicit thinking toggle. Keep
thinking disabled, `do_sample=false`, strict unique-object JSON extraction plus Pydantic projection,
one request per image, local concurrency one, and the two-second default pacing.

The model's higher platform concurrency capacity is an account/model quota characteristic, not
permission for this local repair tool to burst. It does not change the approved execution budget or
the fail-closed batch circuit breaker.

## Official evidence

- Zhipu's current model overview identifies the GLM-5V family as its flagship multimodal line and
  lists the exact `GLM-5V-Turbo` model identity:
  https://docs.bigmodel.cn/cn/guide/start/model-overview
- The official model page documents exact API identifier `glm-5v-turbo`, image input, multimodal
  understanding, and the thinking switch:
  https://docs.bigmodel.cn/cn/guide/models/vlm/glm-5v-turbo
- The Chat Completions reference limits `response_format` to text models. `glm-5v-turbo` is a visual
  model, so the repair request must omit `response_format`, instruct one JSON object in the prompt,
  and validate it locally:
  https://docs.bigmodel.cn/api-reference/%E6%A8%A1%E5%9E%8B-api/%E5%AF%B9%E8%AF%9D%E8%A1%A5%E5%85%A8

## Preserved history and call budget

1. The first legacy canary used one call and failed closed. Its safe v1 artifact collapsed most
   provider errors, so it cannot distinguish authentication, rate limiting, request rejection,
   timeout/network, or server unavailability after the fact.
2. The corrected `glm-4.6v-flash` canary used one additional call with no `response_format`,
   thinking disabled, and deterministic sampling. It failed closed as `provider_rate_limited`;
   the exact account/quota/window cause remains unknown because response bodies were not retained.
3. The user then explicitly raised the lifetime cap from 42 to 43 and approved the higher-tier
   model. Immediately before the completed live phase, historical usage was 2 calls and 41 calls
   remained for one `glm-5v-turbo` canary plus the other 40 images only after that canary passed.

## Artifact and operational guard

- The new canary schema is `ip-asset-metadata-repair-canary-v2`, the new plan schema is
  `ip-asset-metadata-repair-plan-v2`, and the new result schema is
  `ip-asset-metadata-repair-result-v2`. All require exact `glm-5v-turbo` and use v2 fingerprint
  domains. A v1 `glm-4.6v-flash` canary, plan, or result is intentionally incompatible and cannot
  be reused, applied, or restored.
- Use a fresh private canary artifact and the v2 acknowledgement. Reuse the first item's result only
  when the returned model identity and strict local schema pass.
- A canary failure stops without fallback or hidden calls. A later shared rate-limit, timeout, or
  unavailable failure stops the remaining batch and writes only the strict diagnostic suffix.
- Preserve the transport's body-free categories: authentication, rate limit, request rejected,
  timeout, invalid output, and provider unavailable. The CLI reports `local_schema_valid` and
  `provider_json_mode_requested=false`; prompt instructions are not provider JSON mode.
- Provider pricing is not encoded in the repository. Report actual calls rather than inventing cost.

## Completed live evidence (2026-09-03)

The fresh `glm-5v-turbo` v2 canary succeeded with exact returned model identity and strict local
unique-JSON/Pydantic validation. Its item was reused, and the remaining 40 assets completed with
concurrency one, two-second pacing, no fallback and no retry multiplication. The phase used exactly
41 new calls, bringing the lifetime ledger to 43/43. The complete private plan passed fingerprint,
privacy and domain-distribution validation before a provider-free apply; an idempotent second apply
and non-metadata invariant check also passed. Restore readiness was verified without executing a
restore, and the out-of-scope 248-call retrieval evaluation was not run.
