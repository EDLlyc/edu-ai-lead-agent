#!/usr/bin/env bash
# Read-only capture for the exact production state accepted by this incident release.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077
export LC_ALL=C

capture_app_dir=/opt/edu-ai-lead-agent
if [[ "${BRAND_HOTFIX_CAPTURE_SOURCE_ONLY:-0}" == 1 \
    && -n "${BRAND_HOTFIX_CAPTURE_TEST_APP_DIR:-}" ]]; then
  capture_app_dir=$BRAND_HOTFIX_CAPTURE_TEST_APP_DIR
fi
readonly APP_DIR="$capture_app_dir"
unset capture_app_dir
readonly PRIMARY_ENV="${APP_DIR}/.env"
readonly RELEASE_ENV="${APP_DIR}/.release.env"
readonly RELEASE_MARKER="${APP_DIR}/.release-commit"
readonly LEGACY_RELEASE_MARKER="${APP_DIR}/RELEASE_COMMIT"
readonly COMPOSE_PROJECT=edu-ai-lead-agent
readonly PRODUCTION_COMMIT=40e4dec0ae82569fc798355d4515ab0009697c6f
readonly LEGACY_PRODUCTION_COMMIT=7a45a65
readonly ALEMBIC_HEAD=20260901_0042
readonly PRIMARY_ENV_IDENTITY=600:1000:1001
readonly -a PROFILES=(
  --profile governance
  --profile content
  --profile wecom
  --profile official-account-weekly-dag
  --profile official-account-local
  --profile wechat-official-account-draft
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
  official-account-weekly-dag-worker
  official-account-weekly-scheduler
  official-account-local-worker
  wechat-official-account-draft-worker
)
readonly -a ALL_SERVICES=(postgres minio "${APP_SERVICES[@]}")
readonly -a MANAGED_DIRS=(backend deploy infra scripts)
readonly -a MANAGED_FILES=(
  compose.yaml .env.example .gitattributes .gitignore AGENTS.md Makefile README.md environment.yml
)

output=
source_json=
temporary=

die() {
  printf '[brand-embedding-baseline] ERROR: %s\n' "$*" >&2
  return 1
}

cleanup() {
  local rc=$? path
  trap - EXIT
  for path in "${source_json:-}" "${temporary:-}"; do
    [[ -n "$path" ]] || continue
    case "$(basename -- "$path")" in
      .brand-hotfix-source.??????|.brand-hotfix-baseline.??????)
        rm -f -- "$path" >/dev/null 2>&1 || true
        ;;
    esac
  done
  exit "$rc"
}

compose() {
  docker compose --project-name "$COMPOSE_PROJECT" --project-directory "$APP_DIR" \
    --env-file "$PRIMARY_ENV" --env-file "$RELEASE_ENV" "${PROFILES[@]}" "$@"
}

require_mode_0600_file() {
  local path=$1
  [[ -f "$path" && ! -L "$path" && "$(stat -c '%a:%u:%g' "$path")" == 600:0:0 ]]
}

primary_environment_fingerprint() {
  python3 - "$PRIMARY_ENV" "$PRIMARY_ENV_IDENTITY" <<'PY'
import hashlib
import os
import stat
import sys

path = sys.argv[1]
expected_identity = sys.argv[2]
flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
try:
    descriptor = os.open(path, flags)
except OSError:
    raise SystemExit(1) from None
try:
    before = os.fstat(descriptor)
    identity = f"{stat.S_IMODE(before.st_mode):o}:{before.st_uid}:{before.st_gid}"
    if not stat.S_ISREG(before.st_mode) or identity != expected_identity:
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
        f"{digest.hexdigest()}\t{stat.S_IMODE(after.st_mode):o}"
        f"\t{after.st_uid}\t{after.st_gid}"
    )
finally:
    os.close(descriptor)
PY
}

validate_primary_environment() {
  primary_environment_fingerprint >/dev/null \
    || die 'primary environment must match the reviewed stable physical mode and owner'
}

