#!/usr/bin/env bash
# Audited default-off release driver for the offline Zhipu OCR source overlay.
#
# Production invocation contract:
#   * copy this file into the already-validated stage as
#     default-off-release-driver.sh;
#   * invoke it by that absolute stage path with stdin from /dev/null;
#   * pass only reviewed hashes, image identifiers, and protected paths;
#   * never enable OCR/diversity flags and never enqueue/retry/resend work.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

readonly APP_DIR="/opt/edu-ai-lead-agent"
readonly COMPOSE_PROJECT="edu-ai-lead-agent"
readonly COMPOSE_FILE="${APP_DIR}/compose.yaml"
readonly PRIMARY_ENV="${APP_DIR}/.env"
readonly RELEASE_ENV="${APP_DIR}/.release.env"
readonly BACKUP_ROOT="/var/backups/edu-ai/releases"
readonly BACKUP_LOCK="/var/lock/edu-ai-backup.lock"
readonly EXPECTED_ALEMBIC_HEAD="20260815_0021"
readonly EXPECTED_ACTIVE_SOURCES="10"
readonly EXPECTED_BUSINESS_TIMEZONE="Asia/Shanghai"
readonly MINIO_CLIENT_IMAGE="minio/mc:RELEASE.2025-04-16T18-13-26Z"
readonly SAFE_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

readonly -a APP_SERVICES=(
  acquisition-api
  acquisition-scheduler
  acquisition-worker
  governance-scheduler
  governance-worker
  content-scheduler
  content-worker
  wecom-dispatcher
)
readonly -a TAG_SERVICES=(
  backend-migrate
  acquisition-api
  acquisition-scheduler
  acquisition-worker
  governance-scheduler
  governance-worker
  content-scheduler
  content-worker
  wecom-dispatcher
)
readonly -a QUIESCE_ORDER=(
  wecom-dispatcher
  content-worker
  content-scheduler
  governance-worker
  governance-scheduler
  acquisition-worker
  acquisition-scheduler
  acquisition-api
)
readonly -a STAGE_MEMBERS=(
  artifacts.sha256
  backend-image.tar.gz
  backend-image.tar.gz.sha256
  default-off-release-driver.sh
  image-source-files.sha256
  image-validation.txt
  offline-source-overlay.Dockerfile
  source-files.sha256
  source.tar.gz
  source.tar.gz.sha256
)

declare -A OLD_CONTAINER_IDS=()

stage_dir=""
candidate_id=""
candidate_tag=""
candidate_commit=""
candidate_short=""
previous_image_id=""
previous_commit=""
previous_short=""
source_sha256=""
image_bundle_sha256=""
script_sha256=""
previous_source_manifest=""
previous_source_manifest_sha256=""
expected_source_file_count=""
expected_image_source_file_count=""
expected_dependency_base_id=""
expected_pyproject_sha256=""
expected_vector=""
expected_current_day_vector=""
expected_wecom_vector=""
expected_historical_queued=""
expected_env_sha256=""
expected_release_env_sha256=""
expected_brand_sha256=""
expected_brand_count=""
expected_minio_file_count=""
expected_minio_manifest_sha256=""
expected_postgres_volume=""
expected_minio_volume=""
business_date=""
scheduler_safe_until_utc=""
minimum_safe_seconds=900
preflight_sample_seconds=15
stability_seconds=30

backup_id=""
backup_dir=""
rollback_tag_prefix=""
release_extract_dir=""
minio_env_file=""
log_scan_file=""
source_paths_file=""
previous_source_paths_file=""
marker_tmp=""
marker_short_tmp=""
minio_client_id=""
backup_verify_dir=""

# Recovery state. A flag is set before the corresponding first mutation.
backup_ready=0
tags_changed=0
overlay_changed=0
completed=0
services_quiesced=0
recovery_running=0
recovered=0
failure_rc=0

log() {
  printf '[default-off-release] %s\n' "$*" >&2
}

die() {
  log "ERROR: $*"
  return 1
}

usage() {
  cat >&2 <<'EOF'
Usage: /absolute/stage/default-off-release-driver.sh \
  --stage-dir ABSOLUTE_STAGE_DIR \
  --candidate-id sha256:HEX64 --candidate-tag SAFE_LOCAL_TAG \
  --candidate-commit HEX40 --candidate-short HEX7_TO_12 \
  --previous-image-id sha256:HEX64 \
  --previous-commit HEX40 --previous-short HEX7_TO_12 \
  --source-sha256 HEX64 --image-bundle-sha256 HEX64 --script-sha256 HEX64 \
  --previous-source-manifest ABSOLUTE_PATH \
  --previous-source-manifest-sha256 HEX64 --expected-source-file-count INTEGER \
  --expected-image-source-file-count INTEGER \
  --expected-dependency-base-id sha256:HEX64 --expected-pyproject-sha256 HEX64 \
  --expected-vector 15_COLON_SEPARATED_INTEGERS \
  --expected-current-day-vector 3_COLON_SEPARATED_INTEGERS \
  --expected-wecom-vector 6_COLON_SEPARATED_INTEGERS \
  --expected-historical-queued 2_COLON_SEPARATED_INTEGERS \
  --expected-env-sha256 HEX64 --expected-release-env-sha256 HEX64 \
  --expected-brand-sha256 HEX64 --expected-brand-count INTEGER \
  --expected-minio-file-count INTEGER --expected-minio-manifest-sha256 HEX64 \
  --expected-postgres-volume SAFE_NAME --expected-minio-volume SAFE_NAME \
  --business-date 2026-08-16 \
  --scheduler-safe-until-utc YYYY-MM-DDTHH:MM:SSZ \
  [--minimum-safe-seconds 900] [--preflight-sample-seconds 15] \
  [--stability-seconds 30]

stdin must be /dev/null. This driver does not build images, call providers,
enable feature flags, or enqueue/retry/resend work.
EOF
}

require_value() {
  local option=$1
  local value=${2-}
  [[ -n "$value" ]] || die "missing value for ${option}"
}

parse_args() {
  while (($#)); do
    case "$1" in
      --stage-dir) require_value "$1" "${2-}"; stage_dir=$2; shift 2 ;;
      --candidate-id) require_value "$1" "${2-}"; candidate_id=$2; shift 2 ;;
      --candidate-tag) require_value "$1" "${2-}"; candidate_tag=$2; shift 2 ;;
      --candidate-commit) require_value "$1" "${2-}"; candidate_commit=$2; shift 2 ;;
      --candidate-short) require_value "$1" "${2-}"; candidate_short=$2; shift 2 ;;
      --previous-image-id) require_value "$1" "${2-}"; previous_image_id=$2; shift 2 ;;
      --previous-commit) require_value "$1" "${2-}"; previous_commit=$2; shift 2 ;;
      --previous-short) require_value "$1" "${2-}"; previous_short=$2; shift 2 ;;
      --source-sha256) require_value "$1" "${2-}"; source_sha256=$2; shift 2 ;;
      --image-bundle-sha256) require_value "$1" "${2-}"; image_bundle_sha256=$2; shift 2 ;;
      --script-sha256) require_value "$1" "${2-}"; script_sha256=$2; shift 2 ;;
      --previous-source-manifest) require_value "$1" "${2-}"; previous_source_manifest=$2; shift 2 ;;
      --previous-source-manifest-sha256) require_value "$1" "${2-}"; previous_source_manifest_sha256=$2; shift 2 ;;
      --expected-source-file-count) require_value "$1" "${2-}"; expected_source_file_count=$2; shift 2 ;;
      --expected-image-source-file-count) require_value "$1" "${2-}"; expected_image_source_file_count=$2; shift 2 ;;
      --expected-dependency-base-id) require_value "$1" "${2-}"; expected_dependency_base_id=$2; shift 2 ;;
      --expected-pyproject-sha256) require_value "$1" "${2-}"; expected_pyproject_sha256=$2; shift 2 ;;
      --expected-vector) require_value "$1" "${2-}"; expected_vector=$2; shift 2 ;;
      --expected-current-day-vector) require_value "$1" "${2-}"; expected_current_day_vector=$2; shift 2 ;;
      --expected-wecom-vector) require_value "$1" "${2-}"; expected_wecom_vector=$2; shift 2 ;;
      --expected-historical-queued) require_value "$1" "${2-}"; expected_historical_queued=$2; shift 2 ;;
      --expected-env-sha256) require_value "$1" "${2-}"; expected_env_sha256=$2; shift 2 ;;
      --expected-release-env-sha256) require_value "$1" "${2-}"; expected_release_env_sha256=$2; shift 2 ;;
      --expected-brand-sha256) require_value "$1" "${2-}"; expected_brand_sha256=$2; shift 2 ;;
      --expected-brand-count) require_value "$1" "${2-}"; expected_brand_count=$2; shift 2 ;;
      --expected-minio-file-count) require_value "$1" "${2-}"; expected_minio_file_count=$2; shift 2 ;;
      --expected-minio-manifest-sha256) require_value "$1" "${2-}"; expected_minio_manifest_sha256=$2; shift 2 ;;
      --expected-postgres-volume) require_value "$1" "${2-}"; expected_postgres_volume=$2; shift 2 ;;
      --expected-minio-volume) require_value "$1" "${2-}"; expected_minio_volume=$2; shift 2 ;;
      --business-date) require_value "$1" "${2-}"; business_date=$2; shift 2 ;;
      --scheduler-safe-until-utc) require_value "$1" "${2-}"; scheduler_safe_until_utc=$2; shift 2 ;;
      --minimum-safe-seconds) require_value "$1" "${2-}"; minimum_safe_seconds=$2; shift 2 ;;
      --preflight-sample-seconds) require_value "$1" "${2-}"; preflight_sample_seconds=$2; shift 2 ;;
      --stability-seconds) require_value "$1" "${2-}"; stability_seconds=$2; shift 2 ;;
      --help|-h) usage; exit 0 ;;
      *) usage; die "unknown argument: $1" ;;
    esac
  done
}

