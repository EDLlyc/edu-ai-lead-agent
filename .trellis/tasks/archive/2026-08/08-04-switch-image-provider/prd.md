# Switch image generation provider

## Goal

Replace the exhausted ToAPIs image-generation route with the newly supplied OpenAI-compatible
image service so the content worker can generate the approved material-package image again, while
keeping the existing idempotency, private MinIO storage, output validation, manual-use boundary,
and offline fake-provider test path.

## Confirmed repository and provider facts

- The current image path is selected by `IMAGE_PROVIDER_MODE` and only accepts `disabled`, `fake`,
  and `toapis` in `backend/app/core/config.py`.
- `create_image_generator()` currently constructs `ToApisImageGenerator`, whose protocol includes
  a provider upload, an asynchronous `/v1/images/generations` request, provider polling, and a
  provider-host allowlist in `backend/app/infrastructure/ai/image_generation.py`.
- The previous live check authenticated successfully against ToAPIs but image creation returned
  `403` with provider code `quota_not_enough`; this is an exhausted provider quota, not a local
  MinIO or worker failure.
- The supplied documentation site is `https://gpt-best.apifox.cn/`. Its documented image contract
  is OpenAI-compatible `POST /v1/images/generations` with `Authorization: Bearer ...`, JSON fields
  `model`, `prompt`, `size`, `aspect_ratio`, and optional `image` references. It says reference
  image URLs may be placed in `prompt` for models that support them.
- The user confirmed the production API Base URL as `https://ai.comfly.org`. A no-credential
  `GET /v1/models` probe returned HTTP 401 with a standard OneAPI-style JSON error, confirming the
  host is an API gateway rather than the documentation site.

## Requirements

### R1. Provider integration

- Add a generic OpenAI-compatible image provider mode with a configurable HTTPS Base URL, API key,
  model, request timeout, retry budget, and provider response limits.
- Preserve `disabled` and `fake` modes. Keep the old ToAPIs implementation available for rollback
  until the new service passes live verification; the active local Compose configuration should
  target the new provider only after its Base URL is confirmed.
- Send only bounded prompt/model/request data and approved reference-image input. Never log API
  keys, Authorization headers, raw provider bodies, prompts, or private image URLs.
- Normalize synchronous and asynchronous provider results into the existing `ImageGenerationResult`
  contract. A provider task identifier may be retained only as a safe opaque identifier.

### R2. Existing safety and delivery contracts

- Keep request fingerprints provider/model/version aware so changing providers cannot reuse an old
  artifact silently.
- Keep HTTPS-only endpoint validation, response media-type/size/dimension checks, private MinIO
  storage, and the no-automatic-publishing boundary.
- Map authentication, quota, rate-limit, timeout, unavailable, malformed-output, unsafe-output,
  and unsupported-reference failures to typed errors with correct retryability.

### R3. Configuration and operations

- Add safe `.env.example` and Compose entries for the new provider without storing the supplied key.
- Put the supplied key only in the untracked local `.env` after the Base URL is confirmed; the key
  must never appear in a commit, test fixture, task artifact, or log.
- Rebuild the content worker, run a non-destructive provider capability check, and run one bounded
  protected image smoke test only after the endpoint/model contract is verified.

## Acceptance Criteria

- [ ] The actual API Base URL and model are configured explicitly; the documentation hostname is
      never mistaken for the API origin.
- [ ] Unit and contract tests prove Bearer auth, request payload mapping, synchronous/asynchronous
      response normalization, reference-image handling, safe error classification, and response
      redaction.
- [ ] Existing image-package idempotency, validation, private storage, and fake-provider tests
      remain passing.
- [ ] `content-worker` starts with the new configuration and does not emit secrets or raw provider
      responses.
- [ ] A bounded live smoke test either produces one validated image artifact or records a typed,
      non-sensitive provider diagnostic; no fake image is presented as a live result.
- [ ] `make doctor`, focused backend tests, lint/type checks, Compose validation, and
      `git diff --check` pass.

## Out of scope

- No automatic social-platform publishing.
- No CAPTCHA/anti-bot bypass, stealth traffic, or provider-policy evasion.
- No database edits to manufacture a successful image package.
- No removal of the existing fake provider or durable material-package contracts.

## Open questions blocking implementation

- No blocking product questions remain. The implementation will use `https://ai.comfly.org` and
  retain the current `gpt-image-2` model unless the authenticated `/v1/models` capability check
  proves that model unavailable; such a provider capability mismatch is a terminal verification
  finding, not a reason to guess a different model.

## Notes

- This is a complex cross-layer change. After the Base URL is confirmed, add `design.md` and
  `implement.md`, obtain approval of the final planning summary, then activate the task before
  editing product code.
