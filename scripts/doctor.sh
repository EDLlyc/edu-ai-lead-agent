#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

conda_env_name="${CONDA_ENV:-edu-ai}"
doctor_python="${DOCTOR_PYTHON:-}"

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
required_commands=(docker node npm make curl)
if [[ -z "${doctor_python}" ]]; then
  required_commands+=(conda)
fi
for command_name in "${required_commands[@]}"; do
  require_command "$command_name"
done

printf '\nTool versions\n'
if [[ -n "${doctor_python}" ]]; then
  [[ -x "${doctor_python}" ]] || fail "DOCTOR_PYTHON is not executable"
  print_version "Python" "${doctor_python}" --version
else
  print_version "Conda" conda --version
fi
print_version "Docker" docker --version
print_version "Docker Compose" docker compose version
print_version "Node.js" node --version
print_version "npm" npm --version
print_version "Make" make --version
print_version "curl" curl --version

docker info >/dev/null 2>&1 || fail "Docker daemon is unavailable; start Docker and retry"
pass "Docker daemon is available"

if [[ -n "${doctor_python}" ]]; then
  python_command=("${doctor_python}")
  python_version="$("${python_command[@]}" --version 2>&1)" \
    || fail "DOCTOR_PYTHON is unavailable"
  pass "Explicit Python environment is available ($python_version)"
else
  # Conda captures subprocess streams by default, which prevents Compose JSON pipelines from
  # reaching Python stdin. Live output preserves the same interpreter while keeping pipelines
  # byte-for-byte intact.
  python_command=(conda run --no-capture-output --name "${conda_env_name}" python)
  python_version="$("${python_command[@]}" --version 2>&1)" \
    || fail "Conda environment '$conda_env_name' is unavailable"
  pass "Conda environment '$conda_env_name' is available ($python_version)"
fi

"${python_command[@]}" -c \
  'import alembic, fastapi, langgraph, minio, pgvector, psycopg, pydantic, sqlalchemy; from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver' \
  >/dev/null \
  || fail "Backend dependencies are not installed; run 'make setup-backend'"
pass "Backend dependencies import successfully"

"${python_command[@]}" -c \
  'import asyncio; from app.api_main import healthz; response = asyncio.run(healthz()); assert response.status == "ok"' \
  >/dev/null || fail "Backend health shell failed; run 'make backend-check'"
pass "Backend health shell responds successfully"

[[ -d frontend/node_modules ]] || fail "Frontend dependencies are missing; run 'make setup-frontend'"
[[ -x frontend/node_modules/.bin/vite ]] \
  || fail "Vite executable is missing; run 'make setup-frontend'"
pass "Frontend dependencies and Vite build tool are installed"

docker compose config --quiet || fail "Compose configuration is invalid"
pass "Compose configuration renders"

docker compose --profile governance --profile content --profile wecom --profile ip-assets --profile official-account-weekly-dag --profile wechat-official-account-draft config --format json | \
  "${python_command[@]}" -c '
import json
import re
import sys

services = json.load(sys.stdin)["services"]
names = (
    "backend-migrate",
    "acquisition-api",
    "acquisition-scheduler",
    "acquisition-worker",
    "governance-scheduler",
    "governance-worker",
    "official-account-weekly-dag-worker",
    "wechat-official-account-draft-worker",
    "content-scheduler",
    "content-worker",
    "ip-asset-worker",
    "wecom-dispatcher",
)
images = [services[name].get("image") for name in names]
if any(not image for image in images) or len(set(images)) != 1:
    raise SystemExit("all application and migration services must share one APP_IMAGE")
image = images[0]
if image != "edu-ai-lead-agent-backend:local" and not re.fullmatch(
    r"[^@\s]+@sha256:[0-9a-f]{64}", image
):
    raise SystemExit("non-local APP_IMAGE must be a digest-only reference")
' >/dev/null || fail "Application services do not share the local-or-digest APP_IMAGE contract"
pass "All twelve application and migration services share one APP_IMAGE contract"

docker compose --profile official-account-weekly-dag config --format json | \
  "${python_command[@]}" -c '
import json
import sys

