#!/usr/bin/env bash
# Single-use image/source hotfix after the reviewed 0042 migration and zero-effect rollback.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077
export LC_ALL=C

readonly HOTFIX_CURRENT_COMMIT="0c3d74d4baa7156b1fc56ea81f188aa25d5bc5d8"
readonly HOTFIX_CURRENT_IMAGE="sha256:7f025c7cefdf81588e20bdc97263493fd8d7e479d948c2be94d0b389a5bd4902"
readonly HOTFIX_CURRENT_REFERENCE="edu-ai-lead-agent-backend@${HOTFIX_CURRENT_IMAGE}"
readonly HOTFIX_CURRENT_SOURCE_SHA="8ff751ae46c97a654e10edf3095d13989bb27ffd467144f9ef504c85969493c4"
readonly HOTFIX_CURRENT_ENV_SHA="fd160771e46eb5ea32a44331b44e17f8732e7ecdcfa6d08a0e77cede828cec12"
readonly HOTFIX_CURRENT_RELEASE_ENV_SHA="fd560360b08fbad46abaf02816979d0a74b6f8719f7c4aec9a436ff52f8912fc"
readonly HOTFIX_TARGET_COMMIT="267ffddc3c13ac7c3c874e6902b5c09bdeaa0e1e"
readonly HOTFIX_TARGET_IMAGE="sha256:eabffa5565affc5b6da154329d9f94d85fd07d4bc72a8235c30c81b313c88bbf"
readonly HOTFIX_TARGET_TAG="edu-ai-lead-agent-backend:wechat-draft-267ffddc3c13"
readonly HOTFIX_MINIMUM_WEEK="2026-09-07"

hotfix_stage_dir=""
hotfix_release_stage=""
hotfix_operator_sha=""
hotfix_attempt_marker=""

hotfix_log() { printf '[wechat-draft-client-hotfix] %s\n' "$*" >&2; }
hotfix_die() { hotfix_log "ERROR: $*"; return 1; }

