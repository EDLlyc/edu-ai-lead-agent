# Operational Result

Date: 2026-08-04

## Completed

- The active Clash Verge Rev profile was identified through `profiles.yaml`; the effective merge
  template was `profiles/moQE0hDIEMse.yaml`.
- The upstream `dns.fake-ip-filter` now contains only the two task-scoped additions:
  `+.ai.comfly.org` and `webstatic.aiproxy.vip`.
- The application runtime has `COMFLY_OUTPUT_HOSTS=webstatic.aiproxy.vip`.
- The API and CDN names resolved to globally routable addresses from the host and
  `content-worker` after the privileged Clash service reload.
- Host-only discovery reported `webstatic.aiproxy.vip` without exposing a signed URL.
- One single-attempt live Comfly smoke generated and downloaded a validated 1024x1024 PNG using
  `gpt-image-2` (1,367,639 bytes; SHA-256 recorded only in the local smoke output).
- Fake-IP/SSRF, HTTPS, redirect, response-size, media-type, signature, and dimension checks remain
  enabled. No credentials or signed URLs were added to the repository.

## Scope Note

The live command was the provider/download smoke path and wrote its validated image to a temporary
local file. It did not enqueue a second paid request through the material-package worker, so this
run does not claim a new MinIO/database material-package artifact. Existing material-package
persistence code and tests were left unchanged.

## Rollback

Remove only `+.ai.comfly.org` and `webstatic.aiproxy.vip` from the active merge template, remove
`webstatic.aiproxy.vip` from `COMFLY_OUTPUT_HOSTS`, reload `clash_verge_service`, and verify the
resolver returns to its previous behavior. Backups are kept beside the active Windows profile and
DNS settings files with the `before-comfly-20260804` / `before-output-host-20260804` suffixes.
