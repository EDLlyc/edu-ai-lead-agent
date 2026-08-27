# IP 图片翻页相册 MVP — Technical Design

## Architecture and boundaries

This is a frontend-only addition inside `frontend/src/features/ip-assets/`. It extends the existing
standalone IP route table and gallery selection tray but does not change FastAPI, OpenAPI,
PostgreSQL, MinIO, generation jobs, download counters, or the local-profile contract.

```text
ready shared IpAsset cards
  -> ordered gallery selection (insertion order)
  -> explicit album action (2..20)
  -> safe in-memory FlipbookDraft handoff
  -> /ip-assets/flipbook
  -> editable order/title + responsive page renderer
```

The page renderer uses the MIT `react-pageflip@2.0.3` dependency. The external skill's component is
not copied because that repository has no declared license; its tested behavior informs the local
contract only. Next/vinext/Cloudflare example files do not enter this repository.

## Client contracts

```typescript
const IP_ASSET_FLIPBOOK_MIN_PAGES = 2;
const IP_ASSET_FLIPBOOK_MAX_PAGES = 20;

type IpAssetFlipbookPage = Readonly<{
  assetRef: string;
  canonicalName: string;
  previewUrl: string;
  width: number;
  height: number;
}>;

type IpAssetFlipbookDraft = Readonly<{
  version: 1;
  title: string;
  pages: readonly IpAssetFlipbookPage[];
}>;

createIpAssetFlipbookDraft(assets); // validates ready/shared/distinct/count/safe fields
stageIpAssetFlipbookDraft(draft);   // module-memory only
readStagedIpAssetFlipbookDraft();   // returns a copied snapshot without mutation
clearStagedIpAssetFlipbookDraft();  // clears the one-time handoff after page state initializes
openIpAssetFlipbook(draft);         // stage -> pushState -> popstate
```

The selected collection must have one owner. Replace the gallery's ref-only `Set` with an ordered
immutable `Map<asset_ref, IpAsset>` (or an equivalently single ordered structure): card checks use
`has`, ZIP uses keys, and the flipbook draft uses values. Never maintain parallel ref and asset
collections that can drift.

The draft mapper projects only safe card fields and copies values. It validates controlled safe
asset refs, `status === "ready"`, `shared === true`, HTTP(S)-resolvable same-API preview URLs,
positive dimensions, distinct refs, and count `2..20`. It never includes profile tokens, download
URLs, filenames, object keys, favorites, contributor metadata, prompts, or query-cache objects.

## Routing and login

- Add `ip-assets-flipbook` for `/ip-assets/flipbook[/]` to `ApplicationPath`.
- Lazy-load `IpAssetFlipbookPage` under the existing IP feature flag/demo gate, with one standalone
  `main`, route-specific loading text, and document title `IP 翻页相册`.
- Add the path to the login return-target allowlist. Query strings remain allowed by the generic
  safe-route helper, but this feature emits none.
- `openIpAssetFlipbook` uses History API navigation without a page reload. The module-scoped draft
  survives that route transition. The destination initializes local state from a copied snapshot,
  then clears the staged value in an effect. This read-then-clear shape must remain safe under React
  Strict Mode's repeated development render/effect checks.
- A refresh or direct route has no draft and renders a named empty/recovery state with a gallery
  link. Login restoration may safely restore the route but cannot invent an album draft.

## Builder and renderer

`IpAssetFlipbookPage` owns the ephemeral title and ordered page array. It composes focused controls
for title, reorder/removal, return-to-gallery, and the renderer. Reordering is immutable and the
first item is visibly labeled as the cover. Removing down to fewer than two pages keeps the editor
but replaces the renderer with guidance until the minimum is restored; because removed pages are
not recoverable in the consumed draft, the gallery link is the recovery path.

The project-native renderer:

- uses `forwardRef` leaves required by `react-pageflip`;
- marks only the first and final cover leaves `hard`, with interior leaves `soft`;
- appends a blank inside-back leaf only when needed for deterministic spread parity, then a solid
  back cover with no image or text;
- uses `contain` for every heterogeneous IP image so no source is cropped or stretched;
- derives a bounded display ratio from validated page dimensions while constraining both viewport
  width and height;
- locks controls while the library state is not `read`;
- supports buttons, mouse/touch, ArrowLeft/ArrowRight, Space, Home, and End;
- exposes page position through `aria-live`, meaningful leaf labels, visible focus, and text fallbacks
  for failed previews;
- disables non-essential transitions under `prefers-reduced-motion` while preserving direct page
  navigation.

CSS is local to the IP feature through CSS Modules or a single feature-root scope. It follows the
existing warm paper/teal/clay editorial visual language and must not import the external template's
global class sheet.

## Validation and error behavior

| Condition | Result |
| --- | --- |
| 0–1 or more than 20 gallery selections | Album action disabled; visible `2–20` guidance; ZIP remains available |
| Selected item is unready/private/duplicate/invalid | Draft creation refuses navigation and announces a bounded error |
| Feature disabled or user lacks demo marker | Existing fail-closed feature/login behavior; page component is not mounted |
| Route opens without a staged draft | Empty recovery page; no API or storage work |
| Staged draft is missing, already cleared, or malformed | Same empty recovery page |
| Preview URL is unsafe or image load fails | Named page fallback; never fetch an untrusted origin |
| User removes pages below two | Keep editing controls; pause renderer and explain how to restart from gallery |
| User activates controls during a turn | Controls stay disabled until renderer returns to `read` |
| Reduced motion is requested | Remove decorative transitions; controls and page state remain operable |

## Compatibility and rollback

- `package-lock.json` is updated by the existing npm workflow; no package-manager switch.
- Existing gallery selection and ZIP behavior must remain compatible.
- The feature is already behind `VITE_IP_ASSET_HUB_ENABLED`; rollback removes the route/action,
  renderer files, and the single dependency without any data migration.
- No backend deployment ordering or database rollback is required.

## Testing strategy

- Pure tests: draft projection validation, insertion order, immutable reorder/removal, Strict
  Mode-safe read/clear lifecycle, invalid/duplicate/count cases, and leaf parity/back-cover
  generation.
- Component tests: action range guidance, ZIP regression, cover label/order, title edit, controls,
  failed image fallback, reduced-motion-compatible styles, and accessible announcements.
- Route tests: exact/trailing-slash resolution, lazy separation from console, feature flag, login
  safe return, title/loading state, missing-draft recovery, and no leaked draft in URL/storage.
- Contract checks: dependency license/audit, format, lint, strict TypeScript, Vitest, production
  build, and `git diff --check`.
- Browser smoke: select 2–3 ready images, open the album, reorder/change cover, turn pages via mouse
  and keyboard, verify a narrow viewport, then refresh and confirm the recovery state. Audit the API
  and database before/after to prove no job, asset, download, or provider mutation.
