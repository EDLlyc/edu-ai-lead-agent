# Official-Account Editor Handoff UI

## 1. Scope / trigger

`frontend/src/features/official-account-local/OfficialAccountEditorHandoff.tsx` is a narrow,
development-only projection inside the existing official-account local workbench. Trigger it only
for the typed backend capability; it helps an operator copy an already approved Article Package and
download local assets. It never claims that the article is a WeChat draft and must not add account
credentials, upload, publish, send, account-selection or permission-probing actions.

The section renders only when Vite is in development,
`VITE_OFFICIAL_ACCOUNT_LOCAL_ENABLED=true`, and the typed backend capability says
`editor_handoff_enabled=true`. The backend remains authoritative for guessed resource URLs.

## 2. Signatures

- Query: `useOfficialAccountEditorHandoff(runId, enabled)` owns
  `GET /api/v1/official-account-local/article-runs/{run_id}/editor-handoff`.
- Mapper: `mapEditorHandoff(response)` consumes only the generated
  `OfficialAccountEditorHandoffResponse` and returns a readonly view model.
- Browser effect: `copyOfficialAccountEditorBody(url)` fetches the fixed body resource and writes
  both `text/html` and `text/plain` to the local clipboard.
- Resource links use the typed `body_url`, `preview_url`, `bundle_url` and media `download_url`.

## 3. Contracts

- `api.ts` maps generated OpenAPI wire types; do not hand-maintain a second transport schema or
  infer state from Chinese detail text. All resource URLs pass through the existing API-origin
  resolver rather than constructing object-storage paths or arbitrary remote URLs.
- `hooks.ts` owns the GET query as server state, not a mutation. Approval invalidates both run
  detail and handoff metadata.
- Stable `blocking_codes` and `warning_codes` control behavior. Copy and ZIP are enabled only when
  `copy_ready=true`; a blocked projection keeps its typed gate list visible.
- The React tree never uses `dangerouslySetInnerHTML`. The fixed backend preview stays in a sandbox
  iframe, and article markup is rendered only inside that isolated document.
- ZIP, body images, context images and the cover are local download links with generated filenames.
  Rich-copy success is announced only after the clipboard promise resolves; unavailable API,
  permission denial and generic failure remain distinct accessible states.
- Always display `本地交接，未同步公众号` and explain that WeChat still requires body-image upload
  plus a separate cover. An unverified context image remains downloadable under the selected policy,
  while its warning, HTTPS source page and credit stay visible and are never relabeled licensed.

## 4. Validation and error matrix

| Condition | Required UI result |
|---|---|
| Frontend or backend gate is disabled | Do not render the handoff area or fetch its metadata |
| Metadata state is blocked | Show stable gate labels; disable copy and ZIP without parsing message text |
| Clipboard API is unavailable or rejects permission | Announce the exact failure; never announce success |
| Preview URL is present | Render only in the sandbox iframe; never inject its HTML into React |
| Context source URL is non-HTTPS or absent | Do not create an unsafe link; retain the rights warning |
| `publish_permission_unverified` is present | Show direct-use disclosure, source and credit; keep download available |

## 5. Good, base and bad cases

- Good: approved metadata shows all gates, sandbox preview, truthful warning, copy, ZIP and individual
  downloads with keyboard and screen-reader feedback.
- Base: a pending review shows the blocking reason and local-only boundary without a copy-ready CTA.
- Bad: a component calls `fetch` during render, uses `dangerouslySetInnerHTML`, treats GET as a
  mutation, builds media URLs itself or displays an unverified source as licensed.

## 6. Tests required

- Mapper/hook/component tests cover ready and blocked states, generated URLs, approval invalidation,
  direct-use disclosure, safe source links, sandboxing, focus and axe.
- Clipboard tests cover HTML/plain-text success, unavailable APIs, permission rejection and generic
  failure with truthful announcements.
