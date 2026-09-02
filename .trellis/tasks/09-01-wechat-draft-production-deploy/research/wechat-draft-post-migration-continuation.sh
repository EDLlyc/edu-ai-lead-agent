#!/usr/bin/env bash
# One-shot continuation for the reviewed post-migration 0042 incident state.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077
export LC_ALL=C

continuation_app_dir="/opt/edu-ai-lead-agent"
if [[ "${WECHAT_DRAFT_CONTINUATION_SOURCE_ONLY:-0}" == 1 \
      && -n "${WECHAT_DRAFT_CONTINUATION_TEST_APP_DIR:-}" ]]; then
  continuation_app_dir=$WECHAT_DRAFT_CONTINUATION_TEST_APP_DIR
fi
readonly APP_DIR="$continuation_app_dir"
unset continuation_app_dir
readonly COMPOSE_PROJECT="edu-ai-lead-agent"
readonly PRIMARY_ENV="${APP_DIR}/.env"
readonly RELEASE_ENV="${APP_DIR}/.release.env"
readonly RELEASE_LOCK="/var/lock/edu-ai-wechat-draft-release.lock"
readonly ATTEMPT_ROOT="/var/lib/edu-ai-release-attempts"
readonly EVIDENCE_ROOT="/var/backups/edu-ai/releases"
readonly RUNTIME_COMMIT="0c3d74d4baa7156b1fc56ea81f188aa25d5bc5d8"
readonly CANDIDATE_ID="sha256:7f025c7cefdf81588e20bdc97263493fd8d7e479d948c2be94d0b389a5bd4902"
readonly CANDIDATE_REFERENCE="edu-ai-lead-agent-backend@${CANDIDATE_ID}"
readonly EXPECTED_HEAD="20260901_0042"
readonly MINIMUM_WEEK="2026-09-07"
readonly -a PROFILES=(
  --profile governance --profile content --profile wecom --profile ip-assets
  --profile official-account-weekly-dag
)
readonly -a APP_SERVICES=(
  acquisition-api acquisition-scheduler acquisition-worker
  governance-scheduler governance-worker content-scheduler content-worker wecom-dispatcher
)
readonly -a STOP_ORDER=(
  wecom-dispatcher content-worker content-scheduler governance-worker governance-scheduler
  acquisition-worker acquisition-scheduler acquisition-api
)

stage_dir=""
operator_sha=""
attempt_marker=""
evidence_dir=""
recovery_armed=0
completed=0