hotfix_parse_args() {
  while (($#)); do
    case "$1" in
      --stage-dir)
        (($# >= 2)) || hotfix_die "missing stage directory"
        hotfix_stage_dir=$2
        shift 2
        ;;
      *) hotfix_die "unknown argument" ;;
    esac
  done
  [[ "$hotfix_stage_dir" == /* && "$hotfix_stage_dir" != */ ]] \
    || hotfix_die "stage directory must be absolute"
  hotfix_release_stage="${hotfix_stage_dir}/release"
}

hotfix_require_physical_stage() {
  local actual expected stdin_target entries expected_entries
  actual=$(realpath -e -- "${BASH_SOURCE[0]}")
  expected=$(realpath -e -- "${hotfix_stage_dir}/wechat-draft-post-migration-client-hotfix.sh")
  [[ "$actual" == "$expected" && ! -L "$actual" \
      && "$(stat -c '%a:%u:%g' "$actual")" == 600:0:0 ]] \
    || hotfix_die "hotfix must run from the physical mode-0600 stage file"
  [[ "$(stat -c '%a:%u:%g' "$hotfix_stage_dir")" == 700:0:0 \
      && "$(stat -c '%a:%u:%g' "$hotfix_release_stage")" == 700:0:0 ]] \
    || hotfix_die "hotfix stage ownership or mode changed"
  [[ -f "${hotfix_stage_dir}/hotfix.sha256" \
      && ! -L "${hotfix_stage_dir}/hotfix.sha256" \
      && "$(stat -c '%a:%u:%g' "${hotfix_stage_dir}/hotfix.sha256")" == 600:0:0 ]] \
    || hotfix_die "hotfix checksum file changed"
  entries=$(find "$hotfix_stage_dir" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort)
  expected_entries=$(printf '%s\n' hotfix.sha256 release wechat-draft-post-migration-client-hotfix.sh | sort)
  [[ "$entries" == "$expected_entries" ]] || hotfix_die "hotfix stage members changed"
  (cd "$hotfix_stage_dir" && sha256sum -c hotfix.sha256 >/dev/null) \
    || hotfix_die "hotfix checksum failed"
  find "$hotfix_release_stage" -mindepth 1 -maxdepth 1 -type f \
    ! -perm 0600 -print -quit | grep -q . \
    && hotfix_die "release member mode changed"
  [[ -f "${hotfix_release_stage}/artifacts.sha256" ]] \
    || hotfix_die "release artifact manifest is absent"
  python3 "${hotfix_release_stage}/validate-wechat-draft-offline-artifacts.py" \
    "$hotfix_release_stage" >/dev/null
  hotfix_operator_sha=$(sha256sum "$actual" | awk '{print $1}')
  [[ "$hotfix_operator_sha" =~ ^[0-9a-f]{64}$ ]] || hotfix_die "hotfix identity is invalid"
  stdin_target=$(readlink "/proc/$$/fd/0" || true)
  [[ "$stdin_target" == /dev/null ]] || hotfix_die "hotfix stdin must be /dev/null"
}

hotfix_load_helpers() {
  export WECHAT_DRAFT_OPERATOR_SOURCE_ONLY=1
  # shellcheck source=wechat-draft-offline-release-operator.sh
  source "${hotfix_release_stage}/wechat-draft-offline-release-operator.sh"
  unset WECHAT_DRAFT_OPERATOR_SOURCE_ONLY
  stage_dir=$hotfix_release_stage
  metadata_json="${stage_dir}/release-metadata.json"
  production_baseline_json="${stage_dir}/production-baseline.json"
  release_commit=$(metadata_value release_commit)
  candidate_tag=$(metadata_value candidate_tag)
  candidate_id=$(metadata_value candidate_id)
  minimum_week=$HOTFIX_MINIMUM_WEEK
  [[ "$release_commit" == "$HOTFIX_TARGET_COMMIT" \
      && "$candidate_tag" == "$HOTFIX_TARGET_TAG" \
      && "$candidate_id" == "$HOTFIX_TARGET_IMAGE" ]] \
    || hotfix_die "release metadata differs from the reviewed hotfix"
}

hotfix_env_value() {
  local key=$1
  [[ "$key" =~ ^[A-Z][A-Z0-9_]*$ ]] || return 1
  awk -F= -v wanted="$key" \
    '$1 == wanted { value = substr($0, index($0, "=") + 1) } END { print value }' \
    "$PRIMARY_ENV"
}

hotfix_verify_current_services() {
  local service container state image restart_count health reference revision
  [[ -f "${APP_DIR}/.release-commit" && ! -L "${APP_DIR}/.release-commit" \
      && "$(<"${APP_DIR}/.release-commit")" == "$HOTFIX_CURRENT_COMMIT" ]] || return 1
  reference=$(awk -F= '$1 == "APP_IMAGE" { value = substr($0, index($0, "=") + 1) } END { print value }' \
    "$RELEASE_ENV") || return 1
  [[ "$reference" == "$HOTFIX_CURRENT_REFERENCE" \
      && "$(docker image inspect --format '{{.Id}}' "$reference")" == "$HOTFIX_CURRENT_IMAGE" ]] \
    || return 1
  revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
    "$reference") || return 1
  [[ "$revision" == "$HOTFIX_CURRENT_COMMIT" ]] || return 1
  for service in "${APP_SERVICES[@]}"; do
    container=$(compose ps -q "$service") || return 1
    [[ -n "$container" ]] || return 1
    state=$(docker inspect --format '{{.State.Status}}' "$container") || return 1
    image=$(docker inspect --format '{{.Image}}' "$container") || return 1
    restart_count=$(docker inspect --format '{{.RestartCount}}' "$container") || return 1
    [[ "$state" == running && "$image" == "$HOTFIX_CURRENT_IMAGE" && "$restart_count" == 0 ]] \
      || return 1
    if [[ "$service" == acquisition-api ]]; then
      health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' \
        "$container") || return 1
      [[ "$health" == healthy ]] || return 1
    fi
  done
  for service in postgres minio; do
    container=$(compose ps -q "$service") || return 1
    [[ -n "$container" ]] || return 1
    state=$(docker inspect --format '{{.State.Status}}' "$container") || return 1
    restart_count=$(docker inspect --format '{{.RestartCount}}' "$container") || return 1
    health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' \
      "$container") || return 1
    [[ "$state" == running && "$restart_count" == 0 && "$health" == healthy ]] || return 1
  done
}

hotfix_verify_empty_volume() {
  local volume=$1
  docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint sh \
    --mount "type=volume,src=${volume},dst=/data,readonly" "$HOTFIX_CURRENT_REFERENCE" \
    -c 'test -d /data && test -z "$(find /data -mindepth 1 -print -quit)"' </dev/null >/dev/null
}

hotfix_verify_disabled_preflight() {
  local key value worker head volume logical labels
  [[ -f "$PRIMARY_ENV" && ! -L "$PRIMARY_ENV" \
      && "$(stat -c '%a' "$PRIMARY_ENV")" == 600 ]] \
    || hotfix_die "primary environment is not a physical mode-0600 file"
  [[ -f "$RELEASE_ENV" && ! -L "$RELEASE_ENV" \
      && "$(stat -c '%a' "$RELEASE_ENV")" == 600 ]] \
    || hotfix_die "release environment is not a physical mode-0600 file"
  [[ "$(sha256sum "$PRIMARY_ENV" | awk '{print $1}')" == "$HOTFIX_CURRENT_ENV_SHA" \
      && "$(sha256sum "$RELEASE_ENV" | awk '{print $1}')" == "$HOTFIX_CURRENT_RELEASE_ENV_SHA" ]] \
    || hotfix_die "production environment changed after incident review"
  [[ "$(source_tree_fingerprint)" == "$HOTFIX_CURRENT_SOURCE_SHA" ]] \
    || hotfix_die "production source changed after incident review"
  [[ "$(hotfix_env_value WECHAT_MP_MODE)" =~ ^(draft_only)?$ ]] \
    || hotfix_die "WeChat mode is not draft-only"
  [[ "$(hotfix_env_value WECHAT_MP_DRAFT_MIN_WEEK_START)" == "$HOTFIX_MINIMUM_WEEK" ]] \
    || hotfix_die "minimum week changed after incident review"
  for key in WECHAT_MP_ENABLED WECHAT_MP_DRAFT_WORKER_ENABLED \
    WECHAT_MP_DRAFT_AUTO_ENQUEUE_ENABLED WECHAT_MP_DRAFT_PRODUCTION_ENABLED; do
    value=$(hotfix_env_value "$key") || return 1
    [[ "${value,,}" == false ]] || hotfix_die "draft flag is not disabled: $key"
  done
  for key in WECHAT_MP_APP_ID WECHAT_MP_APP_SECRET; do
    value=$(hotfix_env_value "$key") || return 1
    [[ -n "$value" && "$value" != *[[:space:]]* ]] \
      || hotfix_die "required WeChat credential is absent"
  done
  head=$(compose exec -T postgres sh -c \
    'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT version_num FROM alembic_version"') \
    || return 1
  [[ "$head" == "$EXPECTED_HEAD" ]] || hotfix_die "database head changed after incident review"
  hotfix_verify_current_services || hotfix_die "current candidate core is not healthy"
  [[ "$(safe_job_counts)" == 0:0:0 ]] || hotfix_die "existing WeChat draft work is not zero"
  worker=$(compose_with_draft ps --all --quiet wechat-official-account-draft-worker)
  [[ -z "$worker" ]] || hotfix_die "draft worker already exists"
  for logical in official_account_weekly_dag_output wechat_mp_draft_artifacts; do
    volume="${COMPOSE_PROJECT}_${logical}"
    labels=$(docker volume inspect --format '{{json .Labels}}' "$volume") || return 1
    [[ "$labels" == *"\"com.docker.compose.project\":\"${COMPOSE_PROJECT}\""* \
        && "$labels" == *"\"com.docker.compose.volume\":\"${logical}\""* ]] \
      || hotfix_die "draft volume labels changed: $logical"
    hotfix_verify_empty_volume "$volume" || hotfix_die "draft volume is not empty: $logical"
  done
  hotfix_attempt_marker="${ATTEMPT_ROOT}/wechat-draft-client-hotfix-${hotfix_operator_sha}.attempted"
  [[ ! -e "$hotfix_attempt_marker" && ! -L "$hotfix_attempt_marker" ]] \
    || hotfix_die "hotfix identity already has an attempt marker"
}

hotfix_probe_candidate_settings() {
  docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --env-file "$PRIMARY_ENV" \
    -e WECHAT_MP_ENABLED=true \
    -e WECHAT_MP_DRAFT_WORKER_ENABLED=true \
    -e WECHAT_MP_DRAFT_AUTO_ENQUEUE_ENABLED=true \
    -e WECHAT_MP_DRAFT_PRODUCTION_ENABLED=true \
    -e WECHAT_MP_DRAFT_MIN_WEEK_START="$HOTFIX_MINIMUM_WEEK" \
    --entrypoint python "$candidate_tag" -c \
    'import asyncio; from app.core.config import Settings; from app.infrastructure.wechat_official_account.client import WeChatOfficialAccountHttpClient; settings=Settings(_env_file=None); client=WeChatOfficialAccountHttpClient(settings); asyncio.run(client.aclose())' \
    </dev/null >/dev/null
}

hotfix_prepare_attempt() {
  install -d -o root -g root -m 700 "$ATTEMPT_ROOT" "$BACKUP_ROOT" || return 1
  (set -o noclobber; printf 'attempted_at=%s\n' "$(date -u +%FT%TZ)" >"$hotfix_attempt_marker") \
    || hotfix_die "hotfix attempt marker collision"
  chmod 600 "$hotfix_attempt_marker" || return 1
  backup_dir="${BACKUP_ROOT}/wechat-draft-client-hotfix-${hotfix_operator_sha:0:12}-$(date -u +%Y%m%dT%H%M%SZ)"
  install -d -o root -g root -m 700 "$backup_dir" || return 1
  cp -a "$PRIMARY_ENV" "$backup_dir/env.before" || return 1
  cp -a "$RELEASE_ENV" "$backup_dir/release.env.before" || return 1
  : >"$backup_dir/release-env-existed"
}

hotfix_verify_previous_application_services() {
  local service container state image restart_count health
  for service in "${APP_SERVICES[@]}"; do
    container=$(compose ps -q "$service") || return 1
    [[ -n "$container" ]] || return 1
    state=$(docker inspect --format '{{.State.Status}}' "$container") || return 1
    image=$(docker inspect --format '{{.Image}}' "$container") || return 1
    restart_count=$(docker inspect --format '{{.RestartCount}}' "$container") || return 1
    [[ "$state" == running && "$image" == "$HOTFIX_CURRENT_IMAGE" && "$restart_count" == 0 ]] \
      || return 1
    if [[ "$service" == acquisition-api ]]; then
      health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' \
        "$container") || return 1
      [[ "$health" == healthy ]] || return 1
    fi
  done
}

hotfix_recover_previous_application_services() {
  local deadline
  compose up -d --no-build --no-deps "${APP_SERVICES[@]}" >/dev/null || return 1
  deadline=$(( $(date +%s) + 60 )) || return 1
  until hotfix_verify_previous_application_services; do
    (( $(date +%s) < deadline )) || return 1
    sleep 2
  done
}

hotfix_capture_worker_diagnostic() {
  local worker
  [[ -n "$backup_dir" && -d "$backup_dir" ]] || return 0
  worker=$(compose_with_draft ps --all --quiet wechat-official-account-draft-worker) || return 0
  [[ -n "$worker" ]] || return 0
  {
    printf 'state=%s\n' "$(docker inspect --format '{{.State.Status}}' "$worker" 2>/dev/null || printf unknown)"
    printf 'restart_count=%s\n' "$(docker inspect --format '{{.RestartCount}}' "$worker" 2>/dev/null || printf unknown)"
    docker logs --tail 100 "$worker" 2>&1 | python3 -c '
import json
import sys
for raw in sys.stdin:
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        print("log=unparsed")
        continue
    safe = {key: payload[key] for key in ("ok", "event", "error_code") if key in payload}
    print(json.dumps(safe or {"structured": True}, sort_keys=True))
'
  } >"$backup_dir/worker-diagnostic.txt" || return 1
  chmod 600 "$backup_dir/worker-diagnostic.txt" || return 1
}

hotfix_verify_worker() {
  local worker state image restart_count
  worker=$(compose_with_draft ps -q wechat-official-account-draft-worker) || return 1
  [[ -n "$worker" ]] || return 1
  state=$(docker inspect --format '{{.State.Status}}' "$worker") || return 1
  image=$(docker inspect --format '{{.Image}}' "$worker") || return 1
  restart_count=$(docker inspect --format '{{.RestartCount}}' "$worker") || return 1
  [[ "$state" == running && "$image" == "$candidate_id" && "$restart_count" == 0 ]] \
    || return 1
}

hotfix_wait_for_worker() {
  local deadline
  deadline=$(( $(date +%s) + 60 )) || return 1
  until hotfix_verify_worker; do
    (( $(date +%s) < deadline )) || return 1
    sleep 2
  done
}

hotfix_on_exit() {
  local rc=$?
  ((rc != 0 && completed == 0 && recovery_armed == 1)) || return 0
  hotfix_log "activation failed; preserving safe diagnostics and restoring the previous runtime"
  hotfix_capture_worker_diagnostic || true
  compose_with_draft stop -t 30 wechat-official-account-draft-worker >/dev/null 2>&1 || true
  compose_with_draft rm -f wechat-official-account-draft-worker >/dev/null 2>&1 || true
  disable_draft_flags || true
  if [[ "$(safe_job_counts 2>/dev/null || true)" == 0:0:0 ]] \
      && restore_before_migration \
      && hotfix_recover_previous_application_services; then
    hotfix_log "previous runtime restored with zero draft effects"
    return 0
  fi
  hotfix_log "automatic recovery could not prove the previous runtime; stopping application writers"
  compose stop -t 30 "${STOP_ORDER[@]}" >/dev/null 2>&1 || true
}

hotfix_run_activation() {
  local worker
  workspace=$(mktemp -d /tmp/edu-ai-wechat-draft-client-hotfix.XXXXXX)
  trap 'hotfix_on_exit; [[ -z "${workspace:-}" ]] || find "$workspace" -depth -delete' EXIT
  hotfix_prepare_attempt
  quiesce_and_backup
  disable_draft_flags
  write_release_env
  activate_source
  validate_installed_source_modes
  [[ "$(compose exec -T postgres sh -c \
    'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT version_num FROM alembic_version"')" \
      == "$EXPECTED_HEAD" ]] || hotfix_die "database head changed during hotfix"
  compose up -d --no-build --no-deps "${APP_SERVICES[@]}"
  wait_for_candidate_application_services \
    || hotfix_die "candidate core did not become ready within the bounded window"
  verify_candidate_application_services || hotfix_die "candidate core did not converge"
  [[ "$(safe_job_counts)" == 0:0:0 ]] || hotfix_die "candidate core created draft work"
  enable_draft_flags
  compose_with_draft up -d --no-build --no-deps wechat-official-account-draft-worker
  hotfix_wait_for_worker || hotfix_die "draft worker did not become ready"
  [[ "$(safe_job_counts)" == 0:0:0 ]] || hotfix_die "draft worker created work during startup"
  sleep 30
  verify_candidate_application_services || hotfix_die "candidate core drifted during stability"
  hotfix_verify_worker || hotfix_die "draft worker drifted during stability"
  [[ "$(safe_job_counts)" == 0:0:0 ]] || hotfix_die "stable activation created draft work"
  worker=$(compose_with_draft ps -q wechat-official-account-draft-worker)
  ! docker logs --tail 100 "$worker" 2>&1 | grep -Fq '"ok": false' \
    || hotfix_die "draft worker emitted a failed idle-cycle result"
  {
    printf 'schema_version=1\nsource_commit=%s\ncandidate_id=%s\n' \
      "$release_commit" "$candidate_id"
    printf 'alembic_head=%s\nminimum_week_start=%s\n' "$EXPECTED_HEAD" "$minimum_week"
    printf 'draft_jobs=0\ndraft_items=0\ndraft_attempts=0\nprovider_writes=0\n'
    printf 'worker_restart_count=0\ncompleted_at=%s\n' "$(date -u +%FT%TZ)"
  } >"$backup_dir/wechat-draft-client-hotfix-evidence.txt"
  chmod 600 "$backup_dir/wechat-draft-client-hotfix-evidence.txt"
  completed=1
  hotfix_log "activation completed source_commit=${release_commit} minimum_week_start=${minimum_week}"
}

hotfix_main() {
  hotfix_parse_args "$@"
  [[ $EUID -eq 0 ]] || hotfix_die "hotfix requires root"
  hotfix_require_physical_stage
  hotfix_load_helpers
  load_and_verify_image
  hotfix_probe_candidate_settings
  hotfix_verify_disabled_preflight
  sleep 5
  hotfix_verify_disabled_preflight
  exec {release_lock_fd}>"$RELEASE_LOCK"
  flock --nonblock "$release_lock_fd" || hotfix_die "release lock is busy"
  hotfix_verify_disabled_preflight
  hotfix_run_activation
}

if [[ "${WECHAT_DRAFT_CLIENT_HOTFIX_SOURCE_ONLY:-0}" != 1 ]]; then
  hotfix_main "$@"
fi
