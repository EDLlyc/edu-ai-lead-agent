#!/usr/bin/env bash
# Read-only capture of the exact production baseline consumed by the offline builder/operator.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077
export LC_ALL=C

baseline_app_dir="/opt/edu-ai-lead-agent"
if [[ "${WECHAT_DRAFT_BASELINE_SOURCE_ONLY:-0}" == 1 && -n "${WECHAT_DRAFT_BASELINE_TEST_APP_DIR:-}" ]]; then
  baseline_app_dir=$WECHAT_DRAFT_BASELINE_TEST_APP_DIR
fi
readonly APP_DIR="$baseline_app_dir"
unset baseline_app_dir
readonly PRIMARY_ENV="${APP_DIR}/.env"
readonly RELEASE_ENV="${APP_DIR}/.release.env"
readonly COMPOSE_PROJECT="edu-ai-lead-agent"
readonly EXPECTED_HEAD="20260825_0036"
readonly -a PROFILES=(
  --profile governance --profile content --profile wecom --profile ip-assets
  --profile official-account-weekly-dag
)
readonly -a APP_SERVICES=(
  acquisition-api acquisition-scheduler acquisition-worker
  governance-scheduler governance-worker content-scheduler content-worker wecom-dispatcher
)
readonly -a ALL_SERVICES=(postgres minio "${APP_SERVICES[@]}")
readonly -a MANAGED_DIRS=(backend deploy infra scripts)
readonly -a MANAGED_FILES=(
  compose.yaml .env.example .gitattributes .gitignore AGENTS.md Makefile README.md environment.yml
)

output=""

die() { printf '[wechat-draft-baseline] ERROR: %s\n' "$*" >&2; return 1; }

compose() {
  docker compose --project-name "$COMPOSE_PROJECT" --project-directory "$APP_DIR" \
    --env-file "$PRIMARY_ENV" --env-file "$RELEASE_ENV" "${PROFILES[@]}" "$@"
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
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            raise SystemExit("managed source contains an unsafe member")
        if path.is_file():
            value = hashlib.sha256(path.read_bytes()).hexdigest()
            rows.append(
                f"f\t{mode:04o}\t{metadata.st_uid}\t{metadata.st_gid}\t{value}\t{relative}\n"
            )
        else:
            rows.append(
                f"d\t{mode:04o}\t{metadata.st_uid}\t{metadata.st_gid}\t-\t{relative}\n"
            )
print(hashlib.sha256("".join(sorted(rows)).encode()).hexdigest())
PY
}

main() {
  while (($#)); do
    case "$1" in
      --output) (($# >= 2)) || die "missing output path"; output=$2; shift 2 ;;
      -h|--help)
        printf '%s\n' 'Usage: capture-wechat-draft-production-baseline.sh --output ABSENT_ABSOLUTE_JSON' >&2
        return 0
        ;;
      *) die "unknown argument" ;;
    esac
  done
  [[ "$output" == /* && "$output" != */ && ! -e "$output" && ! -L "$output" ]] \
    || die "output must be an absent absolute path"
  [[ -f "$PRIMARY_ENV" && ! -L "$PRIMARY_ENV" && "$(stat -c '%a' "$PRIMARY_ENV")" == 600 ]] \
    || die "primary environment is not a physical mode-0600 file"
  [[ -f "$RELEASE_ENV" && ! -L "$RELEASE_ENV" && "$(stat -c '%a' "$RELEASE_ENV")" == 600 ]] \
    || die "release environment is not a physical mode-0600 file"

  local expected_services actual_services service container image_id="" observed_image health head
  local restart_count restart_counts=""
  expected_services=$(printf '%s\n' "${ALL_SERVICES[@]}" | sort)
  actual_services=$(compose ps --services --status running | sort)
  [[ "$actual_services" == "$expected_services" ]] || die "running service set is not the reviewed baseline"
  for service in "${ALL_SERVICES[@]}"; do
    container=$(compose ps -q "$service")
    [[ -n "$container" && "$(docker inspect --format '{{.State.Status}}' "$container")" == running ]] \
      || die "service is not running: $service"
    if [[ "$service" == postgres || "$service" == minio || "$service" == acquisition-api ]]; then
      health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")
      [[ "$health" == healthy ]] || die "service is not healthy: $service"
    fi
    restart_count=$(docker inspect --format '{{.RestartCount}}' "$container")
    [[ "$restart_count" =~ ^[0-9]+$ ]] || die "service restart count is invalid: $service"
    restart_counts+="${service}=${restart_count}"$'\n'
  done
  for service in "${APP_SERVICES[@]}"; do
    container=$(compose ps -q "$service")
    observed_image=$(docker inspect --format '{{.Image}}' "$container")
    if [[ -z "$image_id" ]]; then image_id=$observed_image; fi
    [[ "$observed_image" == "$image_id" ]] || die "application services do not share one image"
  done
  [[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "running image ID is invalid"
  local revision
  revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image_id")
  [[ "$revision" =~ ^[0-9a-f]{40}$ ]] || die "running image revision is invalid"
  head=$(compose exec -T postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT version_num FROM alembic_version"')
  [[ "$head" == "$EXPECTED_HEAD" ]] || die "production Alembic head is not 0036"

  local source_sha env_sha release_env_sha temporary
  source_sha=$(source_tree_fingerprint)
  env_sha=$(sha256sum "$PRIMARY_ENV" | awk '{print $1}')
  release_env_sha=$(sha256sum "$RELEASE_ENV" | awk '{print $1}')
  temporary=$(mktemp "$(dirname -- "$output")/.wechat-draft-baseline.XXXXXX")
  python3 - "$temporary" "$head" "$image_id" "$revision" "$source_sha" "$env_sha" \
    "$release_env_sha" "$restart_counts" <<'PY'
from datetime import UTC, datetime
import json
import pathlib
import sys

path, head, image, revision, source, env, release_env, restart_rows = sys.argv[1:]
restart_counts = {}
for row in restart_rows.splitlines():
    service, value = row.split("=", 1)
    if service in restart_counts or not value.isdigit():
        raise SystemExit("restart-count capture is invalid")
    restart_counts[service] = int(value)
payload = {
    "schema_version": 1,
    "observed_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "current_alembic_head": head,
    "current_image_id": image,
    "current_image_revision": revision,
    "source_tree_sha256": source,
    "env_sha256": env,
    "release_env_sha256": release_env,
    "restart_counts": dict(sorted(restart_counts.items())),
    "running_services": sorted([
        "postgres", "minio", "acquisition-api", "acquisition-scheduler",
        "acquisition-worker", "governance-scheduler", "governance-worker",
        "content-scheduler", "content-worker", "wecom-dispatcher",
    ]),
}
pathlib.Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  chmod 600 "$temporary"
  mv "$temporary" "$output"
  printf 'production_baseline_captured output=%s\n' "$output"
}

if [[ "${WECHAT_DRAFT_BASELINE_SOURCE_ONLY:-0}" != 1 ]]; then
  main "$@"
fi
