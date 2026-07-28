# State Management

## Initial state model

Use the smallest owner for each state category. TanStack Query is the initial server-state cache;
React component state/reducers own transient interactions; URL state owns shareable navigation and
filters. No general-purpose global state library is required for the first vertical slice.

This is a greenfield choice. Revisit it with actual usage evidence after the material-package flow
exists rather than adding a store preemptively.

## State categories

| Category | Owner | Examples |
|---|---|---|
| Server state | TanStack Query | Pipeline run status, material package, source/evidence metadata |
| URL state | Router/search parameters | Selected package/run ID, date or status filter, pagination |
| Local UI state | `useState` or `useReducer` | Expanded evidence row, active tab, copy feedback, dialog visibility |
| Form state | Local controlled state; add a form library only for demonstrated complexity | Manual run date, internal feedback form |
| Stable app context | Narrow React context/provider | Typed API/Query client, authentication session when introduced, locale/theme if needed |

Do not persist generated copy or package responses in local storage as a second database. The API
and database are authoritative. If a small user preference is persisted, version and validate it
on read and avoid sensitive data.

## Server state

Query keys are owned by the feature and include all request inputs. Define explicit freshness and
polling behavior:

- Poll generated API run states `queued` and `running` at a bounded interval.
- Stop polling for `awaiting_manual_use`, `completed`, `no_topic`, `failed`, or `cancelled`; map
  those wire values to feature-level presentation states in one pure selector.
- Invalidate package/run queries after a successful enqueue or permitted feedback mutation.
- Render cached data as stale when appropriate; do not present it under a different run ID.
- Avoid optimistic updates for generation/audit outcomes that only the backend can determine.

Transform wire data through pure selectors/view-model mappers. Do not duplicate the same response
in Query cache, Context, and component state.

## Local and derived state

Keep UI-only state next to the component that owns the interaction. Derive values during render or
with a pure function. Use `useMemo` only when computation is measurably expensive or referential
stability is part of a child/hook contract.

A reducer is appropriate for a multi-step local interaction with explicit events, but it must not
reimplement the backend pipeline state machine. Backend status remains server state.

## URL state

Use path parameters for resource identity and search parameters for shareable filters/sort/page.
Parse and validate URL input before using it. Provide stable defaults and omit default values from
the URL when practical. Do not put copy text, source excerpts, signed URLs, or secrets in query
parameters.

## When shared client state is justified

Promote state beyond a feature only when multiple distant consumers need the same client-owned,
rapidly changing value and URL/server state is not suitable. Document the owner, lifetime, reset
behavior, and persistence policy. Prefer a narrow context before adding a store dependency for a
single value.

## Avoid

- Redux/Zustand or another store solely to hold API responses.
- Mirroring a query result in `useState` with an effect.
- Treating local “copy complete” state as proof of server-side workflow completion.
- Persisting sensitive source/model content in local/session storage.
- Frontend-only transitions that claim generation succeeded before the API reports it.
- State or actions for automatic social publishing.
