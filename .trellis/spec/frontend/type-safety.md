# Type Safety

## Initial TypeScript contract

Compile with TypeScript strict mode, including `noUncheckedIndexedAccess` and
`exactOptionalPropertyTypes` unless a documented tool incompatibility prevents it. The first slice
must add the actual `tsconfig`, OpenAPI generation command, generated paths, and examples to this
guide.

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
