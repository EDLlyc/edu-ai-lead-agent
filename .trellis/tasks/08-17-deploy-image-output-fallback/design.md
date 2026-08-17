# Design — 部署图片供应商格式容错修复

## Release identities

- Previous runtime: `7ba25d3` / `sha256:7627186…b21c`.
- Application candidate: exact commit `cbc27b2`.
- Codeup head may contain later task/archive/journal commits; the candidate build remains detached at
  `cbc27b2` so operational documentation cannot change runtime identity.
- Operator identity is separately checksum-bound and is not part of the application payload.

## Artifact construction

Use the existing verified immutable dependency base and offline overlay build. The candidate copies
the full committed application source scope rather than patching a running container. The builder
must prove:

1. clean detached `cbc27b2` authority and reachability from Codeup main;
2. exact 321 source and 179 image-source paths;
3. unchanged production dependency contract, runtime lock, Dockerfile, Compose and migration head;
4. only the three intended application blobs differ from 7ba in runtime scope;
5. linux/amd64, non-root `app`, dependency-rootfs prefix, no stale package/source overlays;
6. URL payload and fallback focused tests in the candidate without network.

The protected transfer stage contains only checksummed regular files. Production validates bundle
graph, labels, source manifests and candidate runtime before the first stop.

## Production sequence

```text
read-only stable baseline
  → backup lock
  → dispatcher-first quiesce of all eight services
  → fresh PG/source/env/marker/tag/container backup + MinIO inventory
  → candidate load/validate
  → arm rollback tags
  → retag + atomic source/marker install
  → Alembic-only no-op
  → API → acquisition → governance → content → dispatcher
  → 15–30s stable postcheck
```

Candidate services are recreated explicitly with `--no-build --no-deps`. Scheduler/dispatcher
starts are preceded and followed by observed zero-work/stability gates. No predictive reconcile SQL
is claimed; if ordinary business is active, deployment waits rather than suppressing it.

## Rollback

Recovery is armed before first mutation and is phase-aware. It restores 7ba source, markers, shared
and service tags, then starts old exact containers or recreates one service at a time. Dispatcher is
last. PostgreSQL/MinIO are evidence-only because candidate migration is a proven no-op and the
release performs no business/object write. Ambiguous recovery stops all eight writers.

## Why not standard release

Production still uses the reviewed local-tag/offline baseline and lacks the standard registry
digest/current-manifest prerequisites. Running `make release-prod` would build/push before a known
preflight failure. This task uses the already-successful one-time checksum-bound mechanism and does
not claim to fix the standard release path.
