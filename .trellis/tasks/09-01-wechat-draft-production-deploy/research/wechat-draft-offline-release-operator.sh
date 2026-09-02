#!/usr/bin/env bash
# Single-use production operator for the task-local checksum-bound WeChat draft release.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077
export LC_ALL=C

operator_app_dir="/opt/edu-ai-lead-agent"
if [[ "${WECHAT_DRAFT_OPERATOR_SOURCE_ONLY:-0}" == 1 && -n "${WECHAT_DRAFT_OPERATOR_TEST_APP_DIR:-}" ]]; then
  operator_app_dir=$WECHAT_DRAFT_OPERATOR_TEST_APP_DIR
fi
readonly APP_DIR="$operator_app_dir"
unset operator_app_dir
readonly COMPOSE_PROJECT="edu-ai-lead-agent"
readonly PRIMARY_ENV="${APP_DIR}/.env"
readonly RELEASE_ENV="${APP_DIR}/.release.env"
readonly BACKUP_ROOT="/var/backups/edu-ai/releases"
readonly ATTEMPT_ROOT="/var/lib/edu-ai-release-attempts"
readonly RELEASE_LOCK="/var/lock/edu-ai-wechat-draft-release.lock"
readonly EXPECTED_HEAD="20260901_0042"
readonly -a PROFILES=(
  --profile governance --profile content --profile wecom --profile ip-assets
  --profile official-account-weekly-dag
)
readonly -a APP_SERVICES=(
  acquisition-api acquisition-scheduler acquisition-worker
  governance-scheduler governance-worker content-scheduler content-worker wecom-dispatcher
)
readonly -a ALL_SERVICES=(postgres minio "${APP_SERVICES[@]}")
readonly -a STOP_ORDER=(
  wecom-dispatcher content-worker content-scheduler governance-worker governance-scheduler
  acquisition-worker acquisition-scheduler acquisition-api
)
readonly -a MANAGED_DIRS=(backend deploy infra scripts)
readonly -a MANAGED_FILES=(
  compose.yaml .env.example .gitattributes .gitignore AGENTS.md Makefile README.md environment.yml
)

stage_dir=""
scheduler_safe_until=""
preflight_only=0
metadata_json=""
production_baseline_json=""
release_commit=""
candidate_tag=""
candidate_id=""
candidate_reference=""
minimum_week=""
backup_dir=""
workspace=""
attempt_marker=""
source_activated=0
migrated=0
completed=0
weekly_candidate_count=0
recovery_armed=0
core_verified=0

