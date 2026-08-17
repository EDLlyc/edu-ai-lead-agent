# Provider output contract evidence

## Production incident evidence

- The 2026-08-17 noon package stopped after a single `gpt-image-2` artifact entered
  `review_required` with `image_output_invalid` and safe reason
  `image_output_representation_invalid` at stage `provider_output`.
- No media type, dimensions, bytes, MinIO object, material delivery job, or WeCom attempt existed.
- The adapter observed a non-empty `b64_json` value that failed strict Base64 decoding. Raw response
  content was correctly not retained, so its exact syntax remains unknown.

## Current code boundary

- `OpenAICompatibleImageGenerator` explicitly requests `b64_json` but safely accepts URL, valid
  Base64, direct raster, and a documented task envelope.
- `MaterialPackageExecutor` has a durable one-shot provider-rejection recovery counter and a
  deterministic approved-catalog fallback. Invalid image representation currently bypasses both
  because `ImageOutputValidationError` is non-retryable.
- Direct WeCom mode accepts validated `awaiting_manual_use` catalog-fallback packages.

## Official provider documentation

- Current GPT-Image-2 examples explicitly use `response_format: "url"` and describe image URLs as
  the result representation:
  - https://docs.toapis.com/docs/cn/api-reference/images/gpt-image-2/generation
  - https://docs.toapis.com/docs/en/api-reference/images/gpt-image-2/generation

## Decision

Use URL as the requested representation, keep strict compatibility parsing, and compensate a
single representation-format failure through the existing durable output-recovery budget. A
second identical class of failure uses the already-reviewed catalog fallback. Do not decode
heuristically, persist provider content, or broaden recovery to security/integrity failures.
