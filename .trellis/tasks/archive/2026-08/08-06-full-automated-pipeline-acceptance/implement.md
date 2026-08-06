# Execution Plan

## Ordered Checklist

1. Confirm the working tree and preserve the pre-existing user-owned Trellis skill edit.
2. Confirm Compose service health, API health, content-worker configuration parity, and disabled
   WeCom delivery before triggering the run.
3. Run the existing `preview_run` against the local API with an isolated output root and bounded
   stage timeout. Do not provide a locked business date.
4. Read the redacted manifest; query its run and package identifiers through public local APIs.
5. On a selected-topic success path, validate the exported PNG signature/dimensions and package
   status. On `no_topic`, `review_required`, or `failed`, report the first terminal stage and safe
   error code without manufacturing downstream success.
6. Verify that no WeCom delivery job was created and that previous locked daily results remain
   untouched.
7. Run focused regression and operational checks. Write an evidence summary to the task research
   directory and present the actual result to the user.
8. Correct the preview audit-status normalization and add focused regression coverage for accepted
   and rejected audit outcomes. Do not change persistent data or rerun paid generation solely for
   this display-only repair.
9. Re-run focused tests and inspect a synthetic manifest projection. Finish the task with the
   acceptance artifacts and repair evidence.

## Commands and Checks

- `docker compose ps`
- `curl -fsS http://127.0.0.1:8000/healthz`
- `docker compose exec -T content-worker env` filtered only for non-secret enabled/attempt fields
- `python backend/app/preview_run.py --api-base http://127.0.0.1:8000 --output-root output/preview`
- `python -m pytest backend/tests/unit/test_preview_run.py backend/tests/unit/test_image_generation.py -q`
- `file output/preview/<preview-id>/image-*.png` and/or a local header/dimension check
- `git diff --check`
- `python -m pytest backend/tests/unit/test_preview_run.py -q`

## Review Gates

- Before spending model budget: services healthy, delivery disabled, existing daily lock not targeted.
- Before claiming success: manifest status ready, all required durable terminal statuses observed,
  accepted copy, successful material package/image, and 1024x1024 local image validation.
- Before final report: confirm no secret data in output and no Enterprise WeChat job was created.
- Before calling the preview clean: verify a record with `accepted=true` projects as `accepted`, and
  one with `accepted=false` projects as `rejected`; explicit provider statuses still win.

## Risks

- External sources can produce no eligible topic inside the normal freshness/policy window. This is
  a valid `no_topic` terminal result rather than an implementation failure.
- A provider can time out, reject a request, or return unsafe/invalid image output. The pipeline
  must preserve its typed failure and safety checks.
- The isolated run writes local development data and may incur configured provider cost, as approved
  by the user.
