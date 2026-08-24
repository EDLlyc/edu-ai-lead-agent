# IP Digital Asset Hub UI

## Scenario: Image-first internal shared library

### 1. Scope / Trigger

Use this contract for `frontend/src/features/ip-assets/`, the standalone route boundary in
`frontend/src/app/Application.tsx`, generated API mapping, gallery/search state, upload/download,
detail drawer, or generation-job UX.

The interface is company-internal and unauthenticated. It must visibly say so and must never imply
that department/contributor labels are verified identity. It is feature-flagged off by default with
`VITE_IP_ASSET_HUB_ENABLED=false`.

### 2. Signatures

```typescript
type IpAssetFilters = {
  query: string;
  character: IpAssetCharacter | "";
  assetType: IpAssetType | "";
  department: string;
  sourceKind: IpAssetSource | "";
  orientation: IpAssetOrientation | "";
  tag: string;
};

useIpAssets(filters, enabled); // cursor-backed gallery
useUploadIpAsset(); // multipart mutation
useRecognizeIpAsset(); // explicit transient multipart suggestion mutation
useIpAssetTextSearch(); // bounded session turns + filters
useIpAssetImageSearch(); // transient multipart image
useIpAssetDetail(assetRef); // safe detail
useIpAssetPackageDownload(); // selected refs -> ZIP
useCreateIpAssetGeneration(); // idempotent async enqueue
useIpAssetGeneration(jobRef); // terminal-aware polling

type ApplicationPath = "console" | "ip-assets" | "not-found";
resolveApplicationPath(pathname); // / -> console, /ip-assets[/] -> ip-assets
```

The hub consumes only generated OpenAPI wire types through its feature API mapper. Preview/download
paths are resolved against the configured API origin and accepted only as same-origin HTTP(S)
resources.

### 3. Contracts

- The hub is a calm, image-first enterprise library: a compact product header, one prominent search
  surface, horizontal primary filters, and a full-width responsive gallery. Upload and generation
  use on-demand drawers instead of persistent side rails. The page keeps one logical heading order,
  accessible landmarks, high-contrast focus, responsive single-column fallbacks, and
  `prefers-reduced-motion` guards.
- The hub exists only at `/ip-assets` (with an optional trailing slash) as a lazy standalone page.
  The shared development console at `/` must not import, render, or mount `IpAssetPage`/`IpAssetHub`,
  even when the IP feature flag is enabled. The standalone document owns exactly one `main`, one
  `h1`, a skip link, a route-specific loading state, and the title `IP 数字资产中心`; it must not
  render the EAL console header, Brand Knowledge hero, other workbenches, shared footer, or grain.
- `Application` resolves the pathname before composition. An unknown path or a disabled IP flag
  renders a standalone fail-closed state and never falls back to the shared console or loads the hub
  page. No client-router dependency is required for this narrow MVP route table.
- Required upload/generation `character` and `asset_type` controls have no invalid blank selectable
  option. Native required validation and server typed errors both remain authoritative.
- The upload drawer creates only a local preview after file selection. It calls recognition only
  when the user explicitly activates “AI 辅助识别”; opening the drawer, selecting a file, previewing,
  or editing fields must not invoke the mutation.
- Successful recognition prefills only editable character, asset type, emotion, action, scene,
  intended use, style, and tags, with a visible “AI 建议，请确认” status. It never changes department
  or contributor and never submits the upload form. The ordinary upload mutation remains the only
  durable action.
- Recognition unavailable/failure states keep manual upload enabled and preserve the selected file
  plus current manual values. Selecting a different file invalidates any in-flight result and
  clears stale AI suggestions so an older response cannot populate or be submitted for the new
  image.
- Filters expose character, asset type, department, source/provenance, orientation, and tag.
- TanStack Query owns list/detail/capability/job server state. Current chat turns, selected assets,
  detail focus origin, and form state are ephemeral browser state; no user chat history is persisted.
- Cursor pagination appends stable pages and never replaces an existing gallery with duplicated
  rows. Filter/search changes reset incompatible cursor/search state.
- Text/image semantic results may be `semantic` or `degraded_metadata`; the UI explains degradation
  without presenting it as failure or semantic confidence. Because `ip-asset-hybrid-v2` may attach
  metadata-only cards to a semantic response, the semantic-mode heading says “语义 + 元数据结果”
  instead of claiming every card is a vector hit. Per-result explanations and similarity, when
  present, stay attached to their asset cards; search failures use an accessible alert while
  preserving the existing gallery.
- The composite chat search control owns one rounded `:focus-within` ring. Its child text input must
  not draw a second rectangular `:focus-visible` outline through that shell; keyboard focus remains
  visible through the parent ring on desktop and mobile.