worker = json.load(sys.stdin)["services"]["official-account-weekly-dag-worker"]
command = worker.get("command", [])
expected = (
    "python",
    "-m",
    "app.official_account_weekly_dag_main",
    "worker",
    "--concurrency",
    "3",
    "--lease-seconds",
    "60",
    "--poll-seconds",
    "2",
)
if tuple(command) != expected:
    raise SystemExit("weekly DAG worker command or bounds drifted")
if worker.get("ports"):
    raise SystemExit("weekly DAG worker must not publish a network port")
mounts = worker.get("volumes", [])
if not any(item.get("target") == "/app/output" for item in mounts):
    raise SystemExit("weekly DAG worker output must use its durable volume")
' >/dev/null || fail "Official-account weekly DAG worker profile is invalid"
pass "Official-account weekly DAG worker is bounded, durable, and has no network port"

docker compose --profile wechat-official-account-draft config --format json | \
  "${python_command[@]}" -c '
import json
import sys

worker = json.load(sys.stdin)["services"]["wechat-official-account-draft-worker"]
if tuple(worker.get("command", [])) != (
    "python", "-m", "app.wechat_official_account_draft_main", "worker"
):
    raise SystemExit("WeChat draft worker entrypoint drifted")
if worker.get("ports"):
    raise SystemExit("WeChat draft worker must not publish a network port")
environment = worker.get("environment", {})
for key in (
    "WECHAT_MP_DRAFT_WORKER_ENABLED",
    "WECHAT_MP_DRAFT_AUTO_ENQUEUE_ENABLED",
    "WECHAT_MP_DRAFT_PRODUCTION_ENABLED",
    "WECHAT_MP_DRAFT_MIN_WEEK_START",
):
    if key not in environment:
        raise SystemExit(f"WeChat draft worker is missing {key}")
mounts = {item.get("target"): item for item in worker.get("volumes", [])}
inbox = mounts.get("/app/input/official-account-weekly-editions")
artifacts = mounts.get("/app/output/wechat-mp-draft-artifacts")
if inbox is None or inbox.get("read_only") is not True:
    raise SystemExit("WeChat draft weekly inbox must be a read-only volume")
if artifacts is None or artifacts.get("read_only") is True:
    raise SystemExit("WeChat draft artifact volume must be writable")
' >/dev/null || fail "WeChat Official Account draft worker profile is invalid"
pass "WeChat Official Account draft worker is optional, portless, and volume-isolated"

docker compose --profile ip-assets config --format json | \
  "${python_command[@]}" -c '
import json
import sys

services = json.load(sys.stdin)["services"]
worker = services["ip-asset-worker"]
environment = worker.get("environment", {})
if environment.get("IP_ASSET_HUB_ENABLED") != "true":
    raise SystemExit("IP asset worker profile must explicitly enable the hub")
if environment.get("IP_ASSET_WORKER_ENABLED") != "true":
    raise SystemExit("IP asset worker profile must explicitly enable its worker")
if worker.get("ports"):
    raise SystemExit("IP asset worker must not publish a network port")
for key in (
    "IP_ASSET_GENERATION_ENABLED",
    "IP_ASSET_LEASE_SECONDS",
    "IP_ASSET_HEARTBEAT_SECONDS",
    "IP_ASSET_MAX_ATTEMPTS",
    "VISUAL_EMBEDDING_PROVIDER_MODE",
):
    if environment.get(key) in (None, ""):
        raise SystemExit(f"IP asset worker requires bounded setting {key}")
' >/dev/null || fail "IP asset worker profile is invalid"
pass "IP asset worker is bounded and does not publish a network port"

[[ -s backend/requirements/runtime.lock && -s backend/requirements/dev.lock ]] \
  || fail "Python hash lockfiles are missing; run 'make python-lock'"
grep -q -- '--hash=sha256:' backend/requirements/runtime.lock \
  || fail "Runtime Python lock does not contain hashes"
grep -q '@sha256:' backend/Dockerfile \
  || fail "Backend Python base image is not digest-pinned"
grep -q -- '--require-hashes' backend/Dockerfile \
  || fail "Backend image does not enforce the runtime hash lock"
pass "Python locks and digest-pinned Docker build contract are present"

"${python_command[@]}" - <<'PY' >/dev/null \
  || fail "Migration compatibility declaration does not match the repository head"
