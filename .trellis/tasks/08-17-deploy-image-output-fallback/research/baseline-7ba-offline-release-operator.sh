#!/usr/bin/env bash
# One-shot, checksum-bound local-tag release operator for the reviewed image-fallback
# workspace release.  Invoke the physical mode-0600 file by its absolute path,
# from /opt/edu-ai-lead-agent, with stdin attached to /dev/null.

set -Eeuo pipefail
IFS=$'\n\t'
export LC_ALL=C
umask 077

readonly APP_DIR="/opt/edu-ai-lead-agent"
readonly COMPOSE_PROJECT="edu-ai-lead-agent"
readonly COMPOSE_FILE="${APP_DIR}/compose.yaml"
readonly PRIMARY_ENV="${APP_DIR}/.env"
readonly RELEASE_ENV="${APP_DIR}/.release.env"
readonly BACKUP_ROOT="/var/backups/edu-ai/releases"
readonly BACKUP_LOCK="/var/lock/edu-ai-backup.lock"
readonly SAFE_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH="$SAFE_PATH"
readonly PREVIOUS_COMMIT="7ba25d3eeb290d3f784ae449a5b6ad360a8def58"
readonly PREVIOUS_SHORT="7ba25d3"
readonly PREVIOUS_IMAGE_ID="sha256:7627186cf1650a63bbe2e5e136e2364970a9383f756a62ed7db8c6e5cb50b21c"
readonly CANDIDATE_COMMIT="cbc27b2491e4ebd49e6cc58692b065268e2887db"
readonly DEPENDENCY_BASE_ID="sha256:50fd2519fbc5aa204c45e76cb685d01aaea1656b998d3ed96c9ab6671b3b9374"
readonly SCORING_ACTIVE="scoring-v1-preview.7-delivered-repeat-history"
readonly VETO_ACTIVE="topic-veto-v4-delivered-content"
readonly EXPECTED_ALEMBIC_HEAD="20260815_0021"
readonly EXPECTED_RUNTIME_LOCK_SHA256="3be154ff0e7f741b9f74d516baf739a4a38571218670b47dd1031f9dc1b44915"
readonly EXPECTED_DOCKERFILE_SHA256="d4c2823d9354a7a5c31c2885317cd46b5c764d6afb964306c4204f7ed063fd1f"
readonly EXPECTED_BASE_PYPROJECT_SHA256="c6c8e92b901e75cc4095d28dd81cd9265382ba133827875edb9ddbc6160824e1"
readonly EXPECTED_FINAL_PYPROJECT_SHA256="c6c8e92b901e75cc4095d28dd81cd9265382ba133827875edb9ddbc6160824e1"
readonly EXPECTED_PREVIOUS_SOURCE_FILE_COUNT=321
readonly EXPECTED_SOURCE_FILE_COUNT=321
readonly EXPECTED_IMAGE_SOURCE_FILE_COUNT=179
readonly SHARED_ACTIVE_TAG="edu-ai-lead-agent-backend:local"

readonly -a APP_SERVICES=(
  acquisition-api acquisition-scheduler acquisition-worker
  governance-scheduler governance-worker content-scheduler content-worker
  wecom-dispatcher
)
readonly -a TAG_SERVICES=(
  backend-migrate acquisition-api acquisition-scheduler acquisition-worker
  governance-scheduler governance-worker content-scheduler content-worker
  wecom-dispatcher
)
readonly -a QUIESCE_ORDER=(
  wecom-dispatcher content-worker content-scheduler governance-worker
  governance-scheduler acquisition-worker acquisition-scheduler acquisition-api
)
readonly -a RESTORE_ORDER=(
  acquisition-api acquisition-scheduler acquisition-worker governance-scheduler
  governance-worker content-scheduler content-worker wecom-dispatcher
)
readonly -a STAGE_MEMBERS=(
  artifacts.sha256 backend-image.tar.gz backend-image.tar.gz.sha256
  baseline-7ba-offline-release-operator.sh image-source-files.sha256
  image-validation.txt source-files.sha256 source.tar.gz
  source.tar.gz.sha256 validate-image-fallback-offline-artifacts.py
)
readonly -a EXPECTED_SOURCE_DIFF=(
  backend/app/application/services/material_package.py
  backend/app/domain/image_fallback.py
  backend/app/infrastructure/ai/image_generation.py
  backend/tests/unit/test_image_fallback.py
  backend/tests/unit/test_image_generation.py
  backend/tests/unit/test_material_package.py
  backend/tests/unit/test_wecom_delivery.py
)

declare -A OLD_CONTAINER_IDS=()

stage_dir=""
candidate_commit=""
candidate_short=""
candidate_id=""
candidate_tag=""
source_sha256=""
source_manifest_sha256=""
image_bundle_sha256=""
image_source_manifest_sha256=""
operator_sha256=""
validator_sha256=""
previous_source_manifest=""
previous_source_manifest_sha256=""
expected_source_file_count=""
expected_previous_source_file_count=""
expected_image_source_file_count=""
expected_dependency_base_id=""
expected_durable_vector=""
expected_provider_vector=""
expected_source_vector=""
expected_env_sha256=""
expected_release_env_sha256=""
expected_env_uid=""
expected_env_gid=""
expected_release_env_uid=""
expected_release_env_gid=""
scheduler_safe_until_utc=""
minimum_safe_seconds=900
preflight_sample_seconds=15
stability_seconds=30

operator_path=""
validator_path=""
backup_id=""
backup_dir=""
rollback_tag_prefix=""
source_paths_file=""
source_modes_file=""
previous_source_paths_file=""
destination_evidence_file=""
source_extract_dir=""
install_temp_path=""
marker_full_temp=""
marker_short_temp=""
log_scan_file=""
image_source_observed_file=""
runtime_evidence_dir=""
workspace_temp_dir=""
release_marker_uid=""
release_marker_gid=""
failure_rc=0
validated_minio_volume_name=""

# Recovery state.  Flags are armed before their corresponding first mutation.
writers_stopped=0
backup_ready=0
tags_changed=0
overlay_changed=0
completed=0
recovery_running=0
recovered=0
incident_required=0

log() { printf '[image-fallback-release] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; return 1; }

usage() {
  cat >&2 <<'EOF'
Usage: /absolute/stage/baseline-7ba-offline-release-operator.sh \
  --stage-dir ABSOLUTE_STAGE --candidate-commit HEX40 \
  --candidate-id sha256:HEX64 --candidate-tag ISOLATED_LOCAL_TAG \
  --source-sha256 HEX64 --source-manifest-sha256 HEX64 \
  --image-bundle-sha256 HEX64 --image-source-manifest-sha256 HEX64 \
  --operator-sha256 HEX64 --validator-sha256 HEX64 \
  --previous-source-manifest ABSOLUTE_MODE_0600_PATH \
  --previous-source-manifest-sha256 HEX64 \
  --expected-source-file-count INTEGER \
  --expected-previous-source-file-count INTEGER \
  --expected-image-source-file-count INTEGER \
  --expected-dependency-base-id sha256:HEX64 \
  --expected-durable-vector COLON_SEPARATED_INTEGERS \
  --expected-provider-vector COLON_SEPARATED_INTEGERS \
  --expected-source-vector COLON_SEPARATED_INTEGERS \
  --expected-env-sha256 HEX64 --expected-release-env-sha256 HEX64 \
  --expected-env-uid INTEGER --expected-env-gid INTEGER \
  --expected-release-env-uid INTEGER --expected-release-env-gid INTEGER \
  --scheduler-safe-until-utc YYYY-MM-DDTHH:MM:SSZ

The operator is single-use. It never runs minio-init, seed_sources, a fixture,
an enqueue/replay/retry/resend, an external provider, or a WeCom send.
EOF
}

require_value() { [[ -n "${2-}" ]] || die "missing value for $1"; }

parse_args() {
  while (($#)); do
    case "$1" in
      --stage-dir) require_value "$1" "${2-}"; stage_dir=$2; shift 2 ;;
      --candidate-commit) require_value "$1" "${2-}"; candidate_commit=$2; shift 2 ;;
      --candidate-id) require_value "$1" "${2-}"; candidate_id=$2; shift 2 ;;
      --candidate-tag) require_value "$1" "${2-}"; candidate_tag=$2; shift 2 ;;
      --source-sha256) require_value "$1" "${2-}"; source_sha256=$2; shift 2 ;;
      --source-manifest-sha256) require_value "$1" "${2-}"; source_manifest_sha256=$2; shift 2 ;;
      --image-bundle-sha256) require_value "$1" "${2-}"; image_bundle_sha256=$2; shift 2 ;;
      --image-source-manifest-sha256) require_value "$1" "${2-}"; image_source_manifest_sha256=$2; shift 2 ;;
      --operator-sha256) require_value "$1" "${2-}"; operator_sha256=$2; shift 2 ;;
      --validator-sha256) require_value "$1" "${2-}"; validator_sha256=$2; shift 2 ;;
      --previous-source-manifest) require_value "$1" "${2-}"; previous_source_manifest=$2; shift 2 ;;
      --previous-source-manifest-sha256) require_value "$1" "${2-}"; previous_source_manifest_sha256=$2; shift 2 ;;
      --expected-source-file-count) require_value "$1" "${2-}"; expected_source_file_count=$2; shift 2 ;;
      --expected-previous-source-file-count) require_value "$1" "${2-}"; expected_previous_source_file_count=$2; shift 2 ;;
      --expected-image-source-file-count) require_value "$1" "${2-}"; expected_image_source_file_count=$2; shift 2 ;;
      --expected-dependency-base-id) require_value "$1" "${2-}"; expected_dependency_base_id=$2; shift 2 ;;
      --expected-durable-vector) require_value "$1" "${2-}"; expected_durable_vector=$2; shift 2 ;;
      --expected-provider-vector) require_value "$1" "${2-}"; expected_provider_vector=$2; shift 2 ;;
      --expected-source-vector) require_value "$1" "${2-}"; expected_source_vector=$2; shift 2 ;;
      --expected-env-sha256) require_value "$1" "${2-}"; expected_env_sha256=$2; shift 2 ;;
      --expected-release-env-sha256) require_value "$1" "${2-}"; expected_release_env_sha256=$2; shift 2 ;;
      --expected-env-uid) require_value "$1" "${2-}"; expected_env_uid=$2; shift 2 ;;
      --expected-env-gid) require_value "$1" "${2-}"; expected_env_gid=$2; shift 2 ;;
      --expected-release-env-uid) require_value "$1" "${2-}"; expected_release_env_uid=$2; shift 2 ;;
      --expected-release-env-gid) require_value "$1" "${2-}"; expected_release_env_gid=$2; shift 2 ;;
      --scheduler-safe-until-utc) require_value "$1" "${2-}"; scheduler_safe_until_utc=$2; shift 2 ;;
      --minimum-safe-seconds) require_value "$1" "${2-}"; minimum_safe_seconds=$2; shift 2 ;;
      --preflight-sample-seconds) require_value "$1" "${2-}"; preflight_sample_seconds=$2; shift 2 ;;
      --stability-seconds) require_value "$1" "${2-}"; stability_seconds=$2; shift 2 ;;
      --help|-h) usage; exit 0 ;;
      *) usage; die "unknown argument: $1" ;;
    esac
  done
}

require_regex() { [[ "$1" =~ $2 ]] || die "invalid $3"; }

service_tag() { printf 'edu-ai-lead-agent-%s:latest\n' "$1"; }
rollback_tag_for_service() { printf '%s-%s\n' "$rollback_tag_prefix" "$1"; }

validate_minio_inventory_file() {
  local inventory=$1
  python3 - "$inventory" <<'PY'
import base64
import binascii
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
rows = path.read_bytes().splitlines()
if not rows:
    raise SystemExit(1)
previous = None
seen = set()
for row in rows:
    fields = row.split(b"\t")
    if len(fields) != 3 or re.fullmatch(rb"[0-9a-f]{64}", fields[0]) is None:
        raise SystemExit(1)
    if re.fullmatch(rb"0|[1-9][0-9]*", fields[1]) is None:
        raise SystemExit(1)
    try:
        decoded = base64.b64decode(fields[2], validate=True)
    except (binascii.Error, ValueError):
        raise SystemExit(1)
    parts = decoded.split(b"/")
    if len(decoded) > 4096 or len(parts) < 2 or parts[0] != b"." or any(
        part in {b"", b".", b".."} for part in parts[1:]
    ):
        raise SystemExit(1)
    if decoded in seen or (previous is not None and decoded <= previous):
        raise SystemExit(1)
    seen.add(decoded)
    previous = decoded
PY
}

