# Design: Reliable Comfly Image Output Handling

## Boundary and diagnosis

The existing provider response was accepted and its CDN URL was downloaded with HTTP 200, but the
adapter raised `ImageOutputValidationError` before an image descriptor could be persisted. The
current error projection intentionally hides raw responses, URLs, and provider content, but it
also drops the bounded reason for the rejection. The retained row therefore has an empty validation
snapshot and only `image_output_invalid`.

The repair keeps all untrusted-provider boundaries intact. It changes only the adapter and image
attempt diagnostics after the image worker has claimed an approved package.

## Data flow

```text
Comfly response -> one bounded URL/base64 representation
  -> HTTPS + host/DNS/redirect policy
  -> bounded bytes -> raster signature and dimensions
  -> normalize detected PNG/JPEG/WebP media type
  -> durable validation snapshot -> private MinIO -> material package
```

For URL output, any HTTPS hostname may be used after every resolved address passes the existing
public-IP check; no provider CDN hostname needs to be configured. The CDN `Content-Type` is
advisory. A specific supported image header must agree with the raster signature. A missing or
generic `application/octet-stream` header is accepted only when the bounded downloaded bytes
independently prove to be a supported raster image. HTML, SVG, redirects,
content-type/signature contradictions, oversized files, private/non-global DNS answers, and
unexpected dimensions still fail closed.

## Error and retry contract

- Keep the public parent code `image_output_invalid` for compatibility.
- Carry a small allowlisted failure reason from the adapter to the worker, such as
  `image_download_content_type_invalid`, `image_raster_signature_invalid`, or
  `image_dimensions_invalid`; never retain raw headers, URL paths, provider body, prompt, or
  secret.
- Store the safe reason plus validation stage in the existing JSON validation snapshot. No schema
  migration is necessary.
- Treat malformed/unsafe output as terminal `review_required`. Retry only existing explicitly
  retryable transport, rate-limit, and server failures.

## Compatibility and rollout

The change is backward compatible with existing image rows and keeps the 1024x1024 material image
contract. `POST /api/v1/material-packages/{package_id}/image/retry` locks the package and image,
allows only a terminal image with attempts remaining, clears only transient image execution state,
and queues that same image identity. It does not re-run acquisition, governance, selection, or
accepted copy. Rollback is reverting the adapter deployment, with no database downgrade.
