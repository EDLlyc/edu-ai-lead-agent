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
readonly SOURCE_INSTALL_TMP_ROOT="${BACKUP_ROOT}"
readonly BACKUP_LOCK="/var/lock/edu-ai-backup.lock"
readonly EXPECTED_ALEMBIC_HEAD="20260815_0021"
readonly EXPECTED_ACTIVE_SOURCES="10"
readonly EXPECTED_BUSINESS_TIMEZONE="Asia/Shanghai"
readonly MINIO_CLIENT_IMAGE="minio/mc:RELEASE.2025-04-16T18-13-26Z"
readonly SAFE_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
readonly SHARED_ACTIVE_TAG="${COMPOSE_PROJECT}-backend:local"
readonly SERVICE_ACTIVE_TAG_SUFFIX="latest"
readonly FORBIDDEN_SERVICE_TAG_SUFFIX="local"
readonly API_ENTRYPOINT_MODULE="app.api_main"

readonly -a LONG_LIVED_ENTRYPOINT_MODULES=(
  app.scheduler_main
  app.worker_main
  app.governance_scheduler_main
  app.governance_worker_main
  app.content_scheduler_main
  app.content_worker_main
  app.wecom_dispatcher_main
)

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
source_modes_file=""
destination_modes_file=""
destination_source_owner=""
destination_source_group=""
source_install_tmp_dir=""
source_install_tmp_parent=""
image_source_manifest_tmp=""
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
  assert_candidate_tag_is_isolated
  ((minimum_safe_seconds >= 900)) || die "minimum safe window cannot be weakened below 900 seconds"
  ((preflight_sample_seconds >= 15)) || die "preflight sample cannot be weakened below 15 seconds"
  ((stability_seconds >= 30)) || die "stability sample cannot be weakened below 30 seconds"
}

docker_call() {
  env -i PATH="$SAFE_PATH" HOME=/root /usr/bin/docker "$@"
}

service_active_tag() {
  printf '%s-%s:%s\n' "$COMPOSE_PROJECT" "$1" "$SERVICE_ACTIVE_TAG_SUFFIX"
}

service_forbidden_local_tag() {
  printf '%s-%s:%s\n' "$COMPOSE_PROJECT" "$1" "$FORBIDDEN_SERVICE_TAG_SUFFIX"
}

rollback_tag_for_service() {
  printf '%s-%s\n' "$rollback_tag_prefix" "$1"
}

assert_candidate_tag_is_isolated() {
  local service
  if [[ "$candidate_tag" == "$SHARED_ACTIVE_TAG" ]]; then
    die "candidate tag must not be the active shared tag"
    return 1
  fi
  for service in "${TAG_SERVICES[@]}"; do
    if [[ "$candidate_tag" == "$(service_active_tag "$service")" ]]; then
      die "candidate tag must not be a service active tag"
      return 1
    fi
    if [[ "$candidate_tag" == "$(service_forbidden_local_tag "$service")" ]]; then
      die "candidate tag must not be a forbidden service-local tag"
      return 1
    fi
  done
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
  [[ "$(env_value "$RELEASE_ENV" APP_IMAGE)" == "$SHARED_ACTIVE_TAG" ]] || die "release env does not select the reviewed local shared tag"
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
  local service tag forbidden_tag image
  image=$(docker_call image inspect "$SHARED_ACTIVE_TAG" --format '{{.Id}}' </dev/null)
  [[ "$image" == "$expected_id" ]] || die "shared application tag mismatch"
  for service in "${TAG_SERVICES[@]}"; do
    tag=$(service_active_tag "$service")
    image=$(docker_call image inspect "$tag" --format '{{.Id}}' </dev/null)
    [[ "$image" == "$expected_id" ]] || die "${service} application tag mismatch"
    forbidden_tag=$(service_forbidden_local_tag "$service")
    if docker_call image inspect "$forbidden_tag" >/dev/null 2>&1; then
      die "unexpected ${service} :local tag exists"
    fi
  done
}