import json
import sys
from pathlib import Path

sys.path.insert(0, "deploy/release")
from contract import alembic_head_from_blobs, load_compatibility_declaration

migrations = {
    str(path): path.read_bytes()
    for path in Path("backend/alembic/versions").glob("*.py")
    if not path.name.startswith("__")
}
head = alembic_head_from_blobs(migrations)
declaration = Path("deploy/release/migration-compatibility.json").read_bytes()
load_compatibility_declaration(declaration, head)
PY
pass "Migration compatibility declaration matches the single Alembic head"

docker compose --profile content config --format json | \
  "${python_command[@]}" -c '
import json
import sys

services = json.load(sys.stdin)["services"]
names = ("acquisition-api", "content-worker")
values = [services[name].get("environment", {}).get("IMAGE_MAX_ATTEMPTS") for name in names]
if any(value in (None, "") for value in values) or len(set(values)) != 1:
    raise SystemExit("acquisition-api and content-worker must share IMAGE_MAX_ATTEMPTS")
' >/dev/null || fail "Image retry attempt limit is not shared by API and content worker"
pass "Image retry attempt limit is shared by API and content worker"

docker compose --profile content config --format json | \
  "${python_command[@]}" -c '
import json
import sys

services = json.load(sys.stdin)["services"]
names = ("acquisition-api", "content-worker")
keys = (
    "IMAGE_DIVERSITY_ENABLED",
    "IMAGE_DIVERSITY_POLICY_VERSION",
    "IMAGE_VISUAL_BRIEF_VERSION",
    "IMAGE_DIVERSITY_SELECTOR_VERSION",
    "IMAGE_DIVERSITY_PROMPT_VERSION",
    "IMAGE_DIVERSITY_PIPELINE_VERSION",
    "IMAGE_PERCEPTUAL_HASH_VERSION",
    "IMAGE_SIMILARITY_POLICY_VERSION",
    "IMAGE_DIVERSITY_HISTORY_DAYS",
    "IMAGE_DIVERSITY_HISTORY_LIMIT",
    "IMAGE_SIMILARITY_THRESHOLD",
    "IMAGE_DIVERSITY_MAX_REGENERATIONS",
    "IMAGE_OCR_ENABLED",
    "IMAGE_OCR_MODEL",
    "IMAGE_OCR_MAX_INPUT_BYTES",
    "IMAGE_OCR_MAX_RESPONSE_BYTES",
    "IMAGE_OCR_TIMEOUT_SECONDS",
)
for key in keys:
    values = [services[name].get("environment", {}).get(key) for name in names]
    if any(value in (None, "") for value in values) or len(set(values)) != 1:
        raise SystemExit(f"image diversity setting {key} must be present and identical")
if services["acquisition-api"]["environment"]["IMAGE_DIVERSITY_MAX_REGENERATIONS"] != "1":
    raise SystemExit("image diversity permits exactly one regeneration")
def compose_bool(value):
    normalized = value.strip().casefold()
    if normalized in {"1", "on", "t", "true", "y", "yes"}:
        return True
    if normalized in {"0", "off", "f", "false", "n", "no"}:
        return False
    raise SystemExit("image feature flags must be valid boolean values")

environment = services["acquisition-api"]["environment"]
diversity_enabled = compose_bool(environment["IMAGE_DIVERSITY_ENABLED"])
ocr_enabled = compose_bool(environment["IMAGE_OCR_ENABLED"])
if diversity_enabled and ocr_enabled and environment["IMAGE_OCR_MODEL"] != "glm-ocr":
    raise SystemExit("controlled image OCR must use the reviewed glm-ocr model")
' >/dev/null || fail "Image-diversity settings are not shared by API and content worker"
pass "Image-diversity and bounded image-OCR settings are shared"

docker compose --profile content config --format json | \
  "${python_command[@]}" -c '
import json
import sys

