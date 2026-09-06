#!/usr/bin/env bash
# One-shot root operator for the substantive-release production incident release.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077
export LC_ALL=C

operator_app_dir=/opt/edu-ai-lead-agent
operator_backup_root=/opt/edu-ai-release-backups
operator_attempt_root=/var/lib/edu-ai-release-attempts
operator_lock=/var/lock/edu-ai-deploy.lock
if [[ "${SUBSTANTIVE_RELEASE_OPERATOR_SOURCE_ONLY:-0}" == 1 ]]; then
  [[ -n "${SUBSTANTIVE_RELEASE_OPERATOR_TEST_ROOT:-}" ]] || {
    printf '%s\n' '[substantive-release-release] ERROR: test root is absent' >&2
    return 1 2>/dev/null || exit 1
  }
  operator_app_dir="${SUBSTANTIVE_RELEASE_OPERATOR_TEST_ROOT}/app"
  operator_backup_root="${SUBSTANTIVE_RELEASE_OPERATOR_TEST_ROOT}/backups"
  operator_attempt_root="${SUBSTANTIVE_RELEASE_OPERATOR_TEST_ROOT}/attempts"
  operator_lock="${SUBSTANTIVE_RELEASE_OPERATOR_TEST_ROOT}/release.lock"
fi
readonly APP_DIR="$operator_app_dir"
readonly BACKUP_ROOT="$operator_backup_root"
readonly ATTEMPT_ROOT="$operator_attempt_root"
readonly RELEASE_LOCK="$operator_lock"
unset operator_app_dir operator_backup_root operator_attempt_root operator_lock
readonly PRIMARY_ENV="${APP_DIR}/.env"
readonly RELEASE_ENV="${APP_DIR}/.release.env"
readonly RELEASE_MARKER="${APP_DIR}/.release-commit"
readonly LEGACY_RELEASE_MARKER="${APP_DIR}/RELEASE_COMMIT"
readonly COMPOSE_PROJECT=edu-ai-lead-agent
readonly PRODUCTION_COMMIT=5c560da71bcbb61b765d3fe82c742cf2d5e676e1
readonly LEGACY_PRODUCTION_COMMIT=5c560da71bcbb61b765d3fe82c742cf2d5e676e1
readonly ALEMBIC_HEAD=20260901_0042
readonly ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4
readonly PRIMARY_ENV_IDENTITY=600:1000:1001
readonly BUSINESS_TIMEZONE=Asia/Shanghai
readonly CONTENT_MAX_ATTEMPTS=3
readonly OPERATOR_NAME=substantive-release-operator.sh
readonly VALIDATOR_NAME=validate-substantive-release.py
readonly -a PROFILES=(
  --profile governance --profile content --profile wecom
  --profile official-account-weekly-dag --profile official-account-local
  --profile wechat-official-account-draft
)
readonly -a APP_SERVICES=(
  acquisition-api acquisition-scheduler acquisition-worker
  governance-scheduler governance-worker content-scheduler content-worker
  wecom-dispatcher official-account-weekly-dag-worker
  official-account-weekly-scheduler official-account-local-worker
  wechat-official-account-draft-worker
)
readonly -a ALL_SERVICES=(postgres minio "${APP_SERVICES[@]}")
readonly -a STOP_ORDER=(
  wechat-official-account-draft-worker wecom-dispatcher
  official-account-weekly-scheduler official-account-weekly-dag-worker
  official-account-local-worker content-worker content-scheduler
  governance-worker governance-scheduler acquisition-worker
  acquisition-scheduler acquisition-api
)
readonly -a MANAGED_DIRS=(backend deploy infra scripts)
readonly -a MANAGED_FILES=(
  compose.yaml .env.example .gitattributes .gitignore AGENTS.md Makefile README.md environment.yml
)

stage_dir=
scheduler_cutoff_utc=
preflight_only=0
metadata_json=
baseline_json=
release_commit=
transport_tag=
candidate_config_digest=
candidate_manifest_digest=
candidate_reference=
candidate_runtime_image_id=
candidate_image_owned=0
candidate_reference_owned=0
candidate_owned_image_id=
candidate_primary_env_sha256=
workspace=
backup_dir=
backup_root_identity=
attempt_marker=
recovery_armed=0
source_activated=0
migration_attempted=0
completed=0
declare -a transient_paths=()

log() { printf '[substantive-release-release] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; return 1; }

cleanup_transient_paths() {
  local path
  for path in "${transient_paths[@]}"; do
    case "$path" in
      /tmp/substantive-release-source-observed.??????|\
      /tmp/substantive-release-source-expected.??????|\
      /tmp/substantive-release-image-source.??????|\
      /tmp/substantive-release-compose.??????)
        rm -f -- "$path" >/dev/null 2>&1 || true
        ;;
    esac
  done
}

candidate_image_container_state() {
  local containers container observed_id
  containers=$(docker container ls --all --quiet --no-trunc 2>/dev/null) || return 2
  while IFS= read -r container; do
    [[ -n "$container" ]] || continue
    observed_id=$(docker container inspect --format '{{.Image}}' "$container" 2>/dev/null) \
      || return 2
    [[ "$observed_id" == "$candidate_owned_image_id" ]] && return 0
  done <<<"$containers"
  return 1
}

abandon_candidate_image_ownership() {
  candidate_image_owned=0
  candidate_reference_owned=0
  candidate_owned_image_id=
}

cleanup_candidate_image() {
  local current_id reference_id container_state
  [[ "${completed:-0}" == 0 && "${candidate_image_owned:-0}" == 1 \
      && -n "${transport_tag:-}" \
      && "${candidate_owned_image_id:-}" =~ ^sha256:[0-9a-f]{64}$ ]] || return 0
  current_id=$(docker image inspect --format '{{.Id}}' "$transport_tag" 2>/dev/null) \
    || { abandon_candidate_image_ownership; return 0; }
  [[ "$current_id" == "$candidate_owned_image_id" ]] \
    || { abandon_candidate_image_ownership; return 0; }
  if candidate_image_container_state; then
    abandon_candidate_image_ownership
    return 0
  else
    container_state=$?
    ((container_state == 1)) || { abandon_candidate_image_ownership; return 0; }
  fi
  if [[ "${candidate_reference_owned:-0}" == 1 && -n "${candidate_reference:-}" ]]; then
    reference_id=$(docker image inspect --format '{{.Id}}' "$candidate_reference" 2>/dev/null) \
      || { abandon_candidate_image_ownership; return 0; }
    [[ "$reference_id" == "$candidate_owned_image_id" ]] \
      || { abandon_candidate_image_ownership; return 0; }
    docker image rm "$candidate_reference" >/dev/null 2>&1 \
      || { abandon_candidate_image_ownership; return 0; }
  fi
  current_id=$(docker image inspect --format '{{.Id}}' "$transport_tag" 2>/dev/null) \
    || { abandon_candidate_image_ownership; return 0; }
  [[ "$current_id" == "$candidate_owned_image_id" ]] \
    || { abandon_candidate_image_ownership; return 0; }
  if candidate_image_container_state; then
    abandon_candidate_image_ownership
    return 0
  else
    container_state=$?
    ((container_state == 1)) || { abandon_candidate_image_ownership; return 0; }
  fi
  docker image rm "$transport_tag" >/dev/null 2>&1 || true
  abandon_candidate_image_ownership
}

usage() {
  printf '%s\n' \
    "Usage: $OPERATOR_NAME --stage-dir ABSOLUTE_MODE_0700_DIR --scheduler-cutoff-utc YYYY-MM-DDTHH:MM:SSZ [--preflight-only]" >&2
}

