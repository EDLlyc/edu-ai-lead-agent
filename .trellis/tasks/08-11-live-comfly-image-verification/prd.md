# Live Comfly image-generation verification

## Goal

Run one production-configured Comfly image call locally with the content-driven private brand references; save the successful bounded image under output/imagegen without creating any PostgreSQL material package or Enterprise WeChat delivery.

## Confirmed Facts

- `backend/app/image_live_smoke.py` invokes the configured production image adapter directly and
  does not create a material package, write PostgreSQL records, or enqueue Enterprise WeChat work.
- Its `--content-driven` mode uses the current visual-brief, brand-catalog selection, prompt bundle,
  and reference-image construction used by the material-package path.
- The direct-raster adapter repair in commit `6c58689` accepts only validated PNG, JPEG, or WebP
  creation responses. Earlier local tests were mock-only and did not call Comfly.

## Requirements

1. Execute one Comfly request using the effective local environment configuration and the
   content-driven reference-selection path. If it ends without a saved image and without a captured
   typed result, make at most one diagnostic retry. Two such calls ended without a retained typed
   result and the final file-captured call identified a JSON-envelope rejection. One single-reference
   discrimination call is permitted after adding bounded response metadata to that parser branch.
2. Use a fresh business-run identifier and a non-existent output path under `output/imagegen/` for
   every call so the test cannot overwrite an earlier image or collide with a prior idempotency key.
3. Save a successful result only as a local 1024x1024 image file. Do not create a PostgreSQL
   material package or an Enterprise WeChat delivery job.
4. Report only bounded, non-secret result metadata: provider, model, dimensions, byte length,
   output path, and whether the request succeeded. Do not print API keys, prompts, provider bodies,
   private reference image contents, or temporary URLs.
5. When the smoke command receives a typed image-provider failure, include only its allowlisted
   fields in the terminal summary: common code/retryability, output-validation reason, or provider
   HTTP status and response kind.
6. Attach existing safe HTTP status and normalized response-kind metadata to a provider rejection
   raised while interpreting a successful creation JSON envelope; raw body data remains excluded.
7. Follow the current Comfly `gpt-image-2 Generations` documentation: request only documented
   fields, explicitly request `response_format=b64_json`, and parse the published nested task
   response shape without retaining provider bodies or temporary URLs.

## Out Of Scope

- Changing Comfly configuration, model selection, reference selection, prompt policy, retry
  behavior, or safety validation.
- Retrying failed business material packages or sending any Enterprise WeChat message.
- Uploading the output or deploying code to the server.

## Acceptance Criteria

- [ ] A configured Comfly call completes successfully and creates a new file under
      `output/imagegen/`; the retry, if needed, uses a separate output filename.
- [ ] The command reports an image that meets the existing 1024x1024 output contract.
- [x] The database and Enterprise WeChat paths are not invoked by this validation.
- [x] If the provider fails, the command exposes only the existing typed, non-sensitive failure
      summary and creates no output file.
- [x] Focused local tests prove the new failure summary excludes raw provider material.
- [x] A mocked malformed JSON creation envelope has only `200` and `json` attached to its typed
      rejection, never raw provider data.
- [x] Comfly request-payload tests use only the documented request fields and response format.
- [x] Live calls either save a valid 1024x1024 output locally or provide a typed, non-sensitive
      finding that distinguishes a provider result from a local validation failure.

## Key Decisions

- This is a lightweight operational acceptance test, so PRD-only planning is sufficient.
- The test uses the content-driven path to exercise current private IP reference selection and the
  same Comfly adapter used by automatic image generation.
- The first call ended with no output file and the command harness did not retain its typed result;
  the first retry had the same result. The final file-captured call established that the creation
  response is JSON but has an unsupported envelope. The remaining discrimination call uses one
  known configured brand reference and the standard smoke prompt, rather than the multi-reference
  content-driven input.
- The operator requested that the current public Comfly documentation supersede the historical
  `aspect_ratio` compatibility assumption. The adapter therefore uses documented request fields and
  explicitly requests inline Base64 output.
- All real calls in this task ended with the same typed result: HTTP 200, JSON, no usable image.
  A no-reference request had the same result, which rules out local private assets and local output
  validation. The live acceptance is blocked on the provider returning a supported image envelope.