validate_legacy_release_marker() {
  [[ -f "$LEGACY_RELEASE_MARKER" && ! -L "$LEGACY_RELEASE_MARKER" \
      && "$(stat -c '%a:%u:%g' "$LEGACY_RELEASE_MARKER")" == 600:1000:1001 ]] \
    || die 'legacy release marker must match the reviewed physical mode and owner'
  python3 - "$LEGACY_RELEASE_MARKER" "$LEGACY_PRODUCTION_COMMIT" <<'PY'
import pathlib
import sys

raw = pathlib.Path(sys.argv[1]).read_bytes()
expected = sys.argv[2].encode()
if raw not in {expected, expected + b"\n"}:
    raise SystemExit("legacy release marker differs from the incident baseline")
PY
}

read_release_reference() {
  python3 - "$RELEASE_ENV" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
rows = [
    row
    for row in path.read_text(encoding="utf-8").splitlines()
    if row and not row.lstrip().startswith("#")
]
if len(rows) != 1 or not rows[0].startswith("APP_IMAGE="):
    raise SystemExit("release environment must contain only APP_IMAGE")
reference = rows[0].split("=", 1)[1]
if re.fullmatch(
    r"[a-z0-9.-]+(?::[0-9]+)?(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*"
    r"@sha256:[0-9a-f]{64}",
    reference,
) is None:
    raise SystemExit("release APP_IMAGE must be an immutable repository digest")
print(reference)
PY
}

capture_source_manifest() {
  local destination=$1
  python3 - "$APP_DIR" "$destination" "${MANAGED_DIRS[@]}" -- "${MANAGED_FILES[@]}" <<'PY'
import hashlib
import json
import os
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
        raise SystemExit("managed production path is absent or linked")
    paths = [target, *sorted(target.rglob("*"))] if target.is_dir() else [target]
    for path in paths:
        metadata = path.lstat()
        relative = path.relative_to(root).as_posix()
        mode = stat.S_IMODE(metadata.st_mode)
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise SystemExit("managed production source has an unsafe member")
        if path.is_dir():
            if mode not in {0o700, 0o755}:
                raise SystemExit("managed production directory mode is outside the contract")
            checksum = None
            kind = "d"
        else:
            if mode not in {0o600, 0o644, 0o700, 0o755}:
                raise SystemExit("managed production file mode is outside the contract")
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            kind = "f"
        rows.append(
            {
                "kind": kind,
                "path": relative,
                "mode": mode,
                "uid": metadata.st_uid,
                "gid": metadata.st_gid,
                "sha256": checksum,
            }
        )
paths = [row["path"] for row in rows]
if len(paths) != len(set(paths)):
    raise SystemExit("managed production source has duplicate paths")
rows.sort(key=lambda row: row["path"])
fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as stream:
    json.dump(rows, stream, separators=(",", ":"), sort_keys=True)
PY
}

