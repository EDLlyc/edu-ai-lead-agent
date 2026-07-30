# Hook Guidelines

## Implemented hook contract

Use custom hooks to compose React state/effects and the typed API client, not to hide arbitrary
business logic. TanStack Query owns server state. The first implemented feature uses
`features/brand/hooks.ts`: one key factory, a document query with active-job-only polling, and
upload/activate/deactivate mutations that invalidate that query.

## Server-state hooks

Feature API modules define typed transport calls. Feature hooks own query keys, freshness/polling,
and invalidation. Components consume the hook result and do not call `fetch` directly.

```tsx
export const materialPackageKeys = {
  all: ["material-packages"] as const,
  detail: (id: string) => [...materialPackageKeys.all, "detail", id] as const,
};

export function useMaterialPackage(id: string) {
  return useQuery({
    queryKey: materialPackageKeys.detail(id),
    queryFn: ({ signal }) => getMaterialPackage({ id, signal }),
    enabled: id.length > 0,
  });
}
```

- Include every input that changes a request in the query key.
- Pass the query abort signal to the HTTP client.
- Configure polling only while the generated API run status is `queued` or `running`. Stop for
  `awaiting_manual_use`, `completed`, `no_topic`, `failed`, or `cancelled`.
- Map wire states to explicit UI states (`awaiting_manual_use` -> ready, `no_topic` -> no-topic)
  in one pure feature mapper. Treat 404, no-topic, cancellation, pipeline failure, and network
  failure as different UI states.
- Use `select` or a pure mapper for stable view data, not an effect that copies query data into
  local state.

## Mutations

Mutations are for API-side changes such as enqueueing a manual run or recording permitted internal
feedback. Invalidate or update only the relevant query keys after success. Make duplicate submits
visible and rely on backend idempotency; a disabled button alone is not correctness.

Clipboard copy and file download are browser effects, not server-state mutations. Wrap browser
capability details in small helpers/hooks that expose success/error status and provide an accessible
announcement. Do not send content to a third-party clipboard/download service.

## Custom hook design

- Names start with `use` and describe the capability (`usePipelineRun`, `useCopyFeedback`).
- Return a stable, narrow object with named fields; avoid large pass-through bags.
- Keep pure scoring, formatting, evidence mapping, and validation as ordinary functions.
- Do not create a hook only to rename `useState`.
- Effects synchronize with external systems. Do not use effects to calculate render data, mirror
  props/query results, or initiate event-driven actions that belong in a handler.
- List complete dependencies. Do not silence the hooks linter to make an effect run less often.
- Clean up subscriptions, timers, and object URLs; account for React Strict Mode development
  behavior.

## Authentication and request context

When authentication is introduced, configure it in the shared API transport/provider rather than
accepting tokens as hook arguments or storing secrets in feature state. Propagate request IDs and
display safe correlation IDs in error states without exposing headers or credentials.

## Tests

Test server-state hooks with a fresh QueryClient per test and controlled network handlers. Cover
loading, success, typed API error, cancellation, retry policy, polling stop conditions, and cache
invalidation. Test clipboard/download helpers for success, unavailable APIs, rejected permissions,
and accessible status text.

## Avoid

- `useEffect(() => fetch(...), [])` for server data.
- Query keys built from unstable objects without normalization.
- Infinite browser or TanStack retries that conflict with backend retry semantics.
- Copying query responses into a global store.
- Hooks that expose raw social publishing behavior or credentials.
- Swallowing clipboard/download failure while announcing success.
