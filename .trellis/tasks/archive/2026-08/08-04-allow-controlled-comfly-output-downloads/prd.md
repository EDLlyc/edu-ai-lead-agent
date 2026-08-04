# Allow controlled Comfly image output downloads

## Goal

When Comfly returns a signed or temporary image URL hosted on a CDN different from
`COMFLY_BASE_URL`, the content worker must retrieve the image and persist the validated result
instead of failing solely because the CDN hostname was not known in advance. This lets the real
image-generation smoke test produce an image without weakening the provider boundary into an
arbitrary outbound fetcher.

## Background and confirmed facts

- `OpenAICompatibleImageGenerator._download_image` currently accepts only HTTPS URLs whose
  hostname is in its configured output-host set.
- An empty `COMFLY_OUTPUT_HOSTS` value falls back to the API hostname, so an otherwise successful
  provider response from a different CDN is rejected before any bytes are stored.
- The existing downloader already rejects redirects, credentials, fragments, whitespace, bad
  status codes, unsupported media types, oversized responses, and non-1024x1024 images.
- The user explicitly wants the returned temporary URL downloaded automatically. The exact CDN
  hostname is not available as a stable deployment setting, so a provider-specific opt-in public
  URL policy is required for this deployment.

## Requirements

- Add an explicit Comfly setting that enables downloading provider-returned public HTTPS URLs when
  the URL hostname is not in `COMFLY_OUTPUT_HOSTS`; keep the setting disabled by default for new
  deployments.
- When that setting is enabled, accept the supplier's temporary/signed CDN URL and preserve its
  query string, but reject credentials, fragments, whitespace, non-HTTPS schemes, non-443 ports,
  redirects, private/non-global literal IPs, and hostnames that resolve only to non-global IPs.
- Keep the existing exact hostname allowlist path. Configured hosts remain supported and must not
  require public DNS resolution for deterministic tests or private operator-controlled providers.
- Preserve response size, content-type, image-signature, dimension, timeout, retry, and typed-error
  behavior. The downloader must never save an unvalidated response.
- Expose the new setting in Compose and `.env.example`, and enable it only in the local ignored
  deployment `.env` used for the real Comfly smoke test. Never commit the API key or signed URL.
- Add focused unit coverage for the opt-in CDN success path, DNS/private-address rejection, and
  the existing disabled/allowlist rejection path.

## Acceptance Criteria

- [ ] With the opt-in setting enabled, a Comfly response containing a temporary URL on an
      unlisted public CDN is downloaded and returned as a validated 1024x1024 image.
- [ ] With the opt-in setting disabled, an unlisted CDN URL is still rejected and no image bytes
      are returned to storage.
- [ ] Private, loopback, link-local, reserved, or otherwise non-global output addresses are
      rejected before the download request is sent.
- [ ] Existing URL, response, image-dimension, retry, redaction, and configuration tests pass,
      along with Ruff, mypy, the backend suite, Compose validation, and doctor checks.
- [ ] A real Comfly smoke run stores one generated image in the existing MinIO/image artifact
      pipeline, or reports the external provider failure separately from local URL-policy failure.

## Out of scope

- Trusting arbitrary HTTP URLs, following redirects, proxying provider URLs to frontend clients,
  or removing image-size/type/dimension checks.
- Guessing or hard-coding an undocumented CDN hostname.
- Changing image prompts, models, idempotency behavior, database schema, or social publishing.

## Open questions

None. The user selected automatic download, and the implementation will use an explicit opt-in
public-provider URL policy with SSRF and resource bounds.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
