#!/usr/bin/env bash
# One-shot root operator for the brand-embedding production incident release.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077
export LC_ALL=C

operator_app_dir=/opt/edu-ai-lead-agent
operator_backup_root=/opt/edu-ai-release-backups
operator_attempt_root=/var/lib/edu-ai-release-attempts
operator_lock=/var/lock/edu-ai-brand-embedding-release.lock
if [[ "${BRAND_HOTFIX_OPERATOR_SOURCE_ONLY:-0}" == 1 ]]; then
  [[ -n "${BRAND_HOTFIX_OPERATOR_TEST_ROOT:-}" ]] || {
    printf '%s\n' '[brand-embedding-release] ERROR: test root is absent' >&2
    return 1 2>/dev/null || exit 1
  }
  operator_app_dir="${BRAND_HOTFIX_OPERATOR_TEST_ROOT}/app"
  operator_backup_root="${BRAND_HOTFIX_OPERATOR_TEST_ROOT}/backups"
  operator_attempt_root="${BRAND_HOTFIX_OPERATOR_TEST_ROOT}/attempts"
  operator_lock="${BRAND_HOTFIX_OPERATOR_TEST_ROOT}/release.lock"
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
readonly PRODUCTION_COMMIT=40e4dec0ae82569fc798355d4515ab0009697c6f
readonly LEGACY_PRODUCTION_COMMIT=7a45a65
readonly ALEMBIC_HEAD=20260901_0042
readonly ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4
readonly OPERATOR_NAME=brand-embedding-hotfix-offline-release-operator.sh
readonly VALIDATOR_NAME=validate-brand-embedding-hotfix-offline-artifacts.py
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
candidate_reference=
workspace=
backup_dir=
attempt_marker=
recovery_armed=0
source_activated=0
migration_attempted=0
completed=0
declare -a transient_paths=()

log() { printf '[brand-embedding-release] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; return 1; }

cleanup_transient_paths() {
  local path
  for path in "${transient_paths[@]}"; do
    case "$path" in
      /tmp/brand-hotfix-source-observed.??????|\
      /tmp/brand-hotfix-source-expected.??????|\
      /tmp/brand-hotfix-image-source.??????|\
      /tmp/brand-hotfix-compose.??????)
        rm -f -- "$path" >/dev/null 2>&1 || true
        ;;
    esac
  done
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
  [[ "$release_commit" =~ ^[0-9a-f]{40}$ \
      && "$candidate_config_digest" =~ ^sha256:[0-9a-f]{64}$ \
      && "$candidate_reference" =~ ^[^@[:space:]]+@sha256:[0-9a-f]{64}$ ]] \
    || die 'validated candidate identity could not be read'
  [[ "$(json_string "$metadata_json" scheduler_cutoff_utc)" == "$scheduler_cutoff_utc" ]] \
    || die 'operator cutoff differs from the checksum-bound cutoff'
}