parse_args() {
  while (($#)); do
    case "$1" in
      --stage-dir) (($# >= 2)) || die 'missing stage directory'; stage_dir=$2; shift 2 ;;
      --scheduler-cutoff-utc) (($# >= 2)) || die 'missing scheduler cutoff'; scheduler_cutoff_utc=$2; shift 2 ;;
      --preflight-only) preflight_only=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die 'unknown argument' ;;
    esac
  done
  [[ "$stage_dir" == /* && "$stage_dir" != */ ]] \
    || die 'stage directory must be absolute without a trailing slash'
  [[ "$scheduler_cutoff_utc" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] \
    || die 'scheduler cutoff is invalid'
}

compose() {
  local argument no_build=0
  case "${1:-}" in
    create|up)
      for argument in "$@"; do
        case "$argument" in
          --no-build) no_build=1 ;;
          --build|--build=*)
            die "production Compose ${1} forbids --build"
            return 1
            ;;
        esac
      done
      ((no_build == 1)) \
        || { die "production Compose ${1} requires --no-build"; return 1; }
      ;;
    run)
      for argument in "$@"; do
        case "$argument" in
          --build|--build=*)
            die 'production Compose run forbids --build'
            return 1
            ;;
        esac
      done
      ;;
  esac
  docker compose --project-name "$COMPOSE_PROJECT" --project-directory "$APP_DIR" \
    --env-file "$PRIMARY_ENV" --env-file "$RELEASE_ENV" "${PROFILES[@]}" "$@"
}

json_string() {
  python3 - "$1" "$2" <<'PY'
import json
import pathlib
import sys

value = json.loads(pathlib.Path(sys.argv[1]).read_bytes())[sys.argv[2]]
if not isinstance(value, str):
    raise SystemExit(1)
print(value)
PY
}

baseline_legacy_identity() {
  python3 - "$baseline_json" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_bytes())
values = [
    payload["legacy_release_commit_mode"],
    payload["legacy_release_commit_uid"],
    payload["legacy_release_commit_gid"],
]
if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
    raise SystemExit(1)
print(f"{values[0]:o}:{values[1]}:{values[2]}")
PY
}

baseline_primary_identity() {
  python3 - "$baseline_json" "$PRIMARY_ENV_IDENTITY" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_bytes())
values = [
    payload["primary_env_mode"],
    payload["primary_env_uid"],
    payload["primary_env_gid"],
]
if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
    raise SystemExit(1)
identity = f"{values[0]:o}:{values[1]}:{values[2]}"
if identity != sys.argv[2]:
    raise SystemExit(1)
print(identity)
PY
}

primary_environment_fingerprint() {
  local path=${1:-$PRIMARY_ENV}
  python3 - "$path" <<'PY'
import hashlib
import os
import stat
import sys

path = sys.argv[1]
flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
try:
    descriptor = os.open(path, flags)
except OSError:
    raise SystemExit(1) from None
try:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise SystemExit(1)
    digest = hashlib.sha256()
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
    after = os.fstat(descriptor)
    observed = os.lstat(path)
    stable_fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (
        any(getattr(before, field) != getattr(after, field) for field in stable_fields)
        or not stat.S_ISREG(observed.st_mode)
        or any(getattr(after, field) != getattr(observed, field) for field in stable_fields)
    ):
        raise SystemExit(1)
    print(
        f"{digest.hexdigest()}:{stat.S_IMODE(after.st_mode):o}"
        f":{after.st_uid}:{after.st_gid}"
    )
finally:
    os.close(descriptor)
PY
}

primary_env_matches_baseline() {
  local path=${1:-$PRIMARY_ENV} expected_sha expected_identity expected_fingerprint
  local observed_fingerprint
  expected_sha=$(json_string "$baseline_json" primary_env_sha256) || return 1
  expected_identity=$(baseline_primary_identity) || return 1
  expected_fingerprint="${expected_sha}:${expected_identity}"
  observed_fingerprint=$(primary_environment_fingerprint "$path") || return 1
  [[ "$observed_fingerprint" == "$expected_fingerprint" ]]
}

marker_equals() {
  python3 - "$1" "$2" <<'PY'
import pathlib
import sys

raw = pathlib.Path(sys.argv[1]).read_bytes()
expected = sys.argv[2].encode()
if raw not in {expected, expected + b"\n"}:
    raise SystemExit(1)
PY
}

baseline_restart() {
  python3 - "$baseline_json" "$1" <<'PY'
import json
import pathlib
import sys

value = json.loads(pathlib.Path(sys.argv[1]).read_bytes())["restart_counts"][sys.argv[2]]
if isinstance(value, bool) or not isinstance(value, int) or value < 0:
    raise SystemExit(1)
print(value)
PY
}

require_physical_operator() {
  local actual expected stdin_target
  actual=$(realpath -e -- "${BASH_SOURCE[0]}")
  expected=$(realpath -e -- "${stage_dir}/${OPERATOR_NAME}")
  [[ "$actual" == "$expected" && ! -L "$actual" \
      && "$(stat -c '%a:%u:%g' "$actual")" == 600:0:0 ]] \
    || die 'operator must be the physical root-owned mode-0600 stage file'
  stdin_target=$(readlink "/proc/$$/fd/0" || true)
  [[ "$stdin_target" == /dev/null ]] || die 'operator stdin must be /dev/null'
}