require_regex() {
  local value=$1
  local pattern=$2
  local description=$3
  [[ "$value" =~ $pattern ]] || die "invalid ${description}"
}

validate_args() {
  local required
  for required in \
    stage_dir candidate_id candidate_tag candidate_commit candidate_short \
    previous_image_id previous_commit previous_short source_sha256 \
    image_bundle_sha256 script_sha256 previous_source_manifest \
    previous_source_manifest_sha256 expected_source_file_count \
    expected_image_source_file_count expected_dependency_base_id \
    expected_pyproject_sha256 expected_vector expected_current_day_vector \
    expected_wecom_vector expected_historical_queued expected_env_sha256 \
    expected_release_env_sha256 expected_brand_sha256 expected_brand_count \
    expected_minio_file_count expected_minio_manifest_sha256 \
    expected_postgres_volume expected_minio_volume business_date \
    scheduler_safe_until_utc
  do
    [[ -n "${!required}" ]] || die "required argument not supplied: ${required}"
  done

  [[ "$stage_dir" = /* ]] || die "stage directory must be absolute"
  [[ "$stage_dir" =~ ^/tmp/edu-ai-zhipu-release-[A-Za-z0-9._-]+$ ]] || die "stage directory is outside the allowlist"
  [[ "$previous_source_manifest" = /* ]] || die "previous source manifest must be absolute"
  [[ "$previous_source_manifest" =~ ^/tmp/edu-ai-zhipu-release-[A-Za-z0-9._-]+/source-files\.sha256$ ]] || die "previous source manifest is outside the allowlist"
  require_regex "$candidate_id" '^sha256:[0-9a-f]{64}$' "candidate image id"
  require_regex "$previous_image_id" '^sha256:[0-9a-f]{64}$' "previous image id"
  require_regex "$expected_dependency_base_id" '^sha256:[0-9a-f]{64}$' "dependency base image id"
  require_regex "$candidate_tag" '^edu-ai-lead-agent(-backend)?:[A-Za-z0-9._-]+$' "candidate tag"
  require_regex "$candidate_commit" '^[0-9a-f]{40}$' "candidate commit"
  require_regex "$previous_commit" '^[0-9a-f]{40}$' "previous commit"
  require_regex "$candidate_short" '^[0-9a-f]{7,12}$' "candidate short commit"
  require_regex "$previous_short" '^[0-9a-f]{7,12}$' "previous short commit"
  [[ "$candidate_commit" == "$candidate_short"* ]] || die "candidate short commit is not a prefix"
  [[ "$previous_commit" == "$previous_short"* ]] || die "previous short commit is not a prefix"
  for required in source_sha256 image_bundle_sha256 script_sha256 \
    previous_source_manifest_sha256 expected_env_sha256 \
    expected_release_env_sha256 expected_brand_sha256 \
    expected_minio_manifest_sha256 expected_pyproject_sha256
  do
    require_regex "${!required}" '^[0-9a-f]{64}$' "$required"
  done
  require_regex "$expected_source_file_count" '^[1-9][0-9]*$' "source file count"
  require_regex "$expected_image_source_file_count" '^[1-9][0-9]*$' "image source file count"
  require_regex "$expected_brand_count" '^[1-9][0-9]*$' "brand file count"
  require_regex "$expected_minio_file_count" '^[1-9][0-9]*$' "MinIO file count"
  require_regex "$minimum_safe_seconds" '^[1-9][0-9]*$' "minimum safe seconds"
  require_regex "$preflight_sample_seconds" '^[1-9][0-9]*$' "preflight sample seconds"
  require_regex "$stability_seconds" '^[1-9][0-9]*$' "stability seconds"
  require_regex "$expected_postgres_volume" '^[A-Za-z0-9][A-Za-z0-9_.-]*$' "Postgres volume"
  require_regex "$expected_minio_volume" '^[A-Za-z0-9][A-Za-z0-9_.-]*$' "MinIO volume"
  require_regex "$expected_vector" '^[0-9]+(:[0-9]+){14}$' "durable vector"
  require_regex "$expected_current_day_vector" '^[0-9]+(:[0-9]+){2}$' "current-day vector"
  require_regex "$expected_wecom_vector" '^[0-9]+(:[0-9]+){5}$' "WeCom vector"
  require_regex "$expected_historical_queued" '^[0-9]+:[0-9]+$' "historical queued vector"
  require_regex "$scheduler_safe_until_utc" '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' "scheduler safe-until timestamp"
  [[ "$business_date" == "2026-08-16" ]] || die "this exact release driver is pinned to the reviewed 2026-08-16 business baseline"
  [[ "$candidate_tag" != "${COMPOSE_PROJECT}-backend:local" ]] || die "candidate tag must not be the active shared tag"
  ((minimum_safe_seconds >= 900)) || die "minimum safe window cannot be weakened below 900 seconds"
  ((preflight_sample_seconds >= 15)) || die "preflight sample cannot be weakened below 15 seconds"
  ((stability_seconds >= 30)) || die "stability sample cannot be weakened below 30 seconds"
}

docker_call() {
  env -i PATH="$SAFE_PATH" HOME=/root /usr/bin/docker "$@"
}

compose_call() {
  env -i PATH="$SAFE_PATH" HOME=/root /usr/bin/docker compose \
    --project-name "$COMPOSE_PROJECT" \
    --project-directory "$APP_DIR" \
    --env-file "$PRIMARY_ENV" \
    --env-file "$RELEASE_ENV" \
    -f "$COMPOSE_FILE" \
    "$@" </dev/null
}

container_id() {
  compose_call ps -q "$1" | tr -d '\r\n'
}

container_id_all() {
  compose_call ps -a -q "$1" | tr -d '\r\n'
}

sql_scalar() {
  local query=$1
  local postgres_id
  postgres_id=$(container_id postgres)
  [[ -n "$postgres_id" ]] || die "Postgres container is absent"
  docker_call exec "$postgres_id" sh -c \
    'exec psql -X -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' \
    sh "$query" </dev/null | tr -d '[:space:]'
}

durable_vector() {
  sql_scalar "SELECT concat_ws(':',
    (SELECT count(*) FROM acquisition_runs),
    (SELECT count(*) FROM evidence_candidates),
    (SELECT count(*) FROM governance_runs),
    (SELECT count(*) FROM daily_topic_selections),
    (SELECT count(*) FROM content_slot_runs),
    (SELECT count(*) FROM copy_generation_runs),
    (SELECT count(*) FROM copy_generation_attempts),
    (SELECT count(*) FROM image_artifacts),
    (SELECT coalesce(sum(attempt_count), 0) FROM image_artifacts),
    (SELECT count(*) FROM material_packages),
    (SELECT count(*) FROM model_invocations),
    (SELECT count(*) FROM wecom_delivery_jobs),
    (SELECT count(*) FROM wecom_delivery_attempts),
    (SELECT count(*) FROM image_visual_plan_reservations),
    (SELECT count(*) FROM image_similarity_attempts));"
}

actionable_vector() {
  sql_scalar "SELECT concat_ws(':',
    (SELECT count(*) FROM acquisition_jobs j JOIN acquisition_runs r ON r.id=j.run_id WHERE r.business_date=DATE '${business_date}' AND j.status IN ('queued','running','retry_scheduled')),
    (SELECT count(*) FROM governance_jobs j JOIN governance_runs g ON g.id=j.run_id JOIN acquisition_runs r ON r.id=g.acquisition_run_id WHERE r.business_date=DATE '${business_date}' AND j.status IN ('queued','running','retry_scheduled')),
    (SELECT count(*) FROM topic_selection_jobs j JOIN topic_selection_runs r ON r.id=j.run_id WHERE r.business_date=DATE '${business_date}' AND j.status IN ('queued','running')),
    (SELECT count(*) FROM content_slot_jobs j JOIN content_slot_runs r ON r.id=j.run_id WHERE r.business_date=DATE '${business_date}' AND j.status IN ('queued','running')),
    (SELECT count(*) FROM copy_generation_jobs j JOIN copy_generation_runs r ON r.id=j.run_id WHERE r.business_date=DATE '${business_date}' AND j.status IN ('queued','running','retry_scheduled')),
    (SELECT count(*) FROM wecom_delivery_jobs WHERE status IN ('queued','running','partial','delivery_unknown')));"
}

running_vector() {
  sql_scalar "SELECT concat_ws(':',
    (SELECT count(*) FROM acquisition_jobs WHERE status='running'),
    (SELECT count(*) FROM governance_jobs WHERE status='running'),
    (SELECT count(*) FROM topic_selection_jobs WHERE status='running'),
    (SELECT count(*) FROM content_slot_jobs WHERE status='running'),
    (SELECT count(*) FROM brand_ingestion_jobs WHERE status='running'),
    (SELECT count(*) FROM copy_generation_jobs WHERE status='running'),
    (SELECT count(*) FROM image_artifacts WHERE status='running'),
    (SELECT count(*) FROM wecom_delivery_jobs WHERE status IN ('running','partial','delivery_unknown')));"
}

unknown_status_vector() {
  sql_scalar "SELECT concat_ws(':',
    (SELECT count(*) FROM acquisition_jobs WHERE status NOT IN ('queued','running','retry_scheduled','succeeded','failed','cancelled')),
    (SELECT count(*) FROM governance_jobs WHERE status NOT IN ('queued','running','retry_scheduled','succeeded','review_required','failed','cancelled')),
    (SELECT count(*) FROM topic_selection_jobs WHERE status NOT IN ('queued','running','succeeded','failed')),
    (SELECT count(*) FROM content_slot_jobs WHERE status NOT IN ('queued','running','succeeded','failed')),
    (SELECT count(*) FROM brand_ingestion_jobs WHERE status NOT IN ('queued','running','retry_scheduled','succeeded','failed','cancelled')),
    (SELECT count(*) FROM copy_generation_jobs WHERE status NOT IN ('queued','running','retry_scheduled','succeeded','failed','cancelled')),
    (SELECT count(*) FROM image_artifacts WHERE status NOT IN ('queued','running','succeeded','failed','review_required')),
    (SELECT count(*) FROM wecom_delivery_jobs WHERE status NOT IN ('queued','running','partial','delivery_unknown','delivered','failed','cancelled','delivery_window_expired')));"
}

wecom_vector() {
  sql_scalar "SELECT concat_ws(':',
    (SELECT count(*) FROM wecom_delivery_jobs),
    (SELECT count(*) FROM wecom_delivery_attempts),
    (SELECT count(*) FROM wecom_delivery_jobs WHERE status IN ('queued','running','partial')),
    (SELECT count(*) FROM wecom_delivery_jobs WHERE status = 'delivery_unknown'),
    (SELECT count(*) FROM (SELECT request_fingerprint FROM wecom_delivery_jobs GROUP BY request_fingerprint HAVING count(*) > 1) duplicates),
    (SELECT count(*) FROM (SELECT content_fingerprint FROM wecom_delivery_jobs GROUP BY content_fingerprint HAVING count(*) > 1) duplicates));"
}

historical_queued_vector() {
  sql_scalar "SELECT concat_ws(':',
    (SELECT count(*) FROM copy_generation_jobs j JOIN copy_generation_runs r ON r.id=j.run_id WHERE r.business_date < DATE '${business_date}' AND j.status='queued'),
    (SELECT coalesce(sum(j.attempt_count),0) FROM copy_generation_jobs j JOIN copy_generation_runs r ON r.id=j.run_id WHERE r.business_date < DATE '${business_date}' AND j.status='queued'));"
}

current_day_vector() {
  sql_scalar "SELECT concat_ws(':',
    (SELECT count(*) FROM acquisition_runs WHERE business_date=DATE '${business_date}'),
    (SELECT count(*) FROM content_slot_runs WHERE business_date=DATE '${business_date}'),
    (SELECT count(*) FROM copy_generation_runs WHERE business_date=DATE '${business_date}'));"
}

assert_exact_vectors() {
  local context=$1
  [[ "$(durable_vector)" == "$expected_vector" ]] || die "${context}: durable vector drift"
  [[ "$(current_day_vector)" == "$expected_current_day_vector" ]] || die "${context}: current-day vector drift"
  [[ "$(wecom_vector)" == "$expected_wecom_vector" ]] || die "${context}: WeCom vector drift"
  [[ "$(historical_queued_vector)" == "$expected_historical_queued" ]] || die "${context}: historical queued invariant drift"
  [[ "$(actionable_vector)" == "0:0:0:0:0:0" ]] || die "${context}: running/actionable work is nonzero"
  [[ "$(running_vector)" == "0:0:0:0:0:0:0:0" ]] || die "${context}: running work is nonzero"
  [[ "$(unknown_status_vector)" == "0:0:0:0:0:0:0:0" ]] || die "${context}: unknown job status is nonzero"
  [[ "$(sql_scalar "SELECT count(*) FROM sources WHERE active_version_id IS NOT NULL")" == "$EXPECTED_ACTIVE_SOURCES" ]] || die "${context}: active source count drift"
  [[ "$(sql_scalar "SELECT version_num FROM alembic_version")" == "$EXPECTED_ALEMBIC_HEAD" ]] || die "${context}: Alembic head drift"
}

assert_safe_window() {
  local now_epoch safe_epoch remaining current_business_date final_business_date database_business_date
  now_epoch=$(date -u +%s)
  safe_epoch=$(date -u -d "$scheduler_safe_until_utc" +%s) || die "cannot parse scheduler safe-until timestamp"
  remaining=$((safe_epoch - now_epoch))
  ((remaining >= minimum_safe_seconds)) || die "scheduler maintenance window has less than ${minimum_safe_seconds}s remaining"
  current_business_date=$(TZ="$EXPECTED_BUSINESS_TIMEZONE" date -d "@${now_epoch}" +%F)
  final_business_date=$(TZ="$EXPECTED_BUSINESS_TIMEZONE" date -d "@$((safe_epoch - 1))" +%F)
  [[ "$current_business_date" == "$business_date" ]] || die "current business date no longer matches the reviewed baseline"
  [[ "$final_business_date" == "$business_date" ]] || die "scheduler-safe window crosses the reviewed business date"
  database_business_date=$(sql_scalar "SELECT to_char(current_timestamp AT TIME ZONE '${EXPECTED_BUSINESS_TIMEZONE}', 'YYYY-MM-DD')")
  [[ "$database_business_date" == "$business_date" ]] || die "database business date no longer matches the reviewed baseline"
}

env_value() {
  local file=$1
  local key=$2
  [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] || die "invalid env key"
  awk -v key="$key" '
    index($0, key "=") == 1 {
      value = substr($0, length(key) + 2)
      sub(/\r$/, "", value)
      print value
      found = 1
      exit
    }
    END { if (!found) exit 1 }
  ' "$file"
}

brand_state() {
  local output=$1
  (
    cd "$APP_DIR"
    find private/brand-materials -type f -print0 \
      | sort -z \
      | xargs -0 -r sha256sum
  ) >"$output"
}

brand_digest() {
  local state_file=$1
  sha256sum "$state_file" | awk '{print $1}'
}

assert_protected_inputs() {
  local brand_manifest brand_count postgres_volume minio_volume
  [[ "$(sha256sum "$PRIMARY_ENV" | awk '{print $1}')" == "$expected_env_sha256" ]] || die ".env checksum drift"
  [[ "$(sha256sum "$RELEASE_ENV" | awk '{print $1}')" == "$expected_release_env_sha256" ]] || die ".release.env checksum drift"

  brand_manifest=$(mktemp /tmp/edu-ai-release-driver-brand.XXXXXX)
  brand_state "$brand_manifest"
  brand_count=$(wc -l <"$brand_manifest" | tr -d '[:space:]')
  [[ "$brand_count" == "$expected_brand_count" ]] || die "brand file count drift"
  [[ "$(brand_digest "$brand_manifest")" == "$expected_brand_sha256" ]] || die "brand checksum drift"
  rm -f -- "$brand_manifest"

  postgres_volume=$(docker_call inspect "$(container_id postgres)" --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}' </dev/null)
  minio_volume=$(docker_call inspect "$(container_id minio)" --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}' </dev/null)
  [[ "$postgres_volume" == "$expected_postgres_volume" ]] || die "Postgres volume identity drift"
  [[ "$minio_volume" == "$expected_minio_volume" ]] || die "MinIO volume identity drift"
}

assert_compose_contract() {
  local rendered
  [[ "$(env_value "$RELEASE_ENV" APP_IMAGE)" == "${COMPOSE_PROJECT}-backend:local" ]] || die "release env does not select the reviewed local shared tag"
  rendered=$(mktemp /tmp/edu-ai-release-driver-compose.XXXXXX)
  compose_call --profile governance --profile content --profile wecom config --format json >"$rendered"
  python3 - "$rendered" <<'PY'
import json
import pathlib
import sys

expected = "edu-ai-lead-agent-backend:local"
services = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))["services"]
application_services = (
    "backend-migrate",
    "acquisition-api",
    "acquisition-scheduler",
    "acquisition-worker",
    "governance-scheduler",
    "governance-worker",
    "content-scheduler",
    "content-worker",
    "wecom-dispatcher",
)
if any(services[name]["image"] != expected for name in application_services):
    raise SystemExit("rendered application image contract mismatch")
PY
  rm -f -- "$rendered"
}

assert_infrastructure() {
  local service cid status health
  for service in postgres minio; do
    cid=$(container_id "$service")
    [[ -n "$cid" ]] || die "${service} container is absent"
    status=$(docker_call inspect "$cid" --format '{{.State.Status}}' </dev/null)
    health=$(docker_call inspect "$cid" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' </dev/null)
    [[ "$status" == "running" && "$health" == "healthy" ]] || die "${service} is not running and healthy"
  done
}

assert_minio_client_image() {
  local init_id init_image
  minio_client_id=$(docker_call image inspect "$MINIO_CLIENT_IMAGE" --format '{{.Id}}' </dev/null)
  require_regex "$minio_client_id" '^sha256:[0-9a-f]{64}$' "local MinIO client image id"
  init_id=$(container_id_all minio-init)
  if [[ -n "$init_id" ]]; then
    init_image=$(docker_call inspect "$init_id" --format '{{.Image}}' </dev/null)
    [[ "$init_image" == "$minio_client_id" ]] || die "existing MinIO init container image drift"
  fi
}

assert_safe_logs() {
  log_scan_file=$(mktemp /tmp/edu-ai-release-driver-logs.XXXXXX)
  compose_call --profile governance --profile content --profile wecom logs --no-color --tail 200 \
    "${APP_SERVICES[@]}" >"$log_scan_file" 2>&1
  if LC_ALL=C grep -Eiq 'Traceback|CRITICAL|delivery_unknown|provider_request|provider_send|layout_parsing|comfly|toapis|wecom_[^ ]*(send|request)|data:image/|authorization[" ]*[:=]|bearer[[:space:]]+[A-Za-z0-9._-]+|x-amz-(credential|signature)|webhook/send\?key=|sk-[A-Za-z0-9_-]{16,}|(api[_-]?key|secret|token|password)=[^[:space:]]+' "$log_scan_file"; then
    die "bounded log scan contains a severe/provider/send/secret-shaped marker"
  fi
  rm -f -- "$log_scan_file"
  log_scan_file=""
}

assert_flags_false() {
  local api_id output
  api_id=$(container_id acquisition-api)
  [[ -n "$api_id" ]] || die "API container is absent"
  output=$(docker_call exec "$api_id" python -c \
    'from app.core.config import Settings; s=Settings(); print(":".join((str(s.image_diversity_enabled).lower(),str(s.image_ocr_enabled).lower(),s.image_ocr_model,str(s.image_ocr_max_input_bytes),str(s.image_ocr_max_response_bytes),str(s.image_ocr_timeout_seconds),s.business_timezone)))' \
    </dev/null)
  [[ "$output" == "false:false:glm-ocr:10485760:1048576:120.0:${EXPECTED_BUSINESS_TIMEZONE}" ]] || die "API image/OCR settings are not the exact default-off contract"
}

assert_content_flags_false() {
  local content_id output
  content_id=$(container_id content-worker)
  [[ -n "$content_id" ]] || die "content worker container is absent"
  output=$(docker_call exec "$content_id" python -c \
    'from app.core.config import Settings; s=Settings(); print(":".join((str(s.image_diversity_enabled).lower(),str(s.image_ocr_enabled).lower(),s.image_ocr_model,str(s.image_ocr_max_input_bytes),str(s.image_ocr_max_response_bytes),str(s.image_ocr_timeout_seconds),s.business_timezone)))' \
    </dev/null)
  [[ "$output" == "false:false:glm-ocr:10485760:1048576:120.0:${EXPECTED_BUSINESS_TIMEZONE}" ]] || die "content image/OCR settings are not the exact default-off contract"
}

assert_running_image_and_markers() {
  local expected_id=$1
  local expected_full=$2
  local expected_abbrev=$3
  local service cid image restart_count status name project_label service_label number_label
  for service in "${APP_SERVICES[@]}"; do
    cid=$(container_id "$service")
    [[ -n "$cid" ]] || die "${service} has no container"
    image=$(docker_call inspect "$cid" --format '{{.Image}}' </dev/null)
    restart_count=$(docker_call inspect "$cid" --format '{{.RestartCount}}' </dev/null)
    status=$(docker_call inspect "$cid" --format '{{.State.Status}}' </dev/null)
    name=$(docker_call inspect "$cid" --format '{{.Name}}' </dev/null)
    project_label=$(docker_call inspect "$cid" --format '{{index .Config.Labels "com.docker.compose.project"}}' </dev/null)
    service_label=$(docker_call inspect "$cid" --format '{{index .Config.Labels "com.docker.compose.service"}}' </dev/null)
    number_label=$(docker_call inspect "$cid" --format '{{index .Config.Labels "com.docker.compose.container-number"}}' </dev/null)
    [[ "$image" == "$expected_id" ]] || die "${service} image mismatch"
    [[ "$restart_count" == "0" ]] || die "${service} restart count is nonzero"
    [[ "$status" == "running" ]] || die "${service} is not running"
    [[ "$name" == "/${COMPOSE_PROJECT}-${service}-1" ]] || die "${service} container name mismatch"
    [[ "$project_label" == "$COMPOSE_PROJECT" && "$service_label" == "$service" && "$number_label" == "1" ]] || die "${service} Compose identity mismatch"
  done
  [[ -f "${APP_DIR}/.release-commit" && ! -L "${APP_DIR}/.release-commit" ]] || die "full release marker is unsafe"
  [[ -f "${APP_DIR}/RELEASE_COMMIT" && ! -L "${APP_DIR}/RELEASE_COMMIT" ]] || die "short release marker is unsafe"
  [[ "$(stat -c '%a' "${APP_DIR}/.release-commit")" == "600" ]] || die "full release marker mode mismatch"
  [[ "$(stat -c '%a' "${APP_DIR}/RELEASE_COMMIT")" == "600" ]] || die "short release marker mode mismatch"
  [[ "$(<"${APP_DIR}/.release-commit")" == "$expected_full" ]] || die ".release-commit mismatch"
  [[ "$(<"${APP_DIR}/RELEASE_COMMIT")" == "$expected_abbrev" ]] || die "RELEASE_COMMIT mismatch"
}

assert_active_tags() {
  local expected_id=$1
  local service tag image
  image=$(docker_call image inspect "${COMPOSE_PROJECT}-backend:local" --format '{{.Id}}' </dev/null)
  [[ "$image" == "$expected_id" ]] || die "shared application tag mismatch"
  for service in "${TAG_SERVICES[@]}"; do
    tag="${COMPOSE_PROJECT}-${service}:local"
    image=$(docker_call image inspect "$tag" --format '{{.Id}}' </dev/null)
    [[ "$image" == "$expected_id" ]] || die "${service} application tag mismatch"
  done
}

assert_stage_exact() {
  local actual expected self_path
  [[ -d "$stage_dir" && ! -L "$stage_dir" ]] || die "stage directory is absent or a symlink"
  [[ "$(stat -c '%a' "$stage_dir")" == "700" ]] || die "stage directory permissions are not mode 0700"

  actual=$(find "$stage_dir" -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort)
  expected=$(printf '%s\n' "${STAGE_MEMBERS[@]}" | LC_ALL=C sort)
  [[ "$actual" == "$expected" ]] || die "stage has missing or extra members"
  while IFS= read -r self_path; do
    [[ -f "$self_path" && ! -L "$self_path" ]] || die "stage member is not a regular file"
    [[ "$(stat -c '%a' "$self_path")" == "600" ]] || die "stage member is not mode 0600"
  done < <(find "$stage_dir" -mindepth 1 -maxdepth 1 -print)

  [[ "$0" == /* ]] || die "driver entrypoint must be an absolute path"
  self_path=$(realpath -- "$0")
  [[ "$self_path" == "${stage_dir}/default-off-release-driver.sh" ]] || die "driver was not invoked by its exact absolute stage path"
  [[ "$(sha256sum "$self_path" | awk '{print $1}')" == "$script_sha256" ]] || die "driver checksum mismatch"
  [[ "$(sha256sum "${stage_dir}/source.tar.gz" | awk '{print $1}')" == "$source_sha256" ]] || die "source archive checksum mismatch"
  [[ "$(sha256sum "${stage_dir}/backend-image.tar.gz" | awk '{print $1}')" == "$image_bundle_sha256" ]] || die "image bundle checksum mismatch"
  python3 - "${stage_dir}/artifacts.sha256" <<'PY'
import pathlib
import re
import sys

expected = {
    "backend-image.tar.gz",
    "backend-image.tar.gz.sha256",
    "image-source-files.sha256",
    "image-validation.txt",
    "offline-source-overlay.Dockerfile",
    "source-files.sha256",
    "source.tar.gz",
    "source.tar.gz.sha256",
}
lines = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
targets: list[str] = []
for line in lines:
    match = re.fullmatch(r"[0-9a-f]{64}  ([A-Za-z0-9._-]+)", line)
    if match is None:
        raise SystemExit("unsafe artifacts checksum manifest syntax")
    targets.append(match.group(1))
if len(targets) != len(set(targets)) or set(targets) != expected:
    raise SystemExit("artifacts checksum manifest membership mismatch")
PY
  (
    cd "$stage_dir"
    sha256sum -c artifacts.sha256
    sha256sum -c source.tar.gz.sha256
    sha256sum -c backend-image.tar.gz.sha256
  ) >/dev/null
}

validate_source_manifest() {
  local manifest=$1
  local output=$2
  local expected_count=$3
  python3 - "$manifest" "$output" "$expected_count" <<'PY'
import pathlib
import re
import sys

manifest = pathlib.Path(sys.argv[1])
output = pathlib.Path(sys.argv[2])
expected_count = int(sys.argv[3])
paths: list[str] = []
for line in manifest.read_text(encoding="utf-8").splitlines():
    match = re.fullmatch(r"[0-9a-f]{64}  (.+)", line)
    if match is None:
        raise SystemExit("unsafe source checksum manifest syntax")
    raw = match.group(1)
    path = raw[2:] if raw.startswith("./") else raw
    pure = pathlib.PurePosixPath(path)
    if (
        not path
        or pure.is_absolute()
        or str(pure) != path
        or any(part in {"", ".", ".."} for part in pure.parts)
        or any(char in path for char in ("\0", "\n", "\r"))
        or pure.parts[0] in {".git", ".trellis", "private", "reports", "node_modules", ".venv"}
        or pure.name in {".env", ".release.env"}
    ):
        raise SystemExit("unsafe source checksum path")
    paths.append(path)
if len(paths) != expected_count or len(paths) != len(set(paths)):
    raise SystemExit("source checksum manifest count/uniqueness mismatch")
output.write_text("".join(f"{path}\n" for path in sorted(paths)), encoding="utf-8")
PY
}

extract_and_validate_source() {
  local manifest_count
  source_paths_file=$(mktemp /tmp/edu-ai-release-driver-source-paths.XXXXXX)
  validate_source_manifest "${stage_dir}/source-files.sha256" "$source_paths_file" "$expected_source_file_count"
  python3 - "${stage_dir}/source.tar.gz" "$source_paths_file" <<'PY'
import pathlib
import sys
import tarfile

expected = set(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8").splitlines())
files: list[str] = []
directories: list[str] = []
with tarfile.open(sys.argv[1], mode="r:gz") as archive:
    for member in archive.getmembers():
        path = member.name[2:] if member.name.startswith("./") else member.name
        if member.isdir():
            path = path.rstrip("/")
            if not path:
                continue
        pure = pathlib.PurePosixPath(path)
        if not path or pure.is_absolute() or str(pure) != path or any(part in {"", ".", ".."} for part in pure.parts):
            raise SystemExit("unsafe source archive path")
        if member.isfile():
            files.append(path)
        elif member.isdir():
            directories.append(path)
        else:
            raise SystemExit("source archive contains a non-regular member")
if len(files) != len(set(files)) or set(files) != expected:
    raise SystemExit("source archive regular-file membership mismatch")
for directory in directories:
    prefix = f"{directory}/"
    if directory and not any(path.startswith(prefix) for path in expected):
        raise SystemExit("source archive contains an extra directory")
PY
  release_extract_dir=$(mktemp -d /tmp/edu-ai-release-driver-source.XXXXXX)
  tar --no-same-owner --same-permissions -xzf "${stage_dir}/source.tar.gz" -C "$release_extract_dir"
  (
    cd "$release_extract_dir"
    sha256sum -c "${stage_dir}/source-files.sha256"
  ) >/dev/null
  manifest_count=$(wc -l <"${stage_dir}/source-files.sha256" | tr -d '[:space:]')
  [[ "$manifest_count" == "$expected_source_file_count" ]] || die "source manifest file count mismatch"

  [[ "$(find "$release_extract_dir" -type f | wc -l | tr -d '[:space:]')" == "$expected_source_file_count" ]] || die "source extraction file count mismatch"
}

assert_previous_source() {
  local previous_parent path
  [[ -f "$previous_source_manifest" && ! -L "$previous_source_manifest" ]] || die "previous source manifest is absent or a symlink"
  previous_parent=$(dirname "$previous_source_manifest")
  [[ -d "$previous_parent" && ! -L "$previous_parent" && "$(stat -c '%a' "$previous_parent")" == "700" ]] || die "previous source manifest parent is not protected"
  [[ "$(stat -c '%a' "$previous_source_manifest")" == "600" ]] || die "previous source manifest is not mode 0600"
  [[ "$(sha256sum "$previous_source_manifest" | awk '{print $1}')" == "$previous_source_manifest_sha256" ]] || die "previous source manifest checksum mismatch"
  previous_source_paths_file=$(mktemp /tmp/edu-ai-release-driver-previous-paths.XXXXXX)
  validate_source_manifest "$previous_source_manifest" "$previous_source_paths_file" "$expected_source_file_count"
  cmp -s "$source_paths_file" "$previous_source_paths_file" || die "candidate and previous source path sets differ"
  while IFS= read -r path; do
    [[ -f "${APP_DIR}/${path}" && ! -L "${APP_DIR}/${path}" ]] || die "previous source member is absent, non-regular, or a symlink"
  done <"$previous_source_paths_file"
  (
    cd "$APP_DIR"
    sha256sum -c "$previous_source_manifest"
  ) >/dev/null
}

assert_candidate_image() {
  local actual_id revision dependency_base pyproject_hash release_source
  local source_manifest runtime_openapi_hash committed_openapi_hash
  actual_id=$(docker_call image inspect "$candidate_tag" --format '{{.Id}}' </dev/null)
  [[ "$actual_id" == "$candidate_id" ]] || die "loaded candidate image id mismatch"
  revision=$(docker_call image inspect "$candidate_id" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' </dev/null)
  [[ "$revision" == "$candidate_commit" ]] || die "candidate revision label mismatch"
  dependency_base=$(docker_call image inspect "$candidate_id" --format '{{index .Config.Labels "io.trellis.dependency-base.digest"}}' </dev/null)
  [[ "$dependency_base" == "$expected_dependency_base_id" ]] || die "candidate dependency-base label mismatch"
  pyproject_hash=$(docker_call image inspect "$candidate_id" --format '{{index .Config.Labels "io.trellis.dependency-input.pyproject-sha256"}}' </dev/null)
  [[ "$pyproject_hash" == "$expected_pyproject_sha256" ]] || die "candidate pyproject label mismatch"
  release_source=$(docker_call run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint sh "$candidate_id" \
    -c 'cat /app/.release-source.sha256' </dev/null | tr -d '[:space:]')
  [[ "$release_source" == "$source_sha256" ]] || die "candidate embedded source archive checksum mismatch"

  source_manifest=$(mktemp /tmp/edu-ai-release-driver-image-source.XXXXXX)
  docker_call run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint sh "$candidate_id" \
    -c 'cd /app && find app alembic -type f \( -name "*.py" -o -name "*.html" \) -print0 | sort -z | xargs -0 sha256sum' \
    </dev/null >"$source_manifest"
  cmp -s "$source_manifest" "${stage_dir}/image-source-files.sha256" || die "candidate image source manifest mismatch"
  [[ "$(wc -l <"$source_manifest" | tr -d '[:space:]')" == "$expected_image_source_file_count" ]] || die "candidate image source count mismatch"
  rm -f -- "$source_manifest"

  docker_call run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint python "$candidate_id" -c \
    'import os; from app.api_main import app as api_app; import app.worker_main as acquisition_worker; import app.acquisition_scheduler_main as acquisition_scheduler; import app.governance_scheduler_main as governance_scheduler; import app.governance_worker_main as governance_worker; import app.content_scheduler_main as content_scheduler; import app.content_worker_main as content_worker; import app.wecom_dispatcher_main as wecom_dispatcher; from app.core.config import Settings; s=Settings(); modules=(acquisition_worker,acquisition_scheduler,governance_scheduler,governance_worker,content_scheduler,content_worker,wecom_dispatcher); assert os.geteuid()!=0; assert all(module.__name__.startswith("app.") for module in modules); assert not s.image_diversity_enabled and not s.image_ocr_enabled; assert s.image_ocr_model=="glm-ocr" and s.image_ocr_max_input_bytes==10485760 and s.image_ocr_max_response_bytes==1048576 and s.image_ocr_timeout_seconds==120.0 and s.business_timezone=="Asia/Shanghai"; assert api_app.openapi()["openapi"]' \
    </dev/null

  docker_call run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint pip "$candidate_id" check </dev/null

  docker_call run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint python "$candidate_id" -c \
    'import asyncio,httpx; from pydantic import SecretStr; from app.infrastructure.ai.zhipu import ZhipuImageTextRecognizer; c=httpx.AsyncClient(); r=ZhipuImageTextRecognizer(client=c,base_url="https://offline.invalid/api/paas/v4",api_key=SecretStr("offline"),model="glm-ocr",connect_timeout_seconds=1,read_timeout_seconds=120,total_timeout_seconds=120,concurrency=1,max_attempts=1,max_input_bytes=10485760,max_response_bytes=1048576); assert r._url=="https://offline.invalid/api/paas/v4/layout_parsing"; asyncio.run(c.aclose())' \
    </dev/null

  docker_call run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint sh "$candidate_id" -c \
    'test ! -e /app/build/lib && test ! -e /app/build/bdist && ! find /usr/local/lib -path "*/site-packages/app" -print -quit | grep -q . && python -c '\''import pathlib,app; assert pathlib.Path(app.__file__).resolve().is_relative_to(pathlib.Path("/app/app"))'\''' \
    </dev/null

  runtime_openapi_hash=$(docker_call run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint python "$candidate_id" -c \
    'import hashlib,json; from app.api_main import app as api_app; print(hashlib.sha256(json.dumps(api_app.openapi(),sort_keys=True,separators=(",",":")).encode()).hexdigest())' \
    </dev/null)
  committed_openapi_hash=$(python3 - "${release_extract_dir}/backend/openapi.json" <<'PY'
import hashlib
import json
import pathlib
import sys

document = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
print(hashlib.sha256(payload).hexdigest())
PY
  )
  [[ "$runtime_openapi_hash" == "$committed_openapi_hash" ]] || die "candidate OpenAPI drift"

  docker_call run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint sh "$candidate_id" -c \
    'test "$(cat /app/alembic/versions/20260815_0021_add_image_ocr_delivery_fields.py | wc -c)" -gt 0 && alembic heads | grep -Fx "20260815_0021 (head)"' \
    </dev/null >/dev/null
  [[ "$EXPECTED_ALEMBIC_HEAD" == "20260815_0021" ]] || die "internal Alembic contract changed"
}

capture_old_containers() {
  local service cid image
  for service in "${APP_SERVICES[@]}"; do
    cid=$(container_id "$service")
    [[ -n "$cid" ]] || die "cannot capture old ${service} container"
    image=$(docker_call inspect "$cid" --format '{{.Image}}' </dev/null)
    [[ "$image" == "$previous_image_id" ]] || die "old ${service} image mismatch"
    OLD_CONTAINER_IDS["$service"]=$cid
  done
}

prepare_fresh_backup() {
  local service tag
  backup_id=$(date -u +%Y%m%dT%H%M%SZ)
  require_regex "$backup_id" '^[0-9]{8}T[0-9]{6}Z$' "generated backup id"
  backup_dir="${BACKUP_ROOT}/${backup_id}-zhipu-ocr-default-off"
  rollback_tag_prefix="edu-ai-lead-agent-backend:rollback-${backup_id}"
  [[ ! -e "$backup_dir" ]] || die "generated backup directory already exists"
  for service in "${TAG_SERVICES[@]}"; do
    tag="${rollback_tag_prefix}-${service}"
    if docker_call image inspect "$tag" >/dev/null 2>&1; then
      die "generated rollback tag already exists"
    fi
  done
  install -d -m 0700 "$backup_dir"
}

quiesce_writers() {
  local service cid
  services_quiesced=1
  for service in "${QUIESCE_ORDER[@]}"; do
    cid=${OLD_CONTAINER_IDS[$service]}
    docker_call stop --time 30 "$cid" </dev/null >/dev/null
  done
  for service in "${APP_SERVICES[@]}"; do
    [[ "$(docker_call inspect "${OLD_CONTAINER_IDS[$service]}" --format '{{.State.Status}}' </dev/null)" == "exited" ]] || die "${service} did not quiesce"
  done
  assert_infrastructure
  [[ "$(actionable_vector)" == "0:0:0:0:0:0" ]] || die "actionable work appeared while quiescing"
  assert_exact_vectors "quiesced"
}

create_fresh_backup() {
  local postgres_id minio_access minio_secret minio_bucket minio_network service tag
  local brand_manifest code_list minio_count
  postgres_id=$(container_id postgres)

  docker_call exec "$postgres_id" sh -c \
    'exec pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
    </dev/null >"${backup_dir}/postgres.dump"
  [[ -s "${backup_dir}/postgres.dump" ]] || die "Postgres dump is empty"
  # Deliberately use direct docker exec -i so pg_restore receives the dump,
  # never a remote shell's command stream.
  docker_call exec -i "$postgres_id" sh -c \
    'exec pg_restore --list' \
    <"${backup_dir}/postgres.dump" >"${backup_dir}/postgres.catalog"
  [[ -s "${backup_dir}/postgres.catalog" ]] || die "Postgres dump catalog is empty"

  minio_access=$(env_value "$PRIMARY_ENV" MINIO_ROOT_USER)
  minio_secret=$(env_value "$PRIMARY_ENV" MINIO_ROOT_PASSWORD)
  minio_bucket=$(env_value "$PRIMARY_ENV" MINIO_BUCKET)
  [[ -n "$minio_access" && -n "$minio_secret" && -n "$minio_bucket" ]] || die "protected MinIO configuration is incomplete"
  require_regex "$minio_bucket" '^[A-Za-z0-9][A-Za-z0-9.-]*$' "MinIO bucket"
  minio_network=$(docker_call inspect "$(container_id minio)" --format '{{range $network, $_ := .NetworkSettings.Networks}}{{println $network}}{{end}}' </dev/null)
  [[ "$(printf '%s\n' "$minio_network" | sed '/^$/d' | wc -l | tr -d '[:space:]')" == "1" ]] || die "MinIO container must have exactly one network"
  minio_network=$(printf '%s\n' "$minio_network" | sed -n '1p')
  require_regex "$minio_network" '^[A-Za-z0-9][A-Za-z0-9_.-]*$' "MinIO network"
  minio_env_file=$(mktemp /tmp/edu-ai-release-driver-minio.XXXXXX)
  chmod 600 "$minio_env_file"
  {
    printf 'MC_ACCESS_KEY=%s\n' "$minio_access"
    printf 'MC_SECRET_KEY=%s\n' "$minio_secret"
    printf 'MC_BUCKET=%s\n' "$minio_bucket"
  } >"$minio_env_file"
  docker_call run --rm --pull never --network "$minio_network" \
    --user 0:0 --entrypoint /bin/sh \
    --env-file "$minio_env_file" \
    -v "${backup_dir}:/backup" \
    "$minio_client_id" -c \
    '/usr/bin/mc alias set local http://minio:9000 "$MC_ACCESS_KEY" "$MC_SECRET_KEY" >/dev/null && /usr/bin/mc mirror --preserve --quiet "local/$MC_BUCKET" /backup/minio >/dev/null' \
    </dev/null >/dev/null
  rm -f -- "$minio_env_file"
  minio_env_file=""
  [[ -d "${backup_dir}/minio" ]] || die "MinIO backup is absent"
  (
    cd "${backup_dir}/minio"
    find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum >SHA256SUMS
    sha256sum -c SHA256SUMS
  ) >/dev/null
  minio_count=$(find "${backup_dir}/minio" -type f ! -name SHA256SUMS | wc -l | tr -d '[:space:]')
  [[ "$minio_count" == "$expected_minio_file_count" ]] || die "MinIO backup file count drift"
  [[ "$(sha256sum "${backup_dir}/minio/SHA256SUMS" | awk '{print $1}')" == "$expected_minio_manifest_sha256" ]] || die "MinIO backup manifest drift"

  brand_manifest="${backup_dir}/brand.sha256"
  brand_state "$brand_manifest"
  tar -C "$APP_DIR" -czf "${backup_dir}/brand.tar.gz" private/brand-materials
  [[ "$(brand_digest "$brand_manifest")" == "$expected_brand_sha256" ]] || die "backup brand checksum mismatch"

  cp -a -- "$PRIMARY_ENV" "${backup_dir}/env"
  cp -a -- "$RELEASE_ENV" "${backup_dir}/release.env"
  cp -a -- "${APP_DIR}/.release-commit" "${backup_dir}/release-commit"
  cp -a -- "${APP_DIR}/RELEASE_COMMIT" "${backup_dir}/RELEASE_COMMIT"
  cp -a -- "$previous_source_manifest" "${backup_dir}/source-files.sha256"

  code_list="${backup_dir}/code-files.list"
  awk '{sub(/^\.\//, "", $2); print $2}' "$previous_source_manifest" >"$code_list"
  tar -C "$APP_DIR" -czf "${backup_dir}/code.tar.gz" -T "$code_list"
  tar -tzf "${backup_dir}/code.tar.gz" >/dev/null

  : >"${backup_dir}/image-inventory.txt"
  for service in "${TAG_SERVICES[@]}"; do
    tag="${rollback_tag_prefix}-${service}"
    docker_call image tag "$previous_image_id" "$tag" </dev/null
    printf '%s %s %s\n' "$service" "$tag" "$previous_image_id" >>"${backup_dir}/image-inventory.txt"
    [[ "$(docker_call image inspect "$tag" --format '{{.Id}}' </dev/null)" == "$previous_image_id" ]] || die "rollback tag identity mismatch"
  done

  sha256sum \
    "${backup_dir}/postgres.dump" \
    "${backup_dir}/postgres.catalog" \
    "${backup_dir}/brand.tar.gz" \
    "${backup_dir}/brand.sha256" \
    "${backup_dir}/env" \
    "${backup_dir}/release.env" \
    "${backup_dir}/release-commit" \
    "${backup_dir}/RELEASE_COMMIT" \
    "${backup_dir}/source-files.sha256" \
    "${backup_dir}/code.tar.gz" \
    "${backup_dir}/code-files.list" \
    "${backup_dir}/image-inventory.txt" \
    "${backup_dir}/minio/SHA256SUMS" \
    >"${backup_dir}/protected.sha256"
  chown -R root:root "$backup_dir"
  find "$backup_dir" -type d -exec chmod 700 {} +
  find "$backup_dir" -type f -exec chmod 600 {} +
  (
    cd "$backup_dir"
    sha256sum -c protected.sha256
  ) >/dev/null

  [[ "$(sha256sum "${backup_dir}/env" | awk '{print $1}')" == "$expected_env_sha256" ]] || die "backup env checksum mismatch"
  [[ "$(sha256sum "${backup_dir}/release.env" | awk '{print $1}')" == "$expected_release_env_sha256" ]] || die "backup release-env checksum mismatch"
  [[ "$(sha256sum "${backup_dir}/source-files.sha256" | awk '{print $1}')" == "$previous_source_manifest_sha256" ]] || die "backup source-manifest checksum mismatch"
  [[ "$(<"${backup_dir}/release-commit")" == "$previous_commit" ]] || die "backup full marker mismatch"
  [[ "$(<"${backup_dir}/RELEASE_COMMIT")" == "$previous_short" ]] || die "backup short marker mismatch"
  [[ "$(wc -l <"${backup_dir}/image-inventory.txt" | tr -d '[:space:]')" == "${#TAG_SERVICES[@]}" ]] || die "backup image inventory count mismatch"

  backup_verify_dir=$(mktemp -d /tmp/edu-ai-release-driver-backup-verify.XXXXXX)
  mkdir -m 700 "${backup_verify_dir}/code" "${backup_verify_dir}/brand"
  tar --no-same-owner --same-permissions -xzf "${backup_dir}/code.tar.gz" -C "${backup_verify_dir}/code"
  tar --no-same-owner --same-permissions -xzf "${backup_dir}/brand.tar.gz" -C "${backup_verify_dir}/brand"
  if find "$backup_verify_dir" -type l -print -quit | grep -q .; then
    die "backup archive contains a symlink"
  fi
  (
    cd "${backup_verify_dir}/code"
    sha256sum -c "${backup_dir}/source-files.sha256"
  ) >/dev/null
  (
    cd "${backup_verify_dir}/brand"
    sha256sum -c "${backup_dir}/brand.sha256"
  ) >/dev/null
  [[ "$(find "${backup_verify_dir}/code" -type f | wc -l | tr -d '[:space:]')" == "$expected_source_file_count" ]] || die "backup code archive file count mismatch"
  [[ "$(find "${backup_verify_dir}/brand" -type f | wc -l | tr -d '[:space:]')" == "$expected_brand_count" ]] || die "backup brand archive file count mismatch"
  rm -rf -- "$backup_verify_dir"
  backup_verify_dir=""

  if find "$backup_dir" -type l -print -quit | grep -q .; then
    die "backup contains a symlink"
  fi
  [[ -z "$(find "$backup_dir" -type d \( ! -user root -o ! -group root -o ! -perm 700 \) -print -quit)" ]] || die "backup directory ownership/mode mismatch"
  [[ -z "$(find "$backup_dir" -type f \( ! -user root -o ! -group root -o ! -perm 600 \) -print -quit)" ]] || die "backup file ownership/mode mismatch"
  assert_protected_inputs
  backup_ready=1
  log "fresh rollback backup is complete: ${backup_dir}"
}

load_candidate_bundle() {
  python3 - "${stage_dir}/backend-image.tar.gz" "$candidate_tag" "${candidate_id#sha256:}" <<'PY'
import json
import pathlib
import sys
import tarfile

bundle, expected_tag, expected_config_digest = sys.argv[1:]
manifest_payload: bytes | None = None
with tarfile.open(bundle, mode="r:gz") as archive:
    for member in archive.getmembers():
        path = member.name[2:] if member.name.startswith("./") else member.name
        if member.isdir():
            path = path.rstrip("/")
            if not path:
                continue
        pure = pathlib.PurePosixPath(path)
        if not path or pure.is_absolute() or str(pure) != path or any(part in {"", ".", ".."} for part in pure.parts):
            raise SystemExit("unsafe image bundle path")
        if not (member.isfile() or member.isdir()):
            raise SystemExit("image bundle contains a non-regular member")
        if path == "manifest.json":
            if not member.isfile() or manifest_payload is not None:
                raise SystemExit("image bundle manifest membership mismatch")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise SystemExit("image bundle manifest is unreadable")
            manifest_payload = extracted.read(1_048_577)
if manifest_payload is None or len(manifest_payload) > 1_048_576:
    raise SystemExit("image bundle manifest is absent or oversized")
document = json.loads(manifest_payload)
if not isinstance(document, list) or len(document) != 1:
    raise SystemExit("image bundle must contain exactly one image")
entry = document[0]
if entry.get("RepoTags") != [expected_tag]:
    raise SystemExit("image bundle tag membership mismatch")
if entry.get("Config") != f"{expected_config_digest}.json":
    raise SystemExit("image bundle config digest mismatch")
PY
  # `docker image load` itself writes every RepoTag in the bundle. Arm tag
  # recovery before it even though the validated bundle contains only the
  # isolated candidate tag.
  tags_changed=1
  docker_call image load --input "${stage_dir}/backend-image.tar.gz" </dev/null >/dev/null
  assert_active_tags "$previous_image_id"
  assert_candidate_image
}

retag_candidate() {
  local service
  tags_changed=1
  for service in "${TAG_SERVICES[@]}"; do
    docker_call image tag "$candidate_id" "${COMPOSE_PROJECT}-${service}:local" </dev/null
  done
  docker_call image tag "$candidate_id" "${COMPOSE_PROJECT}-backend:local" </dev/null
  assert_active_tags "$candidate_id"
}

overlay_candidate_source() {
  local app_owner app_group path source_path destination_path mode
  ((backup_ready == 1)) || die "refusing source overlay without a completed fresh backup"
  app_owner=$(stat -c '%U' "$APP_DIR")
  app_group=$(stat -c '%G' "$APP_DIR")
  require_regex "$app_owner" '^[A-Za-z_][A-Za-z0-9_-]*$' "application owner"
  require_regex "$app_group" '^[A-Za-z_][A-Za-z0-9_-]*$' "application group"
  overlay_changed=1
  # Overlay only the regular files already extracted and validated in the
  # protected child. Candidate/previous path-set equality guarantees no stale
  # removed file can survive this source-only update.
  while IFS= read -r path; do
    source_path="${release_extract_dir}/${path}"
    destination_path="${APP_DIR}/${path}"
    [[ -f "$source_path" && ! -L "$source_path" ]] || die "validated source member became unsafe"
    [[ -f "$destination_path" && ! -L "$destination_path" ]] || die "active source destination became unsafe"
    mode=$(stat -c '%a' "$source_path")
    [[ "$mode" =~ ^(600|644|700|755)$ ]] || die "source member mode is outside the reviewed allowlist"
    install -o "$app_owner" -g "$app_group" -m "$mode" -- "$source_path" "$destination_path"
  done <"$source_paths_file"

  marker_tmp=$(mktemp "${APP_DIR}/.release-commit.XXXXXX")
  marker_short_tmp=$(mktemp "${APP_DIR}/RELEASE_COMMIT.XXXXXX")
  printf '%s\n' "$candidate_commit" >"$marker_tmp"
  printf '%s\n' "$candidate_short" >"$marker_short_tmp"
  chown "$app_owner:$app_group" "$marker_tmp" "$marker_short_tmp"
  chmod 600 "$marker_tmp" "$marker_short_tmp"
  mv -f -- "$marker_tmp" "${APP_DIR}/.release-commit"
  marker_tmp=""
  mv -f -- "$marker_short_tmp" "${APP_DIR}/RELEASE_COMMIT"
  marker_short_tmp=""
  (
    cd "$APP_DIR"
    sha256sum -c "${stage_dir}/source-files.sha256"
  ) >/dev/null
  assert_protected_inputs
}

run_one_shots() {
  compose_call up --no-build --no-deps --force-recreate \
    --abort-on-container-exit --exit-code-from minio-init minio-init
  compose_call up --no-build --no-deps --force-recreate \
    --abort-on-container-exit --exit-code-from backend-migrate backend-migrate
  local init_id migrate_id
  init_id=$(container_id_all minio-init)
  [[ -n "$init_id" ]] || die "MinIO init container is absent"
  [[ "$(docker_call inspect "$init_id" --format '{{.Image}}' </dev/null)" == "$minio_client_id" ]] || die "MinIO init image mismatch"
  [[ "$(docker_call inspect "$init_id" --format '{{.State.ExitCode}}' </dev/null)" == "0" ]] || die "MinIO init exit code is nonzero"
  migrate_id=$(container_id_all backend-migrate)
  [[ -n "$migrate_id" ]] || die "migration container is absent"
  [[ "$(docker_call inspect "$migrate_id" --format '{{.Image}}' </dev/null)" == "$candidate_id" ]] || die "migration image mismatch"
  [[ "$(docker_call inspect "$migrate_id" --format '{{.State.ExitCode}}' </dev/null)" == "0" ]] || die "migration exit code is nonzero"
  [[ "$(sql_scalar "SELECT version_num FROM alembic_version")" == "$EXPECTED_ALEMBIC_HEAD" ]] || die "post-migration Alembic head drift"
  [[ "$(sql_scalar "SELECT count(*) FROM sources WHERE active_version_id IS NOT NULL")" == "$EXPECTED_ACTIVE_SOURCES" ]] || die "post-migration source count drift"
  assert_active_tags "$candidate_id"
  assert_protected_inputs
  assert_exact_vectors "after default-off one-shots"
}

wait_for_api_health() {
  local attempt api_id status
  api_id=$(container_id acquisition-api)
  for attempt in $(seq 1 30); do
    status=$(docker_call inspect "$api_id" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' </dev/null || true)
    [[ "$status" == "healthy" ]] && return 0
    sleep 2
  done
  die "API did not become healthy"
}

assert_service_runtime() {
  local service=$1
  local expected_id=$2
  local cid status image restart_count
  cid=$(container_id "$service")
  [[ -n "$cid" ]] || die "${service} has no running container"
  status=$(docker_call inspect "$cid" --format '{{.State.Status}}' </dev/null)
  image=$(docker_call inspect "$cid" --format '{{.Image}}' </dev/null)
  restart_count=$(docker_call inspect "$cid" --format '{{.RestartCount}}' </dev/null)
  [[ "$status" == "running" && "$image" == "$expected_id" && "$restart_count" == "0" ]] || die "${service} runtime identity/liveness mismatch"
}

recreate_service() {
  compose_call up -d --no-build --no-deps --force-recreate "$1"
}

restore_candidate_services() {
  assert_safe_window
  recreate_service acquisition-api
  wait_for_api_health
  assert_service_runtime acquisition-api "$candidate_id"
  assert_flags_false
  assert_exact_vectors "after API restore"

  recreate_service acquisition-scheduler
  sleep 5
  assert_service_runtime acquisition-scheduler "$candidate_id"
  assert_safe_window
  assert_exact_vectors "after acquisition scheduler restore"
  recreate_service acquisition-worker
  sleep 2
  assert_service_runtime acquisition-worker "$candidate_id"
  assert_exact_vectors "after acquisition worker restore"

  recreate_service governance-scheduler
  sleep 5
  assert_service_runtime governance-scheduler "$candidate_id"
  assert_safe_window
  assert_exact_vectors "after governance scheduler restore"
  recreate_service governance-worker
  sleep 2
  assert_service_runtime governance-worker "$candidate_id"
  assert_exact_vectors "after governance worker restore"

  recreate_service content-scheduler
  sleep 5
  assert_service_runtime content-scheduler "$candidate_id"
  assert_safe_window
  assert_exact_vectors "after content scheduler restore"
  recreate_service content-worker
  assert_content_flags_false
  sleep 2
  assert_service_runtime content-worker "$candidate_id"
  assert_exact_vectors "after content worker restore"

  assert_exact_vectors "before dispatcher restore"
  assert_safe_window
  recreate_service wecom-dispatcher
  sleep 2
  assert_service_runtime wecom-dispatcher "$candidate_id"
  assert_exact_vectors "after dispatcher restore"
}

restore_overlay_for_recovery() {
  local app_owner app_group
  ((backup_ready == 1)) || return 1
  [[ -s "${backup_dir}/code.tar.gz" ]] || return 1
  app_owner=$(stat -c '%U' "$APP_DIR")
  app_group=$(stat -c '%G' "$APP_DIR")
  tar -xzf "${backup_dir}/code.tar.gz" -C "$APP_DIR"
  cp -a -- "${backup_dir}/release-commit" "${APP_DIR}/.release-commit"
  cp -a -- "${backup_dir}/RELEASE_COMMIT" "${APP_DIR}/RELEASE_COMMIT"
  chown "$app_owner:$app_group" "${APP_DIR}/.release-commit" "${APP_DIR}/RELEASE_COMMIT"
  chmod 600 "${APP_DIR}/.release-commit" "${APP_DIR}/RELEASE_COMMIT"
  (
    cd "$APP_DIR"
    sha256sum -c "${backup_dir}/source-files.sha256"
  ) >/dev/null
}

restore_tags_for_recovery() {
  local service
  for service in "${TAG_SERVICES[@]}"; do
    docker_call image tag "$previous_image_id" "${COMPOSE_PROJECT}-${service}:local" </dev/null
  done
  docker_call image tag "$previous_image_id" "${COMPOSE_PROJECT}-backend:local" </dev/null
}

restore_old_service() {
  local service=$1
  local cid=${OLD_CONTAINER_IDS[$service]:-}
  local image=""
  if [[ -n "$cid" ]] && docker_call container inspect "$cid" >/dev/null 2>&1; then
    image=$(docker_call inspect "$cid" --format '{{.Image}}' </dev/null)
  fi
  if [[ "$image" == "$previous_image_id" ]]; then
    docker_call start "$cid" </dev/null >/dev/null
  else
    compose_call up -d --no-build --no-deps --force-recreate "$service"
  fi
}

restore_services_for_recovery() {
  assert_safe_window
  restore_old_service acquisition-api
  wait_for_api_health
  assert_service_runtime acquisition-api "$previous_image_id"
  assert_flags_false
  assert_exact_vectors "recovery after API restore"

  restore_old_service acquisition-scheduler
  sleep 5
  assert_service_runtime acquisition-scheduler "$previous_image_id"
  assert_exact_vectors "recovery after acquisition scheduler restore"
  restore_old_service acquisition-worker
  sleep 2
  assert_service_runtime acquisition-worker "$previous_image_id"
  assert_exact_vectors "recovery after acquisition worker restore"

  restore_old_service governance-scheduler
  sleep 5
  assert_safe_window
  assert_service_runtime governance-scheduler "$previous_image_id"
  assert_exact_vectors "recovery after governance scheduler restore"
  restore_old_service governance-worker
  sleep 2
  assert_service_runtime governance-worker "$previous_image_id"
  assert_exact_vectors "recovery after governance worker restore"

  restore_old_service content-scheduler
  sleep 5
  assert_safe_window
  assert_service_runtime content-scheduler "$previous_image_id"
  assert_exact_vectors "recovery after content scheduler restore"
  restore_old_service content-worker
  assert_content_flags_false
  sleep 2
  assert_service_runtime content-worker "$previous_image_id"
  assert_exact_vectors "recovery after content worker restore"

  assert_exact_vectors "recovery before dispatcher restore"
  assert_safe_window
  restore_old_service wecom-dispatcher
  sleep 2
  assert_service_runtime wecom-dispatcher "$previous_image_id"
  assert_running_image_and_markers "$previous_image_id" "$previous_commit" "$previous_short"
  assert_active_tags "$previous_image_id"
  assert_protected_inputs
  assert_exact_vectors "recovery complete"
  assert_safe_logs
}

enter_app_dir() {
  cd "$APP_DIR"
}

recover() {
  local original_rc=${1:-1}
  local recovery_rc=0
  ((recovery_running == 0)) || return 1
  recovery_running=1
  log "recovery starting after exit ${original_rc}; backup_ready=${backup_ready} tags_changed=${tags_changed} overlay_changed=${overlay_changed}"
  enter_app_dir || return 1

  if ((overlay_changed == 1)); then
    restore_overlay_for_recovery || recovery_rc=1
  fi
  if ((tags_changed == 1)); then
    restore_tags_for_recovery || recovery_rc=1
  fi
  if ((services_quiesced == 1 && recovery_rc == 0)); then
    restore_services_for_recovery || recovery_rc=1
  fi
  if ((recovery_rc == 0)); then
    recovered=1
    log "recovery completed"
  else
    log "RECOVERY INCOMPLETE: provider-facing workers remain gated by the failed invariant"
  fi
  return "$recovery_rc"
}

cleanup_local_artifacts() {
  if [[ -n "$minio_env_file" && "$minio_env_file" == /tmp/edu-ai-release-driver-minio.* ]]; then
    rm -f -- "$minio_env_file"
  fi
  if [[ -n "$release_extract_dir" && "$release_extract_dir" == /tmp/edu-ai-release-driver-source.* ]]; then
    rm -rf -- "$release_extract_dir"
  fi
  if [[ -n "$backup_verify_dir" && "$backup_verify_dir" == /tmp/edu-ai-release-driver-backup-verify.* ]]; then
    rm -rf -- "$backup_verify_dir"
  fi
  if [[ -n "$log_scan_file" && "$log_scan_file" == /tmp/edu-ai-release-driver-logs.* ]]; then
    rm -f -- "$log_scan_file"
  fi
  if [[ -n "$source_paths_file" && "$source_paths_file" == /tmp/edu-ai-release-driver-source-paths.* ]]; then
    rm -f -- "$source_paths_file"
  fi
  if [[ -n "$previous_source_paths_file" && "$previous_source_paths_file" == /tmp/edu-ai-release-driver-previous-paths.* ]]; then
    rm -f -- "$previous_source_paths_file"
  fi
  if [[ -n "$marker_tmp" && "$marker_tmp" == "${APP_DIR}/.release-commit."* ]]; then
    rm -f -- "$marker_tmp"
  fi
  if [[ -n "$marker_short_tmp" && "$marker_short_tmp" == "${APP_DIR}/RELEASE_COMMIT."* ]]; then
    rm -f -- "$marker_short_tmp"
  fi
}

on_err() {
  failure_rc=$?
  log "command failed with exit ${failure_rc}"
  return "$failure_rc"
}

on_signal() {
  local signal_name=$1
  local signal_rc=$2
  log "received ${signal_name}"
  exit "$signal_rc"
}

on_exit() {
  local rc=$?
  local recovery_rc=0
  trap - ERR EXIT
  trap '' HUP INT TERM
  if ((rc != 0 && completed == 0)); then
    set +e
    recover "$rc"
    recovery_rc=$?
    set -e
  fi
  cleanup_local_artifacts
  if ((recovery_rc != 0)); then
    log "original exit=${rc}; recovery exit=${recovery_rc}"
    exit 125
  fi
  exit "$rc"
}

install_traps() {
  trap on_err ERR
  trap on_exit EXIT
  trap 'on_signal HUP 129' HUP
  trap 'on_signal INT 130' INT
  trap 'on_signal TERM 143' TERM
}

record_final_evidence() {
  local service cid
  {
    printf 'release_commit=%s\n' "$candidate_commit"
    printf 'source_sha256=%s\n' "$source_sha256"
    printf 'image_bundle_sha256=%s\n' "$image_bundle_sha256"
    printf 'candidate_image_id=%s\n' "$candidate_id"
    printf 'driver_sha256=%s\n' "$script_sha256"
    printf 'durable_vector=%s\n' "$(durable_vector)"
    printf 'wecom_vector=%s\n' "$(wecom_vector)"
    printf 'historical_queued=%s\n' "$(historical_queued_vector)"
    printf 'actionable_vector=%s\n' "$(actionable_vector)"
    for service in "${APP_SERVICES[@]}"; do
      cid=$(container_id "$service")
      printf '%s=%s,%s,%s\n' \
        "$service" "$cid" \
        "$(docker_call inspect "$cid" --format '{{.Image}}' </dev/null)" \
        "$(docker_call inspect "$cid" --format '{{.RestartCount}}' </dev/null)"
    done
  } >"${backup_dir}/release-result.txt"
  chmod 600 "${backup_dir}/release-result.txt"
}

main() {
  local first_vector second_vector
  local lock_fd

  parse_args "$@"
  validate_args
  [[ ! -t 0 && "$(readlink /proc/$$/fd/0)" == "/dev/null" ]] || die "stdin must be exactly /dev/null"
  [[ "$PWD" == "$APP_DIR" && "$(pwd -P)" == "$APP_DIR" && ! -L "$APP_DIR" ]] || die "invoke only from the physical absolute application working directory"
  [[ -f "$COMPOSE_FILE" && -f "$PRIMARY_ENV" && -f "$RELEASE_ENV" ]] || die "absolute Compose inputs are incomplete"
  ((EUID == 0)) || die "release driver requires root"
  assert_stage_exact
  extract_and_validate_source
  assert_previous_source
  [[ "$(df -Pk "$APP_DIR" | awk 'NR==2 {print $4}')" -ge 5242880 ]] || die "less than 5 GiB is free"
  [[ "$(df -Pk "$BACKUP_ROOT" | awk 'NR==2 {print $4}')" -ge 5242880 ]] || die "backup filesystem has less than 5 GiB free"
  [[ "$(df -Pi "$BACKUP_ROOT" | awk 'NR==2 {gsub(/%/, "", $5); print 100-$5}')" -ge 5 ]] || die "backup filesystem has less than 5 percent free inodes"
  systemctl is-enabled edu-ai-backup.timer </dev/null >/dev/null
  systemctl is-active edu-ai-backup.timer </dev/null >/dev/null
  assert_compose_contract
  assert_infrastructure
  assert_minio_client_image
  assert_safe_window
  assert_protected_inputs
  assert_active_tags "$previous_image_id"
  assert_running_image_and_markers "$previous_image_id" "$previous_commit" "$previous_short"
  assert_flags_false
  assert_content_flags_false
  assert_safe_logs
  assert_exact_vectors "preflight sample 1"
  first_vector=$(durable_vector)
  sleep "$preflight_sample_seconds"
  second_vector=$(durable_vector)
  [[ "$second_vector" == "$first_vector" && "$second_vector" == "$expected_vector" ]] || die "preflight samples are not stable"
  assert_exact_vectors "preflight sample 2"
  capture_old_containers

  # Lock is acquired before the first stop and the descriptor remains open
  # until EXIT has finished recovery or the release has completed.
  exec {lock_fd}>"$BACKUP_LOCK"
  flock --nonblock "$lock_fd" || die "another backup/release owns the backup lock"
  prepare_fresh_backup
  quiesce_writers
  create_fresh_backup

  load_candidate_bundle
  assert_active_tags "$previous_image_id"
  retag_candidate
  overlay_candidate_source
  run_one_shots
  restore_candidate_services

  assert_running_image_and_markers "$candidate_id" "$candidate_commit" "$candidate_short"
  assert_active_tags "$candidate_id"
  assert_flags_false
  assert_protected_inputs
  assert_exact_vectors "candidate stability sample 1"
  assert_safe_logs
  assert_safe_window
  sleep "$stability_seconds"
  assert_safe_window
  assert_running_image_and_markers "$candidate_id" "$candidate_commit" "$candidate_short"
  assert_flags_false
  assert_protected_inputs
  assert_exact_vectors "candidate stability sample 2"
  assert_safe_logs
  record_final_evidence
  completed=1
  log "default-off release completed after ${stability_seconds}s stability; no OCR fixture/provider call was run"
}

if [[ ${RELEASE_DRIVER_SOURCE_ONLY:-0} != 1 ]]; then
  install_traps
  main "$@"
fi
