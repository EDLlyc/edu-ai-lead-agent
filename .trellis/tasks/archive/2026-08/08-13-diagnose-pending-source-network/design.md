# Technical design

## Boundary

The application behavior is already correct: `SafeHttpFetcher` validates every DNS answer and
rejects synthetic/non-global addresses before an outbound request. The defect is confined to the
upstream Clash Verge Fake-IP representation for two newly approved domains.

The operational change targets only the active merge template:

`/mnt/c/Users/12297/AppData/Roaming/io.github.clash-verge-rev.clash-verge-rev/profiles/moQE0hDIEMse.yaml`

Add these entries under the existing `dns.fake-ip-filter` list:

```yaml
- '+.cast.org.cn'
- '+.edsurge.com'
```

The domains continue through normal Clash routing. Only their DNS answers change from synthetic
Fake-IP values to answers obtained through the configured real-DNS path.

## Operational flow

1. Reconfirm `profiles.yaml` still selects `Rp1pEZM1ufL7` and that its merge option still points to
   `moQE0hDIEMse` immediately before editing.
2. Copy the active merge template to a timestamped sibling backup and calculate a checksum.
3. Apply an idempotent two-line edit. Abort if either line already exists or the expected DNS list
   shape has changed; do not guess at a different active file.
4. Parse/check the edited YAML without displaying remote profile URLs or secrets.
5. Reload `clash_verge_service`. Do not restart Docker, PostgreSQL, MinIO, or WSL.
6. Query WSL and Compose DNS for both target hosts and public control hosts. Validate every unique
   answer with the same globally-routable semantics used by the application.
7. Invoke the application resolver/public-resolution path for both hosts before any live page
   request. Retain existing negative tests for non-global answers.
8. Run a dedicated bounded pending-source smoke: entry page, deterministic discovery, and at most
   one allowlisted detail page for each source. Do not seed or schedule the pending profiles.
9. Record the safe outcome and readiness decision; keep both sources pending.

## Compatibility and data impact

- No application code, database row, schema, API contract, source version, or scheduler membership
  changes are expected.
- The Windows merge-template edit is host-local operational configuration and is not committed to
  Git. Task artifacts record only the two domain patterns and safe diagnostic outcomes.
- Existing control domains and all unrelated Fake-IP behavior remain unchanged.

## Failure handling

- Active profile/template mismatch: stop before editing.
- Backup or YAML validation failure: stop before service reload.
- Service reload permission failure: preserve the backup and report the exact blocked action.
- Any non-global DNS answer after reload: roll back the two entries and keep both sources pending.
- HTTP, redirect, robots, WAF, path, content-type, size, timeout, or parser failure: do not retry
  around the policy; keep the affected source pending and report its typed failure.

## Rollback

Restore the timestamped sibling backup (or remove exactly the two scoped entries after verifying
the diff), reload `clash_verge_service`, and compare the final checksum/diff to the pre-change
template. No application rollback is required because no product code or data changes are planned.