services = json.load(sys.stdin)["services"]
names = ("acquisition-api", "content-worker")
keys = (
    "VISUAL_SEMANTIC_ENABLED",
    "VISUAL_EMBEDDING_PROVIDER_MODE",
    "VISUAL_EMBEDDING_MODEL",
    "VISUAL_EMBEDDING_DIMENSIONS",
    "VISUAL_EMBEDDING_INPUT_POLICY_VERSION",
    "VISUAL_EMBEDDING_TIMEOUT_SECONDS",
    "VISUAL_EMBEDDING_CONCURRENCY",
    "VISUAL_INDEX_LEASE_SECONDS",
)
for key in keys:
    values = [services[name].get("environment", {}).get(key) for name in names]
    if any(value in (None, "") for value in values) or len(set(values)) != 1:
        raise SystemExit(f"visual retrieval setting {key} must be present and identical")

def compose_bool(value):
    normalized = value.strip().casefold()
    if normalized in {"1", "on", "t", "true", "y", "yes"}:
        return True
    if normalized in {"0", "off", "f", "false", "n", "no"}:
        return False
    raise SystemExit("visual retrieval flag must be a valid boolean")

environment = services["acquisition-api"]["environment"]
enabled = compose_bool(environment["VISUAL_SEMANTIC_ENABLED"])
mode = environment["VISUAL_EMBEDDING_PROVIDER_MODE"]
if enabled and mode not in {"fake", "alibaba"}:
    raise SystemExit("enabled visual retrieval must use fake or alibaba mode")
if environment["VISUAL_EMBEDDING_MODEL"] != "qwen3-vl-embedding":
    raise SystemExit("visual retrieval model identity drifted")
if environment["VISUAL_EMBEDDING_DIMENSIONS"] != "2048":
    raise SystemExit("visual retrieval dimensions drifted")
if environment["VISUAL_EMBEDDING_INPUT_POLICY_VERSION"] != "brand-visual-embedding-input-v2":
    raise SystemExit("visual retrieval input policy drifted")
if enabled and mode == "alibaba":
    for key in ("VISUAL_EMBEDDING_ENDPOINT", "VISUAL_EMBEDDING_API_KEY"):
        values = [services[name].get("environment", {}).get(key) for name in names]
        if any(value in (None, "") for value in values) or len(set(values)) != 1:
            raise SystemExit(f"enabled Alibaba visual retrieval requires shared secret {key}")
' >/dev/null || fail "Visual-retrieval settings are invalid or inconsistent"
pass "Visual retrieval is bounded, shared, and provider-gated"

docker compose --profile content config --format json | \
  "${python_command[@]}" -c '
import json
import sys

services = json.load(sys.stdin)["services"]
names = ("acquisition-api", "content-scheduler", "content-worker")
keys = (
    "CONTENT_ENABLED",
    "CONTENT_SCORING_VERSION",
    "CONTENT_SELECTION_PRIORITY_RULE_VERSION",
    "CONTENT_LLM_RERANK_ENABLED",
    "CONTENT_LLM_RERANK_POLICY_VERSION",
    "CONTENT_LLM_RERANK_CANDIDATE_LIMIT",
    "CONTENT_LLM_RERANK_MAX_OUTPUT_TOKENS",
    "AI_PROVIDER_MODE",
)
for key in keys:
    values = [services[name].get("environment", {}).get(key) for name in names]
    if any(value in (None, "") for value in values) or len(set(values)) != 1:
        raise SystemExit(f"topic rerank setting {key} must be present and identical")

def compose_bool(value):
    normalized = value.strip().casefold()
    if normalized in {"1", "on", "t", "true", "y", "yes"}:
        return True
    if normalized in {"0", "off", "f", "false", "n", "no"}:
        return False
    raise SystemExit("topic rerank flags must be valid boolean values")

environment = services["content-worker"]["environment"]
if environment["CONTENT_SCORING_VERSION"] != "scoring-v1-preview.11-qualified-authoritative-priority":
    raise SystemExit("content selection must pin the qualified-authoritative scoring policy")
if environment["CONTENT_SELECTION_PRIORITY_RULE_VERSION"] != "qualified-authoritative-priority-v1":
    raise SystemExit("content selection must pin the qualified-authoritative priority policy")
if environment["CONTENT_LLM_RERANK_POLICY_VERSION"] != "topic-rerank-v4-minimal-order-contract":
    raise SystemExit("content selection must pin the v4 minimal-order policy")
if environment["CONTENT_LLM_RERANK_CANDIDATE_LIMIT"] != "8":
    raise SystemExit("content selection rerank pool must remain capped at eight")
