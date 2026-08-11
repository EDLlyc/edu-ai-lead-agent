# Design: Comfly Direct Raster Responses

## Boundary

The change is confined to the Comfly/OpenAI-compatible image adapter and its material-package
failure logging boundary. Database schemas, public API schemas, image selection, prompt generation,
and delivery contracts do not change.

## Response Flow

1. The adapter makes `POST /v1/images/generations` with the current idempotency key and bounded
   payload.
2. The low-level request helper returns the bounded body plus safe transport metadata needed only
   for interpretation: HTTP status and normalized `Content-Type`.
3. When the successful creation response declares an allowed raster media type, the adapter
   validates its byte limit, signature, and 1024x1024 dimensions through the same image-byte
   validation path used for Base64 and downloaded output, then returns `ImageGenerationResult`.
4. Otherwise, the adapter continues to parse the current JSON envelope. URL, Base64, task polling,
   quota/authentication, and retry behavior remain unchanged.
5. A non-JSON non-raster response remains a typed provider rejection. Invalid direct raster content
   remains a typed image-output validation failure.
6. The material-package executor only schedules neutralized retry/catalog fallback when the adapter
   raises a real `ImageProviderRejectedError`; a successful direct result is persisted normally.

## Safe Diagnostics

`ImageProviderRejectedError` may carry only an optional HTTP status and normalized response kind
(`json`, `raster`, `other`, or absent). The worker adds populated values to its existing structured
rejection event. It must not log response text, headers other than normalized content type, prompts,
URLs, provider task bodies, or credentials.

## Compatibility and Rollback

- Existing JSON behavior remains the default path, so provider responses already supported by the
  adapter are unchanged.
- The direct raster branch accepts only `image/png`, `image/jpeg`, and `image/webp`; generic or
  missing content types keep the JSON path and cannot turn arbitrary bytes into a success.
- Rollback is a single application-code revert. No migration, data cleanup, or credential change is
  required.

## Risks

- A provider may return a raster body with a misleading content type. The branch validates raster
  signature and dimensions before returning success.
- The live provider response was not retained by design. Mocked transport tests cover the observed
  protocol shape, while a post-deploy isolated smoke test remains an operational follow-up.
