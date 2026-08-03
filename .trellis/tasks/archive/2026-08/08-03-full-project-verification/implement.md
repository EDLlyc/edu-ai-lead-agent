# Verification Plan

## Ordered Gates

1. Capture repository status and current migration head; read Makefile/README command contracts.
2. Run `make doctor` and retain the complete result. If it fails, run the underlying checks enough
   to distinguish an environment failure from a stale assertion.
3. Run `docker compose config` (through the repository target when available).
4. Start/reuse local infrastructure with `make infra-up`; wait for PostgreSQL and MinIO health.
5. Run `make migrate`, `make infra-status`, and the schema/API contract checks.
6. Run backend unit and integration tests, then the full backend quality gates.
7. Run frontend contract, formatting, lint, typecheck, tests, and production build.
8. Run `make check` once as the aggregate regression gate, avoiding repeated paid/provider tests.
9. Start/reuse the API stack as needed and run the documented health/readiness smoke request.
10. Summarize verified gates, unverified provider paths, blockers, and actionable defects.

## Review Gates

- Do not modify product code during the first pass.
- If a command is unavailable or blocked by the environment, record the exact reason and continue
  with independent checks.
- Do not rerun an expensive or paid path merely to obtain a prettier log.
- Before finalizing, compare the reported migration head with the latest migration file and the
  doctor script's expectation.

## Validation Commands

```text
make doctor
make check
make backend-integration-test
make infra-up
make migrate
make infra-status
make api-contract-check
make frontend-check
```

The exact commands actually run and their exit codes are the final evidence; this list is the
planned baseline, not a claim that every command has passed.