write_active_tag_inventory() {
  local output=$1
  local expected_id=$2
  local service tag image
  assert_active_tags "$expected_id"
  : >"$output"
  image=$(docker_call image inspect "$SHARED_ACTIVE_TAG" --format '{{.Id}}' </dev/null)
  [[ "$image" == "$expected_id" ]] || die "shared prior tag identity mismatch"
  printf 'shared %s %s\n' "$SHARED_ACTIVE_TAG" "$expected_id" >>"$output"
  for service in "${TAG_SERVICES[@]}"; do
    tag=$(service_active_tag "$service")
    image=$(docker_call image inspect "$tag" --format '{{.Id}}' </dev/null)
    [[ "$image" == "$expected_id" ]] || die "${service} prior tag identity mismatch"
    printf '%s %s %s\n' "$service" "$tag" "$expected_id" >>"$output"
  done
  [[ "$(wc -l <"$output" | tr -d '[:space:]')" == "$((1 + ${#TAG_SERVICES[@]}))" ]] || die "active tag inventory count mismatch"
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

validate_source_archive_modes() {
  local archive_path=$1
  local expected_paths_file=$2
  local output_modes_file=$3
  local expected_count=$4
  python3 - "$archive_path" "$expected_paths_file" "$output_modes_file" "$expected_count" <<'PY'
import pathlib
import sys
import tarfile

archive_path = pathlib.Path(sys.argv[1])
expected_paths = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
output_path = pathlib.Path(sys.argv[3])
expected_count = int(sys.argv[4])
canonical_modes = {
    0o644: "0644",
    0o664: "0644",
    0o755: "0755",
    0o775: "0755",
}
canonical_directory_modes = {0o755, 0o775}
expected = set(expected_paths)
observed: dict[str, str] = {}
seen: set[str] = set()


def is_safe_path(raw: str) -> bool:
    path = pathlib.PurePosixPath(raw)
    return bool(
        raw
        and not path.is_absolute()
        and str(path) == raw
        and all(part not in {"", ".", ".."} for part in path.parts)
        and all(char not in raw for char in ("\0", "\n", "\r", "\t"))
    )


if (
    len(expected_paths) != expected_count
    or len(expected_paths) != len(expected)
    or expected_paths != sorted(expected_paths)
    or any(not is_safe_path(raw) for raw in expected_paths)
):
    raise SystemExit("source archive expected path set is invalid")

with tarfile.open(archive_path, mode="r:gz") as archive:
    for member in archive.getmembers():
        raw = member.name[2:] if member.name.startswith("./") else member.name
        if member.isdir():
            raw = raw.rstrip("/")
            if not raw:
                if member.mode not in canonical_directory_modes:
                    raise SystemExit("source archive root directory mode is outside the canonical contract")
                continue
        if not is_safe_path(raw) or raw in seen:
            raise SystemExit("unsafe or duplicate source archive member")
        seen.add(raw)
        if member.isfile():
            if raw not in expected:
                raise SystemExit("source archive regular member is outside the exact path set")
            canonical = canonical_modes.get(member.mode)
            if canonical is None:
                raise SystemExit("source archive regular member mode is outside the canonical contract")
            observed[raw] = canonical
        elif member.isdir():
            if member.mode not in canonical_directory_modes:
                raise SystemExit("source archive directory mode is outside the canonical contract")
        else:
            raise SystemExit("source archive contains a non-regular member")

if (
    len(observed) != expected_count
    or set(observed) != expected
):
    raise SystemExit("source archive mode evidence membership mismatch")
output_path.write_text(
    "".join(f"{observed[path]}\t{path}\n" for path in sorted(observed)),
    encoding="utf-8",
)
PY
}

validate_extracted_source_modes() {
  local extracted_root=$1
  local expected_paths_file=$2
  local modes_file=$3
  local expected_count=$4
  python3 - "$extracted_root" "$expected_paths_file" "$modes_file" "$expected_count" <<'PY'
import pathlib
import re
import stat
import sys

root = pathlib.Path(sys.argv[1])
expected_paths = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
mode_lines = pathlib.Path(sys.argv[3]).read_text(encoding="utf-8").splitlines()
expected_count = int(sys.argv[4])
canonical_modes = {
    0o644: "0644",
    0o664: "0644",
    0o755: "0755",
    0o775: "0755",
}
entries: list[tuple[str, str]] = []
for line in mode_lines:
    match = re.fullmatch(r"(0644|0755)\t([^\t\r\n]+)", line)
    if match is None:
        raise SystemExit("source mode evidence syntax is invalid")
    canonical, raw = match.groups()
    path = pathlib.PurePosixPath(raw)
    if (
        path.is_absolute()
        or str(path) != raw
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(char in raw for char in ("\0", "\n", "\r", "\t"))
    ):
        raise SystemExit("source mode evidence path is unsafe")
    entries.append((raw, canonical))
paths = [path for path, _canonical in entries]
if (
    len(entries) != expected_count
    or len(paths) != len(set(paths))
    or paths != sorted(paths)
    or len(expected_paths) != expected_count
    or len(expected_paths) != len(set(expected_paths))
    or expected_paths != sorted(expected_paths)
    or paths != sorted(expected_paths)
):
    raise SystemExit("source mode evidence path set is invalid")
for raw, canonical in entries:
    metadata = (root / raw).lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise SystemExit("extracted source mode member is not regular")
    if canonical_modes.get(stat.S_IMODE(metadata.st_mode)) != canonical:
        raise SystemExit("extracted source member mode differs from canonical evidence")
PY
}

extract_and_validate_source() {
  local manifest_count
  source_paths_file=$(mktemp /tmp/edu-ai-release-driver-source-paths.XXXXXX)
  validate_source_manifest "${stage_dir}/source-files.sha256" "$source_paths_file" "$expected_source_file_count"
  source_modes_file=$(mktemp /tmp/edu-ai-release-driver-source-modes.XXXXXX)
  validate_source_archive_modes \
    "${stage_dir}/source.tar.gz" "$source_paths_file" "$source_modes_file" \
    "$expected_source_file_count"
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
  validate_extracted_source_modes \
    "$release_extract_dir" "$source_paths_file" "$source_modes_file" \
    "$expected_source_file_count"
  (
    cd "$release_extract_dir"
    sha256sum -c "${stage_dir}/source-files.sha256"
  ) >/dev/null
  manifest_count=$(wc -l <"${stage_dir}/source-files.sha256" | tr -d '[:space:]')
  [[ "$manifest_count" == "$expected_source_file_count" ]] || die "source manifest file count mismatch"

  [[ "$(find "$release_extract_dir" -type f | wc -l | tr -d '[:space:]')" == "$expected_source_file_count" ]] || die "source extraction file count mismatch"
}

assert_candidate_source_mode_pair() {
  local semantic_mode=$1
  local observed_mode=$2
  case "${semantic_mode}:${observed_mode}" in
    0644:644|0644:664|0755:755|0755:775) return 0 ;;
    *) die "candidate source mode differs from its semantic class" ;;
  esac
}

assert_destination_source_mode_pair() {
  local semantic_mode=$1
  local observed_mode=$2
  case "${semantic_mode}:${observed_mode}" in
    0644:600|0644:644|0755:700|0755:755) return 0 ;;
    *) die "destination source mode is unsafe or differs from the candidate executable class" ;;
  esac
}

validate_destination_mode_evidence() {
  local candidate_modes_file=$1
  local preserved_modes_file=$2
  local expected_count=$3
  local expected_owner=$4
  local expected_group=$5
  python3 - "$candidate_modes_file" "$preserved_modes_file" "$expected_count" \
    "$expected_owner" "$expected_group" <<'PY'
import pathlib
import re
import sys

candidate_path = pathlib.Path(sys.argv[1])
preserved_path = pathlib.Path(sys.argv[2])
expected_count = int(sys.argv[3])
expected_owner = sys.argv[4]
expected_group = sys.argv[5]
candidate_pattern = re.compile(r"(0644|0755)\t([^\t\r\n]+)")
account_pattern = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
preserved_pattern = re.compile(
    r"(0644|0755)\t(0600|0644|0700|0755)\t"
    r"([A-Za-z_][A-Za-z0-9_-]*)\t([A-Za-z_][A-Za-z0-9_-]*)\t([^\t\r\n]+)"
)
allowed_pairs = {
    ("0644", "0600"),
    ("0644", "0644"),
    ("0755", "0700"),
    ("0755", "0755"),
}


def safe_path(raw: str) -> bool:
    path = pathlib.PurePosixPath(raw)
    return bool(
        raw
        and not path.is_absolute()
        and str(path) == raw
        and all(part not in {"", ".", ".."} for part in path.parts)
        and all(char not in raw for char in ("\0", "\n", "\r", "\t"))
    )


candidate_entries: list[tuple[str, str]] = []
for line in candidate_path.read_text(encoding="utf-8").splitlines():
    match = candidate_pattern.fullmatch(line)
    if match is None:
        raise SystemExit("candidate source mode evidence syntax is invalid")
    semantic, raw = match.groups()
    if not safe_path(raw):
        raise SystemExit("candidate source mode evidence path is unsafe")
    candidate_entries.append((raw, semantic))

if account_pattern.fullmatch(expected_owner) is None or account_pattern.fullmatch(expected_group) is None:
    raise SystemExit("destination mode evidence expected ownership is invalid")

preserved_entries: list[tuple[str, str, str, str, str]] = []
for line in preserved_path.read_text(encoding="utf-8").splitlines():
    match = preserved_pattern.fullmatch(line)
    if match is None:
        raise SystemExit("destination mode evidence syntax is invalid")
    semantic, preserved, owner, group, raw = match.groups()
    if (
        not safe_path(raw)
        or (semantic, preserved) not in allowed_pairs
        or owner != expected_owner
        or group != expected_group
    ):
        raise SystemExit("destination mode evidence entry is unsafe")
    preserved_entries.append((raw, semantic, preserved, owner, group))

candidate_paths = [raw for raw, _semantic in candidate_entries]
preserved_paths = [raw for raw, _semantic, _preserved, _owner, _group in preserved_entries]
if (
    len(candidate_entries) != expected_count
    or len(candidate_paths) != len(set(candidate_paths))
    or candidate_paths != sorted(candidate_paths)
    or len(preserved_entries) != expected_count
    or len(preserved_paths) != len(set(preserved_paths))
    or preserved_paths != sorted(preserved_paths)
    or candidate_paths != preserved_paths
    or any(
        candidate_entries[position][1] != preserved_entries[position][1]
        for position in range(expected_count)
    )
):
    raise SystemExit("destination mode evidence does not bind the exact candidate path set")
PY
}