write_minio_inventory() {
  local minio_id=$1 output=$2 mount_record volume_record
  local mount_type volume_name mount_source mount_rw extra
  [[ ! -e "$output" && ! -L "$output" ]] || { die "MinIO inventory output already exists"; return 1; }
  mount_record=$(docker_call inspect "$minio_id" --format \
    '{{range .Mounts}}{{if eq .Destination "/data"}}{{printf "%s\t%s\t%s\t%t\n" .Type .Name .Source .RW}}{{end}}{{end}}' \
    </dev/null) || return 1
  [[ -n "$mount_record" && "$mount_record" != *$'\n'* ]] \
    || { die "MinIO /data mount is not exact"; return 1; }
  IFS=$'\t' read -r mount_type volume_name mount_source mount_rw extra <<<"$mount_record"
  [[ "$mount_type" == volume && -z "$extra" && "$mount_rw" == true ]] \
    || { die "MinIO /data is not one writable named-volume mount"; return 1; }
  [[ "$volume_name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ && "$mount_source" == /* ]] \
    || { die "MinIO named-volume identity is unsafe"; return 1; }
  volume_record=$(docker_call volume inspect "$volume_name" --format \
    '{{printf "%s\t%s" .Name .Mountpoint}}' </dev/null) || return 1
  [[ "$volume_record" == "${volume_name}"$'\t'"${mount_source}" ]] \
    || { die "MinIO named-volume mountpoint mismatch"; return 1; }
  if ! docker_call run --rm --pull never --network none --read-only \
    --cap-drop ALL --cap-add DAC_READ_SEARCH --security-opt no-new-privileges:true \
    --user 0:0 --pids-limit 64 --memory 512m --cpus 1 \
    --mount "type=volume,src=${volume_name},dst=/inventory-data,readonly" \
    --entrypoint python "$candidate_id" -c '
import base64
import hashlib
import os
import stat
import sys

root = sys.argv[1]
max_entries, max_bytes, max_depth, max_path, chunk = map(int, sys.argv[2:])
rows = []
entry_count = total_bytes = 0

directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK

def identity(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns)

def walk(directory_fd, relative, depth):
    global entry_count, total_bytes
    if depth > max_depth:
        raise ValueError
    initial_directory = os.fstat(directory_fd)
    if not stat.S_ISDIR(initial_directory.st_mode):
        raise ValueError
    try:
        with os.scandir(directory_fd) as iterator:
            names = sorted(os.fsencode(entry.name) for entry in iterator)
        for name in names:
            entry_count += 1
            if entry_count > max_entries or b"/" in name or name in {b"", b".", b".."}:
                raise ValueError
            child_relative = relative + b"/" + name
            if len(child_relative) > max_path:
                raise ValueError
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError
            if relative == b"." and name == b".minio.sys":
                if not stat.S_ISDIR(metadata.st_mode):
                    raise ValueError
                continue
            if stat.S_ISDIR(metadata.st_mode):
                child_fd = os.open(name, directory_flags, dir_fd=directory_fd)
                child_metadata = os.fstat(child_fd)
                if identity(child_metadata) != identity(metadata) or not stat.S_ISDIR(child_metadata.st_mode):
                    os.close(child_fd)
                    raise ValueError
                walk(child_fd, child_relative, depth + 1)
                current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if identity(current) != identity(metadata):
                    raise ValueError
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError
            descriptor = os.open(name, file_flags, dir_fd=directory_fd)
            try:
                before = os.fstat(descriptor)
                if not stat.S_ISREG(before.st_mode) or identity(before) != identity(metadata):
                    raise ValueError
                total_bytes += before.st_size
                if total_bytes > max_bytes:
                    raise ValueError
                digest = hashlib.sha256()
                while True:
                    data = os.read(descriptor, chunk)
                    if not data:
                        break
                    digest.update(data)
                after = os.fstat(descriptor)
                if identity(after) != identity(before):
                    raise ValueError
            finally:
                os.close(descriptor)
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if identity(current) != identity(before):
                raise ValueError
            rows.append((child_relative, digest.hexdigest(), before.st_size))
        final_directory = os.fstat(directory_fd)
        if identity(final_directory) != identity(initial_directory):
            raise ValueError
    finally:
        os.close(directory_fd)

try:
    root_fd = os.open(root, directory_flags)
    if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
        os.close(root_fd)
        raise ValueError
    walk(root_fd, b".", 0)
    if not rows:
        raise ValueError
    for path, digest, size in sorted(rows):
        encoded = base64.b64encode(path).decode("ascii")
        print(f"{digest}\t{size}\t{encoded}")
except BaseException:
    print("MinIO inventory rejected", file=sys.stderr)
    sys.exit(1)
' /inventory-data 1000000 1099511627776 64 4096 1048576 \
    </dev/null >"$output"; then
    unlink -- "$output" 2>/dev/null || true
    die "MinIO inventory failed"
    return 1
  fi
  if [[ ! -s "$output" || -L "$output" ]] || ! validate_minio_inventory_file "$output"; then
    unlink -- "$output" 2>/dev/null || true
    die "MinIO inventory output is empty or unsafe"
    return 1
  fi
  validated_minio_volume_name=$volume_name
}

validate_args() {
  local name service
  for name in stage_dir candidate_commit candidate_id candidate_tag source_sha256 \
    source_manifest_sha256 image_bundle_sha256 image_source_manifest_sha256 \
    operator_sha256 validator_sha256 previous_source_manifest \
    previous_source_manifest_sha256 expected_source_file_count \
    expected_previous_source_file_count \
    expected_image_source_file_count expected_dependency_base_id \
    expected_durable_vector expected_provider_vector expected_source_vector \
    expected_env_sha256 expected_release_env_sha256 \
    expected_env_uid expected_env_gid expected_release_env_uid \
    expected_release_env_gid scheduler_safe_until_utc
  do
    [[ -n "${!name}" ]] || die "required argument not supplied: $name"
  done
  require_regex "$stage_dir" '^/var/tmp/edu-ai-image-fallback-release-[A-Za-z0-9._-]+$' "stage path"
  require_regex "$candidate_commit" '^[0-9a-f]{40}$' "candidate commit"
  [[ "$candidate_commit" == "$CANDIDATE_COMMIT" ]] || die "candidate commit is not exact cbc27b2"
  candidate_short=${candidate_commit:0:7}
  require_regex "$candidate_id" '^sha256:[0-9a-f]{64}$' "candidate image id"
  require_regex "$candidate_tag" '^edu-ai-lead-agent-backend:image-fallback-[0-9a-f]{7,12}$' "isolated candidate tag"
  [[ "$candidate_tag" == "edu-ai-lead-agent-backend:image-fallback-${candidate_commit:0:12}" ]] || die "candidate tag is not bound to the full release commit"
  [[ "$candidate_tag" != "$SHARED_ACTIVE_TAG" ]] || die "candidate tag aliases the shared active tag"
  for service in "${TAG_SERVICES[@]}"; do
    [[ "$candidate_tag" != "$(service_tag "$service")" ]] || die "candidate tag aliases an active service tag"
  done
  for name in source_sha256 source_manifest_sha256 image_bundle_sha256 \
    image_source_manifest_sha256 operator_sha256 validator_sha256 \
    previous_source_manifest_sha256 expected_env_sha256 expected_release_env_sha256
  do
    require_regex "${!name}" '^[0-9a-f]{64}$' "$name"
  done
  require_regex "$expected_dependency_base_id" '^sha256:[0-9a-f]{64}$' "dependency base id"
  require_regex "$expected_source_file_count" '^[1-9][0-9]*$' "source file count"
  require_regex "$expected_previous_source_file_count" '^[1-9][0-9]*$' "previous source file count"
  [[ "$expected_previous_source_file_count" == "$EXPECTED_PREVIOUS_SOURCE_FILE_COUNT" ]] || die "7ba source baseline count is not exact 321"
  [[ "$expected_source_file_count" == "$EXPECTED_SOURCE_FILE_COUNT" ]] || die "candidate source count is not exact 321"
  require_regex "$expected_image_source_file_count" '^[1-9][0-9]*$' "image source file count"
  [[ "$expected_image_source_file_count" == "$EXPECTED_IMAGE_SOURCE_FILE_COUNT" ]] || die "candidate image-source count is not exact 179"
  [[ "$expected_dependency_base_id" == "$DEPENDENCY_BASE_ID" ]] || die "dependency base is not the reviewed immutable image"
  require_regex "$expected_durable_vector" '^[0-9]+(:[0-9]+)+$' "durable vector"
  require_regex "$expected_provider_vector" '^[0-9]+(:[0-9]+)+$' "provider vector"
  require_regex "$expected_source_vector" '^[0-9]+(:[0-9]+)+$' "source vector"
  require_regex "$expected_env_uid" '^[0-9]+$' "primary env uid"
  require_regex "$expected_env_gid" '^[0-9]+$' "primary env gid"
  require_regex "$expected_release_env_uid" '^[0-9]+$' "release env uid"
  require_regex "$expected_release_env_gid" '^[0-9]+$' "release env gid"
  require_regex "$scheduler_safe_until_utc" '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' "safe-until timestamp"
  require_regex "$minimum_safe_seconds" '^[1-9][0-9]*$' "minimum safe seconds"
  require_regex "$preflight_sample_seconds" '^[1-9][0-9]*$' "preflight seconds"
  require_regex "$stability_seconds" '^[1-9][0-9]*$' "stability seconds"
  ((minimum_safe_seconds >= 900)) || die "safe window cannot be weakened"
  ((preflight_sample_seconds >= 15)) || die "preflight sample cannot be weakened"
  ((stability_seconds >= 30)) || die "stability sample cannot be weakened"
  [[ "$previous_source_manifest" = /* ]] || die "previous manifest path must be absolute"
}

assert_safe_window() {
  local canonical deadline_epoch now_epoch remaining
  canonical=$(date -u -d "$scheduler_safe_until_utc" '+%Y-%m-%dT%H:%M:%SZ') \
    || { die "safe-window deadline is not a valid UTC timestamp"; return 1; }
  [[ "$canonical" == "$scheduler_safe_until_utc" ]] \
    || { die "safe-window deadline is not canonical UTC"; return 1; }
  deadline_epoch=$(date -u -d "$scheduler_safe_until_utc" +%s) \
    || { die "safe-window deadline cannot be converted"; return 1; }
  now_epoch=$(date -u +%s) \
    || { die "current UTC time cannot be read"; return 1; }
  [[ "$deadline_epoch" =~ ^[0-9]+$ && "$now_epoch" =~ ^[0-9]+$ ]] \
    || { die "safe-window epoch is invalid"; return 1; }
  remaining=$((deadline_epoch - now_epoch))
  ((remaining >= minimum_safe_seconds)) \
    || { die "scheduler safe window has less than ${minimum_safe_seconds}s remaining"; return 1; }
}

docker_call() { env -i PATH="$SAFE_PATH" HOME=/root /usr/bin/docker "$@"; }

compose_call() {
  env -i PATH="$SAFE_PATH" HOME=/root /usr/bin/docker compose \
    --project-name "$COMPOSE_PROJECT" --project-directory "$APP_DIR" \
    --env-file "$PRIMARY_ENV" --env-file "$RELEASE_ENV" \
    -f "$COMPOSE_FILE" "$@" </dev/null
}

container_id() { compose_call ps -q "$1" | tr -d '\r\n'; }

sql_scalar() {
  local postgres_id query=$1
  postgres_id=$(container_id postgres)
  [[ -n "$postgres_id" ]] || die "PostgreSQL container is absent"
  docker_call exec "$postgres_id" sh -c \
    'exec psql -X -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' \
    sh "$query" </dev/null | tr -d '[:space:]'
}

env_key_count() { awk -F= -v key="$2" '$1 == key { count += 1 } END { print count + 0 }' "$1"; }
env_value() { awk -F= -v key="$2" '$1 == key { sub(/^[^=]*=/, ""); print }' "$1"; }

assert_env_contract() {
  local scoring_count scoring_value
  [[ -f "$PRIMARY_ENV" && ! -L "$PRIMARY_ENV" && -f "$RELEASE_ENV" && ! -L "$RELEASE_ENV" ]] || die "environment files are unsafe"
  [[ "$(realpath -e -- "$PRIMARY_ENV")" == "$PRIMARY_ENV" && "$(realpath -e -- "$RELEASE_ENV")" == "$RELEASE_ENV" ]] || die "environment path contains a symlink"
  [[ "$(stat -c '%a:%u:%g' "$PRIMARY_ENV")" == "600:${expected_env_uid}:${expected_env_gid}" ]] || die "primary env ownership/mode mismatch"
  [[ "$(stat -c '%a:%u:%g' "$RELEASE_ENV")" == "600:${expected_release_env_uid}:${expected_release_env_gid}" ]] || die "release env ownership/mode mismatch"
  [[ "$(sha256sum "$PRIMARY_ENV" | awk '{print $1}')" == "$expected_env_sha256" ]] || die "primary env hash drift"
  [[ "$(sha256sum "$RELEASE_ENV" | awk '{print $1}')" == "$expected_release_env_sha256" ]] || die "release env hash drift"
  [[ "$(env_key_count "$RELEASE_ENV" CONTENT_SCORING_VERSION)" == 0 ]] || die ".release.env must not own scoring"
  [[ "$(env_key_count "$RELEASE_ENV" APP_IMAGE)" == 1 ]] || die ".release.env APP_IMAGE ownership mismatch"
  [[ "$(env_value "$RELEASE_ENV" APP_IMAGE)" == "$SHARED_ACTIVE_TAG" ]] || die ".release.env does not select the reviewed local tag"
  [[ "$(env_key_count "$PRIMARY_ENV" IMAGE_DIVERSITY_ENABLED)" == 1 && "$(env_value "$PRIMARY_ENV" IMAGE_DIVERSITY_ENABLED)" == true ]] || die "diversity must remain true"
  [[ "$(env_key_count "$PRIMARY_ENV" IMAGE_OCR_ENABLED)" == 1 && "$(env_value "$PRIMARY_ENV" IMAGE_OCR_ENABLED)" == true ]] || die "OCR must remain true"
  scoring_count=$(env_key_count "$PRIMARY_ENV" CONTENT_SCORING_VERSION)
  [[ "$scoring_count" == 1 ]] || die "primary env must own scoring exactly once"
  scoring_value=$(env_value "$PRIMARY_ENV" CONTENT_SCORING_VERSION)
  [[ "$scoring_value" == "$SCORING_ACTIVE" ]] || die "pre-release scoring is not exact .7"
}

durable_vector() {
  sql_scalar "SELECT concat_ws(':',
    (SELECT count(*) FROM acquisition_runs), (SELECT count(*) FROM governance_runs),
    (SELECT count(*) FROM topic_selection_runs), (SELECT count(*) FROM content_slot_runs),
    (SELECT count(*) FROM copy_generation_runs), (SELECT count(*) FROM image_artifacts),
    (SELECT count(*) FROM material_packages), (SELECT count(*) FROM model_invocations),
    (SELECT count(*) FROM wecom_delivery_jobs), (SELECT count(*) FROM wecom_delivery_attempts));"
}

provider_vector() {
  sql_scalar "SELECT concat_ws(':',
    (SELECT count(*) FROM model_invocations), (SELECT count(*) FROM image_artifacts),
    (SELECT coalesce(sum(attempt_count),0) FROM image_artifacts),
    (SELECT count(*) FROM wecom_delivery_jobs), (SELECT count(*) FROM wecom_delivery_attempts));"
}

source_vector() {
  sql_scalar "SELECT concat_ws(':', (SELECT count(*) FROM sources),
    (SELECT count(*) FROM source_versions),
    (SELECT count(*) FROM sources WHERE active_version_id IS NOT NULL));"
}

zero_work_vector() {
  sql_scalar "SELECT concat_ws(':',
    (SELECT count(*) FROM acquisition_jobs WHERE status IN ('queued','running','retry_scheduled')),
    (SELECT count(*) FROM governance_jobs WHERE status IN ('queued','running','retry_scheduled')),
    (SELECT count(*) FROM topic_selection_jobs WHERE status IN ('queued','running')),
    (SELECT count(*) FROM content_slot_jobs WHERE status IN ('queued','running')),
    (SELECT count(*) FROM copy_generation_jobs j JOIN copy_generation_runs r ON r.id=j.run_id
      WHERE j.status='running' OR (r.business_date=(now() AT TIME ZONE 'Asia/Shanghai')::date
        AND j.status IN ('queued','retry_scheduled') AND j.available_at<=now())),
    (SELECT count(*) FROM image_artifacts WHERE status IN ('queued','running')),
    (SELECT count(*) FROM wecom_delivery_jobs WHERE status IN ('queued','running','partial','delivery_unknown')));"
}

legacy_prompt_vector() {
  sql_scalar "SELECT concat_ws(':',
    (SELECT count(*) FROM copy_generation_jobs j JOIN copy_generation_runs r ON r.id=j.run_id WHERE r.version_bundle->>'generator_prompt_version'='moments-generator-v17-english-evidence' AND (j.status='running' OR (r.business_date=(now() AT TIME ZONE 'Asia/Shanghai')::date AND j.status IN ('queued','retry_scheduled') AND j.available_at<=now()))),
    (SELECT count(*) FROM material_packages p JOIN copy_generation_runs r ON r.id=p.run_id WHERE r.version_bundle->>'generator_prompt_version'='moments-generator-v17-english-evidence' AND r.business_date=(now() AT TIME ZONE 'Asia/Shanghai')::date AND p.status IN ('queued','ready','awaiting_manual_use')),
    (SELECT count(*) FROM wecom_delivery_jobs w JOIN material_packages p ON p.id=w.material_package_id JOIN copy_generation_runs r ON r.id=p.run_id WHERE r.version_bundle->>'generator_prompt_version'='moments-generator-v17-english-evidence' AND w.status IN ('queued','running','partial','delivery_unknown')));"
}


assert_trusted_root_metadata() {
  local root=$1 target_root=$2 root_device target_device
  [[ "$root" = /* && "$target_root" = /* ]] || { die "trusted root paths must be absolute"; return 1; }
  [[ -d "$root" && ! -L "$root" && "$(realpath -e -- "$root")" == "$root" ]] || { die "backup root is not a physical directory"; return 1; }
  [[ "$(stat -c '%a:%u:%g' "$root")" == "700:0:0" ]] || { die "backup root must be root:root mode 0700"; return 1; }
  [[ -d "$target_root" && ! -L "$target_root" && "$(realpath -e -- "$target_root")" == "$target_root" ]] || { die "atomic target root is not physical"; return 1; }
  root_device=$(stat -c '%d' "$root")
  target_device=$(stat -c '%d' "$target_root")
  [[ "$root_device" == "$target_device" ]] || { die "backup root is not on the atomic target filesystem"; return 1; }
}

assert_trusted_backup_root() {
  local stale
  assert_trusted_root_metadata "$BACKUP_ROOT" "$APP_DIR" || return 1
  stale=$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -name '.image-fallback-*' -print -quit)
  [[ -z "$stale" ]] || { die "stale image-fallback release workspace exists under the backup root"; return 1; }
}

assert_trusted_workspace_contract() {
  local root=$1 workspace=$2 target_root=$3
  assert_trusted_root_metadata "$root" "$target_root" || return 1
  [[ "$workspace" == "$root/.image-fallback-work."* ]] || { die "trusted workspace prefix mismatch"; return 1; }
  [[ "$(dirname -- "$workspace")" == "$root" ]] || { die "trusted workspace is not a direct backup-root child"; return 1; }
  [[ -d "$workspace" && ! -L "$workspace" && "$(realpath -e -- "$workspace")" == "$workspace" ]] || { die "trusted workspace is not physical"; return 1; }
  [[ "$(stat -c '%a:%u:%g' "$workspace")" == "700:0:0" ]] || { die "trusted workspace ownership/mode mismatch"; return 1; }
  [[ "$(stat -c '%d' "$workspace")" == "$(stat -c '%d' "$target_root")" ]] || { die "trusted workspace device mismatch"; return 1; }
}

initialize_trusted_workspace() {
  local root=${1:-$BACKUP_ROOT} target_root=${2:-$APP_DIR}
  local stale
  assert_trusted_root_metadata "$root" "$target_root" || return 1
  stale=$(find "$root" -mindepth 1 -maxdepth 1 -name '.image-fallback-*' -print -quit)
  [[ -z "$stale" ]] || { die "stale image-fallback release workspace exists under the backup root"; return 1; }
  workspace_temp_dir=$(mktemp -d "${root}/.image-fallback-work.XXXXXX")
  chown 0:0 "$workspace_temp_dir"
  chmod 700 "$workspace_temp_dir"
  assert_trusted_workspace_contract "$root" "$workspace_temp_dir" "$target_root"
}

trusted_mktemp_file() {
  local output_name=$1 prefix=$2
  local root=${3:-$BACKUP_ROOT} workspace=${4:-$workspace_temp_dir} target_root=${5:-$APP_DIR}
  local created
  [[ "$output_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ && "$prefix" =~ ^[A-Za-z0-9._-]+$ ]] || { die "trusted temporary arguments are unsafe"; return 1; }
  assert_trusted_workspace_contract "$root" "$workspace" "$target_root" || return 1
  created=$(mktemp "${workspace}/${prefix}.XXXXXX")
  chown 0:0 "$created"
  chmod 600 "$created"
  [[ -f "$created" && ! -L "$created" && "$(realpath -e -- "$created")" == "$created" ]] || { die "trusted temporary file is unsafe"; return 1; }
  [[ "$(stat -c '%a:%u:%g' "$created")" == "600:0:0" ]] || { die "trusted temporary file metadata mismatch"; return 1; }
  printf -v "$output_name" '%s' "$created"
}

trusted_mktemp_dir() {
  local output_name=$1 prefix=$2
  local root=${3:-$BACKUP_ROOT} workspace=${4:-$workspace_temp_dir} target_root=${5:-$APP_DIR}
  local created
  [[ "$output_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ && "$prefix" =~ ^[A-Za-z0-9._-]+$ ]] || { die "trusted temporary arguments are unsafe"; return 1; }
  assert_trusted_workspace_contract "$root" "$workspace" "$target_root" || return 1
  created=$(mktemp -d "${workspace}/${prefix}.XXXXXX")
  chown 0:0 "$created"
  chmod 700 "$created"
  [[ -d "$created" && ! -L "$created" && "$(realpath -e -- "$created")" == "$created" ]] || { die "trusted temporary directory is unsafe"; return 1; }
  [[ "$(stat -c '%a:%u:%g' "$created")" == "700:0:0" ]] || { die "trusted temporary directory metadata mismatch"; return 1; }
  printf -v "$output_name" '%s' "$created"
}

assert_safe_destination_parent() {
  local destination_root=$1 destination=$2 current component mode root_uid root_gid
  local relative parent_relative
  [[ -d "$destination_root" && ! -L "$destination_root" && "$(realpath -e -- "$destination_root")" == "$destination_root" ]] || { die "destination root is not physical"; return 1; }
  [[ "$destination" == "$destination_root/"* ]] || { die "destination escapes its reviewed root"; return 1; }
  [[ "$(realpath -ms -- "$destination")" == "$destination" ]] || { die "destination path is not lexically canonical"; return 1; }
  root_uid=$(stat -c '%u' "$destination_root")
  root_gid=$(stat -c '%g' "$destination_root")
  mode=$(stat -c '%a' "$destination_root")
  (( (8#$mode & 0022) == 0 )) || { die "destination root is group/world writable"; return 1; }
  relative=${destination#"$destination_root/"}
  parent_relative=$(dirname -- "$relative")
  current=$destination_root
  if [[ "$parent_relative" != . ]]; then
    while IFS= read -r component; do
      [[ -n "$component" && "$component" != . && "$component" != .. ]] || { die "destination parent component is unsafe"; return 1; }
      current="${current}/${component}"
      [[ -d "$current" && ! -L "$current" && "$(realpath -e -- "$current")" == "$current" ]] || { die "destination parent contains a symlink or non-directory"; return 1; }
      [[ "$(stat -c '%u:%g' "$current")" == "${root_uid}:${root_gid}" ]] || { die "destination parent ownership is non-uniform"; return 1; }
      mode=$(stat -c '%a' "$current")
      (( (8#$mode & 0022) == 0 )) || { die "destination parent is group/world writable"; return 1; }
    done < <(printf '%s\n' "$parent_relative" | tr '/' '\n')
  fi
}

assert_stage_and_artifacts() {
  local actual expected member artifact_targets expected_artifact_targets
  operator_path="${stage_dir}/baseline-7ba-offline-release-operator.sh"
  validator_path="${stage_dir}/validate-image-fallback-offline-artifacts.py"
  [[ -d "$stage_dir" && ! -L "$stage_dir" && "$(stat -c '%a:%u:%g' "$stage_dir")" == "700:0:0" ]] || die "stage ownership/mode mismatch"
  actual=$(find "$stage_dir" -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort)
  expected=$(printf '%s\n' "${STAGE_MEMBERS[@]}" | LC_ALL=C sort)
  if [[ "$actual" != "$expected" ]]; then die "stage membership mismatch"; return 1; fi
  for member in "${STAGE_MEMBERS[@]}"; do
    [[ -f "${stage_dir}/${member}" && ! -L "${stage_dir}/${member}" && "$(stat -c '%a:%u:%g' "${stage_dir}/${member}")" == "600:0:0" ]] || die "stage member ownership/mode mismatch"
  done
  [[ "$(sha256sum "$operator_path" | awk '{print $1}')" == "$operator_sha256" ]] || die "operator checksum mismatch"
  [[ "$(sha256sum "$validator_path" | awk '{print $1}')" == "$validator_sha256" ]] || die "validator checksum mismatch"
  [[ "$(sha256sum "${stage_dir}/source.tar.gz" | awk '{print $1}')" == "$source_sha256" ]] || die "source archive checksum mismatch"
  [[ "$(sha256sum "${stage_dir}/source-files.sha256" | awk '{print $1}')" == "$source_manifest_sha256" ]] || die "source manifest checksum mismatch"
  [[ "$(sha256sum "${stage_dir}/backend-image.tar.gz" | awk '{print $1}')" == "$image_bundle_sha256" ]] || die "image bundle checksum mismatch"
  [[ "$(sha256sum "${stage_dir}/image-source-files.sha256" | awk '{print $1}')" == "$image_source_manifest_sha256" ]] || die "image source manifest checksum mismatch"
  artifact_targets=$(awk '/^[0-9a-f]{64}  [A-Za-z0-9._-]+$/ { print $2; next } { exit 1 }' "${stage_dir}/artifacts.sha256" | LC_ALL=C sort) || die "artifacts manifest syntax is unsafe"
  expected_artifact_targets=$(printf '%s\n' backend-image.tar.gz backend-image.tar.gz.sha256 \
    baseline-7ba-offline-release-operator.sh image-source-files.sha256 image-validation.txt \
    source-files.sha256 source.tar.gz source.tar.gz.sha256 \
    validate-image-fallback-offline-artifacts.py | LC_ALL=C sort)
  [[ "$artifact_targets" == "$expected_artifact_targets" ]] || die "artifacts manifest membership mismatch"
  (cd "$stage_dir" && sha256sum --strict -c artifacts.sha256 source.tar.gz.sha256 backend-image.tar.gz.sha256) >/dev/null
  [[ "$(wc -l <"${stage_dir}/image-validation.txt" | tr -d '[:space:]')" == 21 ]] || die "image validation evidence shape mismatch"
  grep -Fx "release_sha=${candidate_commit}" "${stage_dir}/image-validation.txt" >/dev/null || die "image validation release SHA mismatch"
  grep -Fx "candidate_tag=${candidate_tag}" "${stage_dir}/image-validation.txt" >/dev/null || die "image validation candidate tag mismatch"
  grep -Fx "candidate_id=${candidate_id}" "${stage_dir}/image-validation.txt" >/dev/null || die "image validation candidate ID mismatch"
  grep -Fx "dependency_base_id=${DEPENDENCY_BASE_ID}" "${stage_dir}/image-validation.txt" >/dev/null || die "image validation dependency base mismatch"
  grep -Fx "runtime_lock_sha256=${EXPECTED_RUNTIME_LOCK_SHA256}" "${stage_dir}/image-validation.txt" >/dev/null || die "runtime.lock audit evidence mismatch"
  grep -Fx "dockerfile_sha256=${EXPECTED_DOCKERFILE_SHA256}" "${stage_dir}/image-validation.txt" >/dev/null || die "Dockerfile audit evidence mismatch"
  grep -Fx "base_pyproject_sha256=${EXPECTED_BASE_PYPROJECT_SHA256}" "${stage_dir}/image-validation.txt" >/dev/null || die "base pyproject audit evidence mismatch"
  grep -Fx "final_pyproject_sha256=${EXPECTED_FINAL_PYPROJECT_SHA256}" "${stage_dir}/image-validation.txt" >/dev/null || die "final pyproject audit evidence mismatch"
  grep -Fx 'production_dependency_delta=none' "${stage_dir}/image-validation.txt" >/dev/null || die "production dependency audit evidence is absent"
  grep -Fx 'pyproject_delta=none' "${stage_dir}/image-validation.txt" >/dev/null || die "pyproject audit evidence mismatch"
  grep -Fx 'compose_openapi_alembic_delta=none' "${stage_dir}/image-validation.txt" >/dev/null || die "protected contract evidence mismatch"
  grep -Fx 'supported_mcp_imports=0' "${stage_dir}/image-validation.txt" >/dev/null || die "supported MCP import audit evidence mismatch"
  grep -Fx 'candidate_mcp_distribution=absent' "${stage_dir}/image-validation.txt" >/dev/null || die "candidate MCP distribution evidence mismatch"
  grep -Fx "source_file_count=${EXPECTED_SOURCE_FILE_COUNT}" "${stage_dir}/image-validation.txt" >/dev/null || die "source count evidence mismatch"
  grep -Fx "image_source_file_count=${EXPECTED_IMAGE_SOURCE_FILE_COUNT}" "${stage_dir}/image-validation.txt" >/dev/null || die "image-source count evidence mismatch"
  grep -Fx "alembic_head=${EXPECTED_ALEMBIC_HEAD}" "${stage_dir}/image-validation.txt" >/dev/null || die "Alembic evidence mismatch"
  grep -Fx 'runtime_probe=non-root,read-only,network-none,cap-drop-all,no-new-privileges' "${stage_dir}/image-validation.txt" >/dev/null || die "runtime probe evidence mismatch"
  grep -Fx 'runtime_config=.7/v4,ocr=true,diversity=true' "${stage_dir}/image-validation.txt" >/dev/null || die "runtime config evidence mismatch"
  grep -Fx 'runtime_diff=3-reviewed-blobs' "${stage_dir}/image-validation.txt" >/dev/null || die "runtime diff evidence mismatch"
  grep -Fx 'production_workbench=absent' "${stage_dir}/image-validation.txt" >/dev/null || die "production Workbench evidence mismatch"
  grep -Fx 'rootfs_dependency_base_prefix=exact' "${stage_dir}/image-validation.txt" >/dev/null || die "rootfs base-prefix evidence mismatch"
}

validate_artifacts() {
  trusted_mktemp_file source_paths_file source-paths
  trusted_mktemp_file source_modes_file source-modes
  python3 "$validator_path" source --archive "${stage_dir}/source.tar.gz" \
    --manifest "${stage_dir}/source-files.sha256" \
    --expected-count "$expected_source_file_count" \
    --paths-output "$source_paths_file" --modes-output "$source_modes_file"
  python3 "$validator_path" image --bundle "${stage_dir}/backend-image.tar.gz" \
    --expected-tag "$candidate_tag" --expected-image-id "$candidate_id"
}

validate_source_transition() {
  local previous_paths=$1 candidate_paths=$2 previous_count=$3 candidate_count=$4
  [[ "$previous_count" == "$candidate_count" && "$candidate_count" == "$EXPECTED_SOURCE_FILE_COUNT" ]] \
    || { die "7ba/cbc source count contract mismatch"; return 1; }
  cmp -- "$previous_paths" "$candidate_paths" >/dev/null \
    || { die "candidate source path set differs from exact 7ba"; return 1; }
}

assert_exact_source_diff() {
  local previous_manifest=$1 candidate_manifest=$2 changed_paths=$3 expected_changed
  python3 - "$previous_manifest" "$candidate_manifest" "$changed_paths" <<'PY'
import pathlib
import sys

def load(path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        result[name.removeprefix("./")] = digest
    return result

before, after = load(sys.argv[1]), load(sys.argv[2])
if before.keys() != after.keys():
    raise SystemExit("source manifest paths differ")
changed = sorted(path for path in before if before[path] != after[path])
pathlib.Path(sys.argv[3]).write_text("".join(f"{path}\n" for path in changed), encoding="utf-8")
PY
  expected_changed=$(printf '%s\n' "${EXPECTED_SOURCE_DIFF[@]}" | LC_ALL=C sort)
  [[ "$(<"$changed_paths")" == "$expected_changed" ]] \
    || { die "candidate source differs from 7ba outside the exact seven reviewed application/test blobs"; return 1; }
}

previous_source_metadata_class() {
  local semantic_mode=$1 destination_mode=$2 uid=$3 gid=$4 path=$5
  local app_uid=$6 app_gid=$7
  if [[ "$uid" == 0 && "$gid" == 0 ]]; then
    case "${semantic_mode}:${destination_mode}" in
      0644:600) printf 'root-nonexec\n'; return 0 ;;
      0755:700) printf 'root-exec\n'; return 0 ;;
      *) die "root-owned source mode differs from the exact 7ba contract"; return 1 ;;
    esac
  fi
  if [[ "$uid" == "$app_uid" && "$gid" == "$app_gid" \
        && "$semantic_mode" == 0644 && "$destination_mode" == 664 ]]; then
    case "$path" in
      .gitattributes|.gitignore|AGENTS.md) printf 'app-metadata\n'; return 0 ;;
    esac
  fi
  die "active source ownership or mode differs from the exact 7ba contract"
  return 1
}

assert_previous_source_metadata_distribution() {
  local root_nonexec_count=$1 root_exec_count=$2 app_metadata_count=$3
  [[ "$root_nonexec_count" == 306 && "$root_exec_count" == 12 && "$app_metadata_count" == 3 ]] \
    || { die "7ba source metadata distribution differs from 306:12:3"; return 1; }
}

assert_previous_source() {
  local app_physical app_uid app_gid path destination semantic_mode
  local destination_mode destination_uid destination_gid metadata_class lifecycle
  local root_nonexec_count=0 root_exec_count=0 app_metadata_count=0
  [[ -f "$previous_source_manifest" && ! -L "$previous_source_manifest" ]] || die "previous source manifest is unsafe"
  [[ "$(stat -c '%a:%u:%g' "$previous_source_manifest")" == "600:0:0" ]] || die "previous source manifest ownership/mode mismatch"
  [[ "$(sha256sum "$previous_source_manifest" | awk '{print $1}')" == "$previous_source_manifest_sha256" ]] || die "previous source manifest checksum mismatch"
  trusted_mktemp_file previous_source_paths_file previous-paths
  python3 "$validator_path" manifest --manifest "$previous_source_manifest" \
    --expected-count "$expected_previous_source_file_count" \
    --paths-output "$previous_source_paths_file"
  validate_source_transition "$previous_source_paths_file" "$source_paths_file" \
    "$expected_previous_source_file_count" "$expected_source_file_count"
  local changed_paths
  trusted_mktemp_file changed_paths source-diff
  assert_exact_source_diff "$previous_source_manifest" \
    "${stage_dir}/source-files.sha256" "$changed_paths"
  unlink -- "$changed_paths"
  app_physical=$(realpath -e -- "$APP_DIR")
  [[ "$app_physical" == "$APP_DIR" ]] || die "application root is not physical"
  app_uid=$(stat -c '%u' "$APP_DIR")
  app_gid=$(stat -c '%g' "$APP_DIR")
  trusted_mktemp_file destination_evidence_file destination-evidence
  : >"$destination_evidence_file"
  while IFS=$'\t' read -r semantic_mode path; do
    destination="${APP_DIR}/${path}"
    assert_safe_destination_parent "$APP_DIR" "$destination"
    lifecycle=existing
    [[ -f "$destination" && ! -L "$destination" && "$(realpath -e -- "$destination")" == "$destination" ]] || die "active source member is unsafe"
    destination_mode=$(stat -c '%a' "$destination")
    destination_uid=$(stat -c '%u' "$destination")
    destination_gid=$(stat -c '%g' "$destination")
    metadata_class=$(previous_source_metadata_class "$semantic_mode" "$destination_mode" \
      "$destination_uid" "$destination_gid" "$path" "$app_uid" "$app_gid")
    case "$metadata_class" in
      root-nonexec) root_nonexec_count=$((root_nonexec_count + 1)) ;;
      root-exec) root_exec_count=$((root_exec_count + 1)) ;;
      app-metadata) app_metadata_count=$((app_metadata_count + 1)) ;;
      *) die "unknown previous source metadata class" ;;
    esac
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$lifecycle" "$semantic_mode" "$destination_mode" "$destination_uid" "$destination_gid" "$path" >>"$destination_evidence_file"
  done <"$source_modes_file"
  [[ "$(wc -l <"$destination_evidence_file" | tr -d '[:space:]')" == "$expected_source_file_count" ]] || die "destination evidence count mismatch"
  assert_previous_source_metadata_distribution \
    "$root_nonexec_count" "$root_exec_count" "$app_metadata_count"
  (cd "$APP_DIR" && sha256sum -c "$previous_source_manifest") >/dev/null
}

assert_candidate_provenance_values() {
  local actual=$1 revision=$2 base=$3 base_pyproject=$4 final_pyproject=$5
  local runtime_lock=$6 dockerfile=$7 source_archive=$8 source_manifest=$9
  local image_source_manifest=${10}
  [[ "$actual" == "$candidate_id" ]] || { die "candidate image id mismatch"; return 1; }
  [[ "$revision" == "$candidate_commit" && "$base" == "$expected_dependency_base_id" ]] || { die "candidate provenance labels mismatch"; return 1; }
  [[ "$base_pyproject" == "$EXPECTED_BASE_PYPROJECT_SHA256" && "$final_pyproject" == "$EXPECTED_FINAL_PYPROJECT_SHA256" ]] || { die "base/final pyproject labels mismatch"; return 1; }
  [[ "$runtime_lock" == "$EXPECTED_RUNTIME_LOCK_SHA256" && "$dockerfile" == "$EXPECTED_DOCKERFILE_SHA256" ]] || { die "runtime lock/Dockerfile labels mismatch"; return 1; }
  [[ "$source_archive" == "$source_sha256" && "$source_manifest" == "$source_manifest_sha256" && "$image_source_manifest" == "$image_source_manifest_sha256" ]] || { die "candidate source provenance labels mismatch"; return 1; }
}

assert_candidate_image() {
  local actual revision base base_pyproject final_pyproject runtime_lock dockerfile imports
  local source_archive source_manifest image_source_manifest platform
  actual=$(docker_call image inspect "$candidate_tag" --format '{{.Id}}' </dev/null)
  platform=$(docker_call image inspect "$candidate_id" --format '{{.Os}}/{{.Architecture}}' </dev/null)
  revision=$(docker_call image inspect "$candidate_id" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' </dev/null)
  base=$(docker_call image inspect "$candidate_id" --format '{{index .Config.Labels "io.trellis.dependency-base.digest"}}' </dev/null)
  base_pyproject=$(docker_call image inspect "$candidate_id" --format '{{index .Config.Labels "io.trellis.dependency-input.base-pyproject-sha256"}}' </dev/null)
  final_pyproject=$(docker_call image inspect "$candidate_id" --format '{{index .Config.Labels "io.trellis.dependency-input.final-pyproject-sha256"}}' </dev/null)
  runtime_lock=$(docker_call image inspect "$candidate_id" --format '{{index .Config.Labels "io.trellis.dependency-input.runtime-lock-sha256"}}' </dev/null)
  dockerfile=$(docker_call image inspect "$candidate_id" --format '{{index .Config.Labels "io.trellis.dependency-input.dockerfile-sha256"}}' </dev/null)
  source_archive=$(docker_call image inspect "$candidate_id" --format '{{index .Config.Labels "io.trellis.release.source-archive-sha256"}}' </dev/null)
  source_manifest=$(docker_call image inspect "$candidate_id" --format '{{index .Config.Labels "io.trellis.release.source-manifest-sha256"}}' </dev/null)
  image_source_manifest=$(docker_call image inspect "$candidate_id" --format '{{index .Config.Labels "io.trellis.release.image-source-manifest-sha256"}}' </dev/null)
  assert_candidate_provenance_values "$actual" "$revision" "$base" "$base_pyproject" \
    "$final_pyproject" "$runtime_lock" "$dockerfile" "$source_archive" \
    "$source_manifest" "$image_source_manifest"
  [[ "$platform" == linux/amd64 ]] || die "candidate image platform is not linux/amd64"
  imports=$(docker_call run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --entrypoint python "$candidate_id" -c \
    'import ast,pathlib; roots=[pathlib.Path("/app/app/api_main.py"),pathlib.Path("/app/app/scheduler_main.py"),pathlib.Path("/app/app/worker_main.py"),pathlib.Path("/app/app/governance_scheduler_main.py"),pathlib.Path("/app/app/governance_worker_main.py"),pathlib.Path("/app/app/content_scheduler_main.py"),pathlib.Path("/app/app/content_worker_main.py"),pathlib.Path("/app/app/wecom_dispatcher_main.py")]; print(sum(any((isinstance(n,ast.Import) and any(a.name=="mcp" or a.name.startswith("mcp.") for a in n.names)) or (isinstance(n,ast.ImportFrom) and (n.module=="mcp" or (n.module or "").startswith("mcp."))) for n in ast.walk(ast.parse(p.read_text()))) for p in roots))' </dev/null)
  [[ "$imports" == 0 ]] || die "supported production entrypoint imports dev-only mcp"
  trusted_mktemp_file image_source_observed_file image-source
  docker_call run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --entrypoint sh "$candidate_id" -c \
    'export LC_ALL=C; cd /app; test -f alembic.ini && test -f pyproject.toml && test -d app && test -d alembic; { printf "%s\0" alembic.ini pyproject.toml; find app alembic -type f \( -name "*.py" -o -name "*.html" \) -print0; } | sort -z | xargs -0 -r sha256sum' \
    </dev/null >"$image_source_observed_file"
  python3 "$validator_path" image-source --observed "$image_source_observed_file" \
    --expected "${stage_dir}/image-source-files.sha256" \
    --expected-count "$expected_image_source_file_count"
  unlink "$image_source_observed_file"
  image_source_observed_file=""
  docker_call run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --entrypoint pip "$candidate_id" check </dev/null
}

assert_active_identity() {
  local service cid image status project_label service_label number_label
  for service in "${APP_SERVICES[@]}"; do
    cid=$(container_id "$service")
    [[ -n "$cid" ]] || die "$service container absent"
    image=$(docker_call inspect "$cid" --format '{{.Image}}' </dev/null)
    status=$(docker_call inspect "$cid" --format '{{.State.Status}}' </dev/null)
    project_label=$(docker_call inspect "$cid" --format '{{index .Config.Labels "com.docker.compose.project"}}' </dev/null)
    service_label=$(docker_call inspect "$cid" --format '{{index .Config.Labels "com.docker.compose.service"}}' </dev/null)
    number_label=$(docker_call inspect "$cid" --format '{{index .Config.Labels "com.docker.compose.container-number"}}' </dev/null)
    [[ "$image" == "$PREVIOUS_IMAGE_ID" ]] || die "$service prior image mismatch"
    [[ "$status" == running && "$project_label" == "$COMPOSE_PROJECT" && "$service_label" == "$service" && "$number_label" == 1 ]] || die "$service prior runtime identity mismatch"
    [[ "$(docker_call inspect "$cid" --format '{{.RestartCount}}' </dev/null)" == 0 ]] || die "$service restart count drift"
    OLD_CONTAINER_IDS["$service"]=$cid
  done
  [[ -f "${APP_DIR}/.release-commit" && ! -L "${APP_DIR}/.release-commit" && "$(realpath -e -- "${APP_DIR}/.release-commit")" == "${APP_DIR}/.release-commit" ]] || die "full release marker is unsafe"
  [[ -f "${APP_DIR}/RELEASE_COMMIT" && ! -L "${APP_DIR}/RELEASE_COMMIT" && "$(realpath -e -- "${APP_DIR}/RELEASE_COMMIT")" == "${APP_DIR}/RELEASE_COMMIT" ]] || die "short release marker is unsafe"
  release_marker_uid=$(stat -c '%u' "${APP_DIR}/.release-commit")
  release_marker_gid=$(stat -c '%g' "${APP_DIR}/.release-commit")
  [[ "$(stat -c '%a:%u:%g' "${APP_DIR}/.release-commit")" == "600:${release_marker_uid}:${release_marker_gid}" ]] || die "full release marker metadata mismatch"
  [[ "$(stat -c '%a:%u:%g' "${APP_DIR}/RELEASE_COMMIT")" == "600:${release_marker_uid}:${release_marker_gid}" ]] || die "short release marker metadata mismatch"
  [[ "$(<"${APP_DIR}/.release-commit")" == "$PREVIOUS_COMMIT" && "$(<"${APP_DIR}/RELEASE_COMMIT")" == "$PREVIOUS_SHORT" ]] || die "prior release markers mismatch"
}

assert_infrastructure() {
  local service cid status
  for service in postgres minio; do
    cid=$(container_id "$service") || return 1
    [[ -n "$cid" ]] || { die "$service container is absent"; return 1; }
    status=$(docker_call inspect "$cid" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' </dev/null) || return 1
    [[ "$status" == healthy ]] || { die "$service is not healthy"; return 1; }
  done
}

assert_active_tags() {
  local expected_id=$1 service image
  image=$(docker_call image inspect "$SHARED_ACTIVE_TAG" --format '{{.Id}}' </dev/null) || return 1
  [[ "$image" == "$expected_id" ]] || { die "shared active tag mismatch"; return 1; }
  for service in "${TAG_SERVICES[@]}"; do
    image=$(docker_call image inspect "$(service_tag "$service")" --format '{{.Id}}' </dev/null) || return 1
    [[ "$image" == "$expected_id" ]] || { die "$service active tag mismatch"; return 1; }
  done
}

assert_runtime_settings() {
  local service=$1 expected_scoring=$2 cid
  cid=$(container_id "$service") || return 1
  docker_call exec "$cid" python -c \
    'import sys; from app.core.config import Settings; from app.application.services.topic_selection import build_topic_scoring_config; s=Settings(); c=build_topic_scoring_config(s); assert s.image_diversity_enabled is True and s.image_ocr_enabled is True and s.image_ocr_model=="glm-ocr"; assert c.version==sys.argv[1]' \
    "$expected_scoring" </dev/null || return 1
}

assert_workbench_absent() {
  local services api_id
  services=$(compose_call config --services) || return 1
  ! grep -Eq '^agent-workbench($|-)' <<<"$services" || { die "Workbench service entered production Compose"; return 1; }
  api_id=$(container_id acquisition-api) || return 1
  docker_call exec "$api_id" python -c \
    'from app.api_main import app; schema=app.openapi(); assert all("agent-workbench" not in path for path in schema.get("paths", {}))' \
    </dev/null || return 1
}

assert_safe_logs() {
  trusted_mktemp_file log_scan_file bounded-logs || return 1
  compose_call --profile governance --profile content --profile wecom logs --no-color --tail 200 \
    "${APP_SERVICES[@]}" >"$log_scan_file" 2>&1 || return 1
  if LC_ALL=C grep -Eiq 'Traceback|CRITICAL|delivery_unknown|authorization[" ]*[:=]|bearer[[:space:]]+[A-Za-z0-9._-]+|x-amz-(credential|signature)|webhook/send\?key=|sk-[A-Za-z0-9_-]{16,}|(api[_-]?key|secret|token|password)=[^[:space:]]+' "$log_scan_file"; then
    die "bounded logs contain a severe or secret-shaped marker"
    return 1
  fi
  unlink "$log_scan_file" || return 1
  log_scan_file=""
}

assert_container_scoring_env_json() {
  local expected_scoring=$1 service=$2 runtime_env=$3
  printf '%s\n' "$runtime_env" | python3 -c \
    'import json,sys; expected,service=sys.argv[1:]; values=[item.split("=",1)[1] for item in json.load(sys.stdin) if item.startswith("CONTENT_SCORING_VERSION=")]; values == [expected] or sys.exit(f"{service} runtime scoring env is not exact")' \
    "$expected_scoring" "$service" || return 1
}

assert_running_release() {
  local expected_id=$1 expected_full=$2 expected_short=$3 expected_scoring=$4
  local service cid image status restarts runtime_env
  for service in "${APP_SERVICES[@]}"; do
    cid=$(container_id "$service") || return 1
    [[ -n "$cid" ]] || { die "$service is absent"; return 1; }
    image=$(docker_call inspect "$cid" --format '{{.Image}}' </dev/null) || return 1
    status=$(docker_call inspect "$cid" --format '{{.State.Status}}' </dev/null) || return 1
    restarts=$(docker_call inspect "$cid" --format '{{.RestartCount}}' </dev/null) || return 1
    [[ "$image" == "$expected_id" && "$status" == running && "$restarts" == 0 ]] || { die "$service candidate runtime mismatch"; return 1; }
    runtime_env=$(docker_call inspect "$cid" --format '{{json .Config.Env}}' </dev/null) || return 1
    assert_container_scoring_env_json "$expected_scoring" "$service" "$runtime_env" || return 1
  done
  [[ -f "${APP_DIR}/.release-commit" && ! -L "${APP_DIR}/.release-commit" && "$(realpath -e -- "${APP_DIR}/.release-commit")" == "${APP_DIR}/.release-commit" ]] || { die "full release marker is unsafe"; return 1; }
  [[ -f "${APP_DIR}/RELEASE_COMMIT" && ! -L "${APP_DIR}/RELEASE_COMMIT" && "$(realpath -e -- "${APP_DIR}/RELEASE_COMMIT")" == "${APP_DIR}/RELEASE_COMMIT" ]] || { die "short release marker is unsafe"; return 1; }
  [[ "$(stat -c '%a:%u:%g' "${APP_DIR}/.release-commit")" == "600:${release_marker_uid}:${release_marker_gid}" && "$(stat -c '%a:%u:%g' "${APP_DIR}/RELEASE_COMMIT")" == "600:${release_marker_uid}:${release_marker_gid}" ]] || { die "release marker metadata drift"; return 1; }
  [[ "$(<"${APP_DIR}/.release-commit")" == "$expected_full" && "$(<"${APP_DIR}/RELEASE_COMMIT")" == "$expected_short" ]] || { die "release marker mismatch"; return 1; }
  assert_infrastructure || return 1
  assert_active_tags "$expected_id" || return 1
  assert_runtime_settings acquisition-api "$expected_scoring" || return 1
  assert_runtime_settings content-worker "$expected_scoring" || return 1
  docker_call exec "$(container_id acquisition-api)" python -c \
    'import urllib.request; response=urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=3); assert response.status == 200; response.close()' \
    </dev/null || return 1
  assert_workbench_absent || return 1
}

phase_preflight_and_load() {
  local first second
  assert_trusted_backup_root
  initialize_trusted_workspace
  assert_stage_and_artifacts
  validate_artifacts
  assert_previous_source
  assert_env_contract
  assert_safe_window
  assert_active_identity
  assert_running_release "$PREVIOUS_IMAGE_ID" "$PREVIOUS_COMMIT" "$PREVIOUS_SHORT" "$SCORING_ACTIVE"
  assert_safe_logs
  [[ "$(zero_work_vector)" == "0:0:0:0:0:0:0" ]] || die "actionable/nonterminal work exists"
  [[ "$(legacy_prompt_vector)" == "0:0:0" ]] || die "legacy v17 work can cross the release"
  [[ "$(durable_vector)" == "$expected_durable_vector" && "$(provider_vector)" == "$expected_provider_vector" && "$(source_vector)" == "$expected_source_vector" ]] || die "preflight vectors drift"
  first="$(durable_vector)|$(provider_vector)|$(source_vector)|$(zero_work_vector)|$(legacy_prompt_vector)"
  sleep "$preflight_sample_seconds"
  assert_safe_window
  [[ "$(zero_work_vector)" == "0:0:0:0:0:0:0" && "$(legacy_prompt_vector)" == "0:0:0" ]] || die "second preflight work sample is nonzero"
  [[ "$(durable_vector)" == "$expected_durable_vector" && "$(provider_vector)" == "$expected_provider_vector" && "$(source_vector)" == "$expected_source_vector" ]] || die "second preflight vectors drift"
  second="$(durable_vector)|$(provider_vector)|$(source_vector)|$(zero_work_vector)|$(legacy_prompt_vector)"
  [[ "$first" == "$second" ]] || die "preflight samples are unstable"
  docker_call image load --input "${stage_dir}/backend-image.tar.gz" </dev/null >/dev/null
  assert_candidate_image
  [[ "$(docker_call ps -aq --filter "ancestor=${candidate_id}" | wc -l | tr -d '[:space:]')" == 0 ]] || die "candidate image already has containers"
}

phase_quiesce() {
  local service
  assert_safe_window
  assert_startup_observed_zero "the first stop"
  [[ "$(durable_vector)" == "$expected_durable_vector" && "$(provider_vector)" == "$expected_provider_vector" && "$(source_vector)" == "$expected_source_vector" ]] || die "vectors drifted before the first stop"
  writers_stopped=1
  for service in "${QUIESCE_ORDER[@]}"; do
    docker_call stop --time 30 "${OLD_CONTAINER_IDS[$service]}" </dev/null >/dev/null
  done
  [[ "$(zero_work_vector)" == "0:0:0:0:0:0:0" ]] || die "work appeared during quiescence"
}

create_unique_backup_directory() {
  local root=$1 identifier=$2 candidate
  [[ "$identifier" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || { die "backup identifier is invalid"; return 1; }
  [[ -d "$root" && ! -L "$root" && "$(realpath -e -- "$root")" == "$root" ]] || { die "backup root changed before backup"; return 1; }
  [[ "$(stat -c '%a:%u:%g' "$root")" == "700:0:0" ]] || { die "backup root metadata changed before backup"; return 1; }
  candidate="${root}/${identifier}-image-fallback"
  [[ ! -e "$candidate" && ! -L "$candidate" ]] || { die "backup directory already exists"; return 1; }
  mkdir -m 0700 -- "$candidate" || return 1
  [[ -d "$candidate" && ! -L "$candidate" && "$(realpath -e -- "$candidate")" == "$candidate" ]] || { die "backup directory is not physical"; return 1; }
  [[ "$(stat -c '%a:%u:%g' "$candidate")" == "700:0:0" ]] || { die "backup directory ownership/mode mismatch"; return 1; }
  backup_dir=$candidate
}

assert_rollback_tags() {
  local service tag image
  [[ -n "$rollback_tag_prefix" ]] || { die "rollback tag prefix is absent"; return 1; }
  for service in "${TAG_SERVICES[@]}"; do
    tag=$(rollback_tag_for_service "$service")
    image=$(docker_call image inspect "$tag" --format '{{.Id}}' </dev/null) || return 1
    [[ "$image" == "$PREVIOUS_IMAGE_ID" ]] \
      || { die "$service immutable rollback tag identity mismatch"; return 1; }
  done
}

phase_backup() {
  local postgres_id minio_id service cid tag image
  backup_id=$(date -u +%Y%m%dT%H%M%SZ)
  create_unique_backup_directory "$BACKUP_ROOT" "$backup_id"
  rollback_tag_prefix="edu-ai-lead-agent-backend:rollback-${backup_id}"
  for service in "${TAG_SERVICES[@]}"; do
    tag=$(rollback_tag_for_service "$service")
    if docker_call image inspect "$tag" >/dev/null 2>&1; then
      die "generated immutable rollback tag already exists"
      return 1
    fi
  done
  postgres_id=$(container_id postgres)
  docker_call exec "$postgres_id" sh -c 'exec pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' </dev/null >"${backup_dir}/postgres.dump"
  docker_call exec -i "$postgres_id" sh -c 'exec pg_restore --list' <"${backup_dir}/postgres.dump" >"${backup_dir}/postgres.catalog"
  [[ -s "${backup_dir}/postgres.dump" && -s "${backup_dir}/postgres.catalog" ]] || die "fresh PostgreSQL backup is incomplete"
  install -m 0600 "$PRIMARY_ENV" "${backup_dir}/env"
  install -m 0600 "$RELEASE_ENV" "${backup_dir}/release.env"
  install -m 0600 "${APP_DIR}/.release-commit" "${backup_dir}/release-commit"
  install -m 0600 "${APP_DIR}/RELEASE_COMMIT" "${backup_dir}/RELEASE_COMMIT"
  install -m 0600 "$previous_source_manifest" "${backup_dir}/source-files.sha256"
  install -m 0600 "$destination_evidence_file" "${backup_dir}/destination-evidence.tsv"
  python3 - "$previous_source_paths_file" "${backup_dir}/code-files.list0" <<'PY'
import pathlib
import sys
paths = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
pathlib.Path(sys.argv[2]).write_bytes(b"".join(path.encode() + b"\0" for path in paths))
PY
  tar --null --verbatim-files-from -C "$APP_DIR" -czf "${backup_dir}/code.tar.gz" -T "${backup_dir}/code-files.list0"
  : >"${backup_dir}/container-image-inventory.txt"
  for service in "${APP_SERVICES[@]}"; do
    cid=${OLD_CONTAINER_IDS[$service]}
    image=$(docker_call inspect "$cid" --format '{{.Image}}' </dev/null)
    printf '%s %s %s\n' "$service" "$cid" "$image" >>"${backup_dir}/container-image-inventory.txt"
  done
  : >"${backup_dir}/active-tag-inventory.txt"
  image=$(docker_call image inspect "$SHARED_ACTIVE_TAG" --format '{{.Id}}' </dev/null)
  printf 'shared %s %s\n' "$SHARED_ACTIVE_TAG" "$image" >>"${backup_dir}/active-tag-inventory.txt"
  for service in "${TAG_SERVICES[@]}"; do
    tag=$(service_tag "$service")
    image=$(docker_call image inspect "$tag" --format '{{.Id}}' </dev/null)
    printf '%s %s %s\n' "$service" "$tag" "$image" >>"${backup_dir}/active-tag-inventory.txt"
  done
  : >"${backup_dir}/rollback-tag-inventory.txt"
  for service in "${TAG_SERVICES[@]}"; do
    tag=$(rollback_tag_for_service "$service")
    docker_call image tag "$PREVIOUS_IMAGE_ID" "$tag" </dev/null
    printf '%s %s %s\n' "$service" "$tag" "$PREVIOUS_IMAGE_ID" >>"${backup_dir}/rollback-tag-inventory.txt"
  done
  assert_rollback_tags
  (
    cd "${APP_DIR}/private/brand-materials"
    find . -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum
  ) >"${backup_dir}/brand.sha256"
  minio_id=$(container_id minio)
  write_minio_inventory "$minio_id" "${backup_dir}/minio.sha256"
  printf 'postgres=%s\nminio=%s\n' \
    "$(docker_call inspect "$postgres_id" --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}' </dev/null)" \
    "$validated_minio_volume_name" >"${backup_dir}/volume-inventory.txt"
  sha256sum "${backup_dir}/postgres.dump" "${backup_dir}/postgres.catalog" \
    "${backup_dir}/env" "${backup_dir}/release.env" \
    "${backup_dir}/release-commit" "${backup_dir}/RELEASE_COMMIT" \
    "${backup_dir}/source-files.sha256" "${backup_dir}/destination-evidence.tsv" \
    "${backup_dir}/code-files.list0" "${backup_dir}/code.tar.gz" \
    "${backup_dir}/container-image-inventory.txt" \
    "${backup_dir}/active-tag-inventory.txt" \
    "${backup_dir}/rollback-tag-inventory.txt" "${backup_dir}/volume-inventory.txt" \
    "${backup_dir}/brand.sha256" "${backup_dir}/minio.sha256" \
    >"${backup_dir}/protected.sha256"
  find "$backup_dir" -type d -exec chmod 700 {} +
  find "$backup_dir" -type f -exec chmod 600 {} +
  (cd "$backup_dir" && sha256sum -c protected.sha256) >/dev/null
  [[ "$(sha256sum "${backup_dir}/source-files.sha256" | awk '{print $1}')" == "$previous_source_manifest_sha256" ]] || die "prior source evidence drift"
  unlink -- "$destination_evidence_file"
  destination_evidence_file="${backup_dir}/destination-evidence.tsv"
  backup_ready=1
}

assert_protected_runtime_unchanged() {
  local postgres_id minio_id
  ((backup_ready == 1)) || { die "protected runtime comparison requires backup"; return 1; }
  trusted_mktemp_dir runtime_evidence_dir runtime-evidence || return 1
  (
    cd "${APP_DIR}/private/brand-materials"
    find . -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum
  ) >"${runtime_evidence_dir}/brand.sha256" || return 1
  minio_id=$(container_id minio) || return 1
  write_minio_inventory "$minio_id" "${runtime_evidence_dir}/minio.sha256" || return 1
  postgres_id=$(container_id postgres) || return 1
  printf 'postgres=%s\nminio=%s\n' \
    "$(docker_call inspect "$postgres_id" --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}' </dev/null)" \
    "$validated_minio_volume_name" \
    >"${runtime_evidence_dir}/volume-inventory.txt" || return 1
  cmp -s "${backup_dir}/brand.sha256" "${runtime_evidence_dir}/brand.sha256" || { die "brand manifest changed"; return 1; }
  cmp -s "${backup_dir}/minio.sha256" "${runtime_evidence_dir}/minio.sha256" || { die "MinIO manifest changed"; return 1; }
  cmp -s "${backup_dir}/volume-inventory.txt" "${runtime_evidence_dir}/volume-inventory.txt" || { die "named volume identity changed"; return 1; }
  find "$runtime_evidence_dir" -depth -delete || return 1
  runtime_evidence_dir=""
}


trusted_atomic_replace_file() {
  local source=$1 destination=$2 mode=$3 uid=$4 gid=$5
  local trusted_root=${6:-$BACKUP_ROOT} trusted_workspace=${7:-$workspace_temp_dir}
  local destination_root=${8:-$APP_DIR} destination_identity parent_identity
  assert_trusted_workspace_contract "$trusted_root" "$trusted_workspace" "$destination_root" || return 1
  [[ -f "$source" && ! -L "$source" && "$(realpath -e -- "$source")" == "$source" ]] || { die "atomic replacement source is unsafe"; return 1; }
  assert_safe_destination_parent "$destination_root" "$destination" || return 1
  [[ -f "$destination" && ! -L "$destination" && "$(realpath -e -- "$destination")" == "$destination" ]] || { die "atomic replacement destination is unsafe"; return 1; }
  [[ "$(stat -c '%a:%u:%g' "$destination")" == "${mode}:${uid}:${gid}" ]] || { die "atomic replacement destination metadata drifted"; return 1; }
  parent_identity=$(stat -c '%d:%i:%a:%u:%g' "$(dirname -- "$destination")")
  destination_identity=$(stat -c '%d:%i:%a:%u:%g' "$destination")
  trusted_mktemp_file install_temp_path atomic-install "$trusted_root" "$trusted_workspace" "$destination_root" || return 1
  install -o "$uid" -g "$gid" -m "$mode" -- "$source" "$install_temp_path"
  [[ -f "$install_temp_path" && ! -L "$install_temp_path" && "$(realpath -e -- "$install_temp_path")" == "$install_temp_path" ]] || { die "atomic replacement temporary is unsafe"; return 1; }
  [[ "$(stat -c '%a:%u:%g' "$install_temp_path")" == "${mode}:${uid}:${gid}" ]] || { die "atomic replacement temporary metadata mismatch"; return 1; }
  cmp -s -- "$source" "$install_temp_path" || { die "atomic replacement temporary content mismatch"; return 1; }
  assert_safe_destination_parent "$destination_root" "$destination" || return 1
  [[ "$(stat -c '%d:%i:%a:%u:%g' "$(dirname -- "$destination")")" == "$parent_identity" ]] || { die "atomic replacement parent changed"; return 1; }
  [[ -f "$destination" && ! -L "$destination" && "$(stat -c '%d:%i:%a:%u:%g' "$destination")" == "$destination_identity" ]] || { die "atomic replacement destination changed"; return 1; }
  mv -T -- "$install_temp_path" "$destination"
  install_temp_path=""
  [[ -f "$destination" && ! -L "$destination" && "$(realpath -e -- "$destination")" == "$destination" ]] || { die "atomic replacement result is unsafe"; return 1; }
  [[ "$(stat -c '%a:%u:%g' "$destination")" == "${mode}:${uid}:${gid}" ]] || { die "atomic replacement result metadata mismatch"; return 1; }
  cmp -s -- "$source" "$destination" || { die "atomic replacement result content mismatch"; return 1; }
}

install_reviewed_source_tree() {
  local source_root=$1 include_additions=$2 destination_root=${3:-$APP_DIR}
  local trusted_root=${4:-$BACKUP_ROOT} trusted_workspace=${5:-$workspace_temp_dir}
  local evidence_file=${6:-$destination_evidence_file}
  local lifecycle semantic_mode destination_mode uid gid path source destination
  local observed_mode observed_uid observed_gid destination_identity parent_identity
  assert_trusted_workspace_contract "$trusted_root" "$trusted_workspace" "$destination_root" || return 1
  [[ -d "$source_root" && ! -L "$source_root" && "$(realpath -e -- "$source_root")" == "$source_root" ]] || { die "reviewed source root is unsafe"; return 1; }
  [[ -f "$evidence_file" && ! -L "$evidence_file" ]] || { die "destination evidence is unsafe"; return 1; }
  while IFS=$'\t' read -r lifecycle semantic_mode destination_mode uid gid path; do
    if [[ "$lifecycle" == addition && "$include_additions" != 1 ]]; then continue; fi
    [[ "$lifecycle" == existing || "$lifecycle" == addition ]] || { die "destination lifecycle evidence is invalid"; return 1; }
    [[ "$path" =~ ^[A-Za-z0-9._/-]+$ && "$path" != -* && "$path" != */../* && "$path" != ../* ]] || { die "destination evidence path is unsafe"; return 1; }
    source="${source_root}/${path}"
    destination="${destination_root}/${path}"
    assert_safe_destination_parent "$source_root" "$source" || return 1
    assert_safe_destination_parent "$destination_root" "$destination" || return 1
    [[ -f "$source" && ! -L "$source" && "$(realpath -e -- "$source")" == "$source" ]] || { die "reviewed source member is unsafe"; return 1; }
    parent_identity=$(stat -c '%d:%i:%a:%u:%g' "$(dirname -- "$destination")")
    if [[ "$lifecycle" == existing ]]; then
      [[ -f "$destination" && ! -L "$destination" && "$(realpath -e -- "$destination")" == "$destination" ]] || { die "source destination changed type"; return 1; }
      observed_mode=$(stat -c '%a' "$destination")
      observed_uid=$(stat -c '%u' "$destination")
      observed_gid=$(stat -c '%g' "$destination")
      [[ "$observed_mode" == "$destination_mode" && "$observed_uid" == "$uid" && "$observed_gid" == "$gid" ]] || { die "source destination metadata drifted"; return 1; }
      destination_identity=$(stat -c '%d:%i:%a:%u:%g' "$destination")
    else
      [[ ! -e "$destination" && ! -L "$destination" ]] || { die "candidate-only destination appeared before install"; return 1; }
      destination_identity=absent
    fi
    trusted_mktemp_file install_temp_path source-install "$trusted_root" "$trusted_workspace" "$destination_root" || return 1
    install -o "$uid" -g "$gid" -m "$destination_mode" -- "$source" "$install_temp_path"
    [[ -f "$install_temp_path" && ! -L "$install_temp_path" && "$(realpath -e -- "$install_temp_path")" == "$install_temp_path" ]] || { die "source install temporary is unsafe"; return 1; }
    [[ "$(stat -c '%a:%u:%g' "$install_temp_path")" == "${destination_mode}:${uid}:${gid}" ]] || { die "source install temporary metadata mismatch"; return 1; }
    cmp -s -- "$source" "$install_temp_path" || { die "source install temporary content mismatch"; return 1; }
    assert_safe_destination_parent "$destination_root" "$destination" || return 1
    [[ "$(stat -c '%d:%i:%a:%u:%g' "$(dirname -- "$destination")")" == "$parent_identity" ]] || { die "source destination parent changed before replacement"; return 1; }
    if [[ "$lifecycle" == existing ]]; then
      [[ -f "$destination" && ! -L "$destination" && "$(realpath -e -- "$destination")" == "$destination" ]] || { die "source destination changed before replacement"; return 1; }
      [[ "$(stat -c '%d:%i:%a:%u:%g' "$destination")" == "$destination_identity" ]] || { die "source destination drifted before replacement"; return 1; }
    else
      [[ ! -e "$destination" && ! -L "$destination" ]] || { die "candidate-only destination appeared before replacement"; return 1; }
    fi
    mv -T -- "$install_temp_path" "$destination"
    install_temp_path=""
    [[ -f "$destination" && ! -L "$destination" && "$(realpath -e -- "$destination")" == "$destination" ]] || { die "installed source destination is unsafe"; return 1; }
    [[ "$(stat -c '%a:%u:%g' "$destination")" == "${destination_mode}:${uid}:${gid}" ]] || { die "installed source metadata mismatch"; return 1; }
    cmp -s -- "$source" "$destination" || { die "installed source content mismatch"; return 1; }
  done <"$evidence_file"
}

write_release_markers() {
  local full=$1 short=$2 uid gid
  [[ -f "${APP_DIR}/.release-commit" && ! -L "${APP_DIR}/.release-commit" && "$(stat -c '%a' "${APP_DIR}/.release-commit")" == 600 ]] \
    || { die "full marker is unsafe"; return 1; }
  [[ -f "${APP_DIR}/RELEASE_COMMIT" && ! -L "${APP_DIR}/RELEASE_COMMIT" && "$(stat -c '%a' "${APP_DIR}/RELEASE_COMMIT")" == 600 ]] \
    || { die "short marker is unsafe"; return 1; }
  uid=$(stat -c '%u' "${APP_DIR}/.release-commit") || return 1
  gid=$(stat -c '%g' "${APP_DIR}/.release-commit") || return 1
  [[ "${uid}:${gid}" == "${release_marker_uid}:${release_marker_gid}" && "$(stat -c '%u:%g' "${APP_DIR}/RELEASE_COMMIT")" == "${uid}:${gid}" ]] \
    || { die "release marker ownership differs"; return 1; }
  trusted_mktemp_file marker_full_temp marker-full || return 1
  trusted_mktemp_file marker_short_temp marker-short || return 1
  printf '%s\n' "$full" >"$marker_full_temp" || return 1
  printf '%s\n' "$short" >"$marker_short_temp" || return 1
  chown "${uid}:${gid}" "$marker_full_temp" "$marker_short_temp" || return 1
  chmod 600 "$marker_full_temp" "$marker_short_temp" || return 1
  trusted_atomic_replace_file "$marker_full_temp" "${APP_DIR}/.release-commit" 600 "$uid" "$gid" || return 1
  unlink "$marker_full_temp" || return 1
  marker_full_temp=""
  trusted_atomic_replace_file "$marker_short_temp" "${APP_DIR}/RELEASE_COMMIT" 600 "$uid" "$gid" || return 1
  unlink "$marker_short_temp" || return 1
  marker_short_temp=""
  [[ "$(<"${APP_DIR}/.release-commit")" == "$full" && "$(<"${APP_DIR}/RELEASE_COMMIT")" == "$short" ]] \
    || { die "release marker content mismatch after install"; return 1; }
  [[ "$(stat -c '%a:%u:%g' "${APP_DIR}/.release-commit")" == "600:${uid}:${gid}" && "$(stat -c '%a:%u:%g' "${APP_DIR}/RELEASE_COMMIT")" == "600:${uid}:${gid}" ]] \
    || { die "release marker metadata mismatch after install"; return 1; }
}

phase_install_candidate() {
  local service
  ((backup_ready == 1)) || die "candidate install requires a complete backup"
  tags_changed=1
  for service in "${TAG_SERVICES[@]}"; do docker_call image tag "$candidate_id" "$(service_tag "$service")" </dev/null; done
  docker_call image tag "$candidate_id" "$SHARED_ACTIVE_TAG" </dev/null
  # The reviewed source archive is extracted only after its exact membership,
  # hashes, and semantic modes passed the pure validator. Candidate and 7ba
  # contain the same exact 321 runtime paths.
  (cd "$APP_DIR" && sha256sum -c "$previous_source_manifest") >/dev/null
  trusted_mktemp_dir source_extract_dir candidate-source
  tar --no-same-owner --same-permissions -xzf "${stage_dir}/source.tar.gz" -C "$source_extract_dir"
  overlay_changed=1
  install_reviewed_source_tree "$source_extract_dir" 1
  (cd "$APP_DIR" && sha256sum -c "${stage_dir}/source-files.sha256") >/dev/null
  write_release_markers "$candidate_commit" "$candidate_short"
}

remove_stale_migration_container() {
  local cid record image status restarts project_label service_label number_label extra
  cid=$(compose_call ps -a -q backend-migrate) || return 1
  [[ "$cid" != *$'\n'* ]] || { die "multiple backend migration containers exist"; return 1; }
  [[ -n "$cid" ]] || return 0
  [[ "$cid" =~ ^[0-9a-f]{64}$ ]] || { die "backend migration container id is unsafe"; return 1; }
  record=$(docker_call inspect "$cid" --format \
    '{{printf "%s\t%s\t%d\t%s\t%s\t%s" .Image .State.Status .RestartCount (index .Config.Labels "com.docker.compose.project") (index .Config.Labels "com.docker.compose.service") (index .Config.Labels "com.docker.compose.container-number")}}' \
    </dev/null) || return 1
  IFS=$'\t' read -r image status restarts project_label service_label number_label extra <<<"$record"
  [[ -z "$extra" && "$image" == "$PREVIOUS_IMAGE_ID" && "$status" == exited \
    && "$restarts" == 0 && "$project_label" == "$COMPOSE_PROJECT" \
    && "$service_label" == backend-migrate && "$number_label" == 1 ]] \
    || { die "existing backend migration container is not the reviewed stale one-shot"; return 1; }
  docker_call rm "$cid" </dev/null >/dev/null || return 1
  [[ -z "$(compose_call ps -a -q backend-migrate)" ]] \
    || { die "stale backend migration container was not removed"; return 1; }
}

phase_migrate_and_probe() {
  local before_sources after_sources
  before_sources=$(source_vector)
  # Exact command override: no default command, no seed_sources, no dependency
  # one-shot, no pull, and no TTY/stdin inheritance.
  remove_stale_migration_container
  if ! compose_call run --rm --no-deps --pull never --no-TTY \
    --entrypoint alembic backend-migrate -c alembic.ini upgrade head; then
    die "Alembic-only migration failed"
    return 1
  fi
  [[ -z "$(compose_call ps -a -q backend-migrate)" ]] || die "Alembic-only migration container was not removed"
  [[ "$(sql_scalar 'SELECT version_num FROM alembic_version')" == "$EXPECTED_ALEMBIC_HEAD" ]] || die "Alembic head drift"
  after_sources=$(source_vector)
  [[ "$before_sources" == "$after_sources" && "$after_sources" == "$expected_source_vector" ]] || die "migration changed source metadata"
  docker_call run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true \
    --env "CONTENT_SCORING_VERSION=${SCORING_ACTIVE}" --entrypoint python "$candidate_id" -c \
    'from app.core.config import Settings; from app.application.services.topic_selection import build_topic_scoring_config; s=Settings(); c=build_topic_scoring_config(s); assert c.version=="scoring-v1-preview.7-delivered-repeat-history" and c.effective_veto_rule_version=="topic-veto-v4-delivered-content" and s.image_ocr_enabled is True and s.image_diversity_enabled is True' </dev/null
  [[ "$(sql_scalar 'SELECT version_num FROM alembic_version')" == "$EXPECTED_ALEMBIC_HEAD" ]] || die "Alembic head changed after candidate probe"
  [[ "$(durable_vector)" == "$expected_durable_vector" && "$(provider_vector)" == "$expected_provider_vector" && "$(source_vector)" == "$expected_source_vector" ]] || die "migration/probe changed a protected vector"
  [[ "$(zero_work_vector)" == "0:0:0:0:0:0:0" && "$(legacy_prompt_vector)" == "0:0:0" ]] || die "migration/probe created work before .7"
}


assert_startup_observed_zero() {
  [[ "$(zero_work_vector)" == "0:0:0:0:0:0:0" && "$(legacy_prompt_vector)" == "0:0:0" ]] || {
    die "observed actionable or legacy work is nonzero at $1"
    return 1
  }
}

wait_for_service() {
  local service=$1 expected_id=$2 attempt cid status image restarts
  for attempt in $(seq 1 30); do
    cid=$(container_id "$service")
    if [[ -n "$cid" ]]; then
      status=$(docker_call inspect "$cid" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' </dev/null || true)
      image=$(docker_call inspect "$cid" --format '{{.Image}}' </dev/null || true)
      restarts=$(docker_call inspect "$cid" --format '{{.RestartCount}}' </dev/null || true)
      if [[ ( "$status" == running || "$status" == healthy ) && "$image" == "$expected_id" && "$restarts" == 0 ]]; then return 0; fi
    fi
    sleep 2
  done
  die "$service did not reach the reviewed runtime identity"
}

phase_restore_candidate() {
  local service
  for service in "${RESTORE_ORDER[@]}"; do
    assert_safe_window
    case "$service" in *scheduler|wecom-dispatcher) assert_startup_observed_zero "before $service" ;; esac
    compose_call up -d --no-build --no-deps --force-recreate "$service"
    wait_for_service "$service" "$candidate_id"
    case "$service" in *scheduler|wecom-dispatcher) sleep 2; assert_startup_observed_zero "after $service start" ;; esac
  done
}

phase_accept() {
  [[ "$(env_value "$PRIMARY_ENV" CONTENT_SCORING_VERSION)" == "$SCORING_ACTIVE" ]] || die "runtime scoring is not .7"
  [[ "$(sha256sum "$PRIMARY_ENV" | awk '{print $1}')" == "$expected_env_sha256" ]] || die "primary env changed"
  [[ "$(sha256sum "$RELEASE_ENV" | awk '{print $1}')" == "$expected_release_env_sha256" ]] || die "release env changed"
  assert_running_release "$candidate_id" "$candidate_commit" "$candidate_short" "$SCORING_ACTIVE"
  assert_rollback_tags
  [[ "$(docker_call ps -q --filter "ancestor=${PREVIOUS_IMAGE_ID}" | wc -l | tr -d '[:space:]')" == 0 ]] || die "old image still has a running container"
  [[ "$(zero_work_vector)" == "0:0:0:0:0:0:0" && "$(legacy_prompt_vector)" == "0:0:0" ]] || die "candidate created actionable or legacy work"
  [[ "$(sql_scalar 'SELECT version_num FROM alembic_version')" == "$EXPECTED_ALEMBIC_HEAD" ]] || die "accepted Alembic head drift"
  [[ "$(durable_vector)" == "$expected_durable_vector" && "$(provider_vector)" == "$expected_provider_vector" && "$(source_vector)" == "$expected_source_vector" ]] || die "immediate acceptance vector drift"
  assert_protected_runtime_unchanged
  assert_safe_logs
  sleep "$stability_seconds"
  assert_running_release "$candidate_id" "$candidate_commit" "$candidate_short" "$SCORING_ACTIVE"
  [[ "$(zero_work_vector)" == "0:0:0:0:0:0:0" && "$(legacy_prompt_vector)" == "0:0:0" ]] || die "candidate stability work vector drift"
  [[ "$(durable_vector)" == "$expected_durable_vector" && "$(provider_vector)" == "$expected_provider_vector" && "$(source_vector)" == "$expected_source_vector" ]] || die "stability vector drift"
  [[ "$(sha256sum "$PRIMARY_ENV" | awk '{print $1}')" == "$expected_env_sha256" ]] || die "primary env changed during stability sample"
  [[ "$(sha256sum "$RELEASE_ENV" | awk '{print $1}')" == "$expected_release_env_sha256" ]] || die "release env changed during stability sample"
  assert_protected_runtime_unchanged
  assert_safe_logs
}

stop_all_app_services() {
  local service cid status stop_failed=0 validation_failed=0
  for service in "${QUIESCE_ORDER[@]}"; do
    if ! compose_call stop --timeout 30 "$service"; then stop_failed=1; fi
  done
  for service in "${APP_SERVICES[@]}"; do
    cid=$(compose_call ps -a -q "$service" | tr -d '\r\n') || return 1
    [[ -n "$cid" ]] || continue
    status=$(docker_call inspect "$cid" --format '{{.State.Status}}' </dev/null) || return 1
    if [[ "$status" == running ]]; then
      die "$service remained running in incident state"
      validation_failed=1
    fi
  done
  assert_infrastructure || return 1
  ((stop_failed == 0 && validation_failed == 0)) || return 1
}



restore_file_atomically() {
  local source=$1 destination=$2 mode uid gid
  [[ -f "$source" && ! -L "$source" && -f "$destination" && ! -L "$destination" ]] \
    || { die "atomic restore input is unsafe"; return 1; }
  mode=$(stat -c '%a' "$destination") || return 1
  uid=$(stat -c '%u' "$destination") || return 1
  gid=$(stat -c '%g' "$destination") || return 1
  trusted_atomic_replace_file "$source" "$destination" "$mode" "$uid" "$gid" || return 1
}

restore_prior_payload() {
  local service
  ((backup_ready == 1)) || return 0
  (cd "$backup_dir" && sha256sum -c protected.sha256) >/dev/null || return 1
  if ((overlay_changed == 1)); then
    trusted_mktemp_dir source_extract_dir prior-source || return 1
    tar --no-same-owner --same-permissions -xzf "${backup_dir}/code.tar.gz" -C "$source_extract_dir" || return 1
    install_reviewed_source_tree "$source_extract_dir" 0 || return 1
    (cd "$APP_DIR" && sha256sum -c "${backup_dir}/source-files.sha256") >/dev/null || return 1
    write_release_markers "$(<"${backup_dir}/release-commit")" "$(<"${backup_dir}/RELEASE_COMMIT")" || return 1
  fi
  if ((tags_changed == 1)); then
    assert_rollback_tags || return 1
    for service in "${TAG_SERVICES[@]}"; do
      docker_call image tag "$(rollback_tag_for_service "$service")" \
        "$(service_tag "$service")" </dev/null || return 1
    done
    docker_call image tag "$(rollback_tag_for_service backend-migrate)" \
      "$SHARED_ACTIVE_TAG" </dev/null || return 1
  fi
  cmp -s "${backup_dir}/env" "$PRIMARY_ENV" || { die "recovered primary env is not byte-exact"; return 1; }
  cmp -s "${backup_dir}/release.env" "$RELEASE_ENV" || { die "recovered release env is not byte-exact"; return 1; }
  [[ "$(stat -c '%a:%u:%g' "$PRIMARY_ENV")" == "600:${expected_env_uid}:${expected_env_gid}" ]] || { die "recovered primary env metadata drift"; return 1; }
  [[ "$(stat -c '%a:%u:%g' "$RELEASE_ENV")" == "600:${expected_release_env_uid}:${expected_release_env_gid}" ]] || { die "recovered release env metadata drift"; return 1; }
  (cd "$APP_DIR" && sha256sum -c "${backup_dir}/source-files.sha256") >/dev/null || return 1
  [[ "$(<"${APP_DIR}/.release-commit")" == "$(<"${backup_dir}/release-commit")" && "$(<"${APP_DIR}/RELEASE_COMMIT")" == "$(<"${backup_dir}/RELEASE_COMMIT")" ]] || { die "recovered release markers drift"; return 1; }
  assert_active_tags "$PREVIOUS_IMAGE_ID" || return 1
}

restore_prior_services() {
  local service cid
  for service in "${RESTORE_ORDER[@]}"; do
    # Recovery must not depend on the deployment safe-window deadline: that
    # deadline can expire while the writers are stopped. The exact zero-work
    # observed-work gates below keep scheduler/dispatcher restoration fail-closed.
    case "$service" in *scheduler|wecom-dispatcher) assert_startup_observed_zero "before $service recovery" || return 1 ;; esac
    cid=${OLD_CONTAINER_IDS[$service]:-}
    if [[ -n "$cid" ]] && docker_call container inspect "$cid" >/dev/null 2>&1; then
      docker_call start "$cid" </dev/null >/dev/null || return 1
    else
      compose_call up -d --no-build --no-deps --force-recreate "$service" || return 1
    fi
    wait_for_service "$service" "$PREVIOUS_IMAGE_ID" || return 1
    case "$service" in *scheduler|wecom-dispatcher) sleep 2; assert_startup_observed_zero "after $service recovery start" || return 1 ;; esac
  done
  assert_running_release "$PREVIOUS_IMAGE_ID" "$PREVIOUS_COMMIT" "$PREVIOUS_SHORT" "$SCORING_ACTIVE" || return 1
  assert_safe_logs || return 1
}

assert_recovery_complete() {
  if ((backup_ready == 1)); then
    cmp -s "${backup_dir}/env" "$PRIMARY_ENV" || { die "recovery gate: primary env differs"; return 1; }
    cmp -s "${backup_dir}/release.env" "$RELEASE_ENV" || { die "recovery gate: release env differs"; return 1; }
    (cd "$APP_DIR" && sha256sum -c "${backup_dir}/source-files.sha256") >/dev/null || return 1
    [[ "$(<"${APP_DIR}/.release-commit")" == "$PREVIOUS_COMMIT" && "$(<"${APP_DIR}/RELEASE_COMMIT")" == "$PREVIOUS_SHORT" ]] || { die "recovery gate: release markers differ"; return 1; }
    assert_active_tags "$PREVIOUS_IMAGE_ID" || return 1
    assert_rollback_tags || return 1
  fi
  if ((writers_stopped == 1)); then
    assert_running_release "$PREVIOUS_IMAGE_ID" "$PREVIOUS_COMMIT" "$PREVIOUS_SHORT" "$SCORING_ACTIVE" || return 1
  fi
  [[ "$(durable_vector)" == "$expected_durable_vector" && "$(provider_vector)" == "$expected_provider_vector" && "$(source_vector)" == "$expected_source_vector" ]] || { die "recovery gate: protected vectors differ"; return 1; }
  [[ "$(zero_work_vector)" == "0:0:0:0:0:0:0" && "$(legacy_prompt_vector)" == "0:0:0" ]] || { die "recovery gate: actionable or legacy work exists"; return 1; }
  if ((backup_ready == 1)); then assert_protected_runtime_unchanged || return 1; fi
  assert_safe_logs || return 1
}

fail_recovery_closed() {
  local stage=$1
  incident_required=1
  if ((writers_stopped == 1)); then
    stop_all_app_services || return 1
  fi
  log "INCIDENT: recovery failed at ${stage}; all application services were stopped"
  return 1
}

recover() {
  local original_rc=${1:-1}
  ((recovery_running == 0)) || return 1
  recovery_running=1
  log "recovery after exit ${original_rc}; backup=${backup_ready} tags=${tags_changed} overlay=${overlay_changed}"
  if ((writers_stopped == 1)); then
    stop_all_app_services || { fail_recovery_closed quiesce || return 1; }
    if [[ "$(durable_vector)" != "$expected_durable_vector" \
          || "$(provider_vector)" != "$expected_provider_vector" \
          || "$(source_vector)" != "$expected_source_vector" \
          || "$(zero_work_vector)" != "0:0:0:0:0:0:0" \
          || "$(legacy_prompt_vector)" != "0:0:0" ]]; then
      incident_required=1
      log "INCIDENT: protected or stable-zero vector drifted; all application services remain stopped"
      return 0
    fi
  fi
  restore_prior_payload || { fail_recovery_closed payload || return 1; }
  if ((writers_stopped == 1)); then
    restore_prior_services || { fail_recovery_closed services || return 1; }
  fi
  assert_recovery_complete || { fail_recovery_closed final-gate || return 1; }
  recovered=1
  log "recovery completed"
}

cleanup_trusted_workspace() {
  local root=$1 workspace=$2 target_root=$3
  [[ -n "$workspace" ]] || return 0
  [[ "$workspace" == "$root/.image-fallback-work."* && "$(dirname -- "$workspace")" == "$root" ]] || { die "refusing unsafe workspace cleanup target"; return 1; }
  assert_trusted_root_metadata "$root" "$target_root" || return 1
  if [[ -L "$workspace" ]]; then
    unlink -- "$workspace" || return 1
  elif [[ -d "$workspace" && "$(realpath -e -- "$workspace")" == "$workspace" ]]; then
    find "$workspace" -xdev -depth -delete || return 1
  elif [[ -e "$workspace" ]]; then
    unlink -- "$workspace" || return 1
  fi
  [[ ! -e "$workspace" && ! -L "$workspace" ]] || { die "trusted workspace cleanup failed"; return 1; }
}

cleanup_local_artifacts() {
  local workspace=${workspace_temp_dir:-}
  [[ -n "$workspace" ]] || return 0
  cleanup_trusted_workspace "$BACKUP_ROOT" "$workspace" "$APP_DIR" || return 1
  workspace_temp_dir=""
}

on_err() { failure_rc=$?; log "command failed with exit ${failure_rc}"; return "$failure_rc"; }
on_signal() { log "received $1"; exit "$2"; }
on_exit() {
  local rc=$? recovery_rc=0 cleanup_rc=0
  trap - ERR EXIT
  trap '' HUP INT TERM
  if ((rc != 0 && completed == 0 && (writers_stopped == 1 || backup_ready == 1 \
      || tags_changed == 1 || overlay_changed == 1))); then
    set +e
    (set -Eeuo pipefail; recover "$rc")
    recovery_rc=$?
    set -e
  fi
  cleanup_local_artifacts || cleanup_rc=$?
  if ((recovery_rc != 0 || cleanup_rc != 0)); then exit 125; fi
  exit "$rc"
}
install_traps() {
  trap on_err ERR
  trap on_exit EXIT
  trap 'on_signal HUP 129' HUP
  trap 'on_signal INT 130' INT
  trap 'on_signal TERM 143' TERM
}

acquire_release_lock() {
  exec {release_lock_fd}>"$BACKUP_LOCK"
  flock --nonblock "$release_lock_fd" || die "backup/release lock is held"
}

claim_single_invocation() {
  local guard="/var/lock/edu-ai-image-fallback-release-${candidate_commit}.once"
  mkdir -m 0700 -- "$guard" 2>/dev/null || die "candidate release invocation was already claimed"
  printf '%s\n' "$operator_sha256" >"${guard}/operator.sha256"
  chmod 600 "${guard}/operator.sha256"
}

run_release() {
  phase_preflight_and_load
  claim_single_invocation
  acquire_release_lock
  phase_quiesce
  phase_backup
  phase_install_candidate
  phase_migrate_and_probe
  phase_restore_candidate
  phase_accept
  completed=1
  log "release completed; no fixture/provider/WeCom action was invoked"
}

main() {
  parse_args "$@"
  validate_args
  ((EUID == 0)) || die "operator requires root"
  [[ "$0" = /* ]] || die "operator path must be absolute"
  [[ "$PWD" == "$APP_DIR" && "$(pwd -P)" == "$APP_DIR" && ! -L "$APP_DIR" ]] || die "operator working directory mismatch"
  [[ ! -t 0 && "$(readlink /proc/$$/fd/0)" == /dev/null ]] || die "stdin must be /dev/null"
  operator_path=$(realpath -- "$0")
  [[ "$operator_path" == "${stage_dir}/baseline-7ba-offline-release-operator.sh" ]] || die "operator entrypoint differs from staged file"
  install_traps
  run_release
}

if [[ ${IMAGE_FALLBACK_OFFLINE_SOURCE_ONLY:-0} != 1 ]]; then
  main "$@"
fi
