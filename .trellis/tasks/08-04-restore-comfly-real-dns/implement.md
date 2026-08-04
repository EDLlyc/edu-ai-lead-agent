# Implementation Plan

1. Add a unit-tested optional output-host observer to the Comfly adapter and a
   `--discover-output-host` local smoke mode. It may print only a normalized hostname and must not
   write an image, log/persist a URL, or alter normal worker behavior.
2. Inspect the active Windows Clash/Mihomo profile and record the current `fake-ip-filter` entries
   without exposing credentials or proxy URLs.
3. Add `+.ai.comfly.org`, reload the active profile, and verify it resolves to a real global
   address from the content-worker container.
4. Perform one bounded hostname-discovery provider request, then add the exact returned CDN
   hostname and reload the active profile. Do not retry a slow or failed paid request blindly.
5. Verify from the content-worker container that the API hostname and CDN hostname resolve to real
   global addresses, while the existing Fake-IP safety check remains unchanged.
6. Run the API health check and inspect all affected Compose services.
7. Run one bounded, idempotent Comfly image smoke attempt. Inspect only safe status, dimensions,
   media type, artifact identity, and storage outcome.
8. If the provider succeeds, confirm exactly one validated MinIO/database artifact. If it fails,
   persist/report the typed external failure and do not retry blindly.
9. Run `make backend-check`, `make frontend-check`, `docker compose config --quiet`, `make doctor`,
   and `git diff --check` if repository files changed; document the filter rollback path.

## Rollback

Remove only the two new `fake-ip-filter` entries from the active proxy profile and reload it. Do not
disable public-address validation or add `198.18.0.0/15` to any allowlist.
