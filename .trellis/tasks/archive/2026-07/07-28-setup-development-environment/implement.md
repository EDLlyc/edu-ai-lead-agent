# Development Environment Implementation Plan

## 1. Root Configuration

- Expand `.gitignore` for backend/frontend build, test, tool, log, and local runtime artifacts.
- Update `environment.yml` while keeping `name: edu-ai`, Python 3.11, and pip.
- Add `.env.example`, `compose.yaml`, `Makefile`, and a setup-focused `README.md`.
- Validate that no command deletes volumes or overwrites real secrets by default.

## 2. Backend Toolchain and Minimal Shell

- Create `backend/pyproject.toml` with runtime dependencies and a `dev` optional-dependency group.
- Configure Ruff, strict mypy/Pyright-equivalent behavior, pytest, asyncio tests, and coverage.
- Add the minimal package/settings/FastAPI health shell and one test proving import and health
  behavior. Do not add product pipeline modules.
- Install with the `edu-ai` interpreter using an editable development install.

## 3. Frontend Toolchain and Minimal Shell

- Scaffold React + TypeScript + Vite with npm.
- Add the initial API/server-state packages and development quality tools required by the specs.
- Enable strict TypeScript options and add scripts for format/lint/typecheck/test/build.
- Keep the UI as a minimal environment-verification shell without material-package behavior.
- Commit the npm lockfile.

## 4. Containerized Infrastructure

- Select explicit compatible image tags for PostgreSQL/pgvector, MinIO, and MinIO client.
- Add named volumes, loopback-bound configurable ports, restart behavior suitable for development,
  and health checks.
- Add the idempotent pgvector initialization SQL and MinIO bucket initialization service.
- Render and start the stack, then verify pgvector and object storage readiness.

## 5. Developer Commands and Documentation

- Add Make targets for setup, infrastructure lifecycle, doctor, backend checks, frontend checks,
  and combined checks.
- Document fresh-clone and existing-environment paths, WSL2 notes, port overrides, troubleshooting,
  and safe shutdown/reset procedures.
- Document that company AI credentials remain blank until a later integration task.

## 6. Validation

Run and record:

```bash
conda run --name edu-ai python -m pip install -e "./backend[dev]"
docker compose config
docker compose up -d
docker compose ps
conda run --name edu-ai ruff check backend
conda run --name edu-ai mypy backend/app
conda run --name edu-ai pytest backend
npm ci --prefix frontend
npm run lint --prefix frontend
npm run typecheck --prefix frontend
npm run test --prefix frontend -- --run
npm run build --prefix frontend
make doctor
git diff --check
git status --short
```

Also query PostgreSQL for the installed `vector` extension and exercise the MinIO health/bucket
check defined by the selected images.

## Review Gates

- All dependency downloads require the normal network approval path.
- Do not run `docker compose down -v`, remove the Conda environment, or delete `node_modules`
  without an explicit recovery need.
- If a package/image version is incompatible, update manifests and lockfiles together and record
  the reason in the task research or design before retrying.
- Before completion, update the greenfield specs with the real setup/source/test paths introduced
  by this task.