capture_destination_source_modes() {
  local destination_root=$1
  local expected_owner=$2
  local expected_group=$3
  local output_modes_file=$4
  local semantic_mode path observed_mode observed_owner observed_group
  [[ -f "$output_modes_file" && ! -L "$output_modes_file" && ! -s "$output_modes_file" ]] \
    || die "destination mode evidence output is absent, unsafe, or nonempty"
  while IFS=$'\t' read -r semantic_mode path; do
    [[ "$semantic_mode" =~ ^0(644|755)$ && -n "$path" ]] || die "candidate source mode evidence became invalid"
    assert_anchored_regular_source_path "$destination_root" "$path" "previous source member"
    observed_mode=$(stat -c '%a' "${destination_root}/${path}")
    observed_owner=$(stat -c '%U' "${destination_root}/${path}")
    observed_group=$(stat -c '%G' "${destination_root}/${path}")
    assert_destination_source_mode_pair "$semantic_mode" "$observed_mode"
    [[ "$observed_owner" == "$expected_owner" && "$observed_group" == "$expected_group" ]] \
      || die "previous source member ownership drift"
    printf '%s\t0%s\t%s\t%s\t%s\n' \
      "$semantic_mode" "$observed_mode" "$observed_owner" "$observed_group" "$path" \
      >>"$output_modes_file"
  done <"$source_modes_file"
  validate_destination_mode_evidence \
    "$source_modes_file" "$output_modes_file" "$expected_source_file_count" \
    "$expected_owner" "$expected_group"
}

