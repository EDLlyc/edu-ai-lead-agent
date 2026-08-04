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

conda run --name "$conda_env_name" python -c \
  'import alembic, fastapi, langgraph, minio, pgvector, psycopg, pydantic, sqlalchemy; from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver' \
  >/dev/null \
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

migration_revision="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT version_num FROM alembic_version;"' \
    2>/dev/null || true
)"
[[ "$migration_revision" == "20260803_0014" ]] \
  || fail "Database migration is not at head; run 'make migrate'"
pass "Alembic migration is at $migration_revision"

governance_table_count="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM unnest(ARRAY['\''governance_runs'\'','\''governance_jobs'\'','\''governance_attempts'\'','\''article_occurrences'\'','\''normalized_articles'\'','\''normalized_passages'\'','\''candidate_analyses'\'','\''analysis_facts'\'','\''evidence_bindings'\'','\''analysis_entities'\'','\''analysis_categories'\'','\''article_embeddings'\'','\''duplicate_relations'\'','\''event_clusters'\'','\''event_cluster_versions'\'','\''event_memberships'\'','\''event_assignment_decisions'\'','\''model_invocations'\'','\''checkpoint_migrations'\'','\''checkpoints'\'','\''checkpoint_blobs'\'','\''checkpoint_writes'\'']) AS required(name) WHERE to_regclass('\''public.'\'' || name) IS NOT NULL;"'
)"
[[ "$governance_table_count" == "22" ]] \
  || fail "Governance/checkpoint schema is incomplete; run 'make migrate'"
pass "Governance and LangGraph checkpoint tables are installed"

topic_selection_table_count="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM unnest(ARRAY['\''topic_scoring_configs'\'','\''topic_selection_runs'\'','\''topic_selection_jobs'\'','\''topic_scores'\'','\''daily_topic_selections'\'']) AS required(name) WHERE to_regclass('\''public.'\'' || name) IS NOT NULL;"'
)"
[[ "$topic_selection_table_count" == "5" ]] \
  || fail "Topic-selection schema is incomplete; run 'make migrate'"
pass "Topic-selection tables are installed"

brand_knowledge_table_count="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM unnest(ARRAY['\''brand_documents'\'','\''brand_document_versions'\'','\''brand_ingestion_jobs'\'','\''brand_ingestion_attempts'\'','\''brand_chunks'\'','\''brand_chunk_embeddings'\'']) AS required(name) WHERE to_regclass('\''public.'\'' || name) IS NOT NULL;"'
)"
[[ "$brand_knowledge_table_count" == "6" ]] \
  || fail "Brand-knowledge schema is incomplete; run 'make migrate'"
pass "Brand-knowledge tables are installed"

brand_embedding_vector_type="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT format_type(attribute.atttypid, attribute.atttypmod) FROM pg_attribute AS attribute JOIN pg_class AS relation ON relation.oid = attribute.attrelid WHERE relation.relname = '\''brand_chunk_embeddings'\'' AND attribute.attname = '\''vector'\'' AND NOT attribute.attisdropped;"'
)"
[[ "$brand_embedding_vector_type" == "vector(2048)" ]] \
  || fail "Brand embedding column is not vector(2048); run 'make migrate'"
pass "Brand embedding column is $brand_embedding_vector_type"

checkpoint_revision="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT max(v) FROM checkpoint_migrations;"'
)"
[[ "$checkpoint_revision" == "9" ]] \
  || fail "LangGraph checkpoint migration is incomplete; run 'make migrate'"
pass "LangGraph checkpoint schema is at migration $checkpoint_revision"

embedding_vector_type="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT format_type(attribute.atttypid, attribute.atttypmod) FROM pg_attribute AS attribute JOIN pg_class AS relation ON relation.oid = attribute.attrelid WHERE relation.relname = '\''article_embeddings'\'' AND attribute.attname = '\''vector'\'' AND NOT attribute.attisdropped;"'
)"
[[ "$embedding_vector_type" == "vector(2048)" ]] \
  || fail "Governance embedding column is not vector(2048); run 'make migrate'"
pass "Governance embedding column is $embedding_vector_type"

source_count="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM sources WHERE active_version_id IS NOT NULL;"'
)"
[[ "$source_count" == "8" ]] || fail "Source registry is not ready; run 'make seed-sources'"
pass "Eight approved source profiles are active"

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
