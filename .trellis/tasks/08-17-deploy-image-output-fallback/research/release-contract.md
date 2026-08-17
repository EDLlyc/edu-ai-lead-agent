# Bounded release contract

## Evidence

- Codeup `origin/main` is `c2ceeee`; local clean `main` is three commits ahead and contains
  application fix `cbc27b2`, its task archive, and journal record. No remote divergence exists.
- Production is exact `7ba25d3` / image `sha256:7627186…b21c`; all eight services are running on
  that image with restart zero. Effective scoring/OCR/diversity are `.7/true/true`.
- Runtime diff 7ba→cbc is exactly:
  - `backend/app/infrastructure/ai/image_generation.py`
  - `backend/app/domain/image_fallback.py`
  - `backend/app/application/services/material_package.py`
- Runtime lock, Dockerfile, pyproject production dependencies, Compose, Settings, Alembic and
  OpenAPI do not change. Source/image path counts remain 321/179.
- The URL contract passed one separately authorized paid live generation: Comfly `gpt-image-2`,
  validated PNG, 1024×1024, no retry, no persistence/delivery mutation. Deployment must not call it
  again.
- The standard digest deployer remains unavailable by recorded contract. The successful 7ba
  activation used a protected local-tag/offline image/source operator with automatic recovery.

## Mandatory controls

- exact clean Codeup-reachable application commit and offline artifact hashes;
- previous 7ba full image/source/tag/container identity;
- stable zero-work/provider/WeCom baseline before first stop and before dispatcher;
- backup lock, all-eight quiesce, fresh PG/source/env/marker/tag backup, MinIO read-only inventory;
- no `minio-init`, no seed, Alembic-only no-op, no provider/fixture/WeCom call;
- service-scoped `--no-build --no-deps` recreation, dispatcher last;
- phase-aware single recovery and all-writers-stopped incident boundary;
- independent read-only postcheck and checksum-bound result evidence.
