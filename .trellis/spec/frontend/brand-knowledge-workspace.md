# Brand Knowledge Workspace

## Scenario: Internal upload, activation, and copy-generation context diagnostics

### 1. Scope / Trigger

Use this contract for the implemented brand workspace under `frontend/src/features/brand/`. It is
an internal operator surface for the single Sai Xiansheng corpus, not a public document uploader,
fact-evidence browser, parent-facing search product, editor, or publishing console. The corpus is
retrieved primarily by the downstream WeChat Moments copy-generation node.

### 2. Signatures

- Page composition: [`App.tsx`](../../../frontend/src/app/App.tsx) renders
  [`BrandKnowledgePanel.tsx`](../../../frontend/src/features/brand/BrandKnowledgePanel.tsx).
- Wire adapter: [`api.ts`](../../../frontend/src/features/brand/api.ts) consumes generated OpenAPI
  `components`; it does not define duplicate response interfaces.
- Server state: [`hooks.ts`](../../../frontend/src/features/brand/hooks.ts) owns query keys,
  mutations, invalidation, and bounded polling.
- Styling: `BrandKnowledgePanel.module.css`; tests:
  [`App.test.tsx`](../../../frontend/src/app/App.test.tsx).

### 3. Contracts

- The upload form accepts the supported extensions, title, kind, and bounded comma-separated tone
  and safety tags. Audience is fixed to `parents` in the MVP.
- Multipart serialization is owned by the feature API adapter. Components never call `fetch`.
- Document list polling runs only while a version job is `queued`, `running`, or
  `retry_scheduled`; terminal state stops polling.
- Successful upload invalidates the document list and announces the durable ingestion job ID in an
  `aria-live` status region.
- Ready inactive versions expose activation; active documents expose deactivation. There is no
  delete-history or automated-publishing action.
- Controlled retrieval is de-emphasized as an internal generation-context diagnostic. It renders
  returned text as text, not HTML, shows document identity plus fused score, and explicitly states
  that it is not a parent-facing service and cannot prove external facts.
- Audience is fixed to `parents` as generated-copy target metadata, not as an operator role.
- Generated wire types under `src/lib/api/generated/` are generator-owned and never edited by hand.

### 4. Validation & Error Matrix

| Condition | Required UI result |
|---|---|
| No documents | Explain how the first upload populates status |
| List request pending/failed | Accessible status/alert with safe remediation |
| Missing title or file | Native form validation / disabled submit; no request |
| Upload accepted | Announce durable job ID and refresh list |
| Version queued/running/retrying | Continue bounded polling |
| Version ready and inactive | Show keyboard-accessible activation button |
| Active document | Show keyboard-accessible deactivation button |
| Context diagnostic returns no items | Empty result, never fabricate brand guidance |
| Context retrieval/provider failure | Accessible alert; no stale success claim |
| Any state | No post/publish button or social credentials |

### 5. Good / Base / Bad Cases

- Good: an internal user uploads Markdown, sees the queued job, watches it reach ready, activates
  the version, and runs a copy-generation context diagnostic for a parent-targeted draft.
- Base: the corpus is empty or the provider is unavailable; the page explains the state without
  pretending generation succeeded.
- Bad: handwritten API response types, infinite polling after terminal status, raw HTML rendering,
  or an action labelled publish/post.

### 6. Tests Required

- Component tests assert the internal copy-generation positioning, brand/evidence boundary, empty
  state, controlled upload, durable job announcement, absence of parent-facing search/publishing
  controls, and automated accessibility.
- TypeScript strict mode and ESLint must pass without assertions that bypass generated types.
- OpenAPI generated-type drift and the production Vite build are required in the final frontend
  gate.
- Later product E2E must cover a ready version and retrieval against controlled backend/provider
  fixtures; real corpus quality is a backend/product acceptance concern.

### 7. Wrong vs Correct

#### Wrong

```tsx
useEffect(() => {
  fetch("/api/v1/brand-documents").then(/* local response casts */);
}, []);
```

#### Correct

```tsx
const documents = useBrandDocuments();
const upload = useUploadBrandDocument();
```

Keep transport and generated types in `features/brand/api.ts`, server-state policy in hooks, and
rendering/interactions in the panel.
