#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

conda_env_name="${CONDA_ENV:-edu-ai}"

pass() { printf '  [ok] %s\n' "$1"; }
fail() { printf '  [error] %s\n' "$1" >&2; exit 1; }
require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing command: $1"
}
print_version() {
  local label="$1"
  shift
  local version_output
  version_output="$("$@" 2>&1)" || fail "Unable to read $label version"
  version_output="${version_output%%$'\n'*}"
  printf '  %-18s %s\n' "$label" "$version_output"
}
require_healthy_service() {
  local service="$1"
  local container_id
  local health_status

  container_id="$(docker compose ps -q "$service")"
  [[ -n "$container_id" ]] || fail "$service is not running; run 'make infra-up'"
  health_status="$(
    docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
      "$container_id"
  )"
  [[ "$health_status" == "healthy" ]] \
    || fail "$service is not healthy (current: $health_status); run 'make infra-logs'"
  pass "$service is healthy"
}

printf 'Edu AI development environment doctor\n'
for command_name in conda docker node npm make curl; do
  require_command "$command_name"
done

printf '\nTool versions\n'
print_version "Conda" conda --version
print_version "Docker" docker --version
print_version "Docker Compose" docker compose version
print_version "Node.js" node --version
print_version "npm" npm --version
print_version "Make" make --version
print_version "curl" curl --version

docker info >/dev/null 2>&1 || fail "Docker daemon is unavailable; start Docker and retry"
pass "Docker daemon is available"

python_version="$(conda run --name "$conda_env_name" python --version 2>&1)" \
  || fail "Conda environment '$conda_env_name' is unavailable"
pass "Conda environment '$conda_env_name' is available ($python_version)"

conda run --name "$conda_env_name" python -c 'import fastapi, pydantic, sqlalchemy' >/dev/null \
  || fail "Backend dependencies are not installed; run 'make setup-backend'"
pass "Backend dependencies import successfully"

conda run --name "$conda_env_name" python -c \
  'import asyncio; from app.api_main import healthz; response = asyncio.run(healthz()); assert response.status == "ok"' \
  >/dev/null || fail "Backend health shell failed; run 'make backend-check'"
pass "Backend health shell responds successfully"

[[ -d frontend/node_modules ]] || fail "Frontend dependencies are missing; run 'make setup-frontend'"
[[ -x frontend/node_modules/.bin/vite ]] \
  || fail "Vite executable is missing; run 'make setup-frontend'"
pass "Frontend dependencies and Vite build tool are installed"

docker compose config --quiet || fail "Compose configuration is invalid"
pass "Compose configuration renders"

require_healthy_service postgres
require_healthy_service minio

vector_version="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT extversion FROM pg_extension WHERE extname = '\''vector'\'';"'
)"
[[ -n "$vector_version" ]] || fail "pgvector extension is not installed"
pass "pgvector extension $vector_version is installed"

minio_address="$(docker compose port minio 9000)"
[[ -n "$minio_address" ]] || fail "Unable to resolve the MinIO host port"
curl --fail --silent "http://${minio_address}/minio/health/live" >/dev/null \
  || fail "MinIO health endpoint is unavailable"
pass "MinIO health endpoint is ready"

docker compose run --rm --no-deps --entrypoint /bin/sh minio-init -c \
  '/usr/bin/mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && /usr/bin/mc stat "local/$MINIO_BUCKET" >/dev/null' \
  >/dev/null || fail "MinIO development bucket is unavailable; run 'make infra-up'"
pass "MinIO development bucket is available"

printf 'Environment doctor completed successfully.\n'