require_safe_window() {
  python3 - "$scheduler_cutoff_utc" <<'PY'
from datetime import UTC, datetime, timedelta
import sys

cutoff = datetime.strptime(sys.argv[1], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
if cutoff <= datetime.now(UTC) + timedelta(minutes=15):
    raise SystemExit("scheduler cutoff leaves less than fifteen minutes")
PY
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

verify_current_source_baseline() {
  local source_observed source_expected
  source_observed=$(mktemp /tmp/brand-hotfix-source-observed.XXXXXX)
  source_expected=$(mktemp /tmp/brand-hotfix-source-expected.XXXXXX)
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

effect_counts() {
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
        (SELECT count(*) FROM copy_generation_jobs WHERE status IN ('\''queued'\'', '\''running'\'', '\''retry_scheduled'\''))::text || '\'':'\'' ||
        (SELECT count(*) FROM wecom_delivery_jobs WHERE status IN ('\''queued'\'', '\''running'\'', '\''partial'\'', '\''delivery_unknown'\''))::text || '\'':'\'' ||
        (SELECT count(*) FROM official_account_weekly_dag_runs WHERE status IN ('\''pending'\'', '\''running'\'', '\''partial'\'', '\''retryable_failed'\''))::text || '\'':'\'' ||
        (SELECT count(*) FROM official_account_article_runs WHERE status IN ('\''queued'\'', '\''running'\''))::text || '\'':'\'' ||
        (SELECT count(*) FROM wechat_mp_draft_jobs WHERE status IN ('\''queued'\'', '\''running'\'', '\''retryable_failed'\''))::text
    "' </dev/null
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
    "pending_copy_jobs", "pending_wecom_jobs", "pending_weekly_runs",
    "pending_official_account_runs", "pending_wechat_draft_jobs",
]
values = json.loads(pathlib.Path(sys.argv[1]).read_bytes())["effect_counts"]
print(":".join(str(values[key]) for key in keys))
PY
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
  require_mode_0600_file "$PRIMARY_ENV" \
    || die 'primary environment is not a physical root-owned mode-0600 file'
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
  [[ "$(effect_counts)" == "$(baseline_effect_counts)" ]] || die 'effect counters drifted'
  verify_current_source_baseline || die 'production source baseline drifted'
  verify_service_set "$previous_image" baseline || die 'service/image/restart baseline drifted'
}

load_and_verify_candidate() {
  local loaded_id repo_digests observed_source
  observed_source=$(mktemp /tmp/brand-hotfix-image-source.XXXXXX)
  transient_paths+=("$observed_source")
  rm -f -- "$observed_source"
  [[ ! -e "$observed_source" && ! -L "$observed_source" ]] \
    || die 'candidate probe output collision'
  gzip -dc "${stage_dir}/backend-image.oci.tar.gz" | docker image load >/dev/null
  loaded_id=$(docker image inspect --format '{{.Id}}' "$transport_tag")
  [[ "$loaded_id" == "$candidate_config_digest" ]] \
    || die 'loaded image differs from the validated config digest'
  repo_digests=$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$transport_tag")
  grep -Fxq "$candidate_reference" <<<"$repo_digests" \
    || die 'derived candidate RepoDigest is absent after image load'
  [[ "$(docker image inspect --format '{{.Id}}' "$candidate_reference")" == "$candidate_config_digest" ]] \
    || die 'candidate RepoDigest resolves to another image'
  docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --env-file "$PRIMARY_ENV" \
    --env WECOM_ENABLED=false --env WECOM_AUTO_DELIVERY_ENABLED=false \
    --env AI_PLATFORM_BASE_URL=https://open.bigmodel.cn/api/paas/v4 \
    --env CONTENT_SCHEDULER_ENABLED=false --env GOVERNANCE_SCHEDULER_ENABLED=false \
    --env OFFICIAL_ACCOUNT_WEEKLY_SCHEDULER_ENABLED=false \
    --env OFFICIAL_ACCOUNT_WEEKLY_WORKER_ENABLED=false \
    --env OFFICIAL_ACCOUNT_LOCAL_WORKER_ENABLED=false \
    --env WECHAT_MP_DRAFT_WORKER_ENABLED=false \
    --env WECHAT_MP_DRAFT_AUTO_ENQUEUE_ENABLED=false \
    --entrypoint python "$candidate_reference" -c \
    'from app.core.config import Settings; s=Settings(_env_file=None); assert s.resolved_brand_embedding_provider_mode == "zhipu"; assert s.brand_embedding_model == "embedding-3"; assert s.brand_embedding_dimensions == 2048; assert not s.wecom_auto_delivery_enabled; import app.api_main, app.scheduler_main, app.worker_main, app.governance_scheduler_main, app.governance_worker_main, app.content_scheduler_main, app.content_worker_main, app.wecom_dispatcher_main, app.official_account_weekly_dag_main, app.official_account_weekly_scheduler_main, app.official_account_worker_main, app.wechat_official_account_draft_main' \
    </dev/null >/dev/null
  docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint python "$candidate_reference" -c \
    'import hashlib,pathlib; root=pathlib.Path("/app"); paths=[root/"alembic.ini",root/"pyproject.toml"]; paths += [p for base in (root/"app",root/"alembic") for p in base.rglob("*") if p.is_file() and p.suffix in {".py",".html"}]; print("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(root).as_posix()}\\n" for p in sorted(set(paths))),end="")' \
    </dev/null >"$observed_source"
  cmp -s "$observed_source" "$stage_dir/image-source.sha256" \
    || die 'loaded image source differs from the complete manifest'
  rm -f -- "$observed_source"
}

verify_candidate_compose() {
  local rendered
  rendered=$(mktemp /tmp/brand-hotfix-compose.XXXXXX)
  transient_paths+=("$rendered")
  if ! APP_IMAGE="$candidate_reference" compose config --format json >"$rendered"; then
    rm -f -- "$rendered"
    die 'candidate Compose render failed'
    return 1
  fi
  if ! python3 - "$rendered" "$candidate_reference" "${APP_SERVICES[@]}" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
reference = sys.argv[2]
names = sys.argv[3:]
services = payload.get("services", {})
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
        or "build" in service
        or service.get("command") != expected[name]
    ):
        raise SystemExit("candidate service image or command changed")
PY
  then
    rm -f -- "$rendered"
    die 'candidate Compose topology validation failed'
    return 1
  fi
  rm -f -- "$rendered"
}

prepare_roots_and_attempt() {
  [[ $EUID -eq 0 ]] || die 'activation requires root'
  install -d -o root -g root -m 700 "$BACKUP_ROOT" "$ATTEMPT_ROOT"
  [[ ! -L "$BACKUP_ROOT" && "$(realpath -e -- "$BACKUP_ROOT")" == "$BACKUP_ROOT" \
      && "$(stat -c '%a:%u:%g:%d' "$BACKUP_ROOT")" == 700:0:0:"$(stat -c '%d' "$APP_DIR")" ]] \
    || die 'fixed backup root is not a physical same-filesystem root-owned mode-0700 directory'
  if find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -name '.brand-embedding-tmp.*' -print -quit \
      | grep -q .; then
    die 'stale reserved release workspace exists'
  fi
  attempt_marker="${ATTEMPT_ROOT}/${release_commit}.brand-embedding-attempted"
  [[ ! -e "$attempt_marker" && ! -L "$attempt_marker" ]] || die 'candidate was already attempted'
  (set -o noclobber; printf 'attempted_at=%s\n' "$(date -u +%FT%TZ)" >"$attempt_marker") \
    || die 'candidate attempt marker collided'
  chmod 600 "$attempt_marker"
  backup_dir="${BACKUP_ROOT}/brand-embedding-${release_commit:0:12}-$(date -u +%Y%m%dT%H%M%SZ)"
  [[ ! -e "$backup_dir" && ! -L "$backup_dir" ]] || die 'backup identity collided'
  install -d -o root -g root -m 700 "$backup_dir"
  cp -a "$PRIMARY_ENV" "$backup_dir/env.before"
  cp -a "$RELEASE_ENV" "$backup_dir/release.env.before"
  cp -a "$RELEASE_MARKER" "$backup_dir/release-commit.before"
  cp -a "$LEGACY_RELEASE_MARKER" "$backup_dir/legacy-release-commit.before"
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
  require_mode_0600_file "$PRIMARY_ENV" \
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
  [[ "$(effect_counts)" == "$(baseline_effect_counts)" ]] || return 1
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
  temporary=$(mktemp "${destination}.brand-embedding.XXXXXX")
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
  temporary=$(mktemp "${APP_DIR}/.release.env.brand-embedding.XXXXXX")
  printf 'APP_IMAGE=%s\n' "$candidate_reference" >"$temporary"
  chown root:root "$temporary"
  chmod 600 "$temporary"
  mv -T "$temporary" "$RELEASE_ENV"
}

restore_previous_state() {
  local name
  compose stop -t 30 "${STOP_ORDER[@]}" >/dev/null 2>&1 || return 1
  if ((source_activated == 1)); then
    while IFS= read -r name; do
      [[ -n "$name" && "$name" != */* ]] || return 1
      if [[ -e "$APP_DIR/$name" || -L "$APP_DIR/$name" ]]; then
        [[ ! -L "$APP_DIR/$name" ]] || return 1
        mv -T "$APP_DIR/$name" "$backup_dir/failed-candidate/$name" || return 1
      fi
      [[ -e "$backup_dir/source.before/$name" \
          && ! -L "$backup_dir/source.before/$name" ]] || return 1
      mv -T "$backup_dir/source.before/$name" "$APP_DIR/$name" || return 1
    done <"$backup_dir/activation-started"
  fi
  cp -a "$backup_dir/env.before" "$PRIMARY_ENV" || return 1
  cp -a "$backup_dir/release.env.before" "$RELEASE_ENV" || return 1
  cp -a "$backup_dir/release-commit.before" "$RELEASE_MARKER" || return 1
  cp -a "$backup_dir/legacy-release-commit.before" "$LEGACY_RELEASE_MARKER" || return 1
  source_activated=0
  compose up -d --no-build --no-deps "${APP_SERVICES[@]}" >/dev/null || return 1
  local deadline=$(( $(date +%s) + 90 ))
  until verify_service_set "$(json_string "$baseline_json" current_image_id)" baseline; do
    (( $(date +%s) < deadline )) || return 1
    sleep 2
  done
  [[ "$(sha256sum "$PRIMARY_ENV" | awk '{print $1}')" == \
      "$(json_string "$baseline_json" primary_env_sha256)" ]] || return 1
  [[ "$(sha256sum "$RELEASE_ENV" | awk '{print $1}')" == \
      "$(json_string "$baseline_json" release_env_sha256)" ]] || return 1
  [[ "$(sha256sum "$LEGACY_RELEASE_MARKER" | awk '{print $1}')" == \
      "$(json_string "$baseline_json" legacy_release_commit_sha256)" \
      && "$(stat -c '%a:%u:%g' "$LEGACY_RELEASE_MARKER")" == \
        "$(baseline_legacy_identity)" ]] || return 1
  marker_equals "$LEGACY_RELEASE_MARKER" "$LEGACY_PRODUCTION_COMMIT" || return 1
  [[ "$(effect_counts)" == "$(baseline_effect_counts)" ]] || return 1
  [[ "$(database_head)" == "$ALEMBIC_HEAD" ]] || return 1
}

stop_writers_for_incident() {
  compose stop -t 30 "${STOP_ORDER[@]}" >/dev/null 2>&1 || true
}

cleanup_workspace() {
  [[ -n "${workspace:-}" ]] || return 0
  [[ "$workspace" =~ ^${BACKUP_ROOT}/\.brand-embedding-tmp\.[A-Za-z0-9]{6}$ \
      && -d "$workspace" && ! -L "$workspace" \
      && "$(stat -c '%a:%u:%g' "$workspace")" == 700:0:0 ]] || return 0
  find "$workspace" -depth -delete >/dev/null 2>&1 || true
}

on_exit() {
  local rc=$?
  ((rc != 0 && completed == 0 && recovery_armed == 1)) || return 0
  local head=
  head=$(database_head 2>/dev/null || true)
  if ((migration_attempted == 0)) || [[ "$head" == "$ALEMBIC_HEAD" ]]; then
    log 'activation failed without schema drift; restoring complete previous state'
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
  until verify_service_set "$candidate_config_digest" zero; do
    (( $(date +%s) < deadline )) || return 1
    sleep 2
  done
}

write_evidence() {
  local evidence="$backup_dir/brand-embedding-activation-evidence.txt" terminal_count
  terminal_count=$(baseline_effect_counts)
  terminal_count=${terminal_count%%:*}
  {
    printf 'schema_version=1\nrelease_commit=%s\n' "$release_commit"
    printf 'candidate_reference=%s\nalembic_head=%s\n' "$candidate_reference" "$ALEMBIC_HEAD"
    printf 'application_services=12\ncopy_provider_unavailable_terminal=%s\n' "$terminal_count"
    printf 'effect_counters_unchanged=true\nprimary_env_unchanged=true\n'
    printf 'migration_invocations=1\nprovider_calls=0\nsend_calls=0\nreplay_calls=0\n'
    printf 'completed_at=%s\n' "$(date -u +%FT%TZ)"
  } >"$evidence"
  chown root:root "$evidence"
  chmod 600 "$evidence"
}

reject_repeat() {
  [[ ! -e "${ATTEMPT_ROOT}/${release_commit}.brand-embedding-attempted" \
      && ! -L "${ATTEMPT_ROOT}/${release_commit}.brand-embedding-attempted" ]] \
    || die 'candidate was already attempted'
}

run_activation() {
  # The read-only preflight precedes the release lock. Recheck under that lock so
  # a competing release or late operator drift cannot authorize stale mutation.
  verify_baseline
  prepare_roots_and_attempt
  workspace=$(mktemp -d "${BACKUP_ROOT}/.brand-embedding-tmp.XXXXXX")
  [[ "$(stat -c '%a:%u:%g' "$workspace")" == 700:0:0 ]] \
    || die 'release workspace identity changed'
  trap 'on_exit; cleanup_workspace; cleanup_transient_paths' EXIT
  prepare_candidate_source
  quiesce_and_backup
  verify_quiesced_baseline \
    || die 'production baseline drifted after quiescence and backup'
  activate_source
  verify_installed_source
  write_candidate_release_env
  migration_attempted=1
  compose run --rm --no-deps -T backend-migrate </dev/null
  [[ "$(database_head)" == "$ALEMBIC_HEAD" ]] || die 'database head changed after migration'
  compose up -d --no-build --no-deps "${APP_SERVICES[@]}"
  wait_for_candidate || die 'candidate services did not converge within the readiness bound'
  require_safe_window
  [[ "$(effect_counts)" == "$(baseline_effect_counts)" ]] \
    || die 'activation changed a protected effect counter'
  [[ "$(sha256sum "$PRIMARY_ENV" | awk '{print $1}')" == \
      "$(json_string "$baseline_json" primary_env_sha256)" ]] \
    || die 'activation changed primary environment bytes'
  [[ "$(release_reference)" == "$candidate_reference" ]] \
    || die 'candidate RepoDigest did not survive release environment installation'
  verify_candidate_identity_markers \
    || die 'candidate full/legacy markers and OCI revision disagree'
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

if [[ "${BRAND_HOTFIX_OPERATOR_SOURCE_ONLY:-0}" != 1 ]]; then
  trap cleanup_transient_paths EXIT
  main "$@"
fi
