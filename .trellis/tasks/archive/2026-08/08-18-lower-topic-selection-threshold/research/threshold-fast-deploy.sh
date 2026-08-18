#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
export LC_ALL=C
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

readonly APP_DIR=/opt/edu-ai-lead-agent
readonly BACKUP_ROOT=/var/backups/edu-ai/releases
readonly PREVIOUS_COMMIT=5d0a4caca97cc61edd201e26bf99f038500f107a
readonly PREVIOUS_SHORT=5d0a4ca
readonly PREVIOUS_ID=sha256:886e6e212bfe2a6a21c3a2bd5826b7283f5d5fb76c2949201861d15892fa8f99
readonly TARGET_COMMIT=572636aa6cca973676abfe99ee7e7e0b4d997c59
readonly TARGET_SHORT=572636a
readonly CANDIDATE_TAG=edu-ai-lead-agent-backend:threshold-572636aa6cca
readonly CANDIDATE_ID=sha256:d0bc989463989c0d040f7b17d5d583f1369a59e105622db7911eac380ab7a992
readonly PREVIOUS_SCORING=scoring-v1-preview.7-delivered-repeat-history
readonly TARGET_SCORING=scoring-v1-preview.8-threshold-059
readonly RELEASE_ID="$(date -u +%Y%m%dT%H%M%SZ)-threshold-059"
readonly BACKUP_DIR="${BACKUP_ROOT}/${RELEASE_ID}"
readonly STAGE=${1:-}

readonly -a START_ORDER=(
  acquisition-api acquisition-scheduler acquisition-worker governance-scheduler
  governance-worker content-scheduler content-worker wecom-dispatcher
)
readonly -a STOP_ORDER=(
  wecom-dispatcher content-worker content-scheduler governance-worker
  governance-scheduler acquisition-worker acquisition-scheduler acquisition-api
)
readonly -a ACTIVE_TAGS=(
  edu-ai-lead-agent-backend:local
  edu-ai-lead-agent-acquisition-api:latest
  edu-ai-lead-agent-acquisition-scheduler:latest
  edu-ai-lead-agent-acquisition-worker:latest
  edu-ai-lead-agent-backend-migrate:latest
  edu-ai-lead-agent-governance-scheduler:latest
  edu-ai-lead-agent-governance-worker:latest
  edu-ai-lead-agent-content-scheduler:latest
  edu-ai-lead-agent-content-worker:latest
  edu-ai-lead-agent-wecom-dispatcher:latest
)
readonly -a DELTA_PATHS=(
  .env.example
  backend/app/application/services/topic_selection.py
  backend/app/core/config.py
  backend/app/domain/topic_selection.py
  backend/tests/integration/test_topic_selection_api.py
  backend/tests/unit/test_topic_selection.py
  backend/tests/unit/test_topic_selection_delivery.py
  compose.yaml
)

mutated=0
completed=0
recovering=0
before_vector=""

fail() { printf 'ERROR: %s\n' "$*" >&2; return 1; }

sql_scalar() { edu_ai_psql_scalar "$1"; }

work_vector() {
  sql_scalar "SELECT concat_ws(':',(SELECT count(*) FROM acquisition_runs),(SELECT count(*) FROM acquisition_jobs),(SELECT count(*) FROM governance_runs),(SELECT count(*) FROM governance_jobs),(SELECT count(*) FROM content_slot_runs),(SELECT count(*) FROM content_slot_selections),(SELECT count(*) FROM copy_generation_runs),(SELECT count(*) FROM image_artifacts),(SELECT coalesce(sum(attempt_count),0) FROM image_artifacts),(SELECT count(*) FROM material_packages),(SELECT count(*) FROM model_invocations),(SELECT count(*) FROM wecom_delivery_jobs),(SELECT count(*) FROM wecom_delivery_attempts));"
}

assert_zero_current_work() {
  local observed
  observed=$(sql_scalar "SELECT concat_ws(':',(SELECT count(*) FROM acquisition_jobs WHERE status IN ('queued','running','retry_scheduled')),(SELECT count(*) FROM governance_jobs WHERE status IN ('queued','running','retry_scheduled')),(SELECT count(*) FROM content_slot_jobs WHERE status IN ('queued','running')),(SELECT count(*) FROM copy_generation_runs WHERE business_date=current_date AND status IN ('queued','running')),(SELECT count(*) FROM image_artifacts WHERE status IN ('queued','running')),(SELECT count(*) FROM material_packages WHERE status='queued'),(SELECT count(*) FROM wecom_delivery_jobs WHERE status IN ('queued','running','partial','delivery_unknown')));")
  [[ "$observed" == 0:0:0:0:0:0:0 ]] || fail "current work is not quiescent"
}

