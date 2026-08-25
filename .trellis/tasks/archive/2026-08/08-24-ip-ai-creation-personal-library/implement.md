# Implementation Plan

## Execution order

1. [x] Update the IP asset domain/port contracts for safe local profiles, shared visibility,
       profile memberships, favorites, one-to-three ordered references, personal asset projections,
       leaderboard periods, and deterministic fingerprints/date windows. Preserve the legacy
       single-reference normalization path.
2. [x] Add the next Alembic migration and SQLAlchemy models for profiles, memberships, favorites,
       generation references, daily download aggregates, `ip_assets.shared_at`, and nullable
       generation `profile_id`; backfill historical visibility and ordinal-zero references without
       inventing personal/analytics data.
3. [x] Extend the PostgreSQL repository with profile bootstrap/lookup, public versus
       profile-accessible asset reads, personal keyset listing, idempotent favorite/share,
       profile-scoped generation enqueue, ordered reference loading, atomic generated membership,
       upload membership, anonymous daily upserts, and deterministic 30-day/all-time ranking.
4. [x] Extend application services so upload can optionally link the current profile, personal media
       is access-checked, ZIP/direct downloads return the exact counted asset set, and generation
       verifies one-to-three references outside transactions while completion remains lease-fenced.
5. [x] Add bounded Pydantic/OpenAPI routes for profile bootstrap/restore, personal lists,
       favorite/unfavorite, explicit sharing, leaderboard, and ordered generation references. Keep
       shared reads anonymous, accept the legacy one-reference request, update exact CORS headers,
       and expose no token/hash/internal/storage fields.
6. [x] Add focused backend unit/API/real-PostgreSQL tests for validation, migration/backfill/model
       parity, concurrency/idempotency, access isolation, lease completion/deduplication, daily
       aggregation rules, ranking windows/ties, privacy, and disabled behavior.
7. [x] Run `make api-generate`, consume only the generated schema, and update the IP asset API mapper
       and query hooks for local-profile headers, personal private-media blobs, favorites, sharing,
       ordered generation references, leaderboard periods, and precise cache invalidation.
8. [x] Add `/ip-assets/create` routing and the dedicated responsive creative-studio page with
       profile setup, numbered reference filmstrip, prompt/options, terminal generation status,
       output actions, and source-filtered personal shelves. Use the current teal/clay system,
       CSS Modules, semantic landmarks, visible focus, reduced-motion guards, and no console mount.
9. [x] Refine the shared hub by removing the creation drawer, linking the studio, adding consistent
       favorite actions, and adding the compact 30-day/all-time ranking rail without regressing
       upload, search, preview, selection, ZIP download, or focus-ring layering.
10. [x] Add frontend mapper, route, component, interaction, responsive, blob-lifecycle, polling,
        cache, and accessibility tests. Cover generation disabled with non-generation functions still
        enabled and token loss with honest re-onboarding.
11. [x] Update backend/frontend IP asset specs and local run documentation with the implemented
        profile boundary, new routes, migration revision, CORS header, reference limit, visibility,
        download counting, leaderboard, and exact validation evidence.
12. [x] Run focused tests, generated-contract checks, backend/frontend final gates, migration/Doctor,
        Compose render, scoped token/privacy scans, and `git diff --check`; then dispatch an
        independent Trellis check and fix only verified in-scope findings.

## Dependency and ownership notes

- This stays one task because steps 2–9 share one migration, repository, OpenAPI contract, generated
  types, and `frontend/src/features/ip-assets/`; parallel child ownership would create merge and
  schema-order conflicts.
- Steps 1–6 establish the backend contract before generated types or UI work. Step 7 is the explicit
  cross-layer checkpoint. Steps 8–10 consume that frozen contract. Spec updates and the independent
  check happen only after behavior stabilizes.
- The implementation agent must preserve unrelated dirty worktree changes and use the actual Alembic
  head at start time rather than assuming the planned revision number is still free.

## Risky seams and rollback points

- `ip_assets.shared_at` changes every gallery/search/reference query. Missing one filter could leak a
  personal generation; over-filtering could hide all historical assets.
- Global blob deduplication plus personal membership must never clear an already-shared asset or
  duplicate immutable bytes. A deliberate shared upload of identical personal-only bytes does make
  that asset shared by contract.
- Generation job/profile/idempotency migration must preserve legacy null-profile jobs and prevent one
  profile from receiving another profile's job/membership.
- Personal media cannot use normal tokenless `<img>`/anchor URLs; object URLs must be revoked and
  tokens must not enter URLs, logs, query keys, errors, or snapshots.
- Download aggregation occurs only after successful body preparation and before response return. A
  database failure must not silently return an uncounted success.
- Rollback first disables generation/new navigation. Do not run an older gallery implementation
  against personal-only rows without the new shared filter.

## Planned validation commands

```bash
conda run --name edu-ai ruff format --check backend/app backend/tests
conda run --name edu-ai ruff check backend/app backend/tests
make backend-typecheck
conda run --name edu-ai pytest -q backend/tests/unit/test_ip_assets.py \
  backend/tests/integration/test_ip_assets.py \
  backend/tests/integration/test_migrations.py --no-cov
make api-generate
npm --prefix frontend test -- --run src/features/ip-assets src/app/Application.test.tsx
make api-contract-check
make backend-check
make frontend-check
docker compose config --quiet
make doctor
git diff --check
```

Also run scoped scans that assert the raw local-profile token/header value, token digest, private
object keys, profile UUIDs, and hidden asset data are absent from logs, URLs, OpenAPI responses,
frontend query keys/snapshots, and committed fixtures.

## Pre-start review gate

- PRD has no blocking decisions and maps every requested deliverable to observable acceptance.
- Design covers schema, API, transactions, deduplication, access, frontend behavior, migration,
  rollback, and privacy boundaries.
- `implement.jsonl` and `check.jsonl` contain real project spec/research entries.
- Implementation may start only after the user explicitly approves the final planning summary in a
  subsequent message.