- Generation polls only `queued`/`running` jobs and stops on success/failure. Terminal success
  invalidates only list queries from an effect; `refetchInterval` must never invalidate its own
  generation-query family. A successful job exposes an action that opens the output asset. Disabled
  generation does not disable upload/search/download.
- Detail and tool drawers trap keyboard focus, exclude controls inside closed `<details>` from the
  focus loop, close on Escape/backdrop/close button, and restore focus to the invoking control. Each
  drawer has an accessible name and does not nest conflicting landmarks.
- Only `ready` assets may load preview resources, enter ZIP selection, download, or become generation
  references. Processing/failed assets show textual preview fallbacks; a failed ready-image request
  also replaces the image with an explicitly named fallback.
- Multi-select ZIP download has an `aria-live` success/failure message. Blob/object URLs are revoked
  after use.
- Every asset card carries meaningful alt text based on the canonical name; broken previews retain a
  textual fallback.
- The UI contains no delete, archive, approve, publish, authentication, or public-share action.

Local browser flow is Vite `http://127.0.0.1:5173/ip-assets` to API `127.0.0.1:8000` through the
backend's exact CORS allowlist. Intranet deployments should be same origin or configure both
`APP_BROWSER_ORIGINS` and `VITE_API_BASE_URL` to exact browser-reachable origins; never use a
wildcard. A production static/reverse-proxy host must rewrite the `/ip-assets` deep link to the SPA
`index.html` while leaving `/api/` routes untouched.

### 4. Validation & Error Matrix

| Condition                                              | Required UI behavior                                                                                |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| Root path `/` with flag on or off                      | Render the shared console without importing/rendering/mounting the IP page                          |
| `/ip-assets` with feature flag false                   | Render an independent unavailable page; do not load the hub or fall back to the console             |
| Unknown browser path                                   | Render the independent not-found state with one main/h1; do not fall back to the console            |
| Production deep link without SPA rewrite               | Treat as hosting misconfiguration; configure `/ip-assets` -> `index.html`, not an in-app workaround |
| Capabilities loading/error/disabled                    | Honest status or disabled panel; no crashing hooks                                                  |
| Required taxonomy absent                               | Browser prevents submit; no invalid enum sent                                                       |
| Upload rejected                                        | Bounded accessible error; selected file/form remain recoverable                                     |
| File selected/previewed before recognition click       | No recognition request                                                                              |
| Recognition unavailable                                | Disable only the recognition control; explain that manual upload remains available                  |
| Recognition pending                                    | Prevent duplicate activation and expose a bounded progress label                                    |
| Recognition succeeds                                   | Show an announced advisory status; prefill editable fields without changing department/contributor  |
| Recognition fails                                      | Preserve selected file and manual values; show an accessible bounded error; do not submit           |
| File changes during/after recognition                  | Ignore the old response and clear stale suggestion status/values                                    |
| Exact duplicate                                        | Show existing canonical asset and refresh gallery without duplicate card                            |
| Semantic unavailable                                   | Render metadata results plus explicit degradation reason                                            |
| Invalid similar-image query                            | Accessible typed error, not “provider unavailable”                                                  |
| Text/image search request fails                        | Keep the current gallery and expose a bounded `role="alert"` message                                |
| Semantic response contains metadata-only merged hits   | Label the set “语义 + 元数据结果”; show similarity only on cards that actually have it              |
| Search text input receives keyboard/pointer focus      | Draw one rounded composite focus ring; no child rectangle, clipping, or horizontal overflow         |
| Processing/failed asset                                | Do not request preview bytes or allow selection/download/reference; render a named fallback         |
| Ready preview fails to load                            | Replace the broken image with a named textual fallback                                              |
| Preview URL crosses API origin or uses non-HTTP scheme | Refuse the resource URL                                                                             |
| ZIP succeeds/fails                                     | Announce result via live region; revoke temporary URL                                               |
| Generation queued/running                              | Poll and expose state; do not imply asset exists yet                                                |
| Generation succeeds                                    | Stop polling, link/select output, refresh gallery                                                   |
| Generation query reaches a terminal state              | Stop its timer; never invalidate the generation query from its own interval callback                |
| Drawer opened/closed by keyboard                       | Focus enters/traps, Escape closes, focus returns to trigger; closed disclosure controls are skipped |
| Reduced-motion preference                              | Disable decorative transitions/animations                                                           |

### 5. Good / Base / Bad Cases

- Good: a colleague focuses one clean rounded chat control, asks for a happy Xiaosai image, sees
  exact metadata and vector-backed matches honestly distinguished, opens the detail drawer by
  keyboard, downloads it, and gets an announced success message.
- Base: embeddings and generation are disabled. The gallery, upload, metadata filters, preview, and
  downloads remain fully usable with clear capability notices.
