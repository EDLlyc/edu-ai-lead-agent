# Prior Fast-Path Summary

Source: `.trellis/tasks/08-15-zhipu-ocr-provider-rejection/result.md`, especially the successful
fast-path section around lines 1208-1265 and the earlier failed-attempt evidence.

## Proven successful order

- terminal ordinary-business state and 15-second zero-actionable baseline;
- dependency-aware quiescence with dispatcher first;
- fresh PostgreSQL/source/env/marker/image rollback evidence;
- exact source/image activation and no-op migration;
- dependency-order restore with dispatcher last;
- 15-30 second stable aggregate/provider/WeCom/log sample.

## Pitfalls that must not recur

- Do not infer archive image ID from the config digest; validate OCI/classic graphs and full IDs.
- Include root `alembic.ini` and `pyproject.toml` in the source manifest.
- Import exactly the Compose entrypoint modules; acquisition scheduler is `app.scheduler_main`.
- Normalize candidate 0664/0775 semantic modes while preserving stricter active 0600/0700 modes.
- Use a fixed trusted root-owned same-device temporary directory; reject symlink/owner/mode drift.
- Never stream a remote script through stdin while Compose/Docker children can consume it; execute a
  physical mode-0600 script with child stdin `/dev/null`.
- `pg_restore` catalog validation needs container stdin (`docker exec -i`).
- Checkers use actual manifest filenames/paths; prior false mismatches came from guessed backup
  suffixes and filenames.
- A script assertion failure after quiescence must recover exactly once; never improvise or rerun.

## Scope distinction

The current dirty OCR driver contains useful later safety hardening but is not an authorized
executable input for this release. The new task-local broad-release operator may reuse the relevant
reviewed controls under independent review, but it remains separate from the authoritative Codeup
application payload.
