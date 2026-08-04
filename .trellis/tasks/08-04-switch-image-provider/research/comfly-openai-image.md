# Comfly OpenAI-Compatible Image API Research

Date: 2026-08-04

## Sources and confirmed facts

- Documentation site: `https://gpt-best.apifox.cn/`.
- The guide says to replace the OpenAI API origin with the Base URL obtained from the service
  management console and to send the key as `Authorization: Bearer <key>`.
- The documented image endpoint is `POST /v1/images/generations`.
- The documented JSON request fields are `model`, `prompt`, `size`, `aspect_ratio`, and optional
  `image` array items. The page notes that reference images are model-dependent and may be supplied
  as URLs in the prompt for models such as Flux Kontext.
- The documented response schema is empty, so the adapter must not assume that the page is a
  complete response contract. It must accept only bounded, explicitly recognized response shapes
  (`data[].url`, `data[].b64_json`, and the documented async task shape if returned) and reject the
  rest without logging the body.

## Live network evidence

- User-confirmed API origin: `https://ai.comfly.org`.
- A no-credential `GET https://ai.comfly.org/v1/models` returned HTTP 401 with a bounded JSON error
  and OneAPI-style response headers. This confirms that the origin is an API gateway, not the
  Apifox documentation page.
- No credential was sent during the documentation or unauthenticated endpoint probes recorded
  here.

## Implementation consequences

- Keep the old ToAPIs adapter available for rollback, but add a provider-neutral OpenAI-compatible
  adapter with `provider="comfly"`.
- Use `https://ai.comfly.org` as the local active Base URL and retain `gpt-image-2` as the model
  until an authenticated `/v1/models` check proves it unavailable.
- Use a bounded data URL in the `image` array for the approved local reference asset when the
  request limit permits; never publish a private MinIO URL or put a secret/reference body in logs.
- A live test must validate the actual response shape before enabling package generation. Existing
  failed ToAPIs rows remain historical; no database row is rewritten by this provider switch.
