# Implementation Plan

## Execution order

1. [x] Add typed reference-source options and a pure candidate/search projection that deduplicates
       shared-ready assets and never mutates query-cache records.
2. [x] Extend `usePersonalIpAssets` with an explicit enabled gate while preserving safe profile-ref
       query keys, cursor behavior, abort signals, and existing personal-shelf callers.
3. [x] Compose shared and personal infinite queries in the creation page; add all/favorite/uploaded/
       shared-generated source tabs with profile gating, active-source search, empty/error/loading,
       and load-more states.
4. [x] Add selected-card ordinals/check indicators, three-reference guidance, and page-owned visible
       accessible feedback for add/remove/reorder/filter/favorite/share/download/generation actions.
5. [x] Refine `OutputStage` to distinguish submitting, queued, running, succeeded, failed, and
       status-error states with honest independent-worker language and no fake progress/liveness.
6. [x] Add restrained selected/pressed/pending styles, responsive handling, and reduced-motion
       guards without changing the established editorial composition.
7. [x] Expand creation-page and hook tests for source switching, shared-ready filtering, profile
       setup gating, search/pagination, selection persistence/limit feedback, job-state wording,
       cache privacy, interaction announcements, axe, and CSS motion guards.
8. [x] Update the frontend IP asset spec with the implemented filter and feedback contract.
9. [x] Run focused tests, `make frontend-check`, `make api-contract-check`, scoped token/privacy
       scans, `git diff --check`, local no-provider browser smoke, and an independent Trellis check.

## Risky seams

- The creation page already has a personal-shelf query; the picker must use a distinct source key
  without disabling or overwriting the shelf query.
- Personal favorites may contain private assets, but reference candidates must remain shared-ready.
- Source/search changes must not clear ordered references or produce duplicate asset cards.
- A visible feedback surface must supplement, not replace, native pressed/disabled/focus semantics.
- Queued wording must not imply the worker or provider is online.

## Planned validation

```bash
npm --prefix frontend test -- --run \
  src/features/ip-assets/IpAssetCreationPage.test.tsx \
  src/features/ip-assets/hooks.test.ts
make frontend-check
make api-contract-check
git diff --check
```

Also scan the changed frontend for raw token usage in URLs/query keys/logs and run the local studio
with API + Vite only, leaving the real generation worker stopped.

## Pre-start review gate

- The filter set and private-reference boundary match the user's accepted scope.
- No backend contract or migration is required.
- Acceptance criteria cover observable feedback rather than implementation-only state.
- Implementation begins only after the user approves the final planning summary in a subsequent
  message.