- Bad: the text input draws a rectangular outline through its rounded shell, the heading labels a
  metadata-only card as purely semantic, an off-origin preview URL is assigned to `<img src>`, or a
  processing asset enters a ZIP.
- Good recognition: selecting a file creates only a local preview; an explicit button click returns
  editable suggestions while department/contributor remain unchanged and upload stays unsubmitted.
- Base recognition: capability is unavailable or the request fails; the chosen file and manual
  values remain usable and the ordinary upload button stays independent.
- Bad recognition: a file-input effect calls the model, an old response populates a replacement
  file, or suggestion success automatically submits the form.

### 6. Tests Required

- API mapper: generated response mapping, safe same-origin resource resolution, cursor, semantic/
  degraded result, mutation body, and unknown/unsafe runtime values.
- Feature flag: absent/false/off values fail closed; only explicit enabled value renders the hub.
- Route composition: `/` excludes the IP page even with the flag enabled; `/ip-assets` and its
  trailing-slash form render only the standalone page; disabled and unknown routes fail closed;
  standalone title cleanup remains correct under React StrictMode.
- Component: capability states, no-auth/intranet wording, gallery/load-more, every filter, required
  taxonomy, upload/duplicate refresh, semantic fallback, transient image query, preview/download,
  per-card match explanations, search alerts, non-ready preview/selection guards, ZIP feedback,
  generation polling/output navigation, and empty/error cases.
- Recognition mapper/component: multipart contains only the selected file; no call before explicit
  click; editable advisory prefill; department/contributor isolation; no automatic submit; disabled
  and provider-failure independence; manual-value preservation; stale response reset on file change;
  announced success/failure and axe coverage.
- Hook: terminal generation status stops polling and invalidates only the list-query prefix without
  recursively refetching the generation query.
- Accessibility: axe, keyboard focus order, drawer trap/restore/Escape/backdrop behavior, closed
  `<details>` exclusion, live announcements, one composite search focus ring with the child outline
  suppressed, descriptive image text, color/focus checks, reduced-motion CSS, and mobile layout.
- Contract/final: generated OpenAPI drift, Prettier, ESLint, strict TypeScript, Vitest, production
  build, plus one local browser smoke through the exact CORS/same-origin deployment path.

### 7. Wrong vs Correct

#### Wrong

```tsx
<select name="character" required>
  <option value="">请选择</option>
  {characters.map(renderOption)}
</select>
```

The form can enter an invalid required-enum state that the generated wire type cannot represent.

#### Correct

```tsx
<select name="character" required defaultValue="xiao_sai">
  {characters.map(renderOption)}
</select>
```

#### Wrong

```css
.hub :focus-visible {
  outline: 3px solid var(--teal);
}
.searchInput:focus-within {
  outline: 3px solid var(--teal);
}
```

Both the child input and the composite shell draw incompatible focus rectangles.

#### Correct

```css
.searchInput:focus-within {
  outline: 3px solid var(--teal);
}
.hub .searchInput input:focus-visible {
  outline: none;
}
```

The rounded shell remains the single visible keyboard-focus indicator.

#### Wrong

```tsx
<img src={apiAsset.preview_url} alt="图片" />
```

#### Correct

```tsx
const preview = ipAssetResourceUrl(apiAsset.preview_url);
return preview === null ? (
  <span>PREVIEW UNAVAILABLE</span>
) : (
  <img src={preview} alt={apiAsset.canonical_name} />
);
```

#### Wrong

```tsx
// Shared console composition
<App>
  <BrandKnowledgePanel />
  {ipAssetsEnabled ? <IpAssetHub /> : null}
</App>
```

#### Correct

```tsx
const route = resolveApplicationPath(window.location.pathname);
if (route === "console") return <App />;
if (route === "ip-assets") return <StandaloneIpAssetRoute />;
return <StandaloneNotFound />;
```

#### Wrong

```tsx
useEffect(() => {
  if (file) recognize(file).then(upload);
}, [file]);
```

#### Correct

```tsx
<button type="button" onClick={() => file && recognize(file)}>
  AI 辅助识别
</button>
```

File selection stays local; recognition and the later user-confirmed upload are distinct actions.

## Design decision: calm enterprise library, not a control console

The hub uses warm off-white surfaces, dark ink text, restrained teal and warm status accents, fine
borders, subtle depth, and one quiet orbital-line gesture. The gallery is the dominant surface;
search and primary filters stay compact and horizontal, while upload, creation, and detail open only
when requested in right-side drawers. This keeps a shared visual library approachable for every
department and prevents forms or operational chrome from competing with the assets.

Avoid oversized hero typography, thick black frames, hazard colors, coordinate rails, dense boxed
filter consoles, or persistent upload/creation columns. The aesthetic must never trade away semantic
markup, focus visibility, AA contrast (including small helper text), touch targets, responsive
behavior, reduced-motion support, or honest capability/state feedback.
