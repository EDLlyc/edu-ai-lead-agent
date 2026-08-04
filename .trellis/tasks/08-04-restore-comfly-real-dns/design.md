# Technical Design

## Operational boundary

The fix is applied in the upstream Windows Clash/Mihomo DNS configuration, not in the repository's
SSRF policy and not by replacing Docker's resolver. Add only the following `dns.fake-ip-filter`
entries:

- `+.ai.comfly.org`
- the exact bare hostname returned by the Comfly temporary output URL

The first entry ensures the provider API hostname receives a real answer. The second entry ensures
the signed output URL's CDN hostname receives a real answer. Both names continue through the
proxy's normal rule matching and outbound policy; only their DNS representation changes from
synthetic Fake-IP to real DNS.

## Discovery and data flow

1. Record the current proxy filter configuration and the existing resolver result.
2. Add a smoke-only observer to the image adapter's compatible URL representation path. It receives
   only the normalized bare hostname and is unset in all normal API/worker paths. The observer is
   called before DNS/public-address rejection, allowing discovery without downloading bytes.
3. Add a `--discover-output-host` smoke mode that prints only that hostname and exits without
   writing an image artifact. Base64 output has no hostname and remains a normal no-host result.
4. Run one bounded provider request using that mode; never display its URL path or query string.
5. Add the exact discovered hostname to the proxy filter, reload the proxy, and verify the API and CDN names
   resolve to globally routable addresses from the content-worker container.
6. Run one idempotent image smoke attempt.
7. Let the existing downloader perform HTTPS, no-redirect, response-size, media-type, signature,
   dimension, and public-address checks before MinIO persistence.

## Compatibility and rollback

- The diagnostic changes only the local smoke/adapter interface. It does not change the provider
  model, normal image worker behavior, image validation, persistence schema, or API contract.
- Existing Fake-IP behavior for all other domains is preserved.
- Rollback is removing only the two added filter entries and reloading Clash/Mihomo.
- If the CDN hostname rotates, the operator must repeat hostname discovery and add the new exact
  entry; broad wildcard trust is not permitted.

## Risks

- A provider response may take longer than the current 120-second provider window; this is reported
  as an external provider timeout and must not trigger repeated paid requests.
- A provider CDN hostname may be outside the Comfly domain and may rotate. The smoke procedure must
  treat the hostname as sensitive metadata and avoid logging its signed URL.
- Windows proxy configuration path and reload mechanism vary by product. The operator must confirm
  the active profile before editing; no broad filesystem search or destructive reset is allowed.
