# Focused Quality Contract for Digital IP Library

This task is local-only and changes a read-only backend projection, generated OpenAPI types,
frontend presentation/localStorage, and deterministic fixture eval. The relevant executable quality
contract distilled from `.trellis/spec/backend/quality-guidelines.md:220-360,892-920` is:

- During implementation, run only affected unit/API/component tests and scoped format/lint/type
  checks. Batch related edits before rerunning gates.
- Because Pydantic/OpenAPI changes, regenerate the checked-in OpenAPI and frontend client and fail
  on drift.
- There is no migration, write repository, worker, scheduler, or provider change, so PostgreSQL
  locking/integration, Doctor, Compose, live source, provider, and deployment checks are outside the
  focused task unless a concrete implementation change crosses those boundaries.
- The final local handoff must record the exact focused commands, `git diff --check`, and any
  unavailable tooling. The user explicitly waived repeated/full repository suites for this task.
- API tests cover the safe negative path: missing/malformed visual manifest yields typed
  unavailable state and never leaks filesystem paths, object keys, bytes, raw exceptions, secrets,
  or private content.
- Frontend tests cover generated-type consumption, empty/error/ready states, localStorage runtime
  validation, bounded feedback, accessibility, and absence of publishing actions.
- Keep evidence and brand knowledge separate at every type and response boundary. Digital-IP
  context remains `evidence_eligible=false`.
- Do not add social publishing, provider calls, unbounded retries, hidden exceptions, blocking I/O
  in async handlers, or a second implementation of existing retrieval/visual-selection logic.
- Human publication remains mandatory; this local feature has no server-side feedback write,
  automatic activation, or automatic knowledge learning.

Relevant frontend contracts are loaded directly from:

- `.trellis/spec/frontend/type-safety.md` for generated wire types and localStorage validation;
- `.trellis/spec/frontend/quality-guidelines.md` for component/accessibility/security checks;
- `.trellis/spec/frontend/brand-knowledge-workspace.md` for internal/manual-only product behavior.