- Playwright serves only verified local files on loopback, blocks every non-loopback request, and at
  320/430 px verifies natural image dimensions, no page-level overflow and exact copy-root/body
  equality. Runtime `mobile_validation=not_run` must not be replaced by fixture evidence.
- Generated-contract drift, ESLint, strict TypeScript, Vitest and production build must pass.

## 7. Wrong versus correct

Wrong:

```tsx
return <article dangerouslySetInnerHTML={{ __html: response.body }} />;
```

Correct:

```tsx
return <iframe title="微信公众号编辑器预览" sandbox="allow-scripts" src={handoff.previewUrl} />;
```

## V2 automatic release and exact mobile identity

### 1. Scope / trigger

- Extend the existing development-only workbench only when the generated capability exposes V2.
  Keep the V1 `manual_only` presentation and all no-publish boundaries available.
- The UI displays and copies an already derived local artifact. It never approves, uploads, sends,
  selects a WeChat account or turns a context image into evidence.

### 2. Signatures

```ts
mapEditorHandoff(response: OfficialAccountEditorHandoffResponse): OfficialAccountEditorHandoffViewModel
copyRichHtml(html: string, clipboard?: Clipboard, documentRef?: Document): Promise<RichClipboardResult>
```

```tsx
<OfficialAccountEditorHandoff
  runId={runId}
  handoff={handoff}
  loading={loading}
  error={error}
/>
```

### 3. Contracts

- Keep the V1 `manual_only` workbench behavior available. When the generated contract exposes a
  V2 release, label `machine` as `自动质量放行` and `manual` as `人工批准放行`; never infer a human
  decision from `copy_ready` or from Chinese detail text.
- Show the selected recipe and each context image's section/block insertion, source, credit and
  `publish_permission_unverified` warning. Context media supplements IP body images and never
  appears as evidence or as a replacement body slot.
- Treat runtime `mobile_validation=not_run` as honest unfinished evidence. Display `passed` only
  when the generated response carries the exact current content fingerprint; do not reuse a
  fixture sidecar for another article.
- The rich clipboard helper first uses `ClipboardItem` with HTML and plain text, then uses a local
  DOM selection/`execCommand` compatibility fallback. Both paths announce success only after the
  browser confirms copying and remove temporary DOM nodes.

### 4. Validation and error matrix

| Condition | Required UI result |
|---|---|
| V2 capability is absent or environment is not development | Do not fetch or render the V2 handoff |
| `release.kind=machine` | Show automatic quality release; never imply a human review |
| `release.kind=manual` | Show immutable human approval without relabeling it automatic |
| Runtime mobile status is `not_run` | State that this run has not been browser-validated |
| Passed report is present for the current content fingerprint | State that exact 320/430 offline validation passed |
| Context source URL is unsafe or rights are unverified | Suppress unsafe link and retain source/credit/rights warning |
| Both rich clipboard and selection fallback fail | Announce failure; never announce copied |

### 5. Good / base / bad cases

- Good: show machine/manual truth, recipe, two identities, stable context block placement, source and
  rights warning, then copy/download only when `copy_ready=true`.
- Base: a valid runtime V2 artifact shows honest `not_run`, local-only boundary and safe downloads.
- Bad: infer approval from `copy_ready`, reuse a fixture browser badge, inject article HTML into
  React, construct an arbitrary remote media URL or add publish controls.

### 6. Tests required

- V2 mapper/component tests cover release kind, recipe, placement, mobile identity and fallback
  clipboard behavior. Playwright derives expected image reading order from Article blocks plus the
  placement plan, loads every local image at 320/430, blocks external requests and emits content,
  body and ordered media hashes.

### 7. Wrong vs correct

Wrong:

```tsx
const approved = handoff.copyReady;
return <span>{approved ? "人工审核通过" : "待审核"}</span>;
```

Correct:

```tsx
return <span>{handoff.release?.kindLabel ?? "交接预检通过"}</span>;
```
