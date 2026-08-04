# Restore real DNS for Comfly image downloads

## Goal

Allow the Comfly image worker to resolve supplier-returned temporary image URLs to real public
addresses so that validated images can complete the existing MinIO artifact pipeline, without
weakening the Fake-IP or SSRF protections.

## Confirmed Facts

- The Comfly model endpoint is configured as `https://ai.comfly.org`; the image provider and
  public-output URL policy are enabled locally.
- The WSL host resolver is `10.255.255.254`. It resolves `ai.comfly.org` to `198.18.1.161`.
- Docker's embedded resolver forwards content-worker DNS requests to that same host resolver.
- `198.18.0.0/15` is reserved Fake-IP/benchmarking space. The downloader correctly rejects it
  before sending a CDN download request, so no unvalidated image was persisted.
- The supplier has returned a temporary image URL at least once, but its generation response can
  exceed the current 120-second worker window.
- The repository's acquisition guidance already requires fixing Fake-IP at the proxy/DNS layer;
  it explicitly forbids treating the range as publicly routable.

## Requirements

- Preserve the existing HTTPS-only, no-redirect, response-size, media-type, image-signature,
  dimension, and public-address checks for Comfly output URLs.
- Do not allow `198.18.0.0/15`, private, loopback, link-local, metadata, or other non-global
  addresses as image download destinations.
- Use a DNS/proxy configuration that returns real public answers for the Comfly API and temporary
  CDN output domains required by the content worker.
- Keep the change scoped and reversible. Do not silently alter unrelated system traffic.
- Verify the API and content worker after the change, then perform at most one paid live image
  smoke test and report the provider response, validated artifact outcome, and any remaining
  external failure without exposing credentials or signed URLs.
- Apply the operational fix in the upstream Windows Clash/Mihomo `dns.fake-ip-filter`, limited to
  `+.ai.comfly.org` and the exact hostname returned by the provider's temporary CDN URL.
- Keep all other proxy domains and routing rules unchanged; record the previous filter state so the
  change can be reverted by removing only the added entries and reloading the proxy.
- Add a local smoke-only diagnostic mode that can report a returned output URL's normalized
  hostname without printing, logging, persisting, or exposing its URL path, query string, prompt,
  response body, or credentials.

## Acceptance Criteria

- [ ] A Comfly API and returned temporary CDN hostname resolve to real globally routable addresses
      from the content worker, not `198.18.0.0/15`.
- [ ] The hostname-only diagnostic never exposes a signed URL or provider response and has focused
      regression coverage for URL, base64, malformed, and rejected output representations.
- [ ] The downloader continues to reject a fixture using Fake-IP or another non-global address
      before any outbound image request.
- [ ] All affected Docker services are healthy after configuration changes.
- [ ] One real image smoke attempt either creates exactly one validated 1024x1024 image artifact
      in the existing pipeline or produces a typed external-provider failure unrelated to the
      local DNS policy.
- [ ] The change is documented with an explicit rollback path and does not commit credentials,
      signed URLs, or host-specific secrets.

## Out of Scope

- Disabling Fake-IP/SSRF validation, allowing arbitrary output hosts, accepting HTTP URLs, or
  following redirects.
- Changing the provider model, prompt, image validation rules, persistence schema, or social
  publishing behavior.
- Broad proxy replacement or changes to unrelated Windows/WSL traffic unless explicitly chosen.

## Technical Notes

- `fake-ip-filter` changes DNS answers for matching names; it does not turn off the proxy or change
  unrelated routing rules. Matching names use real DNS answers and continue through the proxy's
  normal routing policy.
- The CDN hostname is not currently known. Existing smoke output only emits a typed error code, so
  a local smoke-only hostname diagnostic is needed before the operator adds the exact filter entry.
- If the provider rotates CDN hostnames, the exact filter entry must be updated for each new host;
  a broad `*.comfly.org` or arbitrary-host wildcard is intentionally out of scope.

## Notes

- This is a cross-network and live-provider task, so planning will include a design, implementation
  plan, and explicit rollback point before any operational change.