assert_env_contract() {
  local expected=$1 count value
  count=$(awk -F= '$1=="CONTENT_SCORING_VERSION"{n++} END{print n+0}' .env)
  value=$(awk -F= '$1=="CONTENT_SCORING_VERSION"{print substr($0,index($0,"=")+1)}' .env)
  [[ "$count" == 1 && "$value" == "$expected" ]] || fail "primary scoring config drift"
  [[ "$(awk -F= '$1=="CONTENT_SCORING_VERSION"{n++} END{print n+0}' .release.env)" == 0 ]] \
    || fail "release env must not own scoring version"
}

assert_services() {
  local expected_id=$1 service cid
  for service in "${START_ORDER[@]}"; do
    cid=$(edu_ai_compose ps -q "$service")
    [[ -n "$cid" ]] || fail "service container missing"
    [[ "$(docker inspect "$cid" --format '{{.Image}}:{{.State.Status}}:{{.RestartCount}}')" == "${expected_id}:running:0" ]] \
      || fail "service runtime drift"
  done
}

atomic_preserve_target() {
  local source=$1 target=$2 mode uid gid tmp
  [[ -f "$source" && ! -L "$source" && -f "$target" && ! -L "$target" ]] || return 1
  mode=$(stat -c %a "$target")
  uid=$(stat -c %u "$target")
  gid=$(stat -c %g "$target")
  tmp=$(mktemp "${BACKUP_ROOT}/.threshold-install.XXXXXX")
  install -o "$uid" -g "$gid" -m "$mode" "$source" "$tmp"
  mv -Tf "$tmp" "$target"
}

atomic_exact_source() {
  local source=$1 target=$2 mode uid gid tmp
  [[ -f "$source" && ! -L "$source" ]] || return 1
  mode=$(stat -c %a "$source")
  uid=$(stat -c %u "$source")
  gid=$(stat -c %g "$source")
  tmp=$(mktemp "${BACKUP_ROOT}/.threshold-restore.XXXXXX")
  install -o "$uid" -g "$gid" -m "$mode" "$source" "$tmp"
  mv -Tf "$tmp" "$target"
}

stop_all() {
  local service
  for service in "${STOP_ORDER[@]}"; do
    edu_ai_compose stop "$service" >/dev/null
  done
}

start_all() {
  local service
  for service in "${START_ORDER[@]}"; do
    edu_ai_compose up -d --no-build --no-deps --force-recreate "$service" >/dev/null
    sleep 1
  done
}

recover() {
  local rc=0 service tag path
  (( recovering == 0 )) || return 1
  recovering=1
  set +e
  printf 'phase=recovery_started\n'
  cd "$APP_DIR" || return 1
  source scripts/edu-ai-release-common.sh || return 1
  stop_all || rc=1
  for tag in "${ACTIVE_TAGS[@]}"; do docker tag "$PREVIOUS_ID" "$tag" || rc=1; done
  for path in "${DELTA_PATHS[@]}"; do
    atomic_exact_source "$BACKUP_DIR/source/$path" "$APP_DIR/$path" || rc=1
  done
  atomic_exact_source "$BACKUP_DIR/env" "$APP_DIR/.env" || rc=1
  atomic_exact_source "$BACKUP_DIR/release-commit" "$APP_DIR/.release-commit" || rc=1
  atomic_exact_source "$BACKUP_DIR/release-short" "$APP_DIR/RELEASE_COMMIT" || rc=1
  start_all || rc=1
  sleep 10
  assert_services "$PREVIOUS_ID" || rc=1
  assert_env_contract "$PREVIOUS_SCORING" || rc=1
  [[ "$(tr -d '\r\n' <.release-commit)" == "$PREVIOUS_COMMIT" ]] || rc=1
  [[ -z "$before_vector" || "$(work_vector)" == "$before_vector" ]] || rc=1
  if (( rc == 0 )); then printf 'phase=recovery_completed\n'; else printf 'phase=recovery_failed\n'; fi
  return "$rc"
}

