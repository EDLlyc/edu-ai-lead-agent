#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export LC_ALL=C

readonly APP_DIR=/opt/edu-ai-lead-agent
readonly STAGE=/tmp/edu-ai-ocr-off-5d0a4ca.NmphHA
readonly PREVIOUS_COMMIT=cbc27b2491e4ebd49e6cc58692b065268e2887db
readonly PREVIOUS_SHORT=cbc27b2
readonly PREVIOUS_ID=sha256:b9410598a50417b236eaa68ab1f5660c756269f0cbf258c429c95aaf7f5e7d31
readonly TARGET_COMMIT=5d0a4caca97cc61edd201e26bf99f038500f107a
readonly TARGET_SHORT=5d0a4ca
readonly CANDIDATE_ID=sha256:886e6e212bfe2a6a21c3a2bd5826b7283f5d5fb76c2949201861d15892fa8f99
readonly BACKUP_ROOT=/var/backups/edu-ai/releases
readonly RELEASE_ID="$(date -u +%Y%m%dT%H%M%SZ)-ocr-off"
readonly BACKUP_DIR="${BACKUP_ROOT}/${RELEASE_ID}"
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

mutated=0
completed=0
recovering=0

cd "$APP_DIR"
source scripts/edu-ai-release-common.sh

sql_scalar() { edu_ai_psql_scalar "$1"; }

work_vector() {
  sql_scalar "SELECT concat_ws(':',(SELECT count(*) FROM acquisition_runs),(SELECT count(*) FROM acquisition_jobs),(SELECT count(*) FROM governance_runs),(SELECT count(*) FROM governance_jobs),(SELECT count(*) FROM content_slot_runs),(SELECT count(*) FROM content_slot_selections),(SELECT count(*) FROM copy_generation_runs),(SELECT count(*) FROM image_artifacts),(SELECT coalesce(sum(attempt_count),0) FROM image_artifacts),(SELECT count(*) FROM material_packages),(SELECT count(*) FROM model_invocations),(SELECT count(*) FROM wecom_delivery_jobs),(SELECT count(*) FROM wecom_delivery_attempts));"
}

assert_zero_active() {
  [[ "$(sql_scalar "SELECT concat_ws(':',(SELECT count(*) FROM acquisition_jobs WHERE status IN ('queued','running','retry_scheduled')),(SELECT count(*) FROM governance_jobs WHERE status IN ('queued','running','retry_scheduled')),(SELECT count(*) FROM content_slot_jobs WHERE status IN ('queued','running')),(SELECT count(*) FROM copy_generation_runs WHERE business_date=DATE '2026-08-18' AND status IN ('queued','running')),(SELECT count(*) FROM image_artifacts WHERE status IN ('queued','running')),(SELECT count(*) FROM material_packages WHERE status='queued'),(SELECT count(*) FROM wecom_delivery_jobs WHERE status IN ('queued','running','partial','delivery_unknown')));")" == '0:0:0:0:0:0:0' ]]
}

atomic_install() {
  local source_file="$1" target="$2" mode="$3" owner="$4"
  local parent tmp uid gid
  parent="$(dirname "$target")"
  uid="${owner%%:*}"
  gid="${owner#*:}"
  tmp="$(mktemp "${parent}/.ocr-off-install.XXXXXX")"
  install -o "$uid" -g "$gid" -m "$mode" "$source_file" "$tmp"
  mv -Tf "$tmp" "$target"
}

