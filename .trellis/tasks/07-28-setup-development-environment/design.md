# Development Environment Design

## Design Summary

The local environment uses host-native developer runtimes and containerized infrastructure:

```text
Conda edu-ai (Python 3.11)        Node.js 20 + npm
        |                               |
 backend editable package         frontend Vite shell
        |                               |
        +------------ localhost --------+
                         |
             Docker Compose infrastructure
              PostgreSQL/pgvector + MinIO
```

This keeps code editing, tests, and debugger startup fast while matching the report's durable
services. Application containers are deferred until runtime entry points exist and production
deployment is designed.

## Target Repository Shape

```text
.
├── .env.example
├── compose.yaml
├── environment.yml
├── Makefile
├── README.md
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── __init__.py
│   │   ├── api_main.py
│   │   └── core/config.py
│   └── tests/test_health.py
├── frontend/
│   ├── package.json
│   ├── package-lock.json
│   ├── tsconfig*.json
│   ├── vite.config.ts
│   └── src/
└── infra/postgres/init/001-enable-vector.sql
```

The source shells exist only to verify dependency loading, settings, test runners, and build tools.
They must not claim to implement the product pipeline.

## Dependency Ownership

### Python

`environment.yml` owns the Python interpreter and pip. `backend/pyproject.toml` owns runtime and
development Python packages. This avoids duplicating every Python dependency in both Conda and pip
metadata while keeping the environment name stable.

The documented setup is:

```bash
conda env create -f environment.yml
conda activate edu-ai
python -m pip install -e "./backend[dev]"
```

Existing developers use `conda env update -n edu-ai -f environment.yml` before the editable pip
install. The workflow does not use `--prune` by default because it can remove user-installed
diagnostic tools.

### JavaScript

Use the already available Node.js 20 and npm. Commit `package-lock.json` and use `npm ci` for
reproduction. Do not introduce pnpm/Yarn/Corepack unless a later task records a reason.

### Container images

Use PostgreSQL 16 with a pgvector-enabled image and compatible MinIO/minio-client images. Pin
explicit tags selected during implementation; do not use floating `latest` tags in the committed
Compose file. Record image/tag choices in README.

## Compose Services

### PostgreSQL

- Default host port: `5432`, overridable through `.env`.
- Named volume for data.
- `pg_isready` health check.
- Initialization mount executes `CREATE EXTENSION IF NOT EXISTS vector;`.
- Local credentials come from `.env`, seeded from `.env.example` placeholders.

### MinIO

- Default API/console ports: `9000` and `9001`, both overridable.
- Named volume for object data.
- Health check using a command available in the selected pinned image.
- A one-shot client/init service creates the development bucket idempotently.

Compose shutdown defaults to `docker compose down`, never `down -v`. Volume deletion is an
explicit manual recovery action documented separately.

## Configuration Contract

`.env.example` defines local-only variables for app environment, timezone, database, object
storage, ports, and blank company AI-platform settings. Application settings use Pydantic Settings
with explicit aliases and validation. Empty provider credentials are permitted for health checks
because provider calls are out of scope.

The backend database URL uses the host-mapped PostgreSQL port because backend processes run on the
host in this design. Future application containers will require a separate internal service URL or
Compose override rather than silently reusing `localhost`.

## Developer Commands

Root commands wrap, but do not hide, the underlying tools:

- setup/update backend dependencies;
- install frontend dependencies;
- start, stop, inspect, and log infrastructure;
- run backend and frontend checks independently;
- run all checks;
- doctor/smoke-check tool versions, imports, configuration, Compose rendering, database vector
  extension, MinIO readiness, backend health, and frontend build availability.

Failures must name the missing command/service and the remediation command. Commands must not
download dependencies or delete data unless their names/documentation clearly say so.

## Compatibility and Security

- Primary target: Ubuntu/WSL2 with Bash, Make, Conda, Docker Compose, Node.js, npm, and curl.
- Avoid a required `jq` dependency because it is absent locally.
- Keep ports configurable to coexist with other projects.
- Do not mount the Docker socket, run privileged containers, or expose infrastructure to non-local
  interfaces by default.
- Do not place secrets in Compose YAML, package scripts, source, tests, or logs.
- The GitHub repository remains private, but private visibility is not treated as a substitute for
  secret hygiene.

## Rollback

- Before implementation, no application data exists.
- If setup fails, stop containers without deleting volumes and revert the task's files/commit.
- Dependency installs are reversible by recreating the Conda environment and `node_modules` from
  committed manifests; neither directory is tracked.
- Do not remove named volumes automatically during rollback.
