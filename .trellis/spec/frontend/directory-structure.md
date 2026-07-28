# Frontend Directory Structure

## Contract status

The React + TypeScript + Vite environment shell now has real app/provider/style/test paths under
[`frontend/src`](../../../frontend/src). The feature directories in the following tree remain the
target for the first material-package vertical slice; do not treat the environment page as a
product feature.

Implemented shell paths:

- [`src/main.tsx`](../../../frontend/src/main.tsx) only bootstraps React and providers.
- [`src/app/providers.tsx`](../../../frontend/src/app/providers.tsx) owns the TanStack Query client.
- [`src/app/App.tsx`](../../../frontend/src/app/App.tsx) renders the environment verification page.
- [`src/app/CommandCard.tsx`](../../../frontend/src/app/CommandCard.tsx) owns accessible command
  copy feedback.
- [`src/lib/api/client.ts`](../../../frontend/src/lib/api/client.ts) owns the generated-contract
  transport and configured API base URL.
- [`src/lib/api/generated/schema.d.ts`](../../../frontend/src/lib/api/generated/schema.d.ts) is
  generated from the checked-in FastAPI OpenAPI document and is never edited manually.
- [`vite.config.ts`](../../../frontend/vite.config.ts) loads the repository-root `.env` so
  `VITE_API_BASE_URL` stays paired with the backend host port without exposing unprefixed secrets.
- [`src/app/App.test.tsx`](../../../frontend/src/app/App.test.tsx) covers boundaries, copy feedback,
  and automated accessibility.

## Target layout

```text
frontend/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
└── src/
    ├── app/
    │   ├── App.tsx
    │   ├── providers.tsx
    │   └── router.tsx
    ├── components/
    │   └── ui/
    ├── features/
    │   ├── material-packages/
    │   │   ├── api/
    │   │   ├── components/
    │   │   ├── hooks/
    │   │   ├── pages/
    │   │   └── tests/
    │   └── pipeline-runs/
    │       ├── api/
    │       ├── components/
    │       └── hooks/
    ├── lib/
    │   ├── api/
    │   │   ├── generated/
    │   │   └── client.ts
    │   ├── clipboard.ts
    │   └── download.ts
    ├── styles/
    │   ├── globals.css
    │   └── tokens.css
    ├── test/
    │   └── setup.ts
    ├── main.tsx
    └── vite-env.d.ts
```

## Ownership rules

### App shell

`src/app/` owns provider composition, routing, error boundaries, and application-level layout.
It does not own feature API calls or material-package rendering details. Keep `main.tsx` limited to
bootstrapping the app.

### Features

A feature owns its pages, domain-specific components, query/mutation hooks, key factory, and view
mapping. Import another feature through its explicit public exports when needed; do not reach into
unrelated internal directories.

The first vertical slice should center on `material-packages`: load a package, display selected
topic and provenance, copy text, download the image, and show validation/audit state. A separate
`pipeline-runs` feature maps generated API states such as `queued`, `running`, `no_topic`,
`awaiting_manual_use`, and `failed` into presentation states without coupling polling logic to
presentation components.

### Shared UI and libraries

`src/components/ui/` contains reusable visual primitives with no product data-fetching knowledge,
such as `Button`, `StatusBadge`, or `VisuallyHidden`. Do not move a component there until at least
two features need the abstraction.

`src/lib/api/generated/` is generated from FastAPI OpenAPI and never edited manually.
`src/lib/api/client.ts` configures the typed transport, base URL, authentication when introduced,
request IDs, and shared error translation. Browser capability helpers such as clipboard/download
belong in named modules, not a catch-all `utils.ts`.

### Styles and assets

Use CSS custom properties in `tokens.css` for color, spacing, type, focus, and surface tokens.
Use CSS Modules next to feature/components for scoped styles as the initial default. Global CSS is
limited to reset/base behavior and application tokens. Static assets belong under the feature that
owns them or Vite's public directory only when they require a stable public URL.

## Naming and imports

- React component files and exported components: `PascalCase.tsx`.
- Hooks: `useSomething.ts`; functions and variables: `camelCase`.
- CSS Modules: `ComponentName.module.css`.
- Tests: `ComponentName.test.tsx` or `useSomething.test.ts` next to the feature code or in its
  declared test folder.
- Generated files remain in their generator-defined naming scheme.
- Prefer configured absolute aliases such as `@/features/...` for cross-directory imports and
  relative imports within a small local folder. Do not create long `../../../` chains.

## Avoid

- A root `components/` directory filled with feature-specific screens.
- API calls directly in presentation components.
- Handwritten copies of OpenAPI request/response interfaces.
- Global stores for all server responses and form fields.
- A generic `helpers.ts` or `types.ts` spanning unrelated domains.
- Social-platform SDKs, credentials, automated posting routes, or “publish now” UI.
- Leaving this proposed tree uncited after real source exists.