assert_anchored_regular_source_path() {
  local root=$1
  local relative_path=$2
  local label=$3
  local root_resolved path_resolved expected_resolved
  [[ "$root" == /* && -d "$root" && ! -L "$root" ]] || die "${label} root is absent or unsafe"
  [[ -n "$relative_path" && "$relative_path" != /* && "$relative_path" != *$'\n'* && "$relative_path" != *$'\r'* && "$relative_path" != *$'\t'* ]] \
    || die "${label} relative path is unsafe"
  root_resolved=$(realpath -e -- "$root") || die "cannot resolve ${label} root"
  [[ "$root_resolved" == "$root" ]] || die "${label} root is not the physical absolute path"
  [[ -f "${root}/${relative_path}" && ! -L "${root}/${relative_path}" ]] \
    || die "${label} is absent, non-regular, or a symlink"
  path_resolved=$(realpath -e -- "${root}/${relative_path}") || die "cannot resolve ${label}"
  expected_resolved="${root_resolved}/${relative_path}"
  [[ "$path_resolved" == "$expected_resolved" ]] || die "${label} traverses a symlink or escapes its root"
}

assert_trusted_install_tmp_root() {
  local trusted_parent=$1
  local destination_root=$2
  local trusted_parent_resolved destination_root_resolved
  local trusted_mode trusted_uid trusted_gid
  [[ "$trusted_parent" == /* && -d "$trusted_parent" && ! -L "$trusted_parent" ]] \
    || die "trusted install root is absent or unsafe"
  trusted_parent_resolved=$(realpath -e -- "$trusted_parent") \
    || die "cannot resolve trusted install root"
  [[ "$trusted_parent_resolved" == "$trusted_parent" ]] \
    || die "trusted install root is not physical"
  trusted_mode=$(stat -c '%a' "$trusted_parent")
  trusted_uid=$(stat -c '%u' "$trusted_parent")
  trusted_gid=$(stat -c '%g' "$trusted_parent")
  [[ "$trusted_mode" == "700" && "$trusted_uid" == "0" && "$trusted_gid" == "0" ]] \
    || die "trusted install root is not root-owned mode 0700"
  (( (8#$trusted_mode & 8#022) == 0 )) || die "trusted install root is group/world writable"
  [[ "$destination_root" == /* && -d "$destination_root" && ! -L "$destination_root" ]] \
    || die "temporary install destination root is absent or unsafe"
  destination_root_resolved=$(realpath -e -- "$destination_root") \
    || die "cannot resolve temporary install destination root"
  [[ "$destination_root_resolved" == "$destination_root" ]] \
    || die "temporary install destination root is not physical"
  [[ "$(stat -c '%d' "$trusted_parent")" == "$(stat -c '%d' "$destination_root")" ]] \
    || die "trusted install root is not on the destination filesystem"
}

is_source_install_tmp_path() {
  local trusted_parent=$1
  local temp_dir=$2
  local expected_prefix temp_name
  expected_prefix="${trusted_parent}/.edu-ai-source-install."
  [[ "$temp_dir" == "${expected_prefix}"* ]] || return 1
  temp_name=${temp_dir#"$expected_prefix"}
  [[ "$temp_name" =~ ^[A-Za-z0-9]{6}$ ]]
}

assert_source_install_tmp_root_preflight() {
  local trusted_parent=$1
  local destination_root=$2
  local stale_marker
  assert_trusted_install_tmp_root "$trusted_parent" "$destination_root"
  stale_marker=$(find "$trusted_parent" -mindepth 1 -maxdepth 1 \
    -name '.edu-ai-source-install.*' -printf x -quit) \
    || die "cannot scan trusted install root for stale temporary entries"
  [[ -z "$stale_marker" ]] || die "stale source install temporary entry exists"
}

assert_install_tmp_directory() {
  local trusted_parent=$1
  local destination_root=$2
  local destination_path=$3
  local temp_dir=$4
  local destination_parent destination_parent_resolved trusted_parent_resolved
  local temp_parent temp_resolved temp_mode temp_uid temp_gid
  destination_parent=$(dirname -- "$destination_path")
  is_source_install_tmp_path "$trusted_parent" "$temp_dir" \
    || die "temporary install directory name escaped the destination contract"
  [[ -d "$destination_parent" && ! -L "$destination_parent" ]] \
    || die "temporary install destination parent is unsafe"
  destination_parent_resolved=$(realpath -e -- "$destination_parent") \
    || die "cannot resolve temporary install destination parent"
  [[ "$destination_parent_resolved" == "$destination_parent" ]] \
    || die "temporary install destination parent is not physical"
  assert_trusted_install_tmp_root "$trusted_parent" "$destination_parent"
  trusted_parent_resolved=$(realpath -e -- "$trusted_parent") \
    || die "cannot resolve trusted install parent"
  [[ -d "$temp_dir" && ! -L "$temp_dir" ]] || die "temporary install directory is absent or unsafe"
  temp_resolved=$(realpath -e -- "$temp_dir") || die "cannot resolve temporary install directory"
  temp_parent=$(dirname -- "$temp_resolved")
  [[ "$temp_resolved" == "$temp_dir" && "$temp_parent" == "$trusted_parent_resolved" ]] \
    || die "temporary install directory escaped the trusted parent"
  temp_mode=$(stat -c '%a' "$temp_dir")
  temp_uid=$(stat -c '%u' "$temp_dir")
  temp_gid=$(stat -c '%g' "$temp_dir")
  [[ "$temp_mode" == "700" && "$temp_uid" == "0" && "$temp_gid" == "0" ]] \
    || die "temporary install directory is not root-owned mode 0700"
}

cleanup_source_install_tmp_directory() {
  local trusted_parent=$1
  local temp_dir=$2
  local trusted_parent_resolved temp_resolved temp_parent
  local trusted_mode trusted_uid trusted_gid
  is_source_install_tmp_path "$trusted_parent" "$temp_dir" || return 0
  [[ -d "$trusted_parent" && ! -L "$trusted_parent" ]] || return 0
  trusted_parent_resolved=$(realpath -e -- "$trusted_parent" 2>/dev/null) || return 0
  [[ "$trusted_parent_resolved" == "$trusted_parent" ]] || return 0
  trusted_mode=$(stat -c '%a' "$trusted_parent" 2>/dev/null) || return 0
  trusted_uid=$(stat -c '%u' "$trusted_parent" 2>/dev/null) || return 0
  trusted_gid=$(stat -c '%g' "$trusted_parent" 2>/dev/null) || return 0
  [[ "$trusted_mode" == "700" && "$trusted_uid" == "0" && "$trusted_gid" == "0" ]] \
    || return 0
  [[ -d "$temp_dir" && ! -L "$temp_dir" ]] || return 0
  temp_resolved=$(realpath -e -- "$temp_dir" 2>/dev/null) || return 0
  temp_parent=$(dirname -- "$temp_resolved")
  [[ "$temp_resolved" == "$temp_dir" && "$temp_parent" == "$trusted_parent_resolved" ]] \
    || return 0
  rm -rf -- "$temp_dir"
}

assert_previous_source() {
  local previous_parent path app_owner app_group
  [[ -f "$previous_source_manifest" && ! -L "$previous_source_manifest" ]] || die "previous source manifest is absent or a symlink"
  previous_parent=$(dirname "$previous_source_manifest")
  [[ -d "$previous_parent" && ! -L "$previous_parent" && "$(stat -c '%a' "$previous_parent")" == "700" ]] || die "previous source manifest parent is not protected"
  [[ "$(stat -c '%a' "$previous_source_manifest")" == "600" ]] || die "previous source manifest is not mode 0600"
  [[ "$(sha256sum "$previous_source_manifest" | awk '{print $1}')" == "$previous_source_manifest_sha256" ]] || die "previous source manifest checksum mismatch"
  previous_source_paths_file=$(mktemp /tmp/edu-ai-release-driver-previous-paths.XXXXXX)
  validate_source_manifest "$previous_source_manifest" "$previous_source_paths_file" "$expected_source_file_count"
  cmp -s "$source_paths_file" "$previous_source_paths_file" || die "candidate and previous source path sets differ"
  while IFS= read -r path; do
    assert_anchored_regular_source_path "$APP_DIR" "$path" "previous source member"
  done <"$previous_source_paths_file"
  app_owner=$(stat -c '%U' "$APP_DIR")
  app_group=$(stat -c '%G' "$APP_DIR")
  require_regex "$app_owner" '^[A-Za-z_][A-Za-z0-9_-]*$' "application owner"
  require_regex "$app_group" '^[A-Za-z_][A-Za-z0-9_-]*$' "application group"
  destination_source_owner=$app_owner
  destination_source_group=$app_group
  destination_modes_file=$(mktemp /tmp/edu-ai-release-driver-destination-modes.XXXXXX)
  capture_destination_source_modes "$APP_DIR" "$app_owner" "$app_group" "$destination_modes_file"
  (
    cd "$APP_DIR"
    sha256sum -c "$previous_source_manifest"
  ) >/dev/null
}

validate_candidate_source_manifest() {
  local observed_manifest=$1
  local expected_manifest=$2
  local expected_count=$3
  python3 - "$observed_manifest" "$expected_manifest" "$expected_count" <<'PY'
import pathlib
import re
import sys

observed_path = pathlib.Path(sys.argv[1])
expected_path = pathlib.Path(sys.argv[2])
expected_count = int(sys.argv[3])
line_pattern = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9._/-]+)")
required_roots = {"alembic.ini", "pyproject.toml"}
source_roots = {"app", "alembic"}
source_suffixes = {".py", ".html"}


def parse_manifest(path: pathlib.Path, label: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = line_pattern.fullmatch(line)
        if match is None:
            raise SystemExit(f"{label} image source manifest syntax is unsafe")
        digest, raw = match.groups()
        candidate = pathlib.PurePosixPath(raw)
        if (
            candidate.is_absolute()
            or str(candidate) != raw
            or any(part in {"", ".", ".."} for part in candidate.parts)
            or (
                raw not in required_roots
                and (
                    len(candidate.parts) < 2
                    or candidate.parts[0] not in source_roots
                    or candidate.suffix not in source_suffixes
                )
            )
        ):
            raise SystemExit(f"{label} image source manifest path is outside the exact scope")
        entries.append((raw, digest))
    paths = [path for path, _digest in entries]
    if len(entries) != expected_count or len(paths) != len(set(paths)):
        raise SystemExit(f"{label} image source manifest count/uniqueness mismatch")
    if not required_roots.issubset(paths):
        raise SystemExit(f"{label} image source manifest root files are absent")
    if paths != sorted(paths):
        raise SystemExit(f"{label} image source manifest order is not deterministic")
    return entries


expected = parse_manifest(expected_path, "expected")
observed = parse_manifest(observed_path, "observed")
if observed != expected:
    raise SystemExit("candidate image source manifest content mismatch")
PY
}

assert_candidate_source_manifest() {
  image_source_manifest_tmp=$(mktemp /tmp/edu-ai-release-driver-image-source.XXXXXX)
  if ! docker_call run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint sh "$candidate_id" \
    -c 'export LC_ALL=C; cd /app && test -f alembic.ini && test ! -L alembic.ini && test -f pyproject.toml && test ! -L pyproject.toml && test -d app && test ! -L app && test -d alembic && test ! -L alembic && { printf "%s\0" alembic.ini pyproject.toml; find app alembic -type f \( -name "*.py" -o -name "*.html" \) -print0; } | sort -z | xargs -0 -r sha256sum' \
    </dev/null >"$image_source_manifest_tmp"
  then
    rm -f -- "$image_source_manifest_tmp"
    image_source_manifest_tmp=""
    die "candidate image source manifest collection failed"
    return 1
  fi
  if ! validate_candidate_source_manifest \
    "$image_source_manifest_tmp" "${stage_dir}/image-source-files.sha256" \
    "$expected_image_source_file_count"
  then
    rm -f -- "$image_source_manifest_tmp"
    image_source_manifest_tmp=""
    die "candidate image source manifest mismatch"
    return 1
  fi
  rm -f -- "$image_source_manifest_tmp"
  image_source_manifest_tmp=""
}

assert_candidate_image() {
  local actual_id revision dependency_base pyproject_hash release_source
  local runtime_openapi_hash committed_openapi_hash long_lived_modules_csv
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

  assert_candidate_source_manifest

  long_lived_modules_csv=$(IFS=,; printf '%s' "${LONG_LIVED_ENTRYPOINT_MODULES[*]}")
  docker_call run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint python "$candidate_id" -c \
    'import importlib,os,sys; from app.core.config import Settings; api_module=importlib.import_module(sys.argv[1]); assert api_module.__name__==sys.argv[1]; api_app=getattr(api_module,"app"); names=tuple(sys.argv[2].split(",")); assert names and len(names)==len(set(names)); modules=tuple(importlib.import_module(name) for name in names); assert tuple(module.__name__ for module in modules)==names; s=Settings(); assert os.geteuid()!=0; assert not s.image_diversity_enabled and not s.image_ocr_enabled; assert s.image_ocr_model=="glm-ocr" and s.image_ocr_max_input_bytes==10485760 and s.image_ocr_max_response_bytes==1048576 and s.image_ocr_timeout_seconds==120.0 and s.business_timezone=="Asia/Shanghai"; schema=api_app.openapi(); assert isinstance(schema,dict) and isinstance(schema.get("openapi"),str) and schema["openapi"]' \
    "$API_ENTRYPOINT_MODULE" "$long_lived_modules_csv" </dev/null

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
    --security-opt no-new-privileges:true --entrypoint python "$candidate_id" -c \
    'import pathlib,subprocess,sys; expected=sys.argv[1]; marker=f'\''revision: str = "{expected}"'\''; versions=pathlib.Path("/app/alembic/versions").glob("*.py"); assert sum(line==marker for path in versions for line in path.read_text(encoding="utf-8").splitlines())==1; heads=subprocess.run(["alembic","heads"],check=True,capture_output=True,text=True); assert heads.stdout.splitlines()==[f"{expected} (head)"]' \
    "$EXPECTED_ALEMBIC_HEAD" </dev/null
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
    tag=$(rollback_tag_for_service "$service")
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

  write_active_tag_inventory "${backup_dir}/active-tag-inventory.txt" "$previous_image_id"
  : >"${backup_dir}/image-inventory.txt"
  for service in "${TAG_SERVICES[@]}"; do
    tag=$(rollback_tag_for_service "$service")
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
    "${backup_dir}/active-tag-inventory.txt" \
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
  [[ "$(wc -l <"${backup_dir}/active-tag-inventory.txt" | tr -d '[:space:]')" == "$((1 + ${#TAG_SERVICES[@]}))" ]] || die "backup active-tag inventory count mismatch"
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

validate_candidate_bundle() {
  local bundle=${1:-${stage_dir}/backend-image.tar.gz}
  local expected_tag=${2:-$candidate_tag}
  local expected_image_id=${3:-$candidate_id}
  python3 - "$bundle" "$expected_tag" "$expected_image_id" <<'PY'
import gzip
import hashlib
import json
import pathlib
import re
import sys
import tarfile
from typing import Any

BUNDLE, EXPECTED_TAG, EXPECTED_IMAGE_ID = sys.argv[1:]
SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
IMAGE_TAG = re.compile(r"edu-ai-lead-agent(?:-backend)?:[A-Za-z0-9._-]+")
MAX_JSON = 16 * 1024 * 1024
MAX_BLOB = 1024 * 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024 * 1024
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
OCI_MANIFESTS = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
OCI_CONFIGS = {
    "application/vnd.oci.image.config.v1+json",
    "application/vnd.docker.container.image.v1+json",
}
RAW_LAYERS = {
    "application/vnd.oci.image.layer.v1.tar",
    "application/vnd.oci.image.layer.nondistributable.v1.tar",
    "application/vnd.docker.image.rootfs.diff.tar",
    "application/vnd.docker.image.rootfs.foreign.diff.tar",
}
GZIP_LAYERS = {
    "application/vnd.oci.image.layer.v1.tar+gzip",
    "application/vnd.oci.image.layer.nondistributable.v1.tar+gzip",
    "application/vnd.docker.image.rootfs.diff.tar.gzip",
    "application/vnd.docker.image.rootfs.foreign.diff.tar.gzip",
}
OCI_LAYERS = RAW_LAYERS | GZIP_LAYERS


def fail(reason: str) -> None:
    raise SystemExit(reason)


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("image bundle JSON contains a duplicate key")
        result[key] = value
    return result


def parse_json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(
            payload,
            object_pairs_hook=unique_object,
            parse_constant=lambda _value: fail(f"{label} contains a non-standard JSON constant"),
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail(f"{label} is not valid JSON")


def normalized_path(raw: str, *, directory: bool = False) -> str:
    path = raw[2:] if raw.startswith("./") else raw
    if directory:
        path = path.rstrip("/")
    pure = pathlib.PurePosixPath(path)
    if (
        not path
        or pure.is_absolute()
        or str(pure) != path
        or any(part in {"", ".", ".."} for part in pure.parts)
        or any(character in path for character in ("\0", "\n", "\r"))
    ):
        fail("unsafe image bundle path")
    return path


def descriptor(value: Any, label: str, media_types: set[str], *, annotations: bool = False) -> tuple[str, int, str]:
    if not isinstance(value, dict):
        fail(f"{label} descriptor is not an object")
    allowed = {"mediaType", "digest", "size"}
    if annotations:
        allowed.add("annotations")
    if not {"mediaType", "digest", "size"}.issubset(value) or not set(value).issubset(allowed):
        fail(f"{label} descriptor fields conflict")
    media_type = value["mediaType"]
    digest = value["digest"]
    size = value["size"]
    if media_type not in media_types:
        fail(f"{label} descriptor mediaType is unsupported")
    if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
        fail(f"{label} descriptor digest is invalid")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_BLOB:
        fail(f"{label} descriptor size is invalid")
    if "annotations" in value:
        metadata = value["annotations"]
        if not isinstance(metadata, dict) or any(
            not isinstance(key, str) or not isinstance(item, str)
            for key, item in metadata.items()
        ):
            fail(f"{label} descriptor annotations are invalid")
    return digest, size, media_type


if SHA256.fullmatch(EXPECTED_IMAGE_ID) is None:
    fail("expected candidate image id is invalid")
if IMAGE_TAG.fullmatch(EXPECTED_TAG) is None:
    fail("expected candidate tag is invalid")

try:
    archive = tarfile.open(BUNDLE, mode="r:gz")
except (OSError, tarfile.TarError):
    fail("image bundle is not a readable gzip tar archive")

with archive:
    files: dict[str, tarfile.TarInfo] = {}
    directories: set[str] = set()
    seen: set[str] = set()
    total_size = 0
    for member in archive.getmembers():
        if member.isdir():
            path = normalized_path(member.name, directory=True)
            if path in seen:
                fail("image bundle contains a duplicate member")
            seen.add(path)
            directories.add(path)
        elif member.isfile():
            path = normalized_path(member.name)
            if path in seen:
                fail("image bundle contains a duplicate member")
            if member.size < 0 or member.size > MAX_BLOB:
                fail("image bundle member size is invalid")
            total_size += member.size
            if total_size > MAX_TOTAL:
                fail("image bundle total size is excessive")
            seen.add(path)
            files[path] = member
        else:
            fail("image bundle contains a non-regular member")
    if len(seen) > 10_000:
        fail("image bundle member count is excessive")

    def read_member(path: str, limit: int, label: str) -> bytes:
        member = files.get(path)
        if member is None or member.size > limit:
            fail(f"{label} is absent or oversized")
        extracted = archive.extractfile(member)
        if extracted is None:
            fail(f"{label} is unreadable")
        payload = extracted.read(limit + 1)
        if len(payload) != member.size or len(payload) > limit:
            fail(f"{label} size conflicts with its tar member")
        return payload

    def verify_blob(path: str, digest: str, size: int, label: str) -> bytes:
        member = files.get(path)
        if member is None or member.size != size:
            fail(f"{label} blob size mismatch")
        extracted = archive.extractfile(member)
        if extracted is None:
            fail(f"{label} blob is unreadable")
        hasher = hashlib.sha256()
        observed = 0
        chunks: list[bytes] | None = [] if size <= MAX_JSON else None
        while True:
            chunk = extracted.read(1024 * 1024)
            if not chunk:
                break
            observed += len(chunk)
            if observed > size:
                fail(f"{label} blob exceeds its descriptor size")
            hasher.update(chunk)
            if chunks is not None:
                chunks.append(chunk)
        if observed != size or f"sha256:{hasher.hexdigest()}" != digest:
            fail(f"{label} blob digest or size mismatch")
        return b"" if chunks is None else b"".join(chunks)

    docker_manifest = parse_json(read_member("manifest.json", 1024 * 1024, "image bundle manifest.json"), "image bundle manifest.json")
    if not isinstance(docker_manifest, list) or len(docker_manifest) != 1:
        fail("image bundle must contain exactly one image")
    entry = docker_manifest[0]
    if not isinstance(entry, dict) or set(entry) != {"Config", "RepoTags", "Layers"}:
        fail("image bundle manifest.json fields conflict")
    if entry["RepoTags"] != [EXPECTED_TAG]:
        fail("image bundle tag membership mismatch")
    if not isinstance(entry["Config"], str) or not isinstance(entry["Layers"], list) or any(
        not isinstance(layer, str) for layer in entry["Layers"]
    ):
        fail("image bundle manifest.json references are invalid")
    config_path = normalized_path(entry["Config"])
    layer_paths = [normalized_path(layer) for layer in entry["Layers"]]
    if not layer_paths or len(layer_paths) != len(set(layer_paths)) or config_path in layer_paths:
        fail("image bundle manifest.json references conflict")

    has_layout = "oci-layout" in files
    has_index = "index.json" in files
    if has_layout != has_index:
        fail("image bundle archive format markers conflict")

    if has_layout:
        layout = parse_json(read_member("oci-layout", 4096, "OCI layout marker"), "OCI layout marker")
        if layout != {"imageLayoutVersion": "1.0.0"}:
            fail("OCI layout marker is invalid")
        index = parse_json(read_member("index.json", 1024 * 1024, "OCI index"), "OCI index")
        if not isinstance(index, dict) or set(index) != {"schemaVersion", "mediaType", "manifests"}:
            fail("OCI index fields conflict")
        if index["schemaVersion"] != 2 or index["mediaType"] != OCI_INDEX:
            fail("OCI index identity is invalid")
        if not isinstance(index["manifests"], list) or len(index["manifests"]) != 1:
            fail("OCI index must reference exactly one image manifest")
        manifest_digest, manifest_size, manifest_media = descriptor(
            index["manifests"][0], "OCI image manifest", OCI_MANIFESTS, annotations=True
        )
        if manifest_digest != EXPECTED_IMAGE_ID:
            fail("OCI index descriptor does not match candidate image id")
        expected_ref_name = EXPECTED_TAG.rsplit(":", 1)[1]
        expected_annotations = {
            "io.containerd.image.name": f"docker.io/library/{EXPECTED_TAG}",
            "org.opencontainers.image.ref.name": expected_ref_name,
        }
        if index["manifests"][0].get("annotations") != expected_annotations:
            fail("OCI index annotations do not match the isolated candidate tag")
        manifest_path = f"blobs/sha256/{manifest_digest.removeprefix('sha256:')}"
        manifest_payload = verify_blob(
            manifest_path, manifest_digest, manifest_size, "OCI image manifest"
        )
        manifest = parse_json(manifest_payload, "OCI image manifest")
        if not isinstance(manifest, dict) or set(manifest) != {"schemaVersion", "mediaType", "config", "layers"}:
            fail("OCI image manifest fields conflict")
        if manifest["schemaVersion"] != 2 or manifest["mediaType"] != manifest_media:
            fail("OCI image manifest identity conflicts with its index descriptor")
        config_digest, config_size, _ = descriptor(
            manifest["config"], "OCI image config", OCI_CONFIGS
        )
        if not isinstance(manifest["layers"], list) or not manifest["layers"]:
            fail("OCI image layers are absent")
        layer_descriptors = [
            descriptor(value, f"OCI image layer {position}", OCI_LAYERS)
            for position, value in enumerate(manifest["layers"])
        ]
        all_digests = [manifest_digest, config_digest, *(value[0] for value in layer_descriptors)]
        if len(all_digests) != len(set(all_digests)):
            fail("OCI descriptor digests are duplicated")
        expected_config_path = f"blobs/sha256/{config_digest.removeprefix('sha256:')}"
        expected_layer_paths = [
            f"blobs/sha256/{digest.removeprefix('sha256:')}"
            for digest, _size, _media in layer_descriptors
        ]
        if config_path != expected_config_path or layer_paths != expected_layer_paths:
            fail("manifest.json conflicts with OCI descriptor references")
        config_payload = verify_blob(config_path, config_digest, config_size, "OCI image config")
        config = parse_json(config_payload, "OCI image config")
        if not isinstance(config, dict):
            fail("OCI image config is not an object")
        if config.get("architecture") != "amd64" or config.get("os") != "linux":
            fail("OCI image config platform is not the reviewed linux/amd64 target")
        rootfs = config.get("rootfs")
        if (
            not isinstance(rootfs, dict)
            or set(rootfs) != {"type", "diff_ids"}
            or rootfs["type"] != "layers"
            or not isinstance(rootfs["diff_ids"], list)
            or len(rootfs["diff_ids"]) != len(layer_descriptors)
            or any(
                not isinstance(diff_id, str) or SHA256.fullmatch(diff_id) is None
                for diff_id in rootfs["diff_ids"]
            )
        ):
            fail("OCI image config rootfs does not map exactly to its layers")
        for position, ((digest, size, _media), path) in enumerate(
            zip(layer_descriptors, layer_paths, strict=True)
        ):
            verify_blob(path, digest, size, f"OCI image layer {position}")
            member = files[path]
            extracted = archive.extractfile(member)
            if extracted is None:
                fail(f"OCI image layer {position} is unreadable for diff-id verification")
            stream = gzip.GzipFile(fileobj=extracted, mode="rb") if _media in GZIP_LAYERS else extracted
            diff_hasher = hashlib.sha256()
            diff_size = 0
            try:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    diff_size += len(chunk)
                    if diff_size > MAX_BLOB:
                        fail(f"OCI image layer {position} uncompressed size is excessive")
                    diff_hasher.update(chunk)
            except (EOFError, OSError, gzip.BadGzipFile):
                fail(f"OCI image layer {position} compression is invalid")
            observed_diff_id = f"sha256:{diff_hasher.hexdigest()}"
            if observed_diff_id != rootfs["diff_ids"][position]:
                fail(f"OCI image layer {position} diff-id conflicts with its config")
        required_files = {
            "manifest.json",
            "index.json",
            "oci-layout",
            manifest_path,
            config_path,
            *layer_paths,
        }
        if set(files) != required_files or directories != {"blobs", "blobs/sha256"}:
            fail("OCI image bundle contains extra, missing, or dangling members")
    else:
        if any(path.startswith("blobs/sha256/") for path in files):
            fail("classic image archive contains ambiguous OCI blobs")
        config_payload = read_member(config_path, MAX_JSON, "classic image config")
        config_digest = f"sha256:{hashlib.sha256(config_payload).hexdigest()}"
        if config_digest != EXPECTED_IMAGE_ID:
            fail("classic image config digest does not match candidate image id")
        if not isinstance(parse_json(config_payload, "classic image config"), dict):
            fail("classic image config is not an object")
        for position, path in enumerate(layer_paths):
            member = files.get(path)
            if member is None or member.size <= 0:
                fail(f"classic image layer {position} is absent or empty")
            extracted = archive.extractfile(member)
            if extracted is None:
                fail(f"classic image layer {position} is unreadable")
            observed = 0
            while True:
                chunk = extracted.read(1024 * 1024)
                if not chunk:
                    break
                observed += len(chunk)
            if observed != member.size:
                fail(f"classic image layer {position} size mismatch")
        required_files = {"manifest.json", config_path, *layer_paths}
        allowed_directories = {
            str(parent)
            for path in required_files
            for parent in pathlib.PurePosixPath(path).parents
            if str(parent) != "."
        }
        if set(files) != required_files or not directories.issubset(allowed_directories):
            fail("classic image archive contains extra, missing, or dangling members")
PY
}

load_candidate_bundle() {
  validate_candidate_bundle
  # `docker image load` itself writes every RepoTag in the bundle. Arm tag
  # recovery before it even though the validated bundle contains only the
  # isolated candidate tag.
  tags_changed=1
  docker_call image load --input "${stage_dir}/backend-image.tar.gz" </dev/null >/dev/null
  assert_active_tags "$previous_image_id"
  assert_candidate_image
}

retag_candidate() {
  local service tag
  tags_changed=1
  for service in "${TAG_SERVICES[@]}"; do
    tag=$(service_active_tag "$service")
    docker_call image tag "$candidate_id" "$tag" </dev/null
  done
  docker_call image tag "$candidate_id" "$SHARED_ACTIVE_TAG" </dev/null
  assert_active_tags "$candidate_id"
}

install_candidate_source_files() {
  local destination_root=$1
  local app_owner=$2
  local app_group=$3
  local trusted_tmp_root=$4
  local semantic_mode preserved_mode evidence_owner evidence_group path
  local source_path destination_path source_mode destination_mode
  local destination_owner destination_group
  local installed_mode installed_owner installed_group installed_resolved
  local install_tmp_path
  # Overlay only the regular files already extracted and validated in the
  # protected child. Candidate/previous path-set equality guarantees no stale
  # removed file can survive this source-only update.
  validate_destination_mode_evidence \
    "$source_modes_file" "$destination_modes_file" "$expected_source_file_count" \
    "$app_owner" "$app_group"
  while IFS=$'\t' read -r semantic_mode preserved_mode evidence_owner evidence_group path; do
    [[ "$semantic_mode" =~ ^0(644|755)$ && "$preserved_mode" =~ ^0(600|644|700|755)$ && -n "$path" ]] \
      || die "destination mode evidence became invalid"
    [[ "$evidence_owner" == "$app_owner" && "$evidence_group" == "$app_group" ]] \
      || die "destination ownership evidence became invalid"
    source_path="${release_extract_dir}/${path}"
    destination_path="${destination_root}/${path}"
    assert_anchored_regular_source_path "$release_extract_dir" "$path" "validated source member"
    assert_anchored_regular_source_path "$destination_root" "$path" "active source destination"
    source_mode=$(stat -c '%a' "$source_path")
    destination_mode=$(stat -c '%a' "$destination_path")
    destination_owner=$(stat -c '%U' "$destination_path")
    destination_group=$(stat -c '%G' "$destination_path")
    assert_candidate_source_mode_pair "$semantic_mode" "$source_mode"
    assert_destination_source_mode_pair "$semantic_mode" "$destination_mode"
    [[ "0${destination_mode}" == "$preserved_mode" ]] \
      || die "destination source mode changed after preflight"
    [[ "$destination_owner" == "$app_owner" && "$destination_group" == "$app_group" ]] \
      || die "destination source ownership changed after preflight"
    # Install into a generated root-only directory on the destination
    # filesystem, then atomically replace the final path. This prevents
    # `install` from following a final destination symlink introduced after
    # the pre-install check.
    source_install_tmp_parent=$trusted_tmp_root
    source_install_tmp_dir=$(mktemp -d "${source_install_tmp_parent}/.edu-ai-source-install.XXXXXX")
    chmod 700 "$source_install_tmp_dir"
    assert_install_tmp_directory \
      "$trusted_tmp_root" "$destination_root" "$destination_path" "$source_install_tmp_dir"
    install_tmp_path="${source_install_tmp_dir}/payload"
    install -o "$app_owner" -g "$app_group" -m "$preserved_mode" -- \
      "$source_path" "$install_tmp_path"
    assert_anchored_regular_source_path "$source_install_tmp_dir" payload "temporary installed source"
    installed_mode=$(stat -c '%a' "$install_tmp_path")
    installed_owner=$(stat -c '%U' "$install_tmp_path")
    installed_group=$(stat -c '%G' "$install_tmp_path")
    [[ "$installed_mode" == "${preserved_mode#0}" ]] || die "temporary installed source mode was not preserved"
    [[ "$installed_owner" == "$app_owner" && "$installed_group" == "$app_group" ]] \
      || die "temporary installed source ownership drift"
    assert_anchored_regular_source_path "$destination_root" "$path" "pre-replacement source destination"
    destination_mode=$(stat -c '%a' "$destination_path")
    destination_owner=$(stat -c '%U' "$destination_path")
    destination_group=$(stat -c '%G' "$destination_path")
    [[ "0${destination_mode}" == "$preserved_mode" ]] \
      || die "destination source mode changed before atomic replacement"
    [[ "$destination_owner" == "$app_owner" && "$destination_group" == "$app_group" ]] \
      || die "destination source ownership changed before atomic replacement"
    assert_install_tmp_directory \
      "$trusted_tmp_root" "$destination_root" "$destination_path" "$source_install_tmp_dir"
    mv -T -- "$install_tmp_path" "$destination_path"
    rmdir -- "$source_install_tmp_dir"
    source_install_tmp_dir=""
    source_install_tmp_parent=""
    assert_anchored_regular_source_path "$destination_root" "$path" "installed source destination"
    installed_resolved=$(realpath -e -- "$destination_path") || die "cannot resolve installed source destination"
    [[ "$installed_resolved" == "${destination_root}/${path}" ]] || die "installed source destination escaped its root"
    installed_mode=$(stat -c '%a' "$destination_path")
    installed_owner=$(stat -c '%U' "$destination_path")
    installed_group=$(stat -c '%G' "$destination_path")
    [[ "$installed_mode" == "${preserved_mode#0}" ]] || die "installed source destination mode was not preserved"
    [[ "$installed_owner" == "$app_owner" && "$installed_group" == "$app_group" ]] \
      || die "installed source destination ownership drift"
    cmp -s -- "$source_path" "$destination_path" || die "installed source destination content mismatch"
  done <"$destination_modes_file"
}

overlay_candidate_source() {
  local app_owner app_group
  ((backup_ready == 1)) || die "refusing source overlay without a completed fresh backup"
  app_owner=$(stat -c '%U' "$APP_DIR")
  app_group=$(stat -c '%G' "$APP_DIR")
  require_regex "$app_owner" '^[A-Za-z_][A-Za-z0-9_-]*$' "application owner"
  require_regex "$app_group" '^[A-Za-z_][A-Za-z0-9_-]*$' "application group"
  [[ "$app_owner" == "$destination_source_owner" && "$app_group" == "$destination_source_group" ]] \
    || die "application ownership changed after source preflight"
  overlay_changed=1
  install_candidate_source_files \
    "$APP_DIR" "$app_owner" "$app_group" "$SOURCE_INSTALL_TMP_ROOT"

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
  local service tag
  for service in "${TAG_SERVICES[@]}"; do
    tag=$(service_active_tag "$service")
    docker_call image tag "$previous_image_id" "$tag" </dev/null
  done
  docker_call image tag "$previous_image_id" "$SHARED_ACTIVE_TAG" </dev/null
  assert_active_tags "$previous_image_id"
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
  if [[ -n "$source_modes_file" && "$source_modes_file" == /tmp/edu-ai-release-driver-source-modes.* ]]; then
    rm -f -- "$source_modes_file"
  fi
  if [[ -n "$destination_modes_file" && "$destination_modes_file" == /tmp/edu-ai-release-driver-destination-modes.* ]]; then
    rm -f -- "$destination_modes_file"
  fi
  if [[ -n "$source_install_tmp_dir" && -n "$source_install_tmp_parent" \
    && "$source_install_tmp_parent" == "$SOURCE_INSTALL_TMP_ROOT" ]]; then
    cleanup_source_install_tmp_directory \
      "$source_install_tmp_parent" "$source_install_tmp_dir"
  fi
  if [[ -n "$image_source_manifest_tmp" && "$image_source_manifest_tmp" == /tmp/edu-ai-release-driver-image-source.* ]]; then
    rm -f -- "$image_source_manifest_tmp"
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
  assert_source_install_tmp_root_preflight "$SOURCE_INSTALL_TMP_ROOT" "$APP_DIR"
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
