# Technical Design

## Scope and boundaries

This is a frontend-only refinement of `frontend/src/features/ip-assets/`. Existing generated
OpenAPI types, profile headers, personal-list routes, shared-list routes, generation enqueue, and
job polling remain unchanged. No provider call or worker process is part of implementation or test.

## Reference-source state and data flow

Introduce one local `referenceSource` union:

```typescript
type ReferenceSource = "all" | "favorite" | "uploaded" | "generated";
```

- `all` consumes `useIpAssets(pickerFilters, enabled, activeProfile)` so server-side shared search
  and favorite projection remain authoritative.
- Personal sources consume `usePersonalIpAssets(activeProfile, source, enabled)`. Extend that hook
  with an optional `enabled` argument so inactive picker/shelf queries do not issue requests while
  preserving the safe `profile_ref` query key.
- Map personal rows to `item.asset`, then filter `asset.shared && asset.status === "ready"`.
  `generated` is labeled “我的共享 AI 作品”; unshared personal results are intentionally absent.
- For personal sources, apply the bounded text query locally to the same safe metadata fields shown
  by the picker. The existing endpoint has no text argument and changing it is outside scope.
- The active infinite-query result supplies loading/error/next-page behavior. Appended pages are
  deduplicated by `asset_ref`. `references` remains independent local state, so switching source or
  search never mutates the filmstrip.

## Interaction feedback

Replace the visually-hidden-only announcement with one visible status surface that also has
`role="status"`/`aria-live="polite"`. Keep bounded safe Chinese messages; do not render raw errors.
Event handlers set feedback for selection, removal, reorder, filter switch, favorite, share,
download, enqueue, and failures.

Reference cards receive a selected class and a textual badge such as `✓ 已选 · 参考 02` in addition
to `aria-pressed`. The add handler refuses a fourth reference defensively and reports the limit.
Filmstrip callbacks report reorder/remove results through the page-owned feedback function.

CSS adds visible selected, pressed, pending, and focus states. Transitions live only inside the
existing `prefers-reduced-motion: no-preference` block.

## Generation state projection

Pass the enqueue mutation state into `OutputStage` and project a small deterministic step model:

1. waiting: complete brief and choose references;
2. submitting: storing the job;
3. queued: stored, waiting for independent background generation service;
4. running: worker has claimed the task and model generation is in progress;
5. succeeded/failed/status-error: terminal or recoverable outcome.

`generation_available` is described as configured capability, never worker liveness. Polling remains
owned by `useIpAssetGeneration`: two seconds only for queued/running and no generation-query
self-invalidation.

## Compatibility and failure behavior

- Profile setup semantics, token header transport, and query-key privacy stay unchanged.
- If a personal query fails, keep selected references and show a local picker error with retry/load
  behavior; do not fall back to unfiltered private data.
- Favorite cache invalidation continues to use the IP asset key prefix, updating all/personal views.
- If a selected card disappears after favorite/source/search changes, it remains in the filmstrip
  until explicitly removed.
- No API/OpenAPI/backend changes are expected. If implementation discovers an unavoidable contract
  gap, return to planning before changing the backend.

## Validation and rollback

Component tests use mocked shared/personal pages and controlled queued/running/succeeded states.
Hook tests cover the new enabled gate and active-page pagination. Run IP-asset frontend tests,
`make frontend-check`, `make api-contract-check`, `git diff --check`, privacy scans, and a local
browser smoke with the worker stopped.

Rollback is one frontend commit: remove the source-filter state/status surface and restore the
previous picker composition. No durable data or migration rollback is involved.
