# Operational Result

Date: 2026-08-04

## Completed

- The active Clash Verge Rev profile was identified through `profiles.yaml`; the effective merge
  template was `profiles/moQE0hDIEMse.yaml`.
- The upstream `dns.fake-ip-filter` now contains only the two task-scoped additions:
  `+.ai.comfly.org` and `webstatic.aiproxy.vip`.
- The application runtime has `COMFLY_OUTPUT_HOSTS=webstatic.aiproxy.vip`.
- The live content worker uses one provider attempt with a 120-second request timeout and a
  180-second generation window; the original 30-second default was insufficient for this provider.
- The API and CDN names resolved to globally routable addresses from the host and
  `content-worker` after the privileged Clash service reload.
- Host-only discovery reported `webstatic.aiproxy.vip` without exposing a signed URL.
- One single-attempt live Comfly smoke generated and downloaded a validated 1024x1024 PNG using
  `gpt-image-2` (1,367,639 bytes; SHA-256 recorded only in the local smoke output).
- A formal material-package run then used a second accepted copy run and completed the full worker
  path: API enqueue, Comfly generation, image validation, private MinIO storage, database success
  persistence, and API download. The package reached `awaiting_manual_use`; the image reached
  `succeeded` with one attempt, 1024x1024 dimensions, 2,207,695 bytes, and a database SHA-256 that
  matched the bytes returned by the image download endpoint.
- Replaying the same material-package request returned the same package/image IDs; the database
  retained exactly one package and one image artifact for that accepted run.
- Fake-IP/SSRF, HTTPS, redirect, response-size, media-type, signature, and dimension checks remain
  enabled. No credentials or signed URLs were added to the repository.

## Scope Note

The first provider-only smoke wrote a temporary local file. The subsequent formal material-package
run exercised MinIO/database persistence and was the run used for the end-to-end acceptance result.
The package remains `awaiting_manual_use` by design; no social-platform publishing was attempted.

## Rollback

Remove only `+.ai.comfly.org` and `webstatic.aiproxy.vip` from the active merge template, remove
`webstatic.aiproxy.vip` from `COMFLY_OUTPUT_HOSTS`, reload `clash_verge_service`, and verify the
resolver returns to its previous behavior. Backups are kept beside the active Windows profile and
DNS settings files with the `before-comfly-20260804` / `before-output-host-20260804` suffixes.