recover() {
  local rc=0 service cid
  (( recovering == 0 )) || return 1
  recovering=1
  set +e
  printf 'phase=recovery_started\n'
  cd "$APP_DIR" || return 1
  source scripts/edu-ai-release-common.sh || return 1
  for service in "${STOP_ORDER[@]}"; do
    edu_ai_compose stop "$service" >/dev/null 2>&1 || rc=1
  done
  for tag in "${ACTIVE_TAGS[@]}"; do
    docker tag "$PREVIOUS_ID" "$tag" >/dev/null 2>&1 || rc=1
  done
  atomic_install "$BACKUP_DIR/env" "$APP_DIR/.env" 600 1000:1001 || rc=1
  atomic_install "$BACKUP_DIR/env.example" "$APP_DIR/.env.example" 600 0:0 || rc=1
  atomic_install "$BACKUP_DIR/config.py" "$APP_DIR/backend/app/core/config.py" 600 0:0 || rc=1
  atomic_install "$BACKUP_DIR/doctor.sh" "$APP_DIR/scripts/doctor.sh" 700 0:0 || rc=1
  atomic_install "$BACKUP_DIR/release-commit" "$APP_DIR/.release-commit" 600 1000:1001 || rc=1
  atomic_install "$BACKUP_DIR/release-short" "$APP_DIR/RELEASE_COMMIT" 600 1000:1001 || rc=1
  for service in "${START_ORDER[@]}"; do
    edu_ai_compose up -d --no-build --no-deps --force-recreate "$service" >/dev/null 2>&1 || rc=1
  done
  sleep 8
  for service in "${START_ORDER[@]}"; do
    cid="$(edu_ai_compose ps -q "$service")"
    [[ -n "$cid" && "$(docker inspect "$cid" --format '{{.Image}}:{{.State.Status}}:{{.RestartCount}}')" == "${PREVIOUS_ID}:running:0" ]] || rc=1
  done
  if (( rc == 0 )); then
    printf 'phase=recovery_completed\n'
  else
    printf 'phase=recovery_failed\n'
  fi
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

exec 9>/var/lock/edu-ai-ocr-off-deploy.lock
flock -n 9
[[ -d "$BACKUP_ROOT" && ! -L "$BACKUP_ROOT" ]]
[[ "$(stat -c %u:%g:%a "$BACKUP_ROOT")" == '0:0:700' ]]
[[ -f "$STAGE/artifacts.sha256" && ! -L "$STAGE/artifacts.sha256" ]]
(cd "$STAGE" && sha256sum --strict -c artifacts.sha256 >/dev/null)
[[ "$(tr -d '\r\n' < .release-commit)" == "$PREVIOUS_COMMIT" ]]
[[ "$(tr -d '\r\n' < RELEASE_COMMIT)" == "$PREVIOUS_SHORT" ]]
[[ "$(sha256sum .env.example | awk '{print $1}')" == 6e51b50e8bac67df1a388f1479d4a5cc3fffb33af75704c5db40ed19af6bf9b8 ]]
[[ "$(sha256sum backend/app/core/config.py | awk '{print $1}')" == 8f728d381856a2879c5e559ac9578bc6e356edc9d1fd77b48b3577d7a152c80b ]]
[[ "$(sha256sum scripts/doctor.sh | awk '{print $1}')" == d37baa096e2bc5145ac772ff044227545071031b2558473afe3d5ce1253142f2 ]]
[[ "$(sha256sum "$STAGE/env.example.target" | awk '{print $1}')" == 7fe318d7e31fa18f57752c7bb79204d6475ae381c1d81491704b376856bc74b2 ]]
[[ "$(sha256sum "$STAGE/config.py.target" | awk '{print $1}')" == f1e27ab23df20279439e0cb3402401008a76192504cecbabe0f335a1a904acd7 ]]
[[ "$(sha256sum "$STAGE/doctor.sh.target" | awk '{print $1}')" == 1395d9c54a8d1678c1e1862c58689f29b8fea88a3522e007eb350a883be15db4 ]]
[[ "$(awk -F= '$1=="IMAGE_OCR_ENABLED"{n++} END{print n+0}' .env)" == 1 ]]
[[ "$(awk -F= '$1=="IMAGE_OCR_ENABLED"{v=substr($0,index($0,"=")+1)} END{print v}' .env)" == true ]]
[[ "$(awk -F= '$1=="IMAGE_OCR_ENABLED"{n++} END{print n+0}' .release.env)" == 0 ]]
[[ "$(docker image inspect edu-ai-lead-agent-backend:ocr-off-5d0a4caca97c --format '{{.Id}}')" == "$CANDIDATE_ID" ]]
for tag in "${ACTIVE_TAGS[@]}"; do
  [[ "$(docker image inspect "$tag" --format '{{.Id}}')" == "$PREVIOUS_ID" ]]
done
for service in "${START_ORDER[@]}"; do
  cid="$(edu_ai_compose ps -q "$service")"
  [[ -n "$cid" && "$(docker inspect "$cid" --format '{{.Image}}:{{.State.Status}}:{{.RestartCount}}')" == "${PREVIOUS_ID}:running:0" ]]
done
assert_zero_active
before_vector="$(work_vector)"

install -d -o 0 -g 0 -m 0700 "$BACKUP_DIR"
install -o 0 -g 0 -m 0600 .env "$BACKUP_DIR/env"
install -o 0 -g 0 -m 0600 .release.env "$BACKUP_DIR/release.env"
install -o 0 -g 0 -m 0600 .env.example "$BACKUP_DIR/env.example"
install -o 0 -g 0 -m 0600 backend/app/core/config.py "$BACKUP_DIR/config.py"
install -o 0 -g 0 -m 0600 scripts/doctor.sh "$BACKUP_DIR/doctor.sh"
install -o 0 -g 0 -m 0600 .release-commit "$BACKUP_DIR/release-commit"
install -o 0 -g 0 -m 0600 RELEASE_COMMIT "$BACKUP_DIR/release-short"
edu_ai_compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' >"$BACKUP_DIR/postgres.dump"
[[ -s "$BACKUP_DIR/postgres.dump" ]]
edu_ai_compose exec -T postgres sh -c 'pg_restore --list' <"$BACKUP_DIR/postgres.dump" >/dev/null
(cd "$BACKUP_DIR" && sha256sum env release.env env.example config.py doctor.sh release-commit release-short postgres.dump >checksums.sha256)
chmod 0600 "$BACKUP_DIR/checksums.sha256"
printf 'phase=backup_complete backup_id=%s\n' "$RELEASE_ID"

assert_zero_active
mutated=1
for service in "${STOP_ORDER[@]}"; do
  edu_ai_compose stop "$service" >/dev/null
done
for tag in "${ACTIVE_TAGS[@]}"; do
  docker tag "$CANDIDATE_ID" "$tag"
done
atomic_install "$STAGE/env.example.target" "$APP_DIR/.env.example" 600 0:0
atomic_install "$STAGE/config.py.target" "$APP_DIR/backend/app/core/config.py" 600 0:0
atomic_install "$STAGE/doctor.sh.target" "$APP_DIR/scripts/doctor.sh" 700 0:0

env_tmp="$(mktemp "$APP_DIR/.env.ocr-off.XXXXXX")"
awk -F= 'BEGIN{n=0} $1=="IMAGE_OCR_ENABLED"{print "IMAGE_OCR_ENABLED=false"; n++; next} {print} END{if(n!=1) exit 42}' .env >"$env_tmp"
chown 1000:1001 "$env_tmp"
chmod 600 "$env_tmp"
mv -Tf "$env_tmp" .env

printf '%s\n' "$TARGET_COMMIT" >"$APP_DIR/.release-commit.tmp"
chown 1000:1001 "$APP_DIR/.release-commit.tmp"
chmod 600 "$APP_DIR/.release-commit.tmp"
mv -Tf "$APP_DIR/.release-commit.tmp" .release-commit
printf '%s\n' "$TARGET_SHORT" >"$APP_DIR/RELEASE_COMMIT.tmp"
chown 1000:1001 "$APP_DIR/RELEASE_COMMIT.tmp"
chmod 600 "$APP_DIR/RELEASE_COMMIT.tmp"
mv -Tf "$APP_DIR/RELEASE_COMMIT.tmp" RELEASE_COMMIT

[[ "$(sql_scalar 'SELECT version_num FROM alembic_version')" == 20260815_0021 ]]
for service in "${START_ORDER[@]}"; do
  edu_ai_compose up -d --no-build --no-deps --force-recreate "$service" >/dev/null
  sleep 1
done
for _ in $(seq 1 60); do
  api_id="$(edu_ai_compose ps -q acquisition-api)"
  if [[ -n "$api_id" && "$(docker inspect "$api_id" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}')" == healthy ]]; then
    break
  fi
  sleep 1
done
for service in "${START_ORDER[@]}"; do
  cid="$(edu_ai_compose ps -q "$service")"
  [[ -n "$cid" && "$(docker inspect "$cid" --format '{{.Image}}:{{.State.Status}}:{{.RestartCount}}')" == "${CANDIDATE_ID}:running:0" ]]
done
api_id="$(edu_ai_compose ps -q acquisition-api)"
worker_id="$(edu_ai_compose ps -q content-worker)"
for cid in "$api_id" "$worker_id"; do
  [[ "$(docker exec "$cid" python -c 'from app.core.config import Settings; s=Settings(); print(f"{str(s.image_ocr_enabled).lower()}:{str(s.image_diversity_enabled).lower()}")')" == false:true ]]
done
[[ "$(tr -d '\r\n' < .release-commit)" == "$TARGET_COMMIT" ]]
[[ "$(tr -d '\r\n' < RELEASE_COMMIT)" == "$TARGET_SHORT" ]]
[[ "$(sha256sum .env.example | awk '{print $1}')" == 7fe318d7e31fa18f57752c7bb79204d6475ae381c1d81491704b376856bc74b2 ]]
[[ "$(sha256sum backend/app/core/config.py | awk '{print $1}')" == f1e27ab23df20279439e0cb3402401008a76192504cecbabe0f335a1a904acd7 ]]
[[ "$(sha256sum scripts/doctor.sh | awk '{print $1}')" == 1395d9c54a8d1678c1e1862c58689f29b8fea88a3522e007eb350a883be15db4 ]]
[[ "$(awk -F= '$1=="IMAGE_OCR_ENABLED"{v=substr($0,index($0,"=")+1)} END{print v}' .env)" == false ]]
sleep 15
assert_zero_active
[[ "$(work_vector)" == "$before_vector" ]]
completed=1
printf 'phase=deploy_success backup_id=%s candidate_id=%s vector=%s\n' "$RELEASE_ID" "$CANDIDATE_ID" "$before_vector"