if (
    compose_bool(environment["CONTENT_ENABLED"])
    and compose_bool(environment["CONTENT_LLM_RERANK_ENABLED"])
    and environment["AI_PROVIDER_MODE"] not in {"fake", "zhipu"}
):
    raise SystemExit("enabled content rerank must use fake or zhipu provider mode")
' >/dev/null || fail "Layered topic-rerank settings are invalid or inconsistent"
pass "Layered topic rerank is bounded, shared, and provider-gated only when content is enabled"

docker compose --profile governance --profile content --profile wecom config --format json | \
  "${python_command[@]}" -c '
import json
import sys

services = json.load(sys.stdin)["services"]
names = ("acquisition-api", "acquisition-scheduler", "content-scheduler", "content-worker", "wecom-dispatcher")
keys = (
    "CONTENT_SLOT_MODE_ENABLED",
    "CONTENT_MORNING_ENABLED",
    "CONTENT_NOON_ENABLED",
    "CONTENT_EVENING_ENABLED",
    "CONTENT_MORNING_TARGET_HOUR",
    "CONTENT_MORNING_TARGET_MINUTE",
    "CONTENT_NOON_TARGET_HOUR",
    "CONTENT_NOON_TARGET_MINUTE",
    "CONTENT_EVENING_TARGET_HOUR",
    "CONTENT_EVENING_TARGET_MINUTE",
    "CONTENT_SLOT_PREPARE_LEAD_MINUTES",
    "CONTENT_SLOT_DELIVERY_LATE_MINUTES",
    "CONTENT_SLOT_MAX_ITEMS",
    "CONTENT_SLOT_RANKING_VERSION",
    "WECOM_SLOT_PACKAGE_GAP_SECONDS",
)
for key in keys:
    values = [services[name].get("environment", {}).get(key) for name in names]
    if any(value in (None, "") for value in values) or len(set(values)) != 1:
        raise SystemExit(f"slot setting {key} must be present and identical across services")
' >/dev/null || fail "Content-slot settings are not shared across API and workers"
pass "Content-slot feature, window, ranking, and gap settings are shared across services"

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
[[ "$migration_revision" == "20260902_0044" ]] \
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

content_slot_table_count="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM unnest(ARRAY['\''content_slot_runs'\'','\''content_slot_jobs'\'','\''content_slot_scores'\'','\''content_slot_selections'\'','\''wecom_delivery_windows'\'']) AS required(name) WHERE to_regclass('\''public.'\'' || name) IS NOT NULL;"'
)"
[[ "$content_slot_table_count" == "5" ]] \
  || fail "Content-slot and delivery-window schema is incomplete; run 'make migrate'"
pass "Content-slot and delivery-window tables are installed"

visual_diversity_table_count="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM unnest(ARRAY['\''image_visual_plan_reservations'\'','\''image_similarity_attempts'\'']) AS required(name) WHERE to_regclass('\''public.'\'' || name) IS NOT NULL;"'
)"
[[ "$visual_diversity_table_count" == "2" ]] \
  || fail "Visual-diversity schema is incomplete; run 'make migrate'"
pass "Visual-diversity reservation and similarity-attempt tables are installed"

content_slot_queue_counts="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT coalesce(string_agg(status || '\''='\'' || count, '\'','\'' ORDER BY status), '\''empty'\'') FROM (SELECT status, count(*) FROM content_slot_jobs GROUP BY status) AS counts;"'
)"
delivery_window_count="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM wecom_delivery_windows;"'
)"
pass "Content-slot queue counters are readable ($content_slot_queue_counts; windows=$delivery_window_count)"

brand_knowledge_table_count="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM unnest(ARRAY['\''brand_documents'\'','\''brand_document_versions'\'','\''brand_ingestion_jobs'\'','\''brand_ingestion_attempts'\'','\''brand_sections'\'','\''brand_chunks'\'','\''brand_chunk_embeddings'\'']) AS required(name) WHERE to_regclass('\''public.'\'' || name) IS NOT NULL;"'
)"
[[ "$brand_knowledge_table_count" == "7" ]] \
  || fail "Brand-knowledge schema is incomplete; run 'make migrate'"
pass "Brand-knowledge tables are installed"