on_exit() {
  local rc=$?
  trap - EXIT ERR HUP INT TERM
  if (( rc != 0 && mutated == 1 && completed == 0 )); then
    recover || rc=125
  fi
  exit "$rc"
}

trap on_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

[[ $EUID -eq 0 ]] || fail "operator must run as root"
[[ "$STAGE" == /* && -d "$STAGE" && ! -L "$STAGE" ]] || fail "protected stage is invalid"
[[ "$(stat -c %u:%g:%a "$STAGE")" == 0:0:700 ]] || fail "protected stage metadata is invalid"
[[ -d "$BACKUP_ROOT" && ! -L "$BACKUP_ROOT" && "$(stat -c %u:%g:%a "$BACKUP_ROOT")" == 0:0:700 ]] \
  || fail "backup root is invalid"
exec 9>/var/lock/edu-ai-threshold-deploy.lock
flock -n 9

cd "$STAGE"
[[ "$(find . -mindepth 1 -maxdepth 1 -type f -printf '%f\n' | LC_ALL=C sort)" == $'artifacts.sha256\nbackend-image.tar.gz\nbackend-image.tar.gz.sha256\nprevious-source-delta.sha256\nsource-delta.sha256\nsource-delta.tar.gz\nthreshold-fast-deploy.sh' ]] || fail "stage membership drift"
[[ -z "$(find . -mindepth 1 -maxdepth 1 ! -type f -print -quit)" ]] || fail "stage contains non-regular member"
[[ -z "$(find . -mindepth 1 -maxdepth 1 -type f ! -perm 0600 -print -quit)" ]] || fail "stage file mode drift"
sha256sum --strict -c artifacts.sha256 >/dev/null
sha256sum --strict -c backend-image.tar.gz.sha256 >/dev/null

cd "$APP_DIR"
source scripts/edu-ai-release-common.sh
[[ "$(tr -d '\r\n' <.release-commit)" == "$PREVIOUS_COMMIT" ]] || fail "full marker drift"
[[ "$(tr -d '\r\n' <RELEASE_COMMIT)" == "$PREVIOUS_SHORT" ]] || fail "short marker drift"
assert_env_contract "$PREVIOUS_SCORING"
for tag in "${ACTIVE_TAGS[@]}"; do
  [[ "$(docker image inspect "$tag" --format '{{.Id}}')" == "$PREVIOUS_ID" ]] || fail "active tag drift"
done
assert_services "$PREVIOUS_ID"
assert_zero_current_work
(cd "$APP_DIR" && sha256sum --strict -c "$STAGE/previous-source-delta.sha256" >/dev/null)
[[ "$(sql_scalar 'SELECT version_num FROM alembic_version')" == 20260815_0021 ]] || fail "Alembic head drift"
before_vector=$(work_vector)
sleep 15
assert_zero_current_work
[[ "$(work_vector)" == "$before_vector" ]] || fail "preflight vector drift"

[[ ! -e "$BACKUP_DIR" && ! -L "$BACKUP_DIR" ]] || fail "backup collision"
install -d -o 0 -g 0 -m 0700 "$BACKUP_DIR" "$BACKUP_DIR/source" "$BACKUP_DIR/candidate"
for path in "${DELTA_PATHS[@]}"; do
  install -d -o 0 -g 0 -m 0700 "$BACKUP_DIR/source/$(dirname "$path")"
  cp -a -- "$APP_DIR/$path" "$BACKUP_DIR/source/$path"
done
cp -a -- .env "$BACKUP_DIR/env"
cp -a -- .release.env "$BACKUP_DIR/release-env"
cp -a -- .release-commit "$BACKUP_DIR/release-commit"
cp -a -- RELEASE_COMMIT "$BACKUP_DIR/release-short"
edu_ai_compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' >"$BACKUP_DIR/postgres.dump"
[[ -s "$BACKUP_DIR/postgres.dump" ]]
edu_ai_compose exec -T postgres sh -c 'pg_restore --list' <"$BACKUP_DIR/postgres.dump" >/dev/null
(cd "$BACKUP_DIR" && find . -type f ! -name checksums.sha256 -print0 | LC_ALL=C sort -z | xargs -0 sha256sum >checksums.sha256)
chmod 0600 "$BACKUP_DIR/checksums.sha256"
printf 'phase=backup_complete backup_id=%s\n' "$RELEASE_ID"

docker load -i "$STAGE/backend-image.tar.gz" >/dev/null
[[ "$(docker image inspect "$CANDIDATE_TAG" --format '{{.Id}}')" == "$CANDIDATE_ID" ]] || fail "candidate image ID drift"
[[ "$(docker image inspect "$CANDIDATE_ID" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" == "$TARGET_COMMIT" ]] || fail "candidate revision drift"
mapfile -t expected_paths < <(printf '%s\n' "${DELTA_PATHS[@]}" | LC_ALL=C sort)
mapfile -t archive_paths < <(tar -tzf "$STAGE/source-delta.tar.gz" | awk '!/\/$/' | LC_ALL=C sort)
[[ "${archive_paths[*]}" == "${expected_paths[*]}" ]] || fail "source archive path set drift"
tar --no-same-owner --no-same-permissions -xzf "$STAGE/source-delta.tar.gz" -C "$BACKUP_DIR/candidate"
(cd "$BACKUP_DIR/candidate" && sha256sum --strict -c "$STAGE/source-delta.sha256" >/dev/null)

assert_zero_current_work
mutated=1
stop_all
for tag in "${ACTIVE_TAGS[@]}"; do docker tag "$CANDIDATE_ID" "$tag"; done
for path in "${DELTA_PATHS[@]}"; do
  atomic_preserve_target "$BACKUP_DIR/candidate/$path" "$APP_DIR/$path"
done

env_candidate=$(mktemp "${BACKUP_ROOT}/.threshold-env.XXXXXX")
awk -F= -v old="$PREVIOUS_SCORING" -v new="$TARGET_SCORING" '
  BEGIN{n=0}
  $1=="CONTENT_SCORING_VERSION" {if(substr($0,index($0,"=")+1)!=old) exit 41; print "CONTENT_SCORING_VERSION=" new; n++; next}
  {print}
  END{if(n!=1) exit 42}
' .env >"$env_candidate"
atomic_preserve_target "$env_candidate" "$APP_DIR/.env"
printf '%s\n' "$TARGET_COMMIT" >"$BACKUP_DIR/candidate-release-commit"
printf '%s\n' "$TARGET_SHORT" >"$BACKUP_DIR/candidate-release-short"
atomic_preserve_target "$BACKUP_DIR/candidate-release-commit" "$APP_DIR/.release-commit"
atomic_preserve_target "$BACKUP_DIR/candidate-release-short" "$APP_DIR/RELEASE_COMMIT"

assert_env_contract "$TARGET_SCORING"
[[ "$(sql_scalar 'SELECT version_num FROM alembic_version')" == 20260815_0021 ]] || fail "Alembic head changed"
start_all
for _ in $(seq 1 60); do
  api_id=$(edu_ai_compose ps -q acquisition-api)
  [[ -n "$api_id" ]] || { sleep 1; continue; }
  [[ "$(docker inspect "$api_id" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}')" == healthy ]] && break
  sleep 1
done
assert_services "$CANDIDATE_ID"
for service in acquisition-api content-scheduler content-worker; do
  cid=$(edu_ai_compose ps -q "$service")
  [[ "$(docker exec "$cid" python -c 'from app.core.config import get_settings; from app.application.services.topic_selection import build_topic_scoring_config; c=build_topic_scoring_config(get_settings()); print(f"{c.version}|{c.threshold:.2f}|{c.effective_veto_rule_version}")')" == "${TARGET_SCORING}|0.59|topic-veto-v4-delivered-content" ]] || fail "runtime scoring contract drift"
done
[[ "$(tr -d '\r\n' <.release-commit)" == "$TARGET_COMMIT" ]] || fail "target full marker drift"
[[ "$(tr -d '\r\n' <RELEASE_COMMIT)" == "$TARGET_SHORT" ]] || fail "target short marker drift"
sleep 15
assert_zero_current_work
[[ "$(work_vector)" == "$before_vector" ]] || fail "post-release vector drift"
completed=1
printf 'phase=deploy_success backup_id=%s candidate_id=%s vector=%s\n' "$RELEASE_ID" "$CANDIDATE_ID" "$before_vector"