effect_counts() {
  compose exec -T postgres sh -eu -c '
    psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "
      SELECT
        (SELECT count(*) FROM copy_generation_runs
          WHERE status = '\''review_required'\''
            AND error_code = '\''copy_provider_unavailable'\'')::text || '\'':'\'' ||
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

main() {
  while (($#)); do
    case "$1" in
      --output)
        (($# >= 2)) || die 'missing output path'
        output=$2
        shift 2
        ;;
      -h|--help)
        printf '%s\n' \
          'Usage: capture-brand-embedding-production-baseline.sh --output ABSENT_ABSOLUTE_JSON' >&2
        return 0
        ;;
      *) die 'unknown argument' ;;
    esac
  done
  [[ "$output" == /* && "$output" != */ && ! -e "$output" && ! -L "$output" ]] \
    || die 'output must be an absent absolute path'
  local primary_env_fingerprint primary_env_fingerprint_after
  local primary_env_sha256 primary_env_mode primary_env_uid primary_env_gid
  primary_env_fingerprint=$(primary_environment_fingerprint) \
    || die 'primary environment must match the reviewed stable physical mode and owner'
  require_mode_0600_file "$RELEASE_ENV" \
    || die 'release environment must be a physical root-owned mode-0600 file'
  require_mode_0600_file "$RELEASE_MARKER" \
    || die 'release marker must be a physical root-owned mode-0600 file'
  validate_legacy_release_marker
  local current_commit
  current_commit=$(tr -d '\n' <"$RELEASE_MARKER")
  [[ "$current_commit" == "$PRODUCTION_COMMIT" ]] \
    || die 'production commit differs from the incident baseline'

  local expected_services actual_services service container state health restart_count
  local restart_rows= image_id= observed_image revision head release_reference repo_digests
  expected_services=$(printf '%s\n' "${ALL_SERVICES[@]}" | sort)
  actual_services=$(compose ps --services --status running | sort)
  [[ "$actual_services" == "$expected_services" ]] \
    || die 'running service topology differs from the reviewed fourteen-service baseline'
  for service in "${ALL_SERVICES[@]}"; do
    container=$(compose ps -q "$service")
    [[ -n "$container" ]] || die "service container is absent: $service"
    state=$(docker inspect --format '{{.State.Status}}' "$container")
    [[ "$state" == running ]] || die "service is not running: $service"
    if [[ "$service" == postgres || "$service" == minio || "$service" == acquisition-api ]]; then
      health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")
      [[ "$health" == healthy ]] || die "service is not healthy: $service"
    fi
    restart_count=$(docker inspect --format '{{.RestartCount}}' "$container")
    [[ "$restart_count" == 0 ]] || die "service restart count is not the reviewed zero: $service"
    restart_rows+="${service}=${restart_count}"$'\n'
  done
  for service in "${APP_SERVICES[@]}"; do
    container=$(compose ps -q "$service")
    observed_image=$(docker inspect --format '{{.Image}}' "$container")
    [[ -n "$image_id" ]] || image_id=$observed_image
    [[ "$observed_image" == "$image_id" ]] \
      || die 'the twelve application services do not share one image'
  done
  [[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die 'running image ID is invalid'
  revision=$(docker image inspect --format \
    '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image_id")
  [[ "$revision" == "$PRODUCTION_COMMIT" ]] || die 'running image revision changed'
  release_reference=$(read_release_reference)
  repo_digests=$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$image_id")
  grep -Fxq "$release_reference" <<<"$repo_digests" \
    || die 'release digest is not attached to the running image'
  [[ "$(docker image inspect --format '{{.Id}}' "$release_reference")" == "$image_id" ]] \
    || die 'release digest resolves to another image'
  head=$(compose exec -T postgres sh -eu -c \
    'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT version_num FROM alembic_version"' \
    </dev/null)
  [[ "$head" == "$ALEMBIC_HEAD" ]] || die 'production Alembic head changed'

  local counts
  counts=$(effect_counts)
  [[ "$counts" =~ ^([0-9]+)(:[0-9]+){10}(:0){5}$ \
      && $((10#${BASH_REMATCH[1]})) -ge 18 ]] \
    || die 'known terminal-copy/effect counters or pending-work gates changed'
  source_json=$(mktemp "$(dirname -- "$output")/.brand-hotfix-source.XXXXXX")
  rm -f -- "$source_json"
  capture_source_manifest "$source_json"
  primary_env_fingerprint_after=$(primary_environment_fingerprint) \
    || die 'primary environment changed during baseline capture'
  [[ "$primary_env_fingerprint_after" == "$primary_env_fingerprint" ]] \
    || die 'primary environment changed during baseline capture'
  IFS=$'\t' read -r primary_env_sha256 primary_env_mode primary_env_uid primary_env_gid \
    <<<"$primary_env_fingerprint"
  temporary=$(mktemp "$(dirname -- "$output")/.brand-hotfix-baseline.XXXXXX")
  python3 - "$temporary" "$source_json" "$current_commit" "$head" "$image_id" \
    "$release_reference" "$revision" \
    "$primary_env_sha256" "$primary_env_mode" "$primary_env_uid" "$primary_env_gid" \
    "$(sha256sum "$RELEASE_ENV" | awk '{print $1}')" \
    "$(sha256sum "$LEGACY_RELEASE_MARKER" | awk '{print $1}')" \
    "$(stat -c '%a' "$LEGACY_RELEASE_MARKER")" \
    "$(stat -c '%u' "$LEGACY_RELEASE_MARKER")" \
    "$(stat -c '%g' "$LEGACY_RELEASE_MARKER")" "$restart_rows" "$counts" <<'PY'
from datetime import UTC, datetime
import json
import pathlib
import sys

(
    output,
    source_path,
    commit,
    head,
    image_id,
    image_reference,
    revision,
    primary_env,
    primary_env_mode,
    primary_env_uid,
    primary_env_gid,
    release_env,
    legacy_release_commit,
    legacy_release_commit_mode,
    legacy_release_commit_uid,
    legacy_release_commit_gid,
    restart_rows,
    count_row,
) = sys.argv[1:]
service_names = [
    "postgres", "minio", "acquisition-api", "acquisition-scheduler",
    "acquisition-worker", "governance-scheduler", "governance-worker",
    "content-scheduler", "content-worker", "wecom-dispatcher",
    "official-account-weekly-dag-worker", "official-account-weekly-scheduler",
    "official-account-local-worker", "wechat-official-account-draft-worker",
]
restart_counts = {}
for row in restart_rows.splitlines():
    service, raw_value = row.split("=", 1)
    if service in restart_counts or not raw_value.isdigit():
        raise SystemExit("restart evidence is malformed")
    restart_counts[service] = int(raw_value)
if set(restart_counts) != set(service_names):
    raise SystemExit("restart evidence is incomplete")
count_names = [
    "copy_provider_unavailable_terminal", "copy_generation_attempts",
    "wecom_delivery_jobs", "wecom_delivery_attempts", "weekly_dag_runs",
    "weekly_dag_attempts", "official_account_article_runs",
    "official_account_article_attempts", "wechat_mp_draft_jobs",
    "wechat_mp_draft_items", "wechat_mp_draft_attempts",
    "pending_copy_jobs", "pending_wecom_jobs", "pending_weekly_runs",
    "pending_official_account_runs", "pending_wechat_draft_jobs",
]
count_values = count_row.split(":")
if len(count_values) != len(count_names) or not all(value.isdigit() for value in count_values):
    raise SystemExit("effect-count evidence is malformed")
payload = {
    "schema_version": 1,
    "captured_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "current_commit": commit,
    "current_alembic_head": head,
    "current_image_id": image_id,
    "current_image_reference": image_reference,
    "current_image_revision": revision,
    "primary_env_sha256": primary_env,
    "primary_env_mode": int(primary_env_mode, 8),
    "primary_env_uid": int(primary_env_uid),
    "primary_env_gid": int(primary_env_gid),
    "release_env_sha256": release_env,
    "legacy_release_commit_sha256": legacy_release_commit,
    "legacy_release_commit_mode": int(legacy_release_commit_mode, 8),
    "legacy_release_commit_uid": int(legacy_release_commit_uid),
    "legacy_release_commit_gid": int(legacy_release_commit_gid),
    "running_services": sorted(service_names),
    "restart_counts": dict(sorted(restart_counts.items())),
    "effect_counts": dict(zip(count_names, map(int, count_values), strict=True)),
    "source_manifest": json.loads(pathlib.Path(source_path).read_text(encoding="utf-8")),
}
pathlib.Path(output).write_text(
    json.dumps(payload, separators=(",", ":"), sort_keys=True), encoding="utf-8"
)
PY
  chmod 600 "$temporary"
  mv -T "$temporary" "$output"
  rm -f -- "$source_json"
  printf 'brand_embedding_production_baseline_captured output=%s\n' "$output"
}

if [[ "${BRAND_HOTFIX_CAPTURE_SOURCE_ONLY:-0}" != 1 ]]; then
  trap cleanup EXIT
  main "$@"
fi