visual_retrieval_table_count="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM unnest(ARRAY['\''brand_visual_index_jobs'\'','\''brand_visual_asset_embeddings'\'']) AS required(name) WHERE to_regclass('\''public.'\'' || name) IS NOT NULL;"'
)"
[[ "$visual_retrieval_table_count" == "2" ]] \
  || fail "Visual-retrieval schema is incomplete; run 'make migrate'"

visual_input_hash_column_count="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM information_schema.columns WHERE table_schema = '\''public'\'' AND table_name IN ('\''brand_visual_index_jobs'\'', '\''brand_visual_asset_embeddings'\'') AND column_name = '\''embedding_input_sha256'\'' AND is_nullable = '\''NO'\'';"'
)"
[[ "$visual_input_hash_column_count" == "2" ]] \
  || fail "Visual-retrieval normalized-input identity is incomplete; run 'make migrate'"
pass "Visual-retrieval tables and normalized-input identities are installed"

visual_embedding_vector_type="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT format_type(attribute.atttypid, attribute.atttypmod) FROM pg_attribute AS attribute JOIN pg_class AS relation ON relation.oid = attribute.attrelid WHERE relation.relname = '\''brand_visual_asset_embeddings'\'' AND attribute.attname = '\''vector'\'' AND NOT attribute.attisdropped;"'
)"
[[ "$visual_embedding_vector_type" == "vector(2048)" ]] \
  || fail "Visual embedding column is not vector(2048); run 'make migrate'"
pass "Visual embedding column is $visual_embedding_vector_type"

official_account_table_count="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM unnest(ARRAY['\''official_account_article_runs'\'','\''official_account_article_versions'\'','\''official_account_article_attempts'\'','\''official_account_render_versions'\'','\''official_account_generated_visuals'\'','\''official_account_generated_visual_evals'\'','\''official_account_local_media'\'','\''official_account_local_drafts'\'','\''official_account_local_draft_body_media'\'','\''official_account_manual_reviews'\'']) AS required(name) WHERE to_regclass('\''public.'\'' || name) IS NOT NULL;"'
)"
[[ "$official_account_table_count" == "10" ]] \
  || fail "Official-account local schema is incomplete; run 'make migrate'"
pass "Official-account local run, artifact, media, and draft tables are installed"

weekly_dag_table_count="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM unnest(ARRAY['\''official_account_weekly_dag_runs'\'','\''official_account_weekly_dag_nodes'\'','\''official_account_weekly_dag_attempts'\'']) AS required(name) WHERE to_regclass('\''public.'\'' || name) IS NOT NULL;"'
)"
[[ "$weekly_dag_table_count" == "3" ]] \
  || fail "Official-account weekly DAG schema is incomplete; run 'make migrate'"
pass "Official-account weekly DAG run, node, and attempt tables are installed"

ip_asset_table_count="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM unnest(ARRAY['\''ip_assets'\'','\''ip_asset_tags'\'','\''ip_asset_derivatives'\'','\''ip_asset_embedding_jobs'\'','\''ip_asset_embeddings'\'','\''ip_asset_generation_jobs'\'']) AS required(name) WHERE to_regclass('\''public.'\'' || name) IS NOT NULL;"'
)"
[[ "$ip_asset_table_count" == "6" ]] \
  || fail "IP asset hub schema is incomplete; run 'make migrate'"

ip_asset_vector_type="$(
  docker compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT format_type(attribute.atttypid, attribute.atttypmod) FROM pg_attribute AS attribute JOIN pg_class AS relation ON relation.oid = attribute.attrelid WHERE relation.relname = '\''ip_asset_embeddings'\'' AND attribute.attname = '\''vector'\'' AND NOT attribute.attisdropped;"'
)"
[[ "$ip_asset_vector_type" == "vector(2048)" ]] \
  || fail "IP asset embedding column is not vector(2048); run 'make migrate'"
pass "IP asset hub tables and $ip_asset_vector_type embedding column are installed"

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
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM sources WHERE enabled IS TRUE AND active_version_id IS NOT NULL;"'
)"
[[ "$source_count" == "11" ]] || fail "Source registry is not ready; run 'make seed-sources'"
pass "Eleven approved source profiles are active"

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