log() { printf '[wechat-draft-continuation] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; return 1; }

compose() {
  docker compose --project-name "$COMPOSE_PROJECT" --project-directory "$APP_DIR" \
    --env-file "$PRIMARY_ENV" --env-file "$RELEASE_ENV" "${PROFILES[@]}" "$@"
}

compose_with_draft() {
  compose --profile wechat-official-account-draft "$@"
}

env_value() {
  local key=$1
  [[ "$key" =~ ^[A-Z][A-Z0-9_]*$ ]] || return 1
  awk -F= -v wanted="$key" \
    '$1 == wanted { value = substr($0, index($0, "=") + 1) } END { print value }' \
    "$PRIMARY_ENV"
}

parse_args() {
  while (($#)); do
    case "$1" in
      --stage-dir) (($# >= 2)) || die "missing stage directory"; stage_dir=$2; shift 2 ;;
      *) die "unknown argument" ;;
    esac
  done
  [[ "$stage_dir" == /* && "$stage_dir" != */ ]] || die "stage directory must be absolute"
}

require_physical_continuation() {
  local actual expected stdin_target
  actual=$(realpath -e -- "${BASH_SOURCE[0]}")
  expected=$(realpath -e -- "${stage_dir}/wechat-draft-post-migration-continuation.sh")
  [[ "$actual" == "$expected" && ! -L "$actual" && "$(stat -c '%a' "$actual")" == 600 ]] \
    || die "continuation must run from the physical mode-0600 stage file"
  [[ "$(stat -c '%a:%u:%g' "$stage_dir")" == 700:0:0 ]] \
    || die "continuation stage ownership or mode changed"
  [[ -f "${stage_dir}/continuation.sha256" \
      && ! -L "${stage_dir}/continuation.sha256" \
      && "$(stat -c '%a:%u:%g' "${stage_dir}/continuation.sha256")" == 600:0:0 ]] \
    || die "continuation checksum file changed"
  (cd "$stage_dir" && sha256sum -c continuation.sha256 >/dev/null) \
    || die "continuation checksum failed"
  operator_sha=$(sha256sum "$actual" | awk '{print $1}')
  [[ "$operator_sha" =~ ^[0-9a-f]{64}$ ]] || die "continuation identity is invalid"
  stdin_target=$(readlink "/proc/$$/fd/0" || true)
  [[ "$stdin_target" == /dev/null ]] || die "continuation stdin must be /dev/null"
}

set_env_values() {
  python3 - "$PRIMARY_ENV" "$@" <<'PY'
import os
import pathlib
import re
import stat
import sys
import tempfile

path = pathlib.Path(sys.argv[1])
arguments = sys.argv[2:]
if not arguments or len(arguments) % 2:
    raise SystemExit("environment update pairs are invalid")
pairs = list(zip(arguments[::2], arguments[1::2], strict=True))
if len({key for key, _ in pairs}) != len(pairs):
    raise SystemExit("environment update contains duplicate keys")
for key, value in pairs:
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is None or any(
        character in value for character in "\0\r\n"
    ):
        raise SystemExit("environment update is unsafe")
metadata = path.stat()
updates = dict(pairs)
result = []
seen = set()
for row in path.read_text(encoding="utf-8").splitlines():
    key = row.split("=", 1)[0] if "=" in row else ""
    if key in updates:
        if key not in seen:
            result.append(f"{key}={updates[key]}")
            seen.add(key)
    else:
        result.append(row)
for key, value in pairs:
    if key not in seen:
        result.append(f"{key}={value}")
fd, name = tempfile.mkstemp(prefix=".env.wechat-continuation.", dir=path.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write("\n".join(result) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(name, stat.S_IMODE(metadata.st_mode))
    os.chown(name, metadata.st_uid, metadata.st_gid)
    os.replace(name, path)
finally:
    if os.path.exists(name):
        os.unlink(name)
PY
}

disable_draft_flags() {
  set_env_values \
    WECHAT_MP_ENABLED false \
    WECHAT_MP_DRAFT_WORKER_ENABLED false \
    WECHAT_MP_DRAFT_AUTO_ENQUEUE_ENABLED false \
    WECHAT_MP_DRAFT_PRODUCTION_ENABLED false \
    WECHAT_MP_DRAFT_MIN_WEEK_START "$MINIMUM_WEEK"
}

enable_draft_flags() {
  set_env_values \
    WECHAT_MP_DRAFT_MIN_WEEK_START "$MINIMUM_WEEK" \
    WECHAT_MP_DRAFT_PRODUCTION_ENABLED true \
    WECHAT_MP_ENABLED true \
    WECHAT_MP_DRAFT_WORKER_ENABLED true \
    WECHAT_MP_DRAFT_AUTO_ENQUEUE_ENABLED true
}

safe_job_counts() {
  compose exec -T postgres sh -c '
    psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc \
      "SELECT (SELECT count(*) FROM wechat_official_account_draft_jobs)::text || chr(58) || (SELECT count(*) FROM wechat_official_account_draft_job_items)::text || chr(58) || (SELECT count(*) FROM wechat_official_account_draft_attempts)::text"'
}

verify_core() {
  local service container state image restart_count health head reference revision
  [[ -f "${APP_DIR}/.release-commit" && ! -L "${APP_DIR}/.release-commit" \
      && "$(<"${APP_DIR}/.release-commit")" == "$RUNTIME_COMMIT" ]] || return 1
  reference=$(awk -F= '$1 == "APP_IMAGE" { print substr($0, index($0, "=") + 1) }' \
    "$RELEASE_ENV") || return 1
  [[ "$reference" == "$CANDIDATE_REFERENCE" ]] || return 1
  [[ "$(docker image inspect --format '{{.Id}}' "$reference")" == "$CANDIDATE_ID" ]] || return 1
  revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
    "$reference") || return 1
  [[ "$revision" == "$RUNTIME_COMMIT" ]] || return 1
  head=$(compose exec -T postgres sh -c \
    'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT version_num FROM alembic_version"') \
    || return 1
  [[ "$head" == "$EXPECTED_HEAD" ]] || return 1
  for service in postgres minio "${APP_SERVICES[@]}"; do
    container=$(compose ps -q "$service") || return 1
    [[ -n "$container" ]] || return 1
    state=$(docker inspect --format '{{.State.Status}}' "$container") || return 1
    restart_count=$(docker inspect --format '{{.RestartCount}}' "$container") || return 1
    [[ "$state" == running && "$restart_count" == 0 ]] || return 1
    if [[ "$service" != postgres && "$service" != minio ]]; then
      image=$(docker inspect --format '{{.Image}}' "$container") || return 1
      [[ "$image" == "$CANDIDATE_ID" ]] || return 1
    fi
    if [[ "$service" == postgres || "$service" == minio || "$service" == acquisition-api ]]; then
      health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container") \
        || return 1
      [[ "$health" == healthy ]] || return 1
    fi
  done
}

verify_disabled_preflight() {
  local key value worker volume
  [[ -f "$PRIMARY_ENV" && ! -L "$PRIMARY_ENV" && "$(stat -c '%a' "$PRIMARY_ENV")" == 600 ]] \
    || die "primary environment is not a physical mode-0600 file"
  [[ -f "$RELEASE_ENV" && ! -L "$RELEASE_ENV" && "$(stat -c '%a' "$RELEASE_ENV")" == 600 ]] \
    || die "release environment is not a physical mode-0600 file"
  [[ "$(env_value WECHAT_MP_MODE)" == draft_only ]] || die "WeChat mode is not draft-only"
  [[ "$(env_value WECHAT_MP_DRAFT_MIN_WEEK_START)" == "$MINIMUM_WEEK" ]] \
    || die "minimum week differs from the migrated incident state"
  for key in WECHAT_MP_ENABLED WECHAT_MP_DRAFT_WORKER_ENABLED \
    WECHAT_MP_DRAFT_AUTO_ENQUEUE_ENABLED WECHAT_MP_DRAFT_PRODUCTION_ENABLED; do
    value=$(env_value "$key") || return 1
    [[ "${value,,}" == false ]] || die "draft flag is not disabled: $key"
  done
  for key in WECHAT_MP_APP_ID WECHAT_MP_APP_SECRET; do
    value=$(env_value "$key") || return 1
    [[ -n "$value" && "$value" != *[[:space:]]* ]] || die "required WeChat credential is absent"
  done
  verify_core || die "candidate core is not healthy"
  [[ "$(safe_job_counts)" == 0:0:0 ]] || die "existing WeChat draft work is not zero"
  worker=$(compose_with_draft ps --all --quiet wechat-official-account-draft-worker)
  [[ -z "$worker" ]] || die "draft worker already exists"
  for volume in "${COMPOSE_PROJECT}_official_account_weekly_dag_output" \
    "${COMPOSE_PROJECT}_wechat_mp_draft_artifacts"; do
    ! docker volume inspect "$volume" >/dev/null 2>&1 || die "draft volume already exists"
  done
}

ensure_draft_volumes() {
  local logical volume observed
  for logical in official_account_weekly_dag_output wechat_mp_draft_artifacts; do
    volume="${COMPOSE_PROJECT}_${logical}"
    observed=$(docker volume create \
      --label "com.docker.compose.project=${COMPOSE_PROJECT}" \
      --label "com.docker.compose.volume=${logical}" "$volume") || return 1
    [[ "$observed" == "$volume" \
        && "$(docker volume inspect --format '{{.Name}}' "$volume")" == "$volume" ]] || return 1
  done
}

verify_worker() {
  local worker state image restart_count
  worker=$(compose_with_draft ps -q wechat-official-account-draft-worker) || return 1
  [[ -n "$worker" ]] || return 1
  state=$(docker inspect --format '{{.State.Status}}' "$worker") || return 1
  image=$(docker inspect --format '{{.Image}}' "$worker") || return 1
  restart_count=$(docker inspect --format '{{.RestartCount}}' "$worker") || return 1
  [[ "$state" == running && "$image" == "$CANDIDATE_ID" && "$restart_count" == 0 ]] || return 1
}

wait_for_worker() {
  local deadline
  deadline=$(( $(date +%s) + 60 )) || return 1
  until verify_worker; do
    (( $(date +%s) < deadline )) || return 1
    sleep 2
  done
}

prepare_attempt() {
  install -d -o root -g root -m 700 "$ATTEMPT_ROOT" "$EVIDENCE_ROOT" || return 1
  attempt_marker="${ATTEMPT_ROOT}/wechat-draft-continuation-${operator_sha}.attempted"
  [[ ! -e "$attempt_marker" && ! -L "$attempt_marker" ]] \
    || die "continuation already has an attempt marker"
  (set -o noclobber; printf 'attempted_at=%s\n' "$(date -u +%FT%TZ)" >"$attempt_marker") \
    || die "continuation attempt marker collision"
  chmod 600 "$attempt_marker" || return 1
  evidence_dir="${EVIDENCE_ROOT}/wechat-draft-continuation-${operator_sha:0:12}-$(date -u +%Y%m%dT%H%M%SZ)"
  install -d -o root -g root -m 700 "$evidence_dir" || return 1
  cp -a "$PRIMARY_ENV" "$evidence_dir/env.before" || return 1
  recovery_armed=1
}

on_exit() {
  local rc=$?
  ((rc != 0 && completed == 0 && recovery_armed == 1)) || return 0
  log "activation failed; disabling the optional worker and proving zero effects"
  compose_with_draft stop -t 30 wechat-official-account-draft-worker >/dev/null 2>&1 || true
  compose_with_draft rm -f wechat-official-account-draft-worker >/dev/null 2>&1 || true
  if disable_draft_flags && [[ "$(safe_job_counts)" == 0:0:0 ]] && verify_core; then
    log "optional activation disabled with zero draft effects; healthy core retained"
    return 0
  fi
  log "zero-effect recovery failed; stopping application writers for incident handling"
  compose stop -t 30 "${STOP_ORDER[@]}" >/dev/null 2>&1 || true
}

run_activation() {
  trap on_exit EXIT
  prepare_attempt
  ensure_draft_volumes
  enable_draft_flags
  compose_with_draft up -d --no-build --no-deps wechat-official-account-draft-worker
  wait_for_worker || die "draft worker did not become ready within the bounded window"
  verify_core || die "candidate core drifted after optional activation"
  verify_worker || die "draft worker did not become ready"
  [[ "$(safe_job_counts)" == 0:0:0 ]] || die "optional activation created draft work"
  sleep 30
  verify_core || die "candidate core drifted during stable activation"
  verify_worker || die "draft worker drifted during stable activation"
  [[ "$(safe_job_counts)" == 0:0:0 ]] || die "stable activation created draft work"
  {
    printf 'schema_version=1\nruntime_commit=%s\ncandidate_id=%s\n' "$RUNTIME_COMMIT" "$CANDIDATE_ID"
    printf 'alembic_head=%s\nminimum_week_start=%s\n' "$EXPECTED_HEAD" "$MINIMUM_WEEK"
    printf 'draft_jobs=0\ndraft_items=0\ndraft_attempts=0\nprovider_writes=0\n'
    printf 'worker_restart_count=0\ncompleted_at=%s\n' "$(date -u +%FT%TZ)"
  } >"$evidence_dir/wechat-draft-continuation-evidence.txt"
  chmod 600 "$evidence_dir/wechat-draft-continuation-evidence.txt"
  completed=1
  log "activation completed runtime_commit=${RUNTIME_COMMIT} minimum_week_start=${MINIMUM_WEEK}"
}

main() {
  parse_args "$@"
  require_physical_continuation
  [[ $EUID -eq 0 ]] || die "continuation requires root"
  exec {release_lock_fd}>"$RELEASE_LOCK"
  flock --nonblock "$release_lock_fd" || die "release lock is busy"
  verify_disabled_preflight
  sleep 5
  verify_disabled_preflight
  run_activation
}

if [[ "${WECHAT_DRAFT_CONTINUATION_SOURCE_ONLY:-0}" != 1 ]]; then
  main "$@"
fi