validate_stage() {
  python3 "${stage_dir}/${VALIDATOR_NAME}" "$stage_dir" >/dev/null
  metadata_json="${stage_dir}/release-metadata.json"
  baseline_json="${stage_dir}/production-baseline.json"
  release_commit=$(json_string "$metadata_json" release_commit)
  transport_tag=$(json_string "$metadata_json" transport_tag)
  candidate_config_digest=$(json_string "$metadata_json" candidate_config_digest)
  candidate_reference=$(json_string "$metadata_json" candidate_reference)
  candidate_manifest_digest=${candidate_reference##*@}
  [[ "$release_commit" =~ ^[0-9a-f]{40}$ \
      && "$candidate_config_digest" =~ ^sha256:[0-9a-f]{64}$ \
      && "$candidate_manifest_digest" =~ ^sha256:[0-9a-f]{64}$ \
      && "$candidate_reference" =~ ^[^@[:space:]]+@sha256:[0-9a-f]{64}$ ]] \
    || die 'validated candidate identity could not be read'
  [[ "$(json_string "$metadata_json" scheduler_cutoff_utc)" == "$scheduler_cutoff_utc" ]] \
    || die 'operator cutoff differs from the checksum-bound cutoff'
}

require_safe_window() {
  python3 -B "${stage_dir}/${VALIDATOR_NAME}" --window \
    "$scheduler_cutoff_utc" "$baseline_json" >/dev/null
}

capture_environment_plan() {
  local plan previous
  plan=$(python3 -B "${stage_dir}/${VALIDATOR_NAME}" --environment-plan "$PRIMARY_ENV") || return 1
  previous=${plan%%:*}
  candidate_primary_env_sha256=${plan#*:}
  [[ "$previous" == "$(json_string "$baseline_json" primary_env_sha256)" \
      && "$candidate_primary_env_sha256" =~ ^[0-9a-f]{64}$ ]] || return 1
}

primary_env_matches_candidate() {
  local observed
  [[ "$candidate_primary_env_sha256" =~ ^[0-9a-f]{64}$ ]] || return 1
  observed=$(primary_environment_fingerprint "$PRIMARY_ENV") || return 1
  [[ "$observed" == "${candidate_primary_env_sha256}:600:1000:1001" ]]
}

verify_runtime_settings() {
  local expected=$1 service container
  for service in "${APP_SERVICES[@]}"; do
    container=$(compose ps -q "$service") || return 1
    [[ -n "$container" ]] || return 1
    docker inspect --format '{{json .Config.Env}}' "$container" \
      | python3 -B "${stage_dir}/${VALIDATOR_NAME}" --runtime-settings \
          "$expected" "$scheduler_cutoff_utc" "$service" >/dev/null || return 1
  done
  compose exec -T official-account-weekly-scheduler python -c \
    'import json; from app.domain.official_account_weekly_edition import WeeklyEditionSchedule; print(json.dumps(WeeklyEditionSchedule().as_metadata()))' \
    </dev/null | python3 -B "${stage_dir}/${VALIDATOR_NAME}" --weekly-schedule >/dev/null \
    || return 1
}

activate_primary_environment() {
  python3 -B "${stage_dir}/${VALIDATOR_NAME}" --activate-environment \
    "$backup_dir/env.before" "$PRIMARY_ENV" "$candidate_primary_env_sha256" >/dev/null
  primary_env_matches_candidate
}

require_mode_0600_file() {
  local path=$1
  [[ -f "$path" && ! -L "$path" && "$(stat -c '%a:%u:%g' "$path")" == 600:0:0 ]]
}

release_reference() {
  python3 - "$RELEASE_ENV" <<'PY'
import pathlib
import re
import sys

rows = [
    row for row in pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    if row and not row.lstrip().startswith("#")
]
if len(rows) != 1 or not rows[0].startswith("APP_IMAGE="):
    raise SystemExit(1)
value = rows[0].split("=", 1)[1]
if re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", value) is None:
    raise SystemExit(1)
print(value)
PY
}

current_source_manifest() {
  local destination=$1
  python3 - "$APP_DIR" "$destination" "${MANAGED_DIRS[@]}" -- "${MANAGED_FILES[@]}" <<'PY'
import hashlib
import json
import pathlib
import stat
import sys

root = pathlib.Path(sys.argv[1]).resolve(strict=True)
output = pathlib.Path(sys.argv[2])
separator = sys.argv.index("--")
names = sys.argv[3:separator] + sys.argv[separator + 1 :]
rows = []
for name in names:
    target = root / name
    if not target.exists() or target.is_symlink():
        raise SystemExit("managed source is absent or linked")
    paths = [target, *sorted(target.rglob("*"))] if target.is_dir() else [target]
    for path in paths:
        metadata = path.lstat()
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise SystemExit("managed source contains an unsafe member")
        rows.append(
            {
                "kind": "d" if path.is_dir() else "f",
                "path": path.relative_to(root).as_posix(),
                "mode": stat.S_IMODE(metadata.st_mode),
                "uid": metadata.st_uid,
                "gid": metadata.st_gid,
                "sha256": None if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
rows.sort(key=lambda row: row["path"])
output.write_text(json.dumps(rows, separators=(",", ":"), sort_keys=True), encoding="utf-8")
PY
}

write_observed_image_source_manifest() {
  local reference=$1 output=$2
  docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint python "$reference" -c \
    'import hashlib,pathlib,re,sys; root=pathlib.Path("/app"); paths=[root/"alembic.ini",root/"pyproject.toml"]; paths += [p for base in (root/"app",root/"alembic") for p in base.rglob("*") if p.is_file() and p.suffix in {".py",".html"}]; rows=sorted((p.relative_to(root).as_posix(),p) for p in set(paths)); all(pathlib.PurePosixPath(name).as_posix()==name and all(part not in {"",".",".."} for part in pathlib.PurePosixPath(name).parts) and re.fullmatch(r"[A-Za-z0-9._/-]+",name) is not None for name,p in rows) or sys.exit("image source scope contains an unsafe path"); print(*(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {name}" for name,p in rows),sep=chr(10))' \
    </dev/null >"$output"
}

verify_current_source_baseline() {
  local source_observed source_expected
  source_observed=$(mktemp /tmp/substantive-release-source-observed.XXXXXX)
  source_expected=$(mktemp /tmp/substantive-release-source-expected.XXXXXX)
  transient_paths+=("$source_observed" "$source_expected")
  if ! current_source_manifest "$source_observed"; then
    rm -f -- "$source_observed" "$source_expected"
    return 1
  fi
  if ! python3 - "$baseline_json" "$source_expected" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_bytes())["source_manifest"]
pathlib.Path(sys.argv[2]).write_text(
    json.dumps(payload, separators=(",", ":"), sort_keys=True), encoding="utf-8"
)
PY
  then
    rm -f -- "$source_observed" "$source_expected"
    return 1
  fi
  if ! cmp -s "$source_observed" "$source_expected"; then
    rm -f -- "$source_observed" "$source_expected"
    return 1
  fi
  rm -f -- "$source_observed" "$source_expected"
}

current_business_date() {
  python3 - "$BUSINESS_TIMEZONE" <<'PY'
from datetime import datetime
import sys
from zoneinfo import ZoneInfo

print(datetime.now(ZoneInfo(sys.argv[1])).date().isoformat())
PY
}

effect_counts() {
  local business_date=$1
  [[ "$business_date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || return 1
  compose exec -T postgres sh -eu -c '
    psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "
      SELECT
        (SELECT count(*) FROM copy_generation_runs WHERE status = '\''review_required'\'' AND error_code = '\''copy_provider_unavailable'\'')::text || '\'':'\'' ||
        (SELECT count(*) FROM copy_generation_attempts)::text || '\'':'\'' ||
        (SELECT count(*) FROM wecom_delivery_jobs)::text || '\'':'\'' ||
        (SELECT count(*) FROM wecom_delivery_attempts)::text || '\'':'\'' ||
        (SELECT count(*) FROM official_account_weekly_dag_runs)::text || '\'':'\'' ||
        (SELECT count(*) FROM official_account_weekly_dag_attempts)::text || '\'':'\'' ||
        (SELECT count(*) FROM official_account_article_runs)::text || '\'':'\'' ||
        (SELECT count(*) FROM official_account_article_attempts)::text || '\'':'\'' ||
        (SELECT count(*) FROM wechat_mp_draft_jobs)::text || '\'':'\'' ||
        (SELECT count(*) FROM wechat_mp_draft_items)::text || '\'':'\'' ||
        (SELECT count(*) FROM wechat_mp_draft_attempts)::text || '\'':'\'' ||
        (SELECT count(*) FROM copy_generation_jobs job
          JOIN copy_generation_runs run ON run.id = job.run_id
          WHERE run.business_date = '\''$1'\''::date
            AND job.status IN ('\''queued'\'', '\''retry_scheduled'\'')
            AND job.available_at <= statement_timestamp()
            AND job.attempt_count < $2::integer)::text || '\'':'\'' ||
        (SELECT count(*) FROM copy_generation_jobs WHERE status = '\''running'\'')::text || '\'':'\'' ||
        (SELECT count(*) FROM copy_generation_jobs job
          JOIN copy_generation_runs run ON run.id = job.run_id
          WHERE run.business_date = '\''$1'\''::date
            AND job.status IN ('\''queued'\'', '\''running'\'', '\''retry_scheduled'\''))::text || '\'':'\'' ||
        (SELECT count(*) FROM copy_generation_jobs job
          JOIN copy_generation_runs run ON run.id = job.run_id
          WHERE run.business_date > '\''$1'\''::date
            AND job.status IN ('\''queued'\'', '\''retry_scheduled'\''))::text || '\'':'\'' ||
        (SELECT count(*) FROM wecom_delivery_jobs WHERE status IN ('\''queued'\'', '\''running'\'', '\''partial'\'', '\''delivery_unknown'\''))::text || '\'':'\'' ||
        (SELECT count(*) FROM official_account_weekly_dag_runs WHERE status IN ('\''pending'\'', '\''running'\'', '\''partial'\'', '\''retryable_failed'\''))::text || '\'':'\'' ||
        (SELECT count(*) FROM official_account_article_runs WHERE status IN ('\''queued'\'', '\''running'\''))::text || '\'':'\'' ||
        (SELECT count(*) FROM wechat_mp_draft_jobs WHERE status IN ('\''queued'\'', '\''running'\'', '\''retryable_failed'\''))::text || '\'':'\'' ||
        (SELECT count(*) FROM material_packages)::text || '\'':'\'' ||
        (SELECT count(*) FROM copy_generation_runs)::text || '\'':'\'' ||
        (SELECT count(*) FROM copy_generation_jobs)::text || '\'':'\'' ||
        (SELECT count(*) FROM wecom_delivery_jobs WHERE status = '\''delivered'\'')::text || '\'':'\'' ||
        (SELECT count(*) FROM topic_selection_runs run JOIN topic_scoring_configs config ON config.id = run.config_id WHERE config.version = '\''scoring-v1-preview.12-substantive-topic-scope'\'' OR run.config_snapshot->>'\''version'\'' = '\''scoring-v1-preview.12-substantive-topic-scope'\'')::text || '\'':'\'' ||
        (SELECT count(*) FROM topic_selection_jobs job JOIN topic_selection_runs run ON run.id = job.run_id JOIN topic_scoring_configs config ON config.id = run.config_id WHERE config.version = '\''scoring-v1-preview.12-substantive-topic-scope'\'' OR run.config_snapshot->>'\''version'\'' = '\''scoring-v1-preview.12-substantive-topic-scope'\'')::text || '\'':'\'' ||
        (SELECT count(*) FROM content_slot_runs run JOIN topic_scoring_configs config ON config.id = run.config_id WHERE config.version = '\''scoring-v1-preview.12-substantive-topic-scope'\'' OR run.config_snapshot->>'\''version'\'' = '\''scoring-v1-preview.12-substantive-topic-scope'\'')::text || '\'':'\'' ||
        (SELECT count(*) FROM content_slot_jobs job JOIN content_slot_runs run ON run.id = job.run_id JOIN topic_scoring_configs config ON config.id = run.config_id WHERE config.version = '\''scoring-v1-preview.12-substantive-topic-scope'\'' OR run.config_snapshot->>'\''version'\'' = '\''scoring-v1-preview.12-substantive-topic-scope'\'')::text
    "
  ' substantive-release "$business_date" "$CONTENT_MAX_ATTEMPTS" </dev/null
}

frozen_copy_cohort() {
  local business_date=$1
  [[ "$business_date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || return 1
  compose exec -T postgres sh -eu -c '
    psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "
      SELECT concat_ws('\''|'\'', job.id::text, job.run_id::text, job.status,
        run.business_date::text, job.attempt_count::text,
        to_char(job.available_at AT TIME ZONE '\''UTC'\'', '\''YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'\''))
      FROM copy_generation_jobs job
      JOIN copy_generation_runs run ON run.id = job.run_id
      WHERE run.business_date < '\''$1'\''::date
        AND job.status IN ('\''queued'\'', '\''retry_scheduled'\'')
      ORDER BY run.business_date, job.id::text, job.run_id::text, job.status,
        job.attempt_count, job.available_at
    "
  ' substantive-release "$business_date" </dev/null | python3 -c '
import hashlib
import re
import sys

rows = sys.stdin.buffer.read().splitlines()
uuid = re.compile(rb"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
timestamp = re.compile(rb"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z")
expected_dates = [
    b"2026-08-04", b"2026-08-05", b"2026-08-07", b"2026-08-08",
    b"2026-08-09", b"2026-08-10", b"2026-08-11",
]
for row in rows:
    fields = row.split(b"|")
    if (
        len(fields) != 6
        or uuid.fullmatch(fields[0]) is None
        or uuid.fullmatch(fields[1]) is None
        or fields[2] != b"queued"
        or re.fullmatch(rb"[0-9]{4}-[0-9]{2}-[0-9]{2}", fields[3]) is None
        or fields[4] != b"0"
        or timestamp.fullmatch(fields[5]) is None
    ):
        raise SystemExit("frozen copy cohort evidence is malformed")
if [row.split(b"|")[3] for row in rows] != expected_dates:
    raise SystemExit("frozen copy cohort differs from the reviewed business dates")
canonical = b"\n".join(rows) + (b"\n" if rows else b"")
print(f"{len(rows)}:{hashlib.sha256(canonical).hexdigest()}")
'
}

baseline_effect_counts() {
  python3 - "$baseline_json" <<'PY'
import json
import pathlib
import sys

keys = [
    "copy_provider_unavailable_terminal", "copy_generation_attempts",
    "wecom_delivery_jobs", "wecom_delivery_attempts", "weekly_dag_runs",
    "weekly_dag_attempts", "official_account_article_runs",
    "official_account_article_attempts", "wechat_mp_draft_jobs",
    "wechat_mp_draft_items", "wechat_mp_draft_attempts",
    "claimable_copy_jobs", "running_copy_jobs", "current_business_date_copy_jobs",
    "future_copy_jobs", "pending_wecom_jobs", "pending_weekly_runs",
    "pending_official_account_runs", "pending_wechat_draft_jobs",
    "material_packages", "copy_generation_runs", "copy_generation_jobs", "delivered_wecom_jobs",
    "new_policy_topic_runs", "new_policy_topic_jobs", "new_policy_slot_runs", "new_policy_slot_jobs",
]
values = json.loads(pathlib.Path(sys.argv[1]).read_bytes())["effect_counts"]
print(":".join(str(values[key]) for key in keys))
PY
}

baseline_frozen_copy_cohort() {
  python3 - "$baseline_json" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_bytes())
print(f"{payload['frozen_copy_job_count']}:{payload['frozen_copy_job_sha256']}")
PY
}

copy_state_matches_baseline() {
  local business_date business_date_after
  [[ "$(json_string "$baseline_json" business_timezone)" == "$BUSINESS_TIMEZONE" ]] \
    || return 1
  business_date=$(current_business_date) || return 1
  [[ "$business_date" == "$(json_string "$baseline_json" business_date)" ]] \
    || return 1
  [[ "$(effect_counts "$business_date")" == "$(baseline_effect_counts)" ]] \
    || return 1
  [[ "$(frozen_copy_cohort "$business_date")" == \
      "$(baseline_frozen_copy_cohort)" ]] || return 1
  business_date_after=$(current_business_date) || return 1
  [[ "$business_date_after" == "$business_date" ]]
}

new_policy_work_absent() {
  local counts
  counts=$(effect_counts "$(current_business_date)") || return 1
  [[ "$counts" =~ ^([0-9]+:){23}0:0:0:0$ ]]
}

database_head() {
  compose exec -T postgres sh -eu -c \
    'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT version_num FROM alembic_version"' \
    </dev/null
}

verify_service_set() {
  local expected actual service container image state health restart_count
  local expected_image=$1 expected_restart_mode=$2
  expected=$(printf '%s\n' "${ALL_SERVICES[@]}" | sort)
  actual=$(compose ps --services --status running | sort) || return 1
  [[ "$actual" == "$expected" ]] || return 1
  for service in "${ALL_SERVICES[@]}"; do
    container=$(compose ps -q "$service") || return 1
    [[ -n "$container" ]] || return 1
    state=$(docker inspect --format '{{.State.Status}}' "$container") || return 1
    restart_count=$(docker inspect --format '{{.RestartCount}}' "$container") || return 1
    [[ "$state" == running ]] || return 1
    if [[ "$expected_restart_mode" == baseline ]]; then
      [[ "$restart_count" == "$(baseline_restart "$service")" ]] || return 1
    else
      [[ "$restart_count" == 0 ]] || return 1
    fi
    health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container") \
      || return 1
    [[ -z "$health" || "$health" == healthy ]] || return 1
    if [[ "$service" != postgres && "$service" != minio ]]; then
      image=$(docker inspect --format '{{.Image}}' "$container") || return 1
      [[ "$image" == "$expected_image" ]] || return 1
    fi
  done
}

verify_baseline() {
  python3 -B "${stage_dir}/${VALIDATOR_NAME}" --baseline "$baseline_json" >/dev/null \
    || die 'bound baseline no longer satisfies independent incident identities'
  primary_env_matches_baseline \
    || die 'primary environment bytes, mode, or owner drifted'
  require_mode_0600_file "$RELEASE_ENV" \
    || die 'release environment is not a physical root-owned mode-0600 file'
  require_mode_0600_file "$RELEASE_MARKER" \
    || die 'release marker is not a physical root-owned mode-0600 file'
  marker_equals "$RELEASE_MARKER" "$PRODUCTION_COMMIT" \
    || die 'production commit marker drifted'
  [[ -f "$LEGACY_RELEASE_MARKER" && ! -L "$LEGACY_RELEASE_MARKER" \
      && "$(stat -c '%a:%u:%g' "$LEGACY_RELEASE_MARKER")" == \
        "$(baseline_legacy_identity)" \
      && "$(sha256sum "$LEGACY_RELEASE_MARKER" | awk '{print $1}')" == \
        "$(json_string "$baseline_json" legacy_release_commit_sha256)" ]] \
    || die 'legacy release marker identity drifted'
  marker_equals "$LEGACY_RELEASE_MARKER" "$LEGACY_PRODUCTION_COMMIT" \
    || die 'legacy release marker value drifted'
  [[ "$(sha256sum "$PRIMARY_ENV" | awk '{print $1}')" == \
      "$(json_string "$baseline_json" primary_env_sha256)" ]] \
    || die 'primary environment drifted'
  [[ "$(sha256sum "$RELEASE_ENV" | awk '{print $1}')" == \
      "$(json_string "$baseline_json" release_env_sha256)" ]] \
    || die 'release environment drifted'
  local previous_image previous_reference repo_digests
  previous_image=$(json_string "$baseline_json" current_image_id)
  previous_reference=$(json_string "$baseline_json" current_image_reference)
  [[ "$(release_reference)" == "$previous_reference" ]] \
    || die 'active APP_IMAGE differs from the baseline RepoDigest'
  repo_digests=$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$previous_image")
  grep -Fxq "$previous_reference" <<<"$repo_digests" \
    || die 'baseline RepoDigest is not attached to the running image'
  [[ "$(docker image inspect --format '{{.Id}}' "$previous_reference")" == "$previous_image" ]] \
    || die 'baseline RepoDigest resolves to another image'
  [[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$previous_image")" == "$PRODUCTION_COMMIT" ]] \
    || die 'baseline image revision drifted'
  [[ "$(database_head)" == "$ALEMBIC_HEAD" ]] || die 'database head drifted'
  copy_state_matches_baseline \
    || die 'business date, copy cohort, or protected effect counters drifted'
  verify_current_source_baseline || die 'production source baseline drifted'
  verify_service_set "$previous_image" baseline || die 'service/image/restart baseline drifted'
  verify_runtime_settings scoring-v1-preview.11-qualified-authoritative-priority \
    || die 'actual runtime scoring or producer schedule differs from the reviewed baseline'
}

loaded_image_id_matches_candidate() {
  local loaded_id=$1
  [[ "$loaded_id" =~ ^sha256:[0-9a-f]{64}$ \
      && ( "$loaded_id" == "$candidate_manifest_digest" \
      || "$loaded_id" == "$candidate_config_digest" ) ]]
}

load_or_reuse_candidate_image() {
  local existing loaded_id repo_digests preexisting_references
  existing=$(docker image ls --quiet --no-trunc --filter "reference=${transport_tag}") \
    || { die 'candidate transport tag preflight failed'; return 1; }
  if [[ -n "$existing" ]]; then
    [[ "$(sort -u <<<"$existing" | sed '/^$/d' | wc -l)" == 1 ]] \
      || { die 'candidate transport tag resolves ambiguously'; return 1; }
    loaded_id=$(docker image inspect --format '{{.Id}}' "$transport_tag") \
      || { die 'preloaded candidate transport tag could not be inspected'; return 1; }
    loaded_image_id_matches_candidate "$loaded_id" \
      || { die 'preloaded candidate differs from the validated manifest and config digests'; return 1; }
    candidate_image_owned=0
    candidate_reference_owned=0
    candidate_owned_image_id=
  else
    preexisting_references=$(docker image ls --digests --format '{{.Repository}}@{{.Digest}}') \
      || { die 'preexisting image reference inventory failed'; return 1; }
    if grep -Fxq "$candidate_reference" <<<"$preexisting_references"; then
      candidate_reference_owned=0
    else
      candidate_reference_owned=1
    fi
    gzip -dc "${stage_dir}/backend-image.oci.tar.gz" | docker image load >/dev/null
    loaded_id=$(docker image inspect --format '{{.Id}}' "$transport_tag") \
      || { candidate_reference_owned=0; die 'validated OCI archive did not create the transport tag'; return 1; }
    loaded_image_id_matches_candidate "$loaded_id" \
      || { candidate_reference_owned=0; die 'loaded image differs from the validated manifest and config digests'; return 1; }
    candidate_owned_image_id=$loaded_id
    candidate_image_owned=1
  fi
  repo_digests=$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$transport_tag") \
    || { die 'candidate RepoDigest inventory failed'; return 1; }
  grep -Fxq "$candidate_reference" <<<"$repo_digests" \
    || { die 'derived candidate RepoDigest is absent after image load'; return 1; }
  [[ "$(docker image inspect --format '{{.Id}}' "$candidate_reference")" == "$loaded_id" ]] \
    || { die 'candidate RepoDigest resolves to another image'; return 1; }
  candidate_runtime_image_id=$loaded_id
}

load_and_verify_candidate() {
  local observed_source
  observed_source=$(mktemp /tmp/substantive-release-image-source.XXXXXX)
  transient_paths+=("$observed_source")
  rm -f -- "$observed_source"
  [[ ! -e "$observed_source" && ! -L "$observed_source" ]] \
    || die 'candidate probe output collision'
  load_or_reuse_candidate_image
  docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --env-file "$PRIMARY_ENV" \
    --env WECOM_ENABLED=false --env WECOM_AUTO_DELIVERY_ENABLED=false \
    --env AI_PLATFORM_BASE_URL=https://open.bigmodel.cn/api/paas/v4 \
    --env CONTENT_SCORING_VERSION=scoring-v1-preview.12-substantive-topic-scope \
    --env CONTENT_SCHEDULER_ENABLED=false --env GOVERNANCE_SCHEDULER_ENABLED=false \
    --env OFFICIAL_ACCOUNT_WEEKLY_SCHEDULER_ENABLED=false \
    --env OFFICIAL_ACCOUNT_WEEKLY_WORKER_ENABLED=false \
    --env OFFICIAL_ACCOUNT_LOCAL_WORKER_ENABLED=false \
    --env WECHAT_MP_DRAFT_WORKER_ENABLED=false \
    --env WECHAT_MP_DRAFT_AUTO_ENQUEUE_ENABLED=false \
    --entrypoint python "$candidate_reference" -c \
    'from app.core.config import Settings; s=Settings(_env_file=None); assert s.content_scoring_version == "scoring-v1-preview.12-substantive-topic-scope"; assert s.content_selection_priority_rule_version == "qualified-authoritative-priority-v1"; assert s.resolved_brand_embedding_provider_mode == "zhipu"; assert s.brand_embedding_model == "embedding-3"; assert s.brand_embedding_dimensions == 2048; assert not s.wecom_auto_delivery_enabled; import app.api_main, app.scheduler_main, app.worker_main, app.governance_scheduler_main, app.governance_worker_main, app.content_scheduler_main, app.content_worker_main, app.wecom_dispatcher_main, app.official_account_weekly_dag_main, app.official_account_weekly_scheduler_main, app.official_account_worker_main, app.wechat_official_account_draft_main' \
    </dev/null >/dev/null
  write_observed_image_source_manifest "$candidate_reference" "$observed_source" \
    || { die 'loaded image source manifest could not be read'; return 1; }
  cmp -s "$observed_source" "$stage_dir/image-source.sha256" \
    || { die 'loaded image source differs from the complete manifest'; return 1; }
  rm -f -- "$observed_source"
}

verify_candidate_compose() {
  local rendered
  rendered=$(mktemp /tmp/substantive-release-compose.XXXXXX)
  transient_paths+=("$rendered")
  if ! APP_IMAGE="$candidate_reference" compose config --format json >"$rendered"; then
    rm -f -- "$rendered"
    die 'candidate Compose render failed'
    return 1
  fi
  if ! python3 - "$rendered" "$candidate_reference" "$APP_DIR" "${APP_SERVICES[@]}" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
reference = sys.argv[2]
app_dir = pathlib.Path(sys.argv[3])
names = sys.argv[4:]
services = payload.get("services", {})
expected_build = {"context": str(app_dir / "backend"), "dockerfile": "Dockerfile"}
expected = {
    "acquisition-api": ["python", "-m", "uvicorn", "app.api_main:app", "--host", "0.0.0.0", "--port", "8000"],
    "acquisition-scheduler": ["python", "-m", "app.scheduler_main"],
    "acquisition-worker": ["python", "-m", "app.worker_main"],
    "governance-scheduler": ["python", "-m", "app.governance_scheduler_main"],
    "governance-worker": ["python", "-m", "app.governance_worker_main"],
    "content-scheduler": ["python", "-m", "app.content_scheduler_main"],
    "content-worker": ["python", "-m", "app.content_worker_main"],
    "wecom-dispatcher": ["python", "-m", "app.wecom_dispatcher_main"],
    "official-account-weekly-dag-worker": ["python", "-m", "app.official_account_weekly_dag_main", "--handler-mode", "production", "worker", "--concurrency", "3", "--lease-seconds", "900", "--poll-seconds", "2"],
    "official-account-weekly-scheduler": ["python", "-m", "app.official_account_weekly_scheduler_main"],
    "official-account-local-worker": ["python", "-m", "app.official_account_worker_main"],
    "wechat-official-account-draft-worker": ["python", "-m", "app.wechat_official_account_draft_main", "worker"],
}
if names != list(expected) or set(names) - set(services):
    raise SystemExit("candidate Compose topology is incomplete")
for name in names:
    service = services[name]
    if (
        service.get("image") != reference
        or service.get("build") != expected_build
        or "pull_policy" in service
        or service.get("command") != expected[name]
    ):
        raise SystemExit(
            "candidate service image, inherited build, pull policy, or command changed"
        )
PY
  then
    rm -f -- "$rendered"
    die 'candidate Compose topology validation failed'
    return 1
  fi
  rm -f -- "$rendered"
}

verify_candidate_source_compatibility() {
  if ! python3 - "$baseline_json" "$stage_dir/source-manifest.tsv" <<'PY'
import json
import pathlib
import sys

baseline_path = pathlib.Path(sys.argv[1])
manifest_path = pathlib.Path(sys.argv[2])
baseline_payload = json.loads(baseline_path.read_bytes())
baseline_rows = baseline_payload.get("source_manifest")
if not isinstance(baseline_rows, list) or not baseline_rows:
    raise SystemExit("production source baseline is absent")

baseline = {}
for row in baseline_rows:
    if not isinstance(row, dict) or set(row) != {
        "kind", "path", "mode", "uid", "gid", "sha256"
    }:
        raise SystemExit("production source baseline row changed")
    name = row["path"]
    if not isinstance(name, str) or name in baseline:
        raise SystemExit("production source baseline path changed")
    baseline[name] = row

candidate = {}
for line in manifest_path.read_text(encoding="utf-8").splitlines():
    pieces = line.split("\t")
    if len(pieces) != 4:
        raise SystemExit("candidate source manifest row changed")
    kind, raw_mode, _checksum, name = pieces
    if name in candidate:
        raise SystemExit("candidate source manifest path is duplicated")
    try:
        mode = int(raw_mode, 8)
    except ValueError as error:
        raise SystemExit("candidate source manifest mode changed") from error
    if (kind == "d" and mode != 0o755) or (
        kind == "f" and mode not in {0o644, 0o755}
    ):
        raise SystemExit("candidate source manifest mode changed")
    if kind not in {"d", "f"}:
        raise SystemExit("candidate source manifest type changed")
    candidate[name] = (kind, mode)

missing = set(baseline) - set(candidate)
if missing:
    raise SystemExit("candidate source omits a captured production path")
for name, previous in baseline.items():
    kind, semantic_mode = candidate[name]
    if previous["kind"] != kind:
        raise SystemExit("candidate source type differs from production")
    if kind == "f" and bool(previous["mode"] & 0o111) != bool(
        semantic_mode & 0o111
    ):
        raise SystemExit("candidate executable class differs from production")
PY
  then
    die 'candidate source compatibility validation failed'
    return 1
  fi
}

prepare_roots_and_attempt() {
  [[ $EUID -eq 0 ]] || die 'activation requires root'
  local root reserved
  for root in "$BACKUP_ROOT" "$ATTEMPT_ROOT"; do
    [[ ! -L "$root" && "$(realpath -e -- "$(dirname -- "$root")")" == "$(dirname -- "$root")" ]] \
      || die 'release trust-root parent is linked or missing'
    if [[ -e "$root" ]]; then
      [[ -d "$root" && "$(stat -c '%a:%u:%g' "$root")" == 700:0:0 ]] \
        || die 'existing release trust root has an unreviewed identity'
    else
      install -d -o root -g root -m 700 "$root"
    fi
  done
  [[ ! -L "$BACKUP_ROOT" && "$(realpath -e -- "$BACKUP_ROOT")" == "$BACKUP_ROOT" \
      && "$(stat -c '%a:%u:%g:%d' "$BACKUP_ROOT")" == 700:0:0:"$(stat -c '%d' "$APP_DIR")" ]] \
    || die 'fixed backup root is not a physical same-filesystem root-owned mode-0700 directory'
  backup_root_identity=$(stat -c '%d:%i' "$BACKUP_ROOT")
  reserved=$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 \
    -name '.substantive-release-tmp.*' -printf x -quit) \
    || die 'reserved workspace namespace could not be scanned safely'
  [[ -z "$reserved" ]] || die 'stale reserved release workspace exists'
  [[ "$(stat -c '%d:%i' "$BACKUP_ROOT")" == "$backup_root_identity" ]] \
    || die 'backup root changed during namespace scan'
  attempt_marker="${ATTEMPT_ROOT}/${release_commit}.substantive-release-attempted"
  [[ ! -e "$attempt_marker" && ! -L "$attempt_marker" ]] || die 'candidate was already attempted'
  (set -o noclobber; printf 'attempted_at=%s\n' "$(date -u +%FT%TZ)" >"$attempt_marker") \
    || die 'candidate attempt marker collided'
  chmod 600 "$attempt_marker"
  backup_dir="${BACKUP_ROOT}/substantive-release-${release_commit:0:12}-$(date -u +%Y%m%dT%H%M%SZ)"
  [[ ! -e "$backup_dir" && ! -L "$backup_dir" ]] || die 'backup identity collided'
  install -d -o root -g root -m 700 "$backup_dir"
  cp -a "$PRIMARY_ENV" "$backup_dir/env.before"
  cp -a "$RELEASE_ENV" "$backup_dir/release.env.before"
  cp -a "$RELEASE_MARKER" "$backup_dir/release-commit.before"
  cp -a "$LEGACY_RELEASE_MARKER" "$backup_dir/legacy-release-commit.before"
  primary_env_matches_baseline "$backup_dir/env.before" \
    || die 'primary environment backup did not preserve bytes, mode, and owner'
}

prepare_candidate_source() {
  local candidate_root="${workspace}/candidate"
  install -d -o root -g root -m 700 "$candidate_root"
  tar -xzf "$stage_dir/source.tar.gz" -C "$candidate_root" --no-same-owner --no-same-permissions
  python3 - "$candidate_root" "$baseline_json" "$stage_dir/source-manifest.tsv" <<'PY'
import json
import os
import pathlib
import stat
import sys

root = pathlib.Path(sys.argv[1]).resolve(strict=True)
baseline = {
    row["path"]: row
    for row in json.loads(pathlib.Path(sys.argv[2]).read_bytes())["source_manifest"]
}
candidate = {}
for line in pathlib.Path(sys.argv[3]).read_text(encoding="utf-8").splitlines():
    kind, raw_mode, checksum, name = line.split("\t")
    candidate[name] = (kind, int(raw_mode, 8))
if set(baseline) - set(candidate):
    raise SystemExit("candidate source omits a captured production path")
for name in sorted(candidate, key=lambda value: (value.count("/"), value)):
    kind, semantic_mode = candidate[name]
    path = root / name
    if path.is_symlink() or (kind == "f" and not path.is_file()) or (
        kind == "d" and not path.is_dir()
    ):
        raise SystemExit("candidate source shape changed after extraction")
    previous = baseline.get(name)
    if previous is None:
        uid = gid = 0
        mode = 0o700 if kind == "d" or semantic_mode & 0o111 else 0o600
    else:
        if previous["kind"] != kind:
            raise SystemExit("candidate source type differs from production")
        if kind == "f" and bool(previous["mode"] & 0o111) != bool(semantic_mode & 0o111):
            raise SystemExit("candidate executable class differs from production")
        uid, gid, mode = previous["uid"], previous["gid"], previous["mode"]
    os.chown(path, uid, gid, follow_symlinks=False)
    os.chmod(path, mode, follow_symlinks=False)
PY
}

quiesce_and_backup() {
  recovery_armed=1
  compose stop -t 90 "${STOP_ORDER[@]}"
  "${APP_DIR}/scripts/edu-ai-backup.sh" </dev/null
}

verify_quiesced_baseline() {
  primary_env_matches_baseline \
    && require_mode_0600_file "$RELEASE_ENV" \
    && require_mode_0600_file "$RELEASE_MARKER" \
    || return 1
  marker_equals "$RELEASE_MARKER" "$PRODUCTION_COMMIT" || return 1
  [[ -f "$LEGACY_RELEASE_MARKER" && ! -L "$LEGACY_RELEASE_MARKER" \
      && "$(stat -c '%a:%u:%g' "$LEGACY_RELEASE_MARKER")" == \
        "$(baseline_legacy_identity)" \
      && "$(sha256sum "$LEGACY_RELEASE_MARKER" | awk '{print $1}')" == \
        "$(json_string "$baseline_json" legacy_release_commit_sha256)" ]] \
    || return 1
  marker_equals "$LEGACY_RELEASE_MARKER" "$LEGACY_PRODUCTION_COMMIT" || return 1
  [[ "$(sha256sum "$PRIMARY_ENV" | awk '{print $1}')" == \
      "$(json_string "$baseline_json" primary_env_sha256)" \
      && "$(sha256sum "$RELEASE_ENV" | awk '{print $1}')" == \
        "$(json_string "$baseline_json" release_env_sha256)" ]] \
    || return 1
  [[ "$(database_head)" == "$ALEMBIC_HEAD" ]] || return 1
  copy_state_matches_baseline || return 1
  verify_current_source_baseline || return 1
}

activate_source() {
  local name candidate_root="${workspace}/candidate"
  install -d -o root -g root -m 700 "$backup_dir/source.before" "$backup_dir/failed-candidate"
  : >"$backup_dir/activation-started"
  source_activated=1
  for name in "${MANAGED_DIRS[@]}" "${MANAGED_FILES[@]}"; do
    [[ -e "$APP_DIR/$name" && ! -L "$APP_DIR/$name" \
        && -e "$candidate_root/$name" && ! -L "$candidate_root/$name" ]] \
      || die "source activation shape changed: $name"
    printf '%s\n' "$name" >>"$backup_dir/activation-started"
    mv -T "$APP_DIR/$name" "$backup_dir/source.before/$name"
    mv -T "$candidate_root/$name" "$APP_DIR/$name"
  done
  write_commit_marker "$RELEASE_MARKER" "$release_commit"
  write_commit_marker "$LEGACY_RELEASE_MARKER" "$release_commit"
}

write_commit_marker() {
  local destination=$1 value=$2 temporary
  temporary=$(mktemp "${destination}.substantive-release.XXXXXX")
  printf '%s\n' "$value" >"$temporary"
  chown root:root "$temporary"
  chmod 600 "$temporary"
  mv -T "$temporary" "$destination"
}

verify_candidate_identity_markers() {
  [[ -f "$RELEASE_MARKER" && ! -L "$RELEASE_MARKER" \
      && "$(stat -c '%a:%u:%g' "$RELEASE_MARKER")" == 600:0:0 ]] \
    || return 1
  [[ -f "$LEGACY_RELEASE_MARKER" && ! -L "$LEGACY_RELEASE_MARKER" \
      && "$(stat -c '%a:%u:%g' "$LEGACY_RELEASE_MARKER")" == 600:0:0 ]] \
    || return 1
  marker_equals "$RELEASE_MARKER" "$release_commit" || return 1
  marker_equals "$LEGACY_RELEASE_MARKER" "$release_commit" || return 1
  [[ "$(docker image inspect --format \
      '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
      "$candidate_reference")" == "$release_commit" ]] || return 1
}

verify_installed_source() {
  python3 - "$APP_DIR" "$baseline_json" "$stage_dir/source-manifest.tsv" <<'PY'
import hashlib
import json
import pathlib
import stat
import sys

root = pathlib.Path(sys.argv[1]).resolve(strict=True)
baseline = {
    row["path"]: row
    for row in json.loads(pathlib.Path(sys.argv[2]).read_bytes())["source_manifest"]
}
for line in pathlib.Path(sys.argv[3]).read_text(encoding="utf-8").splitlines():
    kind, raw_mode, checksum, name = line.split("\t")
    semantic_mode = int(raw_mode, 8)
    path = root / name
    if path.is_symlink() or (kind == "f" and not path.is_file()) or (
        kind == "d" and not path.is_dir()
    ):
        raise SystemExit("installed source shape changed")
    metadata = path.lstat()
    previous = baseline.get(name)
    if previous is None:
        expected_uid = expected_gid = 0
        expected_mode = 0o700 if kind == "d" or semantic_mode & 0o111 else 0o600
    else:
        expected_uid = previous["uid"]
        expected_gid = previous["gid"]
        expected_mode = previous["mode"]
    if (
        metadata.st_uid != expected_uid
        or metadata.st_gid != expected_gid
        or stat.S_IMODE(metadata.st_mode) != expected_mode
    ):
        raise SystemExit("installed source owner or mode changed")
    if kind == "f" and hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
        raise SystemExit("installed source bytes changed")
PY
}

write_candidate_release_env() {
  local temporary
  temporary=$(mktemp "${APP_DIR}/.release.env.substantive-release.XXXXXX")
  printf 'APP_IMAGE=%s\n' "$candidate_reference" >"$temporary"
  chown root:root "$temporary"
  chmod 600 "$temporary"
  mv -T "$temporary" "$RELEASE_ENV"
}

restore_primary_environment_from_backup() {
  python3 -B "${stage_dir}/${VALIDATOR_NAME}" --restore-environment \
    "$backup_dir/env.before" "$PRIMARY_ENV" "$candidate_primary_env_sha256" >/dev/null \
    || return 1
  primary_env_matches_baseline
}

restore_previous_state() {
  local name
  compose stop -t 30 "${STOP_ORDER[@]}" >/dev/null 2>&1 || return 1
  require_safe_window || return 1
  new_policy_work_absent || return 1
  copy_state_matches_baseline || return 1
  [[ "$(database_head)" == "$ALEMBIC_HEAD" ]] || return 1
  if ((source_activated == 1)); then
    while IFS= read -r name; do
      [[ -n "$name" && "$name" != */* ]] || return 1
      # A failed first rename leaves the original in place. Do not move that
      # surviving original away; the full source-baseline verification below
      # proves it is still exact before any old-code process can start.
      [[ -e "$backup_dir/source.before/$name" ]] || continue
      if [[ -e "$APP_DIR/$name" || -L "$APP_DIR/$name" ]]; then
        [[ ! -L "$APP_DIR/$name" ]] || return 1
        mv -T "$APP_DIR/$name" "$backup_dir/failed-candidate/$name" || return 1
      fi
      [[ -e "$backup_dir/source.before/$name" \
          && ! -L "$backup_dir/source.before/$name" ]] || return 1
      mv -T "$backup_dir/source.before/$name" "$APP_DIR/$name" || return 1
    done <"$backup_dir/activation-started"
  fi
  restore_primary_environment_from_backup || return 1
  cp -a "$backup_dir/release.env.before" "$RELEASE_ENV" || return 1
  cp -a "$backup_dir/release-commit.before" "$RELEASE_MARKER" || return 1
  cp -a "$backup_dir/legacy-release-commit.before" "$LEGACY_RELEASE_MARKER" || return 1
  source_activated=0
  verify_current_source_baseline || return 1
  copy_state_matches_baseline || return 1
  [[ "$(database_head)" == "$ALEMBIC_HEAD" ]] || return 1
  compose up -d --no-build --no-deps "${APP_SERVICES[@]}" >/dev/null || return 1
  local deadline=$(( $(date +%s) + 90 ))
  until verify_service_set "$(json_string "$baseline_json" current_image_id)" baseline; do
    (( $(date +%s) < deadline )) || return 1
    sleep 2
  done
  primary_env_matches_baseline || return 1
  [[ "$(sha256sum "$RELEASE_ENV" | awk '{print $1}')" == \
      "$(json_string "$baseline_json" release_env_sha256)" ]] || return 1
  [[ "$(sha256sum "$LEGACY_RELEASE_MARKER" | awk '{print $1}')" == \
      "$(json_string "$baseline_json" legacy_release_commit_sha256)" \
      && "$(stat -c '%a:%u:%g' "$LEGACY_RELEASE_MARKER")" == \
        "$(baseline_legacy_identity)" ]] || return 1
  marker_equals "$LEGACY_RELEASE_MARKER" "$LEGACY_PRODUCTION_COMMIT" || return 1
  marker_equals "$RELEASE_MARKER" "$PRODUCTION_COMMIT" || return 1
  verify_runtime_settings scoring-v1-preview.11-qualified-authoritative-priority || return 1
  new_policy_work_absent || return 1
  copy_state_matches_baseline || return 1
  [[ "$(database_head)" == "$ALEMBIC_HEAD" ]] || return 1
}

stop_writers_for_incident() {
  compose stop -t 30 "${STOP_ORDER[@]}" >/dev/null 2>&1 || true
}

cleanup_workspace() {
  [[ -n "${workspace:-}" ]] || return 0
  [[ "$backup_root_identity" =~ ^[0-9]+:[0-9]+$ \
      && ! -L "$BACKUP_ROOT" && -d "$BACKUP_ROOT" \
      && "$(realpath -e -- "$BACKUP_ROOT")" == "$BACKUP_ROOT" \
      && "$(stat -c '%a:%u:%g:%d:%i' "$BACKUP_ROOT")" == "700:0:0:${backup_root_identity}" \
      && "$(stat -c '%d' "$BACKUP_ROOT")" == "$(stat -c '%d' "$APP_DIR")" ]] || return 0
  [[ "$workspace" =~ ^${BACKUP_ROOT}/\.substantive-release-tmp\.[A-Za-z0-9]{6}$ \
      && -d "$workspace" && ! -L "$workspace" \
      && "$(stat -c '%a:%u:%g' "$workspace")" == 700:0:0 ]] || return 0
  python3 - "$BACKUP_ROOT" "$workspace" "$backup_root_identity" <<'PY' >/dev/null 2>&1 || true
import os
from pathlib import Path
import re
import shutil
import stat
import sys

root, workspace = map(Path, sys.argv[1:3])
expected = tuple(map(int, sys.argv[3].split(":")))
if (
    not shutil.rmtree.avoids_symlink_attacks
    or root.resolve(strict=True) != root
    or workspace.parent != root
    or re.fullmatch(r"\.substantive-release-tmp\.[A-Za-z0-9]{6}", workspace.name) is None
):
    raise SystemExit(1)
descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    identity = os.fstat(descriptor)
    if (identity.st_dev, identity.st_ino) != expected or (
        stat.S_IMODE(identity.st_mode), identity.st_uid, identity.st_gid
    ) != (0o700, 0, 0):
        raise SystemExit(1)
    child = os.stat(workspace.name, dir_fd=descriptor, follow_symlinks=False)
    if not stat.S_ISDIR(child.st_mode) or (
        stat.S_IMODE(child.st_mode), child.st_uid, child.st_gid
    ) != (0o700, 0, 0):
        raise SystemExit(1)
    # Descriptor-relative, symlink-safe removal cannot follow a replaced root.
    shutil.rmtree(workspace.name, dir_fd=descriptor)
finally:
    os.close(descriptor)
PY
}

on_exit() {
  local rc=$?
  ((rc != 0 && completed == 0 && recovery_armed == 1)) || return 0
  local head=
  head=$(database_head 2>/dev/null || true)
  if [[ "$head" == "$ALEMBIC_HEAD" ]]; then
    log 'activation failed; quiesce and prove zero new-policy work before old-code restoration'
    if restore_previous_state; then
      log 'previous source, environments, image, services, and counters restored'
      return 0
    fi
  fi
  log 'automatic recovery could not prove safety; application writers remain stopped'
  stop_writers_for_incident
}

wait_for_candidate() {
  local deadline=$(( $(date +%s) + 90 ))
  until verify_service_set "$candidate_runtime_image_id" zero; do
    (( $(date +%s) < deadline )) || return 1
    sleep 2
  done
}

write_evidence() {
  local evidence="$backup_dir/substantive-release-activation-evidence.txt"
  local terminal_count frozen_copy frozen_count frozen_digest
  terminal_count=$(baseline_effect_counts)
  terminal_count=${terminal_count%%:*}
  frozen_copy=$(baseline_frozen_copy_cohort)
  frozen_count=${frozen_copy%%:*}
  frozen_digest=${frozen_copy#*:}
  {
    printf 'schema_version=1\nrelease_commit=%s\n' "$release_commit"
    printf 'candidate_reference=%s\nalembic_head=%s\n' "$candidate_reference" "$ALEMBIC_HEAD"
    printf 'application_services=12\ncopy_provider_unavailable_terminal=%s\n' "$terminal_count"
    printf 'business_timezone=%s\nbusiness_date=%s\n' \
      "$BUSINESS_TIMEZONE" "$(json_string "$baseline_json" business_date)"
    printf 'frozen_copy_job_count=%s\nfrozen_copy_job_sha256=%s\n' \
      "$frozen_count" "$frozen_digest"
    printf 'claimable_copy_jobs=0\nrunning_copy_jobs=0\ncurrent_business_date_copy_jobs=0\n'
    printf 'effect_counters_unchanged=true\nprimary_env_only_scoring_version_changed=true\n'
    printf 'old_scoring_version=scoring-v1-preview.11-qualified-authoritative-priority\n'
    printf 'new_scoring_version=scoring-v1-preview.12-substantive-topic-scope\n'
    printf 'candidate_primary_env_sha256=%s\nnew_policy_runs_jobs=0\n' "$candidate_primary_env_sha256"
    printf 'migration_invocations=1\nprovider_calls=0\nsend_calls=0\nreplay_calls=0\n'
    printf 'completed_at=%s\n' "$(date -u +%FT%TZ)"
  } >"$evidence"
  chown root:root "$evidence"
  chmod 600 "$evidence"
}

reject_repeat() {
  [[ ! -e "${ATTEMPT_ROOT}/${release_commit}.substantive-release-attempted" \
      && ! -L "${ATTEMPT_ROOT}/${release_commit}.substantive-release-attempted" ]] \
    || die 'candidate was already attempted'
}

run_activation() {
  # The read-only preflight precedes the release lock. Recheck under that lock so
  # a competing release or late operator drift cannot authorize stale mutation.
  verify_baseline
  require_safe_window
  capture_environment_plan
  # Recheck archive-to-destination type/mode compatibility before consuming the
  # one-shot attempt identity. prepare_candidate_source repeats the invariant
  # after extraction and before any writer is stopped.
  verify_candidate_source_compatibility
  prepare_roots_and_attempt
  workspace=$(mktemp -d "${BACKUP_ROOT}/.substantive-release-tmp.XXXXXX")
  [[ "$(stat -c '%a:%u:%g' "$workspace")" == 700:0:0 ]] \
    || die 'release workspace identity changed'
  trap 'on_exit; cleanup_workspace; cleanup_candidate_image; cleanup_transient_paths' EXIT
  prepare_candidate_source
  require_safe_window
  verify_baseline
  quiesce_and_backup
  verify_quiesced_baseline \
    || die 'production baseline drifted after quiescence and backup'
  require_safe_window
  activate_source
  verify_installed_source
  write_candidate_release_env
  activate_primary_environment
  primary_env_matches_candidate \
    || die 'primary environment drifted immediately before migration'
  copy_state_matches_baseline \
    || die 'copy state drifted immediately before migration'
  migration_attempted=1
  compose run --rm --no-deps -T backend-migrate </dev/null
  [[ "$(database_head)" == "$ALEMBIC_HEAD" ]] || die 'database head changed after migration'
  require_safe_window
  primary_env_matches_candidate \
    || die 'primary environment drifted immediately before service start'
  copy_state_matches_baseline \
    || die 'copy state drifted immediately before service start'
  compose up -d --no-build --no-deps "${APP_SERVICES[@]}"
  wait_for_candidate || die 'candidate services did not converge within the readiness bound'
  require_safe_window
  copy_state_matches_baseline \
    || die 'activation changed business date, copy cohort, or a protected effect counter'
  primary_env_matches_candidate \
    || die 'activation differs from the exact single-key environment plan'
  [[ "$(release_reference)" == "$candidate_reference" ]] \
    || die 'candidate RepoDigest did not survive release environment installation'
  verify_candidate_identity_markers \
    || die 'candidate full/legacy markers and OCI revision disagree'
  verify_runtime_settings scoring-v1-preview.12-substantive-topic-scope \
    || die 'candidate runtime scoring or producer schedule did not converge'
  copy_state_matches_baseline || die 'protected state changed during final runtime verification'
  require_safe_window
  write_evidence
  completed=1
  log "activation completed release_commit=${release_commit} application_services=12"
}

main() {
  parse_args "$@"
  require_physical_operator
  validate_stage
  require_safe_window
  verify_baseline
  capture_environment_plan
  verify_candidate_source_compatibility
  load_and_verify_candidate
  verify_candidate_compose
  reject_repeat
  if ((preflight_only == 1)); then
    log "preflight completed release_commit=${release_commit} candidate_reference=${candidate_reference}"
    return 0
  fi
  [[ $EUID -eq 0 ]] || die 'activation requires root'
  exec {release_lock_fd}>"$RELEASE_LOCK"
  flock --nonblock "$release_lock_fd" || die 'release lock is busy'
  run_activation
}

if [[ "${SUBSTANTIVE_RELEASE_OPERATOR_SOURCE_ONLY:-0}" != 1 ]]; then
  trap 'cleanup_candidate_image; cleanup_transient_paths' EXIT
  main "$@"
fi
