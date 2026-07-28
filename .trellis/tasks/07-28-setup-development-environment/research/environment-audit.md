# Local Development Environment Audit

## Observed on 2026-07-28

| Capability | Observed state |
|---|---|
| Operating system | Ubuntu 24.04 tooling under WSL2 (`x86_64`) |
| Docker | 29.1.3 |
| Docker Compose | 2.40.3 |
| Node.js | 20.20.2 |
| npm | 10.8.2 |
| pnpm/Corepack | Not available on the current PATH; npm is the lowest-complexity default |
| Conda environment | `edu-ai` |
| Python | 3.11.15 |
| Python packages | Only pip/setuptools/wheel/packaging are installed |
| Make | Available |
| jq | Not available; developer commands must not require it |
| Trellis | 0.6.9, Codex hooks active |
| GitHub | Private repository `EDLlyc/edu-ai-lead-agent`, branch `main` |

## Repository Evidence

- `environment.yml` currently owns only Python 3.11 and pip.
- `.trellis/spec/backend/` selects FastAPI/Pydantic, SQLAlchemy 2 async, PostgreSQL/pgvector,
  separate process boundaries, strict checks, and real PostgreSQL integration behavior.
- `.trellis/spec/frontend/` selects React/TypeScript/Vite, npm-compatible generated API tooling,
  TanStack Query, strict types, tests, accessibility, and build checks.
- No backend/frontend application manifests or source files exist yet.

## Planning Consequences

- Use npm rather than introducing another JavaScript package manager.
- Use Conda for the interpreter and `backend/pyproject.toml` for package dependency truth.
- Run developer application processes on the host and infrastructure in Compose for the first
  slice; defer application containers.
- Add configurable loopback ports because WSL2 commonly hosts multiple local projects.
- Network access will be required during implementation for PyPI/npm packages and container
  images. The committed result must include lock/pin information so later setup is reproducible.
