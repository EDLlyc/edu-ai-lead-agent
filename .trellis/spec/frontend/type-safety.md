# Type Safety

## Implemented TypeScript contract

Compile with TypeScript strict mode, including `noUncheckedIndexedAccess` and
`exactOptionalPropertyTypes`. The real `tsconfig`, OpenAPI generation commands, generated path,
and the first consumer in `features/brand/api.ts` are now implemented.

## OpenAPI-generated wire types

FastAPI's checked-in [`backend/openapi.json`](../../../backend/openapi.json) is the cross-layer
source of truth. `make api-generate` exports it deterministically through
[`backend/scripts/export_openapi.py`](../../../backend/scripts/export_openapi.py), then uses
`openapi-typescript` to write
[`frontend/src/lib/api/generated/schema.d.ts`](../../../frontend/src/lib/api/generated/schema.d.ts).
The shared [`client.ts`](../../../frontend/src/lib/api/client.ts) consumes those paths through
`openapi-fetch`. Generated files:

- are never edited manually;
- are regenerated whenever API schemas change;
- are checked for drift in CI;
- remain wire types and are not automatically the best shape for rendering.

Do not define a handwritten `MaterialPackageResponse` that duplicates the backend. Map the
generated response into a feature view model only when the UI needs formatting, derived states, or
stronger presentation invariants.

```ts
type MaterialPackageResponse =
  paths["/api/v1/material-packages/{package_id}"]["get"]["responses"][200]["content"]["application/json"];

export type MaterialPackageViewModel = Readonly<{
  id: string;
  selectedTopic: Readonly<{
    title: string;
    categoryLabel: string;
    sourceTrustLabel: string;
  }>;
  generatedAtLabel: string;
  copywriting: string;
  parentTakeaway: string;
  interaction: string;
  sources: readonly SourceLinkViewModel[];
  image: ImageViewModel;
  validationStatusLabel: string;
  auditStatusLabel: string;
  warnings: readonly string[];
}>;
```

The exact generated lookup may differ with the selected generator; update this example to the real
output rather than preserving it as fiction.

## Domain and view types

- Keep component props close to components.
- Keep feature view models and discriminated UI states inside the feature.
- Reuse generated status/enum unions instead of duplicating strings.
- Represent asynchronous views with discriminated unions when this prevents impossible states:

```ts
type PackageScreenState =
  | { readonly kind: "loading" }
  | { readonly kind: "not-found" }
  | { readonly kind: "no-topic"; readonly runId: string }
  | { readonly kind: "cancelled"; readonly runId: string }
  | { readonly kind: "failed"; readonly requestId?: string }
  | { readonly kind: "ready"; readonly package: MaterialPackageViewModel };
```

The backend/OpenAPI contract owns wire status values; do not handwrite a second transport enum.
The initial mapping is `queued`/`running` -> loading, `awaiting_manual_use`/`completed` -> ready,
`no_topic` -> no-topic, `failed` -> failed, and `cancelled` -> cancelled. Hyphenated discriminants
are frontend-only view states and must never be sent back as API status values. `completed` means
only that the internal material workflow was acknowledged, not that content was published.

- Use `unknown` at truly untyped boundaries and narrow it before access.
- Prefer readonly data and pure mappers; never mutate generated responses/query-cache data.

## Runtime validation boundaries

The backend validates API payloads with Pydantic, while generated frontend types provide compile-
time safety. Validate data that bypasses that contract: URL/search parameters, local-storage
preferences, `postMessage`, user-uploaded configuration, and feature flags. Zod is the initial
default if a schema library is needed; infer TypeScript types from the runtime schema instead of
writing both independently.

Treat source text and model-generated content as untrusted display data even when its outer API
shape is valid. Render it as text, validate URLs and filenames, and do not use
`dangerouslySetInnerHTML`.

## Scenario: Image artifact quality projection

### 1. Scope / Trigger

Use this contract when the material-package API exposes deterministic image validation, provider-
neutral visual audit, or bounded automatic-repair state. These fields belong to the image artifact,
not to the copy-level validation/audit projection.

### 2. Signatures

- Generated wire type: `MaterialPackageResponse["image"]` includes `validation`, `audit`, and
  `repair_count`.
- Feature mapper: `mapMaterialPackage(response)` returns `ImageViewModel` with `validation`, `audit`,
  and `repairCount`.
- The UI renders those values in the image section and keeps the existing package-level quality
  section for copy claims.

### 3. Contracts

- `validation` contains `version`, `configured`, nullable `passed`, bounded `issue_codes`, provider/
  model metadata, and optional media/dimension/byte observations.
- `audit.status` is one of `accepted`, `rejected`, `not_configured`, or `unknown`; it must not be
  inferred from color or from the package-level audit.
- `repair_count` is a non-negative bounded count (currently `0` or `1`) and is displayed as a status,
  not as an action control.
- Generated OpenAPI types are the only wire contract; `api.ts` is the single normalization boundary.

### 4. Validation & Error Matrix

| Condition | Required UI result |
|---|---|
| Deterministic validation passed | Show an explicit validation-passed label |
| Deterministic validation failed | Show an explicit failed label and issue codes |
| Visual audit rejected | Show an explicit audit-not-passed label and issue codes |
| Audit is not configured or unknown | Show an explicit non-passed/unfinished label; never imply acceptance |
| `repair_count` is `1` | Show that one automatic repair occurred; do not offer a second repair action |

### 5. Good / Base / Bad Cases

- Good: a generated response maps directly through the OpenAPI type and the UI shows validation,
  audit, versions, issue codes, and repair count without exposing prompts or storage details.
- Base: historical image rows use the backend's safe not-configured fallback and remain inspectable.
- Bad: cast a raw image object in JSX, reuse copy-level audit state, or display an unconfigured audit
  as accepted.

### 6. Tests Required

- Mapper tests assert `validation.passed`, `audit.status`, and `repairCount` survive the wire-to-view
  projection.
- Component tests cover passed validation/audit, issue-code display, review-required image state, and
  the one-repair label.
- `make frontend-check` must pass generated-contract drift, strict TypeScript, lint, tests, and build.

### 7. Wrong vs Correct

#### Wrong

```tsx
const audit = (response.image as { audit?: { passed?: boolean } }).audit;
return <span>{audit?.passed ? "通过" : "失败"}</span>;
```

#### Correct

```typescript
const materialPackage = mapMaterialPackage(response);
return <ImageQualitySummary image={materialPackage.image} />;
```

## Error typing

Translate transport failures into a small typed client error containing safe code, message,
request ID, retryability, and status. Components should branch on codes/status rather than parsing
message strings. Unknown exceptions stay unknown until translated at the feature boundary.

## Forbidden patterns

- Explicit or implicit `any` in application code.
- `as unknown as T` to bypass the generated API contract.
- Non-null assertions on API/query data without an immediately preceding invariant check.
- Handwritten copies of backend request/response schemas.
- Stringly typed pipeline/audit state when a generated or discriminated union exists.
- Type assertions used to hide incomplete handling of no-topic or failed states.
- Editing generated API files.
