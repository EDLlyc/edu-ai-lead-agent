# Current official-account editor handoff audit

Audit date: 2026-08-27. This is a read-only planning record for the
`wechat-official-account-editor-adaptation` task.

## Existing reusable boundaries

- `backend/app/application/services/official_account_export.py:225` owns the current
  `wechat-draft-preflight-v1`. It checks conservative metadata lengths, HTML size, placeholder and
  executable markup rejection, tag/attribute allowlists, source URLs, controlled media, MIME,
  bytes, dimensions, the 2.35:1 cover, and manual review.
- `backend/app/application/services/official_account_export.py:495` always records
  `mobile_screenshot_not_run`; static validation must not be presented as browser acceptance.
- `backend/app/application/services/official_account_export.py:2021` and `:2037` already demonstrate
  deterministic ZIP writing and post-write verification. Historical writers and bytes are frozen;
  a new handoff module can follow the contract without editing old dispatch.
- `backend/app/official_account_local_cli.py:147` supports fixture review/copy-ready output after
  approval. `:161` keeps live local exports review-only.
- `backend/app/api/v1/routes/official_account_local.py` currently has seven local-simulation paths:
  capabilities, run list/create/detail/retry, immutable manual review, verified media, and sandboxed
  draft preview. It contains no publish/send/account/credential route.
- `backend/app/api/v1/routes/official_account_local.py:304` serves a fixed preview document with a
  restrictive CSP. `:268` revalidates media bytes through `OfficialAccountLocalMediaResolver`.
- `frontend/src/features/official-account-local/OfficialAccountLocalPanel.tsx:824` only embeds the
  existing sandboxed draft preview. The feature has no handoff preflight, clipboard, ZIP, cover, or
  individual handoff download UI.
- `frontend/src/features/official-account-local/api.ts` maps generated OpenAPI responses to readonly
  view models; `hooks.ts` owns TanStack Query state. The local workbench is already gated by Vite
  development mode plus `VITE_OFFICIAL_ACCOUNT_LOCAL_ENABLED=true`.

## Current specification constraints

- `.trellis/spec/backend/official-account-editorial-repackage.md:697`--`:708` requires polished
  local export to remain independent from WeChat, WeCom, and publish dependencies and makes
  re-export perform zero provider/source calls.
- The current renderer/style/template family is V8 news-context and the local adapter is V7; these
  identities and historical output must remain replayable.
- `.trellis/spec/backend/official-account-editorial-repackage.md:779`--`:781` fixes the current
  bundle at 1--5 body images, 0--2 context images, a separate cover, relative assets, deterministic
  ZIP, `simulation=true`, `local_only=true`, `copy_ready=false`, and `published=false`.
- `.trellis/spec/backend/official-account-editorial-repackage.md:783`--`:794` currently rejects
  copy-ready export with unverified context-image rights. The new editor-handoff is therefore a
  separate version family; it must not silently relax the historical exporter.

## Dirty worktree audit

At planning time the repository had more than 50 unrelated modified/untracked paths. Relevant
official-account export, route, schema, feature and test files had no local diff, while high-collision
global files such as `.env.example`, `compose.yaml`, project specs and frontend package files did.
Implementation must re-run a local diff immediately before changing every high-collision file and
merge additively.

## Resulting design implication

No database migration, repository extension, worker, or provider adapter is needed for this task.
The handoff is a deterministic read-only projection of already durable approved state. Real WeChat
image upload, cover media, draft creation, credential handling and publish status require a future
separately authorized durable adapter/job.