log() { printf '[wechat-draft-release] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; return 1; }

usage() {
  printf '%s\n' \
    'Usage: wechat-draft-offline-release-operator.sh --stage-dir ABSOLUTE_MODE_0700_DIR --scheduler-safe-until-utc YYYY-MM-DDTHH:MM:SSZ [--preflight-only]' >&2
}

parse_args() {
  while (($#)); do
    case "$1" in
      --stage-dir) (($# >= 2)) || die "missing stage directory"; stage_dir=$2; shift 2 ;;
      --scheduler-safe-until-utc) (($# >= 2)) || die "missing scheduler boundary"; scheduler_safe_until=$2; shift 2 ;;
      --preflight-only) preflight_only=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown argument" ;;
    esac
  done
  [[ "$stage_dir" == /* && "$stage_dir" != */ ]] || die "stage directory must be absolute"
  [[ "$scheduler_safe_until" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] \
    || die "scheduler boundary is invalid"
}

compose() {
  docker compose --project-name "$COMPOSE_PROJECT" --project-directory "$APP_DIR" \
    --env-file "$PRIMARY_ENV" --env-file "$RELEASE_ENV" "${PROFILES[@]}" "$@"
}

compose_with_draft() {
  compose --profile wechat-official-account-draft "$@"
}

metadata_value() {
  python3 - "$metadata_json" "$1" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_bytes())
value = payload[sys.argv[2]]
if not isinstance(value, str):
    raise SystemExit(1)
print(value)
PY
}

baseline_value() {
  python3 - "$production_baseline_json" "$1" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_bytes())
value = payload[sys.argv[2]]
if isinstance(value, list):
    print("\n".join(value))
elif isinstance(value, str):
    print(value)
else:
    raise SystemExit(1)
PY
}

baseline_restart_count() {
  python3 - "$production_baseline_json" "$1" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_bytes())
value = payload["restart_counts"][sys.argv[2]]
if isinstance(value, bool) or not isinstance(value, int) or value < 0:
    raise SystemExit(1)
print(value)
PY
}

validate_bound_release_image() {
  local expected_image=$1 reference repo_digests observed_image
  reference=$(awk -F= '$1 == "APP_IMAGE" { value = substr($0, index($0, "=") + 1) } END { print value }' \
    "$RELEASE_ENV") || return 1
  [[ "$reference" =~ ^[^@[:space:]]+@sha256:[0-9a-f]{64}$ ]] \
    || die "bound release image is not an immutable digest"
  repo_digests=$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' \
    "$expected_image") || return 1
  grep -Fxq "$reference" <<<"$repo_digests" \
    || die "bound release image is not attached to the running image"
  observed_image=$(docker image inspect --format '{{.Id}}' "$reference") || return 1
  [[ "$observed_image" == "$expected_image" ]] \
    || die "bound release image resolves to a different image"
}

require_physical_operator() {
  local actual expected mode stdin_target
  actual=$(realpath -e -- "${BASH_SOURCE[0]}")
  expected=$(realpath -e -- "${stage_dir}/wechat-draft-offline-release-operator.sh")
  [[ "$actual" == "$expected" && ! -L "$actual" ]] || die "operator must run from the physical stage file"
  mode=$(stat -c '%a' "$actual")
  [[ "$mode" == 600 ]] || die "operator must be mode 0600"
  stdin_target=$(readlink "/proc/$$/fd/0" || true)
  [[ "$stdin_target" == "/dev/null" ]] || die "operator stdin must be /dev/null"
}

validate_stage() {
  [[ -x /usr/bin/python3 || -x /bin/python3 ]] || die "system Python is unavailable"
  python3 "${stage_dir}/validate-wechat-draft-offline-artifacts.py" "$stage_dir" >/dev/null
  metadata_json="${stage_dir}/release-metadata.json"
  production_baseline_json="${stage_dir}/production-baseline.json"
  release_commit=$(metadata_value release_commit)
  candidate_tag=$(metadata_value candidate_tag)
  candidate_id=$(metadata_value candidate_id)
  [[ "$release_commit" =~ ^[0-9a-f]{40}$ ]] || die "release commit is invalid"
  [[ "$candidate_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "candidate image ID is invalid"
}

source_tree_fingerprint() {
  python3 - "$APP_DIR" "${MANAGED_DIRS[@]}" -- "${MANAGED_FILES[@]}" <<'PY'
import hashlib
import pathlib
import stat
import sys

root = pathlib.Path(sys.argv[1]).resolve(strict=True)
separator = sys.argv.index("--")
names = sys.argv[2:separator] + sys.argv[separator + 1:]
rows = []
for name in names:
    target = root / name
    if not target.exists() or target.is_symlink():
        raise SystemExit("managed source path is absent or symlinked")
    paths = [target, *sorted(target.rglob("*"))] if target.is_dir() else [target]
    for path in paths:
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            raise SystemExit("managed source contains an unsafe member")
        relative = path.relative_to(root).as_posix()
        if path.is_file():
            value = hashlib.sha256(path.read_bytes()).hexdigest()
            rows.append(
                f"f\t{mode:04o}\t{metadata.st_uid}\t{metadata.st_gid}\t{value}\t{relative}\n"
            )
        else:
            rows.append(
                f"d\t{mode:04o}\t{metadata.st_uid}\t{metadata.st_gid}\t-\t{relative}\n"
            )
payload = "".join(sorted(rows)).encode()
print(hashlib.sha256(payload).hexdigest())
PY
}

validate_installed_source_modes() {
  python3 - "$APP_DIR" "${MANAGED_DIRS[@]}" -- "${MANAGED_FILES[@]}" <<'PY'
import pathlib
import stat
import sys

root = pathlib.Path(sys.argv[1]).resolve(strict=True)
separator = sys.argv.index("--")
names = sys.argv[2:separator] + sys.argv[separator + 1:]
for name in names:
    target = root / name
    if not target.exists() or target.is_symlink():
        raise SystemExit("installed source path is absent or symlinked")
    paths = [target, *sorted(target.rglob("*"))] if target.is_dir() else [target]
    for path in paths:
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            raise SystemExit("installed source contains an unsafe member")
        if metadata.st_uid != 0 or metadata.st_gid != 0:
            raise SystemExit("installed source must be root-owned")
        if path.is_dir() and mode != 0o700:
            raise SystemExit("installed source directory mode drifted")
        if path.is_file() and mode not in {0o600, 0o700}:
            raise SystemExit("installed source file mode drifted")
PY
}

preflight_production_baseline() {
  local expected_head expected_image expected_revision expected_source expected_env
  local expected_release_env actual_services service container image revision
  expected_head=$(baseline_value current_alembic_head)
  expected_image=$(baseline_value current_image_id)
  expected_revision=$(baseline_value current_image_revision)
  expected_source=$(baseline_value source_tree_sha256)
  expected_env=$(baseline_value env_sha256)
  expected_release_env=$(baseline_value release_env_sha256)
  [[ "$expected_head" == 20260825_0036 ]] || die "reviewed previous Alembic head changed"
  validate_bound_release_image "$expected_image" \
    || die "bound release image validation failed"
  [[ "$(compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT version_num FROM alembic_version"')" == "$expected_head" ]] \
    || die "production Alembic head differs from the bound baseline"
  [[ "$(sha256sum "$PRIMARY_ENV" | awk '{print $1}')" == "$expected_env" ]] \
    || die "primary environment differs from the bound baseline"
  [[ "$(sha256sum "$RELEASE_ENV" | awk '{print $1}')" == "$expected_release_env" ]] \
    || die "release environment differs from the bound baseline"
  [[ "$(source_tree_fingerprint)" == "$expected_source" ]] \
    || die "production source differs from the bound baseline"
  actual_services=$(compose ps --services --status running | sort)
  [[ "$actual_services" == "$(baseline_value running_services)" ]] \
    || die "running service set differs from the bound baseline"
  for service in "${ALL_SERVICES[@]}"; do
    container=$(compose ps -q "$service")
    [[ -n "$container" ]] || die "baseline service is absent: $service"
    [[ "$(docker inspect --format '{{.RestartCount}}' "$container")" == \
      "$(baseline_restart_count "$service")" ]] || die "baseline restart count differs: $service"
    if [[ "$service" != postgres && "$service" != minio ]]; then
      image=$(docker inspect --format '{{.Image}}' "$container")
      [[ "$image" == "$expected_image" ]] || die "running application image differs: $service"
    fi
  done
  revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$expected_image")
  [[ "$revision" == "$expected_revision" ]] || die "running image revision differs from baseline"
}

require_scheduler_window() {
  python3 - "$scheduler_safe_until" <<'PY'
from datetime import UTC, datetime, timedelta
import sys

boundary = datetime.strptime(sys.argv[1], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
if boundary <= datetime.now(UTC) + timedelta(minutes=15):
    raise SystemExit("scheduler boundary leaves less than 15 minutes")
PY
}

derive_minimum_week() {
  minimum_week=$(TZ=Asia/Shanghai python3 - <<'PY'
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
days = 7 - today.weekday()
print((today + timedelta(days=days)).isoformat())
PY
  )
  [[ "$minimum_week" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || die "minimum week derivation failed"
}

load_and_verify_image() {
  local candidate_repository repo_digests
  gzip -dc "${stage_dir}/backend-image.tar.gz" | docker image load >/dev/null
  [[ "$(docker image inspect --format '{{.Id}}' "$candidate_tag")" == "$candidate_id" ]] \
    || die "loaded image ID differs from metadata"
  [[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$candidate_tag")" == "$release_commit" ]] \
    || die "loaded image revision differs from metadata"
  docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint python "$candidate_tag" -c \
    'from app.core.config import Settings; s=Settings(_env_file=None); assert not s.wechat_mp_draft_worker_enabled and not s.wechat_mp_draft_production_enabled; import app.wechat_official_account_draft_main' \
    </dev/null >/dev/null
  candidate_repository=${candidate_tag%%:*}
  candidate_reference="${candidate_repository}@${candidate_id}"
  [[ "$candidate_reference" =~ ^[^@[:space:]]+@sha256:[0-9a-f]{64}$ ]] \
    || die "candidate immutable reference is invalid"
  repo_digests=$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$candidate_tag")
  grep -Fxq "$candidate_reference" <<<"$repo_digests" \
    || die "candidate immutable reference is absent after image load"
}

env_presence_preflight() {
  [[ -f "$PRIMARY_ENV" && ! -L "$PRIMARY_ENV" && "$(stat -c '%a' "$PRIMARY_ENV")" == 600 ]] \
    || die "primary environment must be a physical mode-0600 file"
  [[ -f "$APP_DIR/compose.yaml" ]] || die "production compose file is missing"
  python3 - "$PRIMARY_ENV" <<'PY'
import pathlib
import sys

rows = {}
for raw in pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if raw and not raw.lstrip().startswith("#") and "=" in raw:
        key, value = raw.split("=", 1)
        rows[key] = value
for key in ("WECHAT_MP_APP_ID", "WECHAT_MP_APP_SECRET"):
    value = rows.get(key, "")
    if not value.strip() or any(character.isspace() for character in value):
        raise SystemExit(f"required WeChat credential is absent: {key}")
PY
}

write_release_env() {
  local temporary
  [[ "$candidate_reference" =~ ^[^@[:space:]]+@sha256:[0-9a-f]{64}$ ]] \
    || die "candidate immutable reference is unavailable"
  temporary=$(mktemp "${APP_DIR}/.release.env.wechat.XXXXXX")
  printf 'APP_IMAGE=%s\n' "$candidate_reference" >"$temporary"
  chmod 600 "$temporary"
  install -o root -g root -m 600 "$temporary" "$RELEASE_ENV"
  rm -f "$temporary"
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
original = path.stat()
rows = path.read_text(encoding="utf-8").splitlines()
updates = dict(pairs)
updated = []
seen = set()
for row in rows:
    key = row.split("=", 1)[0] if "=" in row else ""
    if key in updates:
        if key not in seen:
            updated.append(f"{key}={updates[key]}")
            seen.add(key)
        continue
    updated.append(row)
for key, value in pairs:
    if key not in seen:
        updated.append(f"{key}={value}")
fd, name = tempfile.mkstemp(prefix=".env.wechat.", dir=path.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write("\n".join(updated) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(name, stat.S_IMODE(original.st_mode))
    os.chown(name, original.st_uid, original.st_gid)
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
    WECHAT_MP_DRAFT_MIN_WEEK_START "$minimum_week"
}

enable_draft_flags() {
  set_env_values \
    WECHAT_MP_DRAFT_MIN_WEEK_START "$minimum_week" \
    WECHAT_MP_DRAFT_PRODUCTION_ENABLED true \
    WECHAT_MP_ENABLED true \
    WECHAT_MP_DRAFT_WORKER_ENABLED true \
    WECHAT_MP_DRAFT_AUTO_ENQUEUE_ENABLED true
}

safe_job_counts() {
  compose exec -T postgres sh -c '
    table=$(psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc \
      "SELECT to_regclass('"'"'public.wechat_official_account_draft_jobs'"'"')")
    if [ -z "$table" ]; then
      printf "0:0:0\n"
    else
      psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc \
        "SELECT (SELECT count(*) FROM wechat_official_account_draft_jobs)::text || '"'"':'"'"' || (SELECT count(*) FROM wechat_official_account_draft_job_items)::text || '"'"':'"'"' || (SELECT count(*) FROM wechat_official_account_draft_attempts)::text"
    fi'
}

preflight_services() {
  local service container state health
  for service in postgres minio "${APP_SERVICES[@]}"; do
    container=$(compose ps -q "$service")
    [[ -n "$container" ]] || die "required service is absent: $service"
    state=$(docker inspect --format '{{.State.Status}}' "$container")
    [[ "$state" == running ]] || die "required service is not running: $service"
    if [[ "$service" == postgres || "$service" == minio || "$service" == acquisition-api ]]; then
      health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")
      [[ "$health" == healthy ]] || die "required service is not healthy: $service"
    fi
  done
  [[ "$(safe_job_counts)" == "0:0:0" ]] || die "existing WeChat draft work is not zero"
  local volume candidate_count
  volume="${COMPOSE_PROJECT}_official_account_weekly_dag_output"
  if docker volume inspect "$volume" >/dev/null 2>&1; then
    candidate_count=$(docker run --rm --network none --read-only --cap-drop ALL \
      --security-opt no-new-privileges:true --entrypoint sh \
      --mount "type=volume,src=${volume},dst=/input,readonly" "$candidate_tag" -c \
      'test -d /input && ! touch /input/.wechat-draft-write-probe 2>/dev/null && find /input -mindepth 1 -maxdepth 1 -name "official-account-weekly-edition-*" -print | wc -l')
  else
    # A first activation may legitimately precede the first weekly-DAG run. Read-only preflight
    # treats the absent volume as an empty inbox and does not create production state.
    candidate_count=0
  fi
  [[ "$candidate_count" =~ ^[0-9]+$ && "$candidate_count" -le 1000 ]] \
    || die "weekly candidate scan bound would be exceeded"
  weekly_candidate_count=$candidate_count
}

verify_candidate_application_services() {
  local service container state image restart_count health
  for service in "${APP_SERVICES[@]}"; do
    container=$(compose ps -q "$service")
    [[ -n "$container" ]] || return 1
    state=$(docker inspect --format '{{.State.Status}}' "$container")
    image=$(docker inspect --format '{{.Image}}' "$container")
    restart_count=$(docker inspect --format '{{.RestartCount}}' "$container")
    [[ "$state" == running && "$image" == "$candidate_id" && "$restart_count" == 0 ]] \
      || return 1
    if [[ "$service" == acquisition-api ]]; then
      health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")
      [[ "$health" == healthy ]] || return 1
    fi
  done
}

ensure_draft_volumes() {
  local logical volume observed
  for logical in official_account_weekly_dag_output wechat_mp_draft_artifacts; do
    volume="${COMPOSE_PROJECT}_${logical}"
    if ! docker volume inspect "$volume" >/dev/null 2>&1; then
      observed=$(docker volume create \
        --label "com.docker.compose.project=${COMPOSE_PROJECT}" \
        --label "com.docker.compose.volume=${logical}" \
        "$volume")
      [[ "$observed" == "$volume" ]] || die "created volume identity changed: $logical"
    fi
    [[ "$(docker volume inspect --format '{{.Name}}' "$volume")" == "$volume" ]] \
      || die "required draft volume is unavailable: $logical"
  done
}

prepare_attempt() {
  install -d -o root -g root -m 700 "$ATTEMPT_ROOT" "$BACKUP_ROOT"
  attempt_marker="${ATTEMPT_ROOT}/${release_commit}.attempted"
  [[ ! -e "$attempt_marker" && ! -L "$attempt_marker" ]] || die "candidate already has an attempt marker"
  ( set -o noclobber; printf 'attempted_at=%s\n' "$(date -u +%FT%TZ)" >"$attempt_marker" ) \
    || die "candidate attempt marker collision"
  chmod 600 "$attempt_marker"
  backup_dir="${BACKUP_ROOT}/wechat-draft-${release_commit:0:12}-$(date -u +%Y%m%dT%H%M%SZ)"
  install -d -o root -g root -m 700 "$backup_dir"
  cp -a "$PRIMARY_ENV" "$backup_dir/env.before"
  if [[ -f "$RELEASE_ENV" && ! -L "$RELEASE_ENV" ]]; then
    cp -a "$RELEASE_ENV" "$backup_dir/release.env.before"
    : >"$backup_dir/release-env-existed"
  fi
}

quiesce_and_backup() {
  compose_with_draft stop -t 90 wechat-official-account-draft-worker >/dev/null 2>&1 || true
  recovery_armed=1
  compose_with_draft rm -f wechat-official-account-draft-worker >/dev/null 2>&1 || true
  compose stop -t 90 "${STOP_ORDER[@]}"
  "${APP_DIR}/scripts/edu-ai-backup.sh" </dev/null
}

activate_source() {
  local candidate_root="$workspace/candidate" name
  install -d -m 700 "$workspace" "$candidate_root" "$backup_dir/source.before" "$backup_dir/root.before"
  : >"$backup_dir/dirs-backed-up"
  : >"$backup_dir/dirs-installed"
  : >"$backup_dir/root-existed"
  : >"$backup_dir/root-installed"
  tar -xzf "${stage_dir}/source.tar.gz" -C "$candidate_root" --no-same-owner --no-same-permissions
  if [[ -f "$APP_DIR/.release-commit" && ! -L "$APP_DIR/.release-commit" ]]; then
    cp -a "$APP_DIR/.release-commit" "$backup_dir/root.before/.release-commit"
    printf '%s\n' .release-commit >>"$backup_dir/root-existed"
  fi
  source_activated=1
  for name in "${MANAGED_DIRS[@]}"; do
    [[ -d "$candidate_root/$name" ]] || die "candidate source directory is missing: $name"
    if [[ -e "$APP_DIR/$name" || -L "$APP_DIR/$name" ]]; then
      printf '%s\n' "$name" >>"$backup_dir/dirs-backed-up"
      mv "$APP_DIR/$name" "$backup_dir/source.before/$name"
    fi
    printf '%s\n' "$name" >>"$backup_dir/dirs-installed"
    mv "$candidate_root/$name" "$APP_DIR/$name"
  done
  for name in "${MANAGED_FILES[@]}"; do
    [[ -f "$candidate_root/$name" && ! -L "$candidate_root/$name" ]] \
      || die "candidate root file is missing: $name"
    if [[ -e "$APP_DIR/$name" || -L "$APP_DIR/$name" ]]; then
      cp -a "$APP_DIR/$name" "$backup_dir/root.before/$name"
      printf '%s\n' "$name" >>"$backup_dir/root-existed"
    fi
    printf '%s\n' "$name" >>"$backup_dir/root-installed"
    install -m "$(stat -c '%a' "$candidate_root/$name")" "$candidate_root/$name" "$APP_DIR/$name"
  done
  printf '%s\n' .release-commit >>"$backup_dir/root-installed"
  printf '%s\n' "$release_commit" >"$APP_DIR/.release-commit"
  chmod 600 "$APP_DIR/.release-commit"
}

restore_before_migration() {
  local name
  if ((source_activated == 1)); then
    install -d -m 700 "$backup_dir/failed-candidate" || return 1
    for name in "${MANAGED_DIRS[@]}"; do
      if grep -Fxq "$name" "$backup_dir/dirs-installed" && [[ -e "$APP_DIR/$name" ]]; then
        mv "$APP_DIR/$name" "$backup_dir/failed-candidate/$name" || return 1
      fi
      if grep -Fxq "$name" "$backup_dir/dirs-backed-up"; then
        [[ ! -e "$backup_dir/source.before/$name" ]] \
          || mv "$backup_dir/source.before/$name" "$APP_DIR/$name" \
          || return 1
      fi
    done
    for name in "${MANAGED_FILES[@]}" .release-commit; do
      grep -Fxq "$name" "$backup_dir/root-installed" || continue
      if grep -Fxq "$name" "$backup_dir/root-existed"; then
        cp -a "$backup_dir/root.before/$name" "$APP_DIR/$name" || return 1
      elif [[ -f "$APP_DIR/$name" && ! -L "$APP_DIR/$name" ]]; then
        find "$APP_DIR/$name" -maxdepth 0 -type f -delete || return 1
      fi
    done
  fi
  cp -a "$backup_dir/env.before" "$PRIMARY_ENV" || return 1
  if [[ -e "$backup_dir/release-env-existed" ]]; then
    cp -a "$backup_dir/release.env.before" "$RELEASE_ENV" || return 1
  elif [[ -f "$RELEASE_ENV" && ! -L "$RELEASE_ENV" ]]; then
    find "$RELEASE_ENV" -maxdepth 0 -type f -delete || return 1
  fi
  source_activated=0
}

verify_previous_application_services() {
  local expected_image expected_restart service container state image restart_count health
  expected_image=$(baseline_value current_image_id) || return 1
  for service in "${APP_SERVICES[@]}"; do
    container=$(compose ps -q "$service") || return 1
    [[ -n "$container" ]] || return 1
    state=$(docker inspect --format '{{.State.Status}}' "$container") || return 1
    image=$(docker inspect --format '{{.Image}}' "$container") || return 1
    restart_count=$(docker inspect --format '{{.RestartCount}}' "$container") || return 1
    expected_restart=$(baseline_restart_count "$service") || return 1
    [[ "$state" == running && "$image" == "$expected_image" \
        && "$restart_count" == "$expected_restart" ]] || return 1
    if [[ "$service" == acquisition-api ]]; then
      health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container") \
        || return 1
      [[ "$health" == healthy ]] || return 1
    fi
  done
}

recover_previous_application_services() {
  local deadline
  compose up -d --no-build --no-deps "${APP_SERVICES[@]}" >/dev/null || return 1
  deadline=$(( $(date +%s) + 60 )) || return 1
  until verify_previous_application_services; do
    (( $(date +%s) < deadline )) || return 1
    sleep 2
  done
}

on_exit() {
  local rc=$?
  ((rc != 0 && completed == 0 && recovery_armed == 1)) || return 0
  if ((migrated == 0)); then
    log "failure before migration completion; restoring previous source/environment"
    if restore_before_migration && recover_previous_application_services; then
      log "previous application services restored and verified"
      return 0
    fi
    log "pre-migration recovery could not verify the previous application services"
  elif ((core_verified == 1)); then
    log "optional activation failure; proving zero effects before retaining verified core services"
    if compose_with_draft stop -t 30 wechat-official-account-draft-worker >/dev/null 2>&1 \
      && compose_with_draft rm -f wechat-official-account-draft-worker >/dev/null 2>&1 \
      && disable_draft_flags \
      && [[ "$(safe_job_counts)" == "0:0:0" ]] \
      && verify_candidate_application_services; then
      log "optional worker disabled with zero draft effects; verified core services retained"
      return 0
    fi
    log "optional recovery could not prove a zero-effect healthy core state"
  fi
  if ((migrated == 0)); then
    log "pre-migration recovery failed; stopping application writers for incident handling"
  else
    log "post-migration failure; stopping application writers for incident handling"
  fi
  compose_with_draft stop -t 30 wechat-official-account-draft-worker >/dev/null 2>&1 || true
  compose stop -t 30 "${STOP_ORDER[@]}" >/dev/null 2>&1 || true
}

run_activation() {
  workspace=$(mktemp -d /tmp/edu-ai-wechat-draft-release.XXXXXX)
  trap 'on_exit; [[ -z "${workspace:-}" ]] || find "$workspace" -depth -delete' EXIT
  prepare_attempt
  quiesce_and_backup
  disable_draft_flags
  write_release_env
  activate_source
  validate_installed_source_modes
  compose run --rm --no-deps backend-migrate
  # The previous application remains conservatively incompatible after this point.
  migrated=1
  [[ "$(compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT version_num FROM alembic_version"')" == "$EXPECTED_HEAD" ]] \
    || die "database head differs after migration"
  compose up -d --no-build --no-deps "${APP_SERVICES[@]}"
  sleep 5
  preflight_services
  verify_candidate_application_services \
    || die "ordinary application services did not converge on the candidate"
  core_verified=1
  ensure_draft_volumes
  enable_draft_flags
  compose_with_draft up -d --no-build --no-deps wechat-official-account-draft-worker
  sleep 5
  [[ "$(safe_job_counts)" == "0:0:0" ]] || die "activation created draft work"
  local worker restart_count
  worker=$(compose_with_draft ps -q wechat-official-account-draft-worker)
  [[ -n "$worker" && "$(docker inspect --format '{{.State.Status}}' "$worker")" == running ]] \
    || die "optional WeChat draft worker is not running"
  restart_count=$(docker inspect --format '{{.RestartCount}}' "$worker")
  [[ "$restart_count" == 0 ]] || die "optional WeChat draft worker restarted"
  if ((weekly_candidate_count > 0)); then
    docker logs "$worker" 2>&1 | grep -Fq 'wechat_mp_draft_before_activation' \
      || die "historical weekly aggregates did not produce the typed skip"
  fi
  local service container
  for service in "${APP_SERVICES[@]}"; do
    container=$(compose ps -q "$service")
    [[ -n "$container" && "$(docker inspect --format '{{.RestartCount}}' "$container")" == 0 ]] \
      || die "ordinary application service restarted after activation: $service"
  done
  sleep 30
  preflight_services
  verify_candidate_application_services \
    || die "ordinary application services drifted during stable activation"
  worker=$(compose_with_draft ps -q wechat-official-account-draft-worker)
  [[ -n "$worker" \
      && "$(docker inspect --format '{{.State.Status}}' "$worker")" == running \
      && "$(docker inspect --format '{{.RestartCount}}' "$worker")" == 0 ]] \
    || die "optional WeChat draft worker drifted during stable activation"
  {
    printf 'schema_version=1\nrelease_commit=%s\ncandidate_id=%s\n' "$release_commit" "$candidate_id"
    printf 'alembic_head=%s\nminimum_week_start=%s\n' "$EXPECTED_HEAD" "$minimum_week"
    printf 'draft_jobs=0\ndraft_items=0\ndraft_attempts=0\nprovider_writes=0\n'
    printf 'worker_restart_count=0\ncompleted_at=%s\n' "$(date -u +%FT%TZ)"
  } >"$backup_dir/wechat-draft-activation-evidence.txt"
  chmod 600 "$backup_dir/wechat-draft-activation-evidence.txt"
  completed=1
  log "activation completed release_commit=${release_commit} minimum_week_start=${minimum_week}"
}

main() {
  parse_args "$@"
  require_physical_operator
  validate_stage
  require_scheduler_window
  derive_minimum_week
  env_presence_preflight
  [[ -f "$RELEASE_ENV" && ! -L "$RELEASE_ENV" && "$(stat -c '%a' "$RELEASE_ENV")" == 600 ]] \
    || die "release environment must be a physical mode-0600 file"
  preflight_production_baseline
  load_and_verify_image
  preflight_services
  sleep 5
  preflight_services
  if ((preflight_only == 1)); then
    log "preflight completed release_commit=${release_commit} minimum_week_start=${minimum_week}"
    return 0
  fi
  [[ $EUID -eq 0 ]] || die "activation requires root"
  exec {release_lock_fd}>"$RELEASE_LOCK"
  flock --nonblock "$release_lock_fd" || die "release lock is busy"
  run_activation
}

if [[ "${WECHAT_DRAFT_OPERATOR_SOURCE_ONLY:-0}" != 1 ]]; then
  main "$@"
fi
