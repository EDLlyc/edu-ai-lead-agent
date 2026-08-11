# Repair Comfly Direct Image Responses

## Goal

Ensure an automatic material-package run preserves a successful Comfly image result when the
OpenAI-compatible generation endpoint returns a raster response directly, instead of misclassifying
it as `image_provider_rejected` and unnecessarily using the brand-catalog fallback.

## Background

- On 2026-08-11, six server image artifacts completed only through the brand-catalog fallback.
  Each had two attempts and `provider_rejection_retry_count=1`.
- The production Comfly model and credentials are available. A server diagnostic request to
  `/v1/images/generations` returned HTTP 200 after about 90 seconds with a non-JSON body.
- `OpenAICompatibleImageGenerator.generate` calls `_request_json` for the creation response.
  `_request_json` rejects every non-JSON response at
  `backend/app/infrastructure/ai/image_generation.py:579-602`.
- Existing tests cover JSON URL and Base64 response envelopes, but not a raster response returned
  directly by `/v1/images/generations`.

## Requirements

1. Accept a successful direct PNG, JPEG, or WebP response from the Comfly creation endpoint when
   its bytes and dimensions meet the existing generated-image contract.
2. Preserve existing JSON URL, JSON Base64, asynchronous task-polling, response-size, media-type,
   dimension, idempotency, and output-host safety behavior.
3. Do not treat arbitrary non-JSON HTTP 200 bodies as images. Unsupported media types, invalid
   raster signatures, invalid dimensions, and oversized direct outputs must retain typed failure
   behavior.
4. Retain no raw provider bodies, prompts, URLs, API keys, or private assets in logs or durable
   state. Add only bounded safe diagnostics (HTTP status and normalized content type/response
   category) when a true provider rejection is logged.
5. Keep the existing one neutralized retry and brand-catalog fallback for actual provider
   rejections. A valid direct image response must bypass both recovery actions.
6. Add deterministic local tests using `httpx.MockTransport`; no local test may call Comfly or
   create a material package in PostgreSQL.

## Out Of Scope

- Changing Comfly model, API key, reference-image selection, prompt policy, provider timeout, or
  enterprise-WeChat delivery behavior.
- Loosening image-output validation or storing raw provider diagnostics.
- Retrying or modifying the historical 2026-08-11 material packages.

## Acceptance Criteria

- [x] A mocked direct 1024x1024 PNG response from `/v1/images/generations` returns a successful
      `ImageGenerationResult` without polling or downloading a URL.
- [x] Direct JPEG/WebP handling follows the existing byte-signature and 1024x1024 validation rules.
- [x] A direct response with an unsupported content type, invalid raster signature, invalid
      dimensions, or an oversized body raises the established typed validation/rejection error and
      never becomes a false success.
- [x] Existing Comfly URL, Base64, polling, quota/authentication, and multi-reference tests stay
      green.
- [x] True rejections expose only safe HTTP status/content-type category metadata to the worker
      log; raw response content remains absent.
- [x] Focused image-generation tests, Ruff, strict mypy, and the backend quality gate pass locally.

## Decisions

- Direct raster compatibility is limited to the Comfly creation endpoint. Task-polling remains a
  JSON protocol unless provider evidence requires a separate extension.
- The existing fallback is retained as a last-resort resilience feature, not used to mask a valid
  model result.
- The server diagnostic established a non-JSON HTTP 200 response but did not retain its raw body or
  headers; implementation will test documented raster response forms locally without storing
  sensitive provider payloads.
