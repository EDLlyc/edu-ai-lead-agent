# Production baseline before no-source-link deployment

Captured read-only on 2026-09-15 Asia/Shanghai before planning approval.

## Runtime identity

- Release marker: `d2e709c0b6a5e47d1b91d2ec623de734aa3c0eb2`.
- Application image:
  `offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:baffc27e9dc4ccbd9fed5ab248e4e00784f80ecfb25f966fe8c63ee286601d8d`.
- Schema from the prior activation record: `20260914_0047`; it must be freshly
  revalidated under the deployment lock.
- 12 application containers and two dependencies are running; unhealthy and
  restarting counts are both zero.
- Root filesystem has 38,653,552 KiB available and the backup timer is active.
- Standard `release-manifest.json` and `current-release-state.json` remain absent.

## Rule state

- The running draft worker does not contain
  `wechat-source-presentation-v2-no-links` and still contains the historical
  `阅读原文` implementation.
- The reviewed V2 change is uncommitted in the release worktree and touches five
  runtime modules, two unit-test modules, and three backend specification files.
- The release branch head is `366e2e6b393c7408500571ce4f14152ccb03df8f`; the
  extra commit after production revision `d2e709c` is activation documentation,
  not an application-byte change.

## Existing draft boundary

The demonstration article titled
`科学课从背答案变成动手做：家长如何接住这轮变化` was updated separately in
place and read back successfully. The body no longer contains the read-original
prompt, its native source URL is absent, seven images and cover metadata are
preserved, and it remains unpublished. This is evidence for the requested reader
experience only; its private provider identity and receipts are not inputs to the
prospective code deployment and must not be replayed.

## Prior release patterns

- The 2026-09-14 readable-source overlay establishes exact-base local OCI build,
  load-before-stop, protected marker backup, 12-service recreation, no-migration
  rollback, and network-disabled smoke patterns.
- The later M/W/F activation establishes the current image/schema/topology and
  the first admitted edition date of 2026-09-16. This deployment must retain its
  exclusive mode and history ownership without admitting or replaying work.
