#!/usr/bin/env bash
# Build a checksum-bound OCI/source stage from the one reviewed Codeup hotfix ref.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077
export LC_ALL=C

readonly SAFE_PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
readonly CONTAINERD_ADDRESS=/run/containerd/containerd.sock
readonly SOURCE_URL=https://codeup.aliyun.com/601cdb1a841cc46b7c49b115/marketingUseOnly/edu-ai-lead-agent.git
readonly SOURCE_SSH_URL=git@codeup.aliyun.com:601cdb1a841cc46b7c49b115/marketingUseOnly/edu-ai-lead-agent.git
readonly SOURCE_SSH_ALIAS=codeup-edu-ai
readonly SOURCE_SSH_ALIAS_URL=git@codeup-edu-ai:601cdb1a841cc46b7c49b115/marketingUseOnly/edu-ai-lead-agent.git
readonly RELEASE_HEAD_REF=refs/heads/release/brand-embedding-hotfix-20260904
readonly RELEASE_REF=refs/remotes/origin/release/brand-embedding-hotfix-20260904
readonly MAIN_HEAD_REF=refs/heads/main
readonly MAIN_REF=refs/remotes/origin/main
readonly PRODUCTION_COMMIT=40e4dec0ae82569fc798355d4515ab0009697c6f
readonly ALEMBIC_HEAD=20260901_0042
readonly TASK_PATH=.trellis/tasks/09-04-production-brand-embedding-hotfix/research
readonly BUILDER_NAME=build-brand-embedding-hotfix-offline-artifacts.sh
readonly CAPTURE_NAME=capture-brand-embedding-production-baseline.sh
readonly OPERATOR_NAME=brand-embedding-hotfix-offline-release-operator.sh
readonly VALIDATOR_NAME=validate-brand-embedding-hotfix-offline-artifacts.py
readonly -a SOURCE_PATHS=(
  backend deploy infra scripts compose.yaml .env.example .gitattributes .gitignore
  AGENTS.md Makefile README.md environment.yml
)
readonly -a APP_SERVICES=(
  acquisition-api acquisition-scheduler acquisition-worker
  governance-scheduler governance-worker content-scheduler content-worker
  wecom-dispatcher official-account-weekly-dag-worker
  official-account-weekly-scheduler official-account-local-worker
  wechat-official-account-draft-worker
)
readonly -a PROFILES=(
  --profile governance --profile content --profile wecom
  --profile official-account-weekly-dag --profile official-account-local
  --profile wechat-official-account-draft
)
readonly -a FINAL_MEMBERS=(
  audit-diff.tsv backend-image.oci.tar.gz
  build-brand-embedding-hotfix-offline-artifacts.sh
  capture-brand-embedding-production-baseline.sh image-source.sha256
  production-baseline.json release-metadata.json runtime-diff.tsv
  source-manifest.tsv source.tar.gz
  validate-brand-embedding-hotfix-offline-artifacts.py
  brand-embedding-hotfix-offline-release-operator.sh
)

release_sha=
main_fix_commit=
main_operator_commit=
production_baseline=
scheduler_cutoff_utc=
output_dir=
repo_root=
scratch=
worktree=
stage=
candidate_repository=
transport_tag=
candidate_config_digest=
candidate_manifest_digest=
candidate_reference=
candidate_image_owned=0
candidate_reference_owned=0
candidate_owned_image_id=
containerd_reference=
short_transport_reference=
legacy_builder_image_id=
preexisting_repo_digests=

log() { printf '[brand-embedding-builder] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; return 1; }

docker_clean() {
  env -i PATH="$SAFE_PATH" HOME="$scratch" LC_ALL=C docker "$@" </dev/null
}

ctr_clean() {
  env -i PATH="$SAFE_PATH" HOME="$scratch" LC_ALL=C \
    ctr --address "$CONTAINERD_ADDRESS" "$@" </dev/null
}

cleanup_candidate_image() {
  local current_id reference_id
  [[ "${candidate_image_owned:-0}" == 1 && -n "${transport_tag:-}" \
      && "${candidate_owned_image_id:-}" =~ ^sha256:[0-9a-f]{64}$ ]] || return 0
  current_id=$(docker_clean image inspect --format '{{.Id}}' "$transport_tag" 2>/dev/null) \
    || {
      candidate_image_owned=0
      candidate_reference_owned=0
      candidate_owned_image_id=
      return 0
    }
  if [[ "$current_id" != "$candidate_owned_image_id" ]]; then
    candidate_image_owned=0
    candidate_reference_owned=0
    candidate_owned_image_id=
    return 0
  fi
  if [[ "${candidate_reference_owned:-0}" == 1 && -n "${candidate_reference:-}" ]]; then
    reference_id=$(docker_clean image inspect --format '{{.Id}}' "$candidate_reference" 2>/dev/null) \
      || reference_id=
    if [[ "$reference_id" == "$candidate_owned_image_id" ]]; then
      docker_clean image rm "$candidate_reference" >/dev/null 2>&1 || true
    fi
  fi
  docker_clean image rm "$transport_tag" >/dev/null 2>&1 || true
  candidate_image_owned=0
  candidate_reference_owned=0
  candidate_owned_image_id=
}

cleanup() {
  local rc=$?
  cleanup_candidate_image
  if [[ -n "${worktree:-}" && -d "$worktree" && -n "${repo_root:-}" ]]; then
    git -C "$repo_root" worktree remove --force "$worktree" >/dev/null 2>&1 || true
  fi
  if [[ -n "${scratch:-}" && "$scratch" == /tmp/edu-ai-brand-embedding-build.?????? ]]; then
    find "$scratch" -depth -delete >/dev/null 2>&1 || true
  fi
  exit "$rc"
}
trap cleanup EXIT

usage() {
  printf '%s\n' \
    "Usage: $BUILDER_NAME --release-sha HEX40 --main-fix-commit HEX40 --main-operator-commit HEX40 --production-baseline ABSOLUTE_MODE_0600_JSON --scheduler-cutoff-utc YYYY-MM-DDTHH:MM:SSZ --output-dir ABSENT_ABSOLUTE_DIR" >&2
}

parse_args() {
  while (($#)); do
    case "$1" in
      --release-sha) (($# >= 2)) || die 'missing release SHA'; release_sha=$2; shift 2 ;;
      --main-fix-commit) (($# >= 2)) || die 'missing main fix commit'; main_fix_commit=$2; shift 2 ;;
      --main-operator-commit) (($# >= 2)) || die 'missing main operator commit'; main_operator_commit=$2; shift 2 ;;
      --production-baseline) (($# >= 2)) || die 'missing baseline'; production_baseline=$2; shift 2 ;;
      --scheduler-cutoff-utc) (($# >= 2)) || die 'missing cutoff'; scheduler_cutoff_utc=$2; shift 2 ;;
      --output-dir) (($# >= 2)) || die 'missing output directory'; output_dir=$2; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) die 'unknown argument' ;;
    esac
  done
  [[ "$release_sha" =~ ^[0-9a-f]{40}$ ]] || die 'release SHA must be lowercase HEX40'
  [[ "$main_fix_commit" =~ ^[0-9a-f]{40}$ ]] || die 'main fix commit must be lowercase HEX40'
  [[ "$main_operator_commit" =~ ^[0-9a-f]{40}$ ]] \
    || die 'main operator commit must be lowercase HEX40'
  [[ "$scheduler_cutoff_utc" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] \
    || die 'scheduler cutoff is invalid'
  [[ "$production_baseline" == /* && -f "$production_baseline" \
      && ! -L "$production_baseline" \
      && "$(stat -c '%a:%u:%g' "$production_baseline")" == 600:0:0 ]] \
    || die 'production baseline must be a physical root-owned mode-0600 file'
  [[ "$output_dir" == /* && "$output_dir" != */ && ! -e "$output_dir" && ! -L "$output_dir" ]] \
    || die 'output directory must be an absent absolute path'
  local parent
  parent=$(dirname -- "$output_dir")
  [[ -d "$parent" && ! -L "$parent" && "$(realpath -e -- "$parent")" == "$parent" ]] \
    || die 'output parent must be a physical directory'
}

git_clean() {
  env -i PATH="$SAFE_PATH" HOME="$scratch" LC_ALL=C GIT_CONFIG_NOSYSTEM=1 \
    GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false SSH_ASKPASS=/bin/false git "$@"
}

git_fetch() {
  local -a environment=(
    PATH="$SAFE_PATH" HOME="${HOME:?}" LC_ALL=C GIT_CONFIG_NOSYSTEM=1
    GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false SSH_ASKPASS=/bin/false
    GIT_SSH_COMMAND='ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no -o NumberOfPasswordPrompts=0 -o ConnectTimeout=10'
  )
  if [[ -n "${SSH_AUTH_SOCK:-}" ]]; then
    environment+=(SSH_AUTH_SOCK="$SSH_AUTH_SOCK")
  fi
  env -i "${environment[@]}" git "$@" </dev/null
}

validate_source_alias() {
  local resolved host port user
  resolved=$(env -i PATH="$SAFE_PATH" HOME="${HOME:?}" LC_ALL=C \
    ssh -G "$SOURCE_SSH_ALIAS" </dev/null 2>/dev/null) \
    || die 'Codeup SSH alias cannot be resolved non-interactively'
  host=$(awk '$1 == "hostname" { print $2; exit }' <<<"$resolved")
  port=$(awk '$1 == "port" { print $2; exit }' <<<"$resolved")
  user=$(awk '$1 == "user" { print $2; exit }' <<<"$resolved")
  [[ "$host" == codeup.aliyun.com && "$port" == 22 && "$user" == git ]] \
    || die 'Codeup SSH alias does not resolve to the reviewed endpoint'
}

assert_authority() {
  local origin origin_sha main_sha committed running
  origin=$(git_clean -C "$repo_root" config --get remote.origin.url)
  case "$origin" in
    "$SOURCE_URL"|"$SOURCE_SSH_URL") ;;
    "$SOURCE_SSH_ALIAS_URL") validate_source_alias ;;
    *) die 'origin is not the reviewed Codeup repository' ;;
  esac
  git_fetch -C "$repo_root" fetch --quiet --no-tags origin \
    "$RELEASE_HEAD_REF:$RELEASE_REF" "$MAIN_HEAD_REF:$MAIN_REF" \
    || die 'authoritative Codeup refs could not be fetched'
  origin_sha=$(git_clean -C "$repo_root" rev-parse --verify "${RELEASE_REF}^{commit}")
  [[ "$origin_sha" == "$release_sha" ]] || die 'release SHA differs from the fetched hotfix ref'
  git_clean -C "$repo_root" merge-base --is-ancestor "$PRODUCTION_COMMIT" "$release_sha" \
    || die 'release does not descend from the production commit'
  main_sha=$(git_clean -C "$repo_root" rev-parse --verify "${MAIN_REF}^{commit}")
  [[ "$main_sha" =~ ^[0-9a-f]{40}$ ]] || die 'fetched main identity is invalid'
  git_clean -C "$repo_root" merge-base --is-ancestor "$main_fix_commit" "$main_sha" \
    || die 'main does not contain the reviewed fix commit'
  git_clean -C "$repo_root" merge-base --is-ancestor "$main_operator_commit" "$main_sha" \
    || die 'main does not contain the reviewed operator commit'
  committed=$(git_clean -C "$repo_root" show "${release_sha}:${TASK_PATH}/${BUILDER_NAME}" | sha256sum | awk '{print $1}')
  running=$(sha256sum "${repo_root}/${TASK_PATH}/${BUILDER_NAME}" | awk '{print $1}')
  [[ "$committed" == "$running" ]] || die 'builder bytes differ from the selected release commit'
}

create_worktree() {
  git_clean -C "$repo_root" worktree add --detach "$worktree" "$release_sha" >/dev/null
  [[ "$(git_clean -C "$worktree" rev-parse HEAD)" == "$release_sha" ]] \
    || die 'detached worktree commit changed'
  [[ -z "$(git_clean -C "$worktree" status --porcelain=v1 --untracked-files=all)" ]] \
    || die 'detached worktree is not clean'
}

capture_complete_diff() {
  local complete="$scratch/complete-diff.tsv"
  git_clean -C "$repo_root" diff --name-status --no-renames \
    "$PRODUCTION_COMMIT" "$release_sha" >"$complete"
  python3 - "$complete" "$stage/runtime-diff.tsv" "$stage/audit-diff.tsv" <<'PY'
import pathlib
import sys

source, runtime_output, audit_output = map(pathlib.Path, sys.argv[1:])
runtime = {
    ".env.example": "M",
    "backend/app/api_main.py": "M",
    "backend/app/content_worker_main.py": "M",
    "backend/app/core/config.py": "M",
    "backend/app/infrastructure/ai/factory.py": "M",
    "compose.yaml": "M",
    "scripts/doctor.sh": "M",
    "scripts/validate_brand_delivery_config.py": "A",
}
audit_exact = {
    ".trellis/spec/backend/brand-knowledge-rag.md": "M",
    ".trellis/spec/backend/official-account-weekly-dag.md": "M",
    ".trellis/spec/backend/quality-guidelines.md": "M",
    "backend/tests/unit/test_brand_embedding_zhipu.py": "A",
    "deploy/release/tests/test_brand_embedding_hotfix_contract.py": "A",
    "deploy/release/tests/test_local_release.py": "M",
    "scripts/release-prod.sh": "M",
}
task_prefix = ".trellis/tasks/09-04-production-brand-embedding-hotfix/"
seen = {}
audit = {}
for row in source.read_text(encoding="utf-8").splitlines():
    pieces = row.split("\t")
    if len(pieces) != 2 or pieces[0] not in {"A", "M"} or pieces[1] in seen:
        raise SystemExit("complete production diff has an unsafe status or duplicate")
    status, name = pieces
    seen[name] = status
    if name in runtime:
        if runtime[name] != status:
            raise SystemExit("reviewed runtime path has an unexpected status")
    elif name in audit_exact:
        if audit_exact[name] != status:
            raise SystemExit("reviewed audit path has an unexpected status")
        audit[name] = status
    elif name.startswith(task_prefix) and status == "A":
        audit[name] = status
    else:
        raise SystemExit("production diff escaped runtime and audit allowlists")
if {name: seen.get(name) for name in runtime} != runtime:
    raise SystemExit("complete runtime diff does not equal the reviewed eight-path allowlist")
if set(audit_exact) - set(audit) or not any(name.startswith(task_prefix) for name in audit):
    raise SystemExit("audit/test diff evidence is incomplete")
runtime_output.write_text(
    "".join(f"{runtime[name]}\t{name}\n" for name in sorted(runtime)), encoding="utf-8"
)
audit_output.write_text(
    "".join(f"{audit[name]}\t{name}\n" for name in sorted(audit)), encoding="utf-8"
)
PY
}

build_source_archive() {
  local raw_tar="$scratch/source.raw.tar"
  git_clean -C "$worktree" archive --format=tar "$release_sha" -- "${SOURCE_PATHS[@]}" >"$raw_tar"
  python3 - "$raw_tar" "$stage/source.tar.gz" "$stage/source-manifest.tsv" <<'PY'
import gzip
import hashlib
import io
import pathlib
import stat
import sys
import tarfile

source, output, manifest = map(pathlib.Path, sys.argv[1:])
rows = []
with tarfile.open(source, "r:") as incoming:
    with output.open("wb") as raw_output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_output, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as outgoing:
                for original in incoming:
                    if original.issym() or original.islnk() or not (
                        original.isfile() or original.isdir()
                    ):
                        raise SystemExit("source archive contains an unsupported member")
                    info = tarfile.TarInfo(original.name.rstrip("/") + ("/" if original.isdir() else ""))
                    info.uid = 0
                    info.gid = 0
                    info.uname = "root"
                    info.gname = "root"
                    info.mtime = 0
                    if original.isdir():
                        info.type = tarfile.DIRTYPE
                        info.mode = 0o755
                        outgoing.addfile(info)
                        rows.append((original.name.rstrip("/"), "d", "0755", "-"))
                    else:
                        stream = incoming.extractfile(original)
                        if stream is None:
                            raise SystemExit("source archive member is unreadable")
                        value = stream.read()
                        info.type = tarfile.REGTYPE
                        info.size = len(value)
                        info.mode = 0o755 if stat.S_IMODE(original.mode) & 0o111 else 0o644
                        outgoing.addfile(info, io.BytesIO(value))
                        rows.append(
                            (
                                original.name,
                                "f",
                                f"{info.mode:04o}",
                                hashlib.sha256(value).hexdigest(),
                            )
                        )
paths = [row[0] for row in rows]
if len(paths) != len(set(paths)):
    raise SystemExit("source archive paths are not unique")
manifest.write_text(
    "".join(f"{kind}\t{mode}\t{checksum}\t{name}\n" for name, kind, mode, checksum in sorted(rows)),
    encoding="utf-8",
)
PY
}

write_image_source_manifest() {
  python3 - "$worktree/backend" "$stage/image-source.sha256" <<'PY'
import hashlib
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1]).resolve(strict=True)
output = pathlib.Path(sys.argv[2])
paths = [root / "alembic.ini", root / "pyproject.toml"]
for subtree in (root / "app", root / "alembic"):
    paths.extend(
        path for path in subtree.rglob("*") if path.is_file() and path.suffix in {".py", ".html"}
    )
rows = []
for path in sorted(set(paths)):
    if path.is_symlink() or not path.is_file():
        raise SystemExit("image source scope contains an unsafe path")
    relative = path.relative_to(root).as_posix()
    normalized = pathlib.PurePosixPath(relative)
    if (
        normalized.as_posix() != relative
        or any(part in {"", ".", ".."} for part in normalized.parts)
        or re.fullmatch(r"[A-Za-z0-9._/-]+", relative) is None
    ):
        raise SystemExit("image source scope contains an unsafe path")
    rows.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {relative}\n")
output.write_text("".join(rows), encoding="utf-8")
PY
}

write_observed_image_source_manifest() {
  local reference=$1 output=$2
  docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint python "$reference" -c \
    'import hashlib,pathlib,re,sys; root=pathlib.Path("/app"); paths=[root/"alembic.ini",root/"pyproject.toml"]; paths += [p for base in (root/"app",root/"alembic") for p in base.rglob("*") if p.is_file() and p.suffix in {".py",".html"}]; paths=sorted(set(paths)); names=[p.relative_to(root).as_posix() for p in paths]; all(pathlib.PurePosixPath(name).as_posix()==name and all(part not in {"",".",".."} for part in pathlib.PurePosixPath(name).parts) and re.fullmatch(r"[A-Za-z0-9._/-]+",name) is not None for name in names) or sys.exit("image source scope contains an unsafe path"); rows=[f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {name}" for p,name in zip(paths,names,strict=True)]; print(*rows,sep=chr(10))' \
    </dev/null >"$output"
}

validate_compose_entrypoints() {
  local rendered="$scratch/compose.json"
  env -i PATH="$SAFE_PATH" HOME="$scratch" LC_ALL=C COMPOSE_DISABLE_ENV_FILE=true \
    docker compose -f "$worktree/compose.yaml" "${PROFILES[@]}" config --format json \
    >"$rendered"
  python3 - "$rendered" "${APP_SERVICES[@]}" <<'PY'
import json
import pathlib
import sys

expected_services = sys.argv[2:]
expected = {
    "acquisition-api": ["python", "-m", "uvicorn", "app.api_main:app", "--host", "0.0.0.0", "--port", "8000"],
    "acquisition-scheduler": ["python", "-m", "app.scheduler_main"],
    "acquisition-worker": ["python", "-m", "app.worker_main"],
    "governance-scheduler": ["python", "-m", "app.governance_scheduler_main"],
    "governance-worker": ["python", "-m", "app.governance_worker_main"],
    "content-scheduler": ["python", "-m", "app.content_scheduler_main"],
    "content-worker": ["python", "-m", "app.content_worker_main"],
    "wecom-dispatcher": ["python", "-m", "app.wecom_dispatcher_main"],
    "official-account-weekly-dag-worker": ["python", "-m", "app.official_account_weekly_dag_main", "--handler-mode", "fixture", "worker", "--concurrency", "3", "--lease-seconds", "900", "--poll-seconds", "2"],
    "official-account-weekly-scheduler": ["python", "-m", "app.official_account_weekly_scheduler_main"],
    "official-account-local-worker": ["python", "-m", "app.official_account_worker_main"],
    "wechat-official-account-draft-worker": ["python", "-m", "app.wechat_official_account_draft_main", "worker"],
}
payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
services = payload.get("services", {})
if expected_services != list(expected) or not isinstance(services, dict):
    raise SystemExit("reviewed service ordering changed")
for name, prefix in expected.items():
    command = services.get(name, {}).get("command")
    if command != prefix:
        raise SystemExit(f"Compose entrypoint changed: {name}")
PY
}

derive_oci_identity() {
  readarray -t identity < <(python3 - "$stage/backend-image.oci.tar.gz" <<'PY'
import gzip
import hashlib
import json
import pathlib
import tarfile
import sys

path = pathlib.Path(sys.argv[1])
with tarfile.open(path, "r:gz") as archive:
    index = json.load(archive.extractfile("index.json"))
    descriptor = index["manifests"][0]
    manifest_digest = descriptor["digest"]
    manifest = json.load(archive.extractfile(f"blobs/sha256/{manifest_digest[7:]}"))
    config_digest = manifest["config"]["digest"]
print(manifest_digest)
print(config_digest)
PY
  )
  [[ "${#identity[@]}" -eq 2 \
      && "${identity[0]}" =~ ^sha256:[0-9a-f]{64}$ \
      && "${identity[1]}" =~ ^sha256:[0-9a-f]{64}$ ]] \
    || die 'OCI identity derivation failed'
  candidate_manifest_digest=${identity[0]}
  candidate_config_digest=${identity[1]}
  candidate_reference="${candidate_repository}@${candidate_manifest_digest}"
}

normalize_containerd_reference() {
  python3 "$stage/$VALIDATOR_NAME" --normalize-containerd-reference "$1"
}

validate_containerd_socket() {
  [[ -S "$CONTAINERD_ADDRESS" && ! -L "$CONTAINERD_ADDRESS" \
      && "$(realpath -e -- "$CONTAINERD_ADDRESS")" == "$CONTAINERD_ADDRESS" ]]
}

validate_legacy_builder_capabilities() {
  local context endpoint platform driver_status docker_versions docker_help ctr_version ctr_help
  context=$(docker_clean context show) || { die 'Docker context cannot be read'; return 1; }
  [[ "$context" =~ ^[A-Za-z0-9._-]+$ ]] \
    || { die 'Docker context name is unsafe'; return 1; }
  endpoint=$(docker_clean context inspect --format '{{.Endpoints.docker.Host}}' "$context") \
    || { die 'Docker context endpoint cannot be read'; return 1; }
  [[ "$endpoint" == unix:///var/run/docker.sock ]] \
    || { die 'legacy fallback requires the reviewed local Docker socket'; return 1; }
  validate_containerd_socket \
    || { die 'legacy fallback requires the reviewed local containerd socket'; return 1; }
  docker_versions=$(docker_clean version --format '{{.Client.Version}} {{.Server.Version}}') \
    || { die 'Docker client/server capability probe failed'; return 1; }
  [[ "$docker_versions" == '29.1.3 29.1.3' ]] \
    || { die 'Docker client/server versions differ from the reviewed pair'; return 1; }
  platform=$(docker_clean info --format '{{.OSType}}/{{.Architecture}}') \
    || { die 'Docker daemon platform probe failed'; return 1; }
  [[ "$platform" == linux/x86_64 ]] \
    || { die 'legacy fallback requires a linux/amd64 Docker daemon'; return 1; }
  driver_status=$(docker_clean info --format '{{json .DriverStatus}}') \
    || { die 'Docker snapshotter capability probe failed'; return 1; }
  python3 - "$driver_status" <<'PY' \
    || { die 'Docker does not use the reviewed containerd snapshotter'; return 1; }
import json
import sys

try:
    status = json.loads(sys.argv[1])
except json.JSONDecodeError as exc:
    raise SystemExit(1) from exc
if not isinstance(status, list) or ["driver-type", "io.containerd.snapshotter.v1"] not in status:
    raise SystemExit(1)
PY
  docker_help=$(docker_clean build --help) \
    || { die 'legacy Docker build help is unavailable'; return 1; }
  for flag in --pull --platform --tag; do
    grep -Eq "(^|[[:space:]])${flag}([[:space:]]|$)" <<<"$docker_help" \
      || { die "legacy Docker build lacks ${flag}"; return 1; }
  done
  ctr_version=$(ctr_clean version) \
    || { die 'containerd client/server capability probe failed'; return 1; }
  [[ "$(grep -c '^Client:$' <<<"$ctr_version")" == 1 \
      && "$(grep -c '^Server:$' <<<"$ctr_version")" == 1 \
      && "$(grep -c '^  Version:  2\.2\.1$' <<<"$ctr_version")" == 2 ]] \
    || { die 'containerd client/server versions differ from the reviewed pair'; return 1; }
  ctr_clean namespaces list -q | grep -Fxq moby \
    || { die 'containerd moby namespace is unavailable'; return 1; }
  ctr_clean --namespace moby images inspect --help >/dev/null \
    || { die 'containerd image inspect capability is unavailable'; return 1; }
  ctr_help=$(ctr_clean --namespace moby images export --help) \
    || { die 'containerd OCI export help is unavailable'; return 1; }
  for flag in --skip-manifest-json --platform; do
    grep -Fq -- "$flag" <<<"$ctr_help" \
      || { die "containerd OCI export lacks ${flag}"; return 1; }
  done
}

select_image_builder_route() {
  local output
  if output=$(docker_clean buildx version 2>&1); then
    printf 'buildx\n'
    return 0
  fi
  case "$output" in
    *"unknown command"*"buildx"*|*"is not a docker command"*"buildx"*) ;;
    *) die 'docker buildx capability probe failed; refusing fallback'; return 1 ;;
  esac
  validate_legacy_builder_capabilities || return 1
  printf 'legacy-containerd\n'
}

assert_transport_tag_absent() {
  local existing
  existing=$(docker_clean image ls --quiet --filter "reference=${transport_tag}") \
    || { die 'candidate transport tag preflight failed'; return 1; }
  [[ -z "$existing" ]] \
    || { die 'candidate transport tag already exists locally'; return 1; }
  preexisting_repo_digests="$scratch/preexisting-repo-digests"
  docker_clean image ls --digests --format '{{.Repository}}@{{.Digest}}' \
    >"$preexisting_repo_digests" \
    || { die 'preexisting image reference inventory failed'; return 1; }
  candidate_image_owned=0
  candidate_owned_image_id=
}

assert_transport_tag_absent_before_load() {
  local existing
  existing=$(docker_clean image ls --quiet --filter "reference=${transport_tag}") \
    || {
      candidate_image_owned=0
      candidate_reference_owned=0
      candidate_owned_image_id=
      die 'candidate transport tag load preflight failed'
      return 1
    }
  if [[ -n "$existing" ]]; then
    candidate_image_owned=0
    candidate_reference_owned=0
    candidate_owned_image_id=
    die 'candidate transport tag appeared before validated OCI load'
    return 1
  fi
}

bind_candidate_reference_ownership() {
  [[ -n "$candidate_reference" && -f "$preexisting_repo_digests" ]] \
    || { die 'candidate reference ownership cannot be established'; return 1; }
  if grep -Fxq "$candidate_reference" "$preexisting_repo_digests"; then
    candidate_reference_owned=0
  else
    candidate_reference_owned=1
  fi
}

loaded_image_id_matches_candidate() {
  local loaded_id=$1
  [[ "$loaded_id" =~ ^sha256:[0-9a-f]{64}$ \
      && ( "$loaded_id" == "$candidate_manifest_digest" \
      || "$loaded_id" == "$candidate_config_digest" ) ]]
}

bind_loaded_candidate_image_identity() {
  local loaded_id=$1
  candidate_image_owned=0
  candidate_owned_image_id=
  if ! [[ "$loaded_id" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    candidate_reference_owned=0
    die 'loaded image ID is not a SHA-256 identity'
    return 1
  fi
  if ! loaded_image_id_matches_candidate "$loaded_id"; then
    candidate_reference_owned=0
    log "image identity mismatch manifest=${candidate_manifest_digest} config=${candidate_config_digest} loaded=${loaded_id}"
    die 'loaded image ID differs from the archive manifest and config digests'
    return 1
  fi
  candidate_owned_image_id=$loaded_id
  candidate_image_owned=1
}

validate_candidate_image_graph() {
  python3 - "$stage/$VALIDATOR_NAME" "$stage" "$release_sha" \
    "$transport_tag" "$candidate_repository" "$candidate_reference" \
    "$candidate_config_digest" "$candidate_manifest_digest" <<'PY'
import importlib.util
import pathlib
import sys

(
    validator_path,
    raw_stage,
    release_commit,
    transport_tag,
    candidate_repository,
    candidate_reference,
    candidate_config_digest,
    candidate_manifest_digest,
) = sys.argv[1:]
spec = importlib.util.spec_from_file_location("brand_hotfix_validator", validator_path)
if spec is None or spec.loader is None:
    raise SystemExit("validator import failed")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
metadata = {
    "release_commit": release_commit,
    "transport_tag": transport_tag,
    "candidate_repository": candidate_repository,
    "candidate_reference": candidate_reference,
    "candidate_config_digest": candidate_config_digest,
}
observed_manifest = module.validate_image_archive(pathlib.Path(raw_stage), metadata)
if observed_manifest != candidate_manifest_digest:
    raise SystemExit("strict OCI manifest identity changed")
PY
}

run_buildx_image() {
  local created=$1 raw_archive=$2
  env -i PATH="$SAFE_PATH" HOME="$scratch" LC_ALL=C DOCKER_BUILDKIT=1 \
    docker buildx build --pull --platform linux/amd64 --provenance=false --sbom=false \
      --annotation "manifest-descriptor:io.containerd.image.name=${containerd_reference}" \
      --annotation "manifest-descriptor:org.opencontainers.image.ref.name=${short_transport_reference}" \
      --build-arg "CODEUP_COMMIT=${release_sha}" --build-arg "SOURCE_URL=${SOURCE_URL}" \
      --build-arg "BUILD_CREATED=${created}" --tag "$transport_tag" \
      --output "type=oci,name=${transport_tag},dest=${raw_archive}" "$worktree/backend" \
      </dev/null >&2
}

run_legacy_docker_build() {
  local created=$1
  env -i PATH="$SAFE_PATH" HOME="$scratch" LC_ALL=C DOCKER_BUILDKIT=0 \
    docker build --pull --platform linux/amd64 \
      --build-arg "CODEUP_COMMIT=${release_sha}" --build-arg "SOURCE_URL=${SOURCE_URL}" \
      --build-arg "BUILD_CREATED=${created}" --tag "$transport_tag" "$worktree/backend" \
      </dev/null >&2
}

export_canonical_legacy_oci() {
  local raw_archive=$1 legacy_archive="$scratch/backend-image.containerd.oci.tar"
  ctr_clean --namespace moby images inspect "$containerd_reference" >/dev/null \
    || { die 'legacy image is absent from the reviewed containerd namespace'; return 1; }
  ctr_clean --namespace moby images export --skip-manifest-json --platform linux/amd64 \
    "$legacy_archive" "$containerd_reference" >&2 \
    || { die 'legacy containerd OCI export failed'; return 1; }
  python3 "$stage/$VALIDATOR_NAME" --canonicalize-legacy-oci \
    "$legacy_archive" "$raw_archive" "$transport_tag" >&2 \
    || { die 'legacy containerd OCI canonicalization failed'; return 1; }
}

bind_legacy_builder_image_identity() {
  candidate_image_owned=0
  candidate_owned_image_id=
  legacy_builder_image_id=
  legacy_builder_image_id=$(docker_clean image inspect --format '{{.Id}}' "$transport_tag") \
    || {
      candidate_image_owned=0
      die 'legacy builder transport tag is unavailable'
      return 1
    }
  [[ "$legacy_builder_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] \
    || {
      candidate_image_owned=0
      die 'legacy builder image identity is invalid'
      return 1
    }
  candidate_owned_image_id=$legacy_builder_image_id
  candidate_image_owned=1
}

discard_owned_legacy_transport_tag() {
  local current_id
  [[ "$candidate_image_owned" == 1 && -n "$transport_tag" \
      && "$legacy_builder_image_id" =~ ^sha256:[0-9a-f]{64}$ \
      && "$candidate_owned_image_id" == "$legacy_builder_image_id" ]] \
    || {
      candidate_image_owned=0
      candidate_reference_owned=0
      candidate_owned_image_id=
      die 'legacy transport tag ownership is unavailable'
      return 1
    }
  current_id=$(docker_clean image inspect --format '{{.Id}}' "$transport_tag") \
    || {
      candidate_image_owned=0
      candidate_reference_owned=0
      candidate_owned_image_id=
      die 'owned legacy transport tag disappeared before OCI load'
      return 1
    }
  [[ "$current_id" == "$legacy_builder_image_id" ]] \
    || {
      candidate_image_owned=0
      candidate_reference_owned=0
      candidate_owned_image_id=
      die 'owned legacy transport tag identity changed before OCI load'
      return 1
    }
  docker_clean image rm "$transport_tag" >/dev/null \
    || { die 'owned legacy transport tag could not be removed before OCI load'; return 1; }
  assert_transport_tag_absent_before_load || return 1
  candidate_image_owned=0
  candidate_owned_image_id=
}

build_and_probe_image() {
  local raw_archive="$scratch/backend-image.oci.tar" created loaded_id repo_digests observed route
  created=$(git_clean -C "$repo_root" show -s --format=%cI "$release_sha")
  route=$(select_image_builder_route) \
    || { die 'no reviewed image builder route is available'; return 1; }
  assert_transport_tag_absent || return 1
  containerd_reference=$(normalize_containerd_reference "$transport_tag") \
    || { die 'candidate containerd reference normalization failed'; return 1; }
  short_transport_reference=${transport_tag##*:}
  [[ "$short_transport_reference" =~ ^[a-z0-9][a-z0-9._-]*$ ]] \
    || { die 'candidate short transport reference is invalid'; return 1; }
  case "$route" in
    buildx) run_buildx_image "$created" "$raw_archive" ;;
    legacy-containerd)
      run_legacy_docker_build "$created"
      bind_legacy_builder_image_identity
      export_canonical_legacy_oci "$raw_archive"
      ;;
    *) die 'image builder route changed unexpectedly' ;;
  esac
  gzip -n -c "$raw_archive" >"$stage/backend-image.oci.tar.gz"
  derive_oci_identity
  validate_candidate_image_graph \
    || { die 'candidate image failed strict OCI graph validation'; return 1; }
  bind_candidate_reference_ownership
  if [[ "$route" == legacy-containerd ]]; then
    discard_owned_legacy_transport_tag || return 1
  fi
  assert_transport_tag_absent_before_load || return 1
  gzip -dc "$stage/backend-image.oci.tar.gz" | docker image load >/dev/null
  loaded_id=$(docker image inspect --format '{{.Id}}' "$transport_tag") \
    || { die 'validated OCI archive did not create the transport tag'; return 1; }
  bind_loaded_candidate_image_identity "$loaded_id" || return 1
  repo_digests=$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$transport_tag")
  grep -Fxq "$candidate_reference" <<<"$repo_digests" \
    || die 'loaded archive did not produce the derived candidate RepoDigest'
  [[ "$(docker image inspect --format '{{.Id}}' "$candidate_reference")" == "$loaded_id" ]] \
    || die 'derived candidate RepoDigest resolves to another image'
  docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint python "$candidate_reference" \
    -c 'import app.api_main, app.scheduler_main, app.worker_main, app.governance_scheduler_main, app.governance_worker_main, app.content_scheduler_main, app.content_worker_main, app.wecom_dispatcher_main, app.official_account_weekly_dag_main, app.official_account_weekly_scheduler_main, app.official_account_worker_main, app.wechat_official_account_draft_main' \
    </dev/null >/dev/null
  docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint python \
    --env AI_PROVIDER_MODE=zhipu --env AI_PLATFORM_API_KEY=offline-never-sent \
    --env AI_PLATFORM_BASE_URL=https://open.bigmodel.cn/api/paas/v4 \
    --env CONTENT_ENABLED=true --env CONTENT_WORKER_ENABLED=true \
    --env BRAND_EMBEDDING_PROVIDER_MODE=auto "$candidate_reference" -c \
    'from app.core.config import Settings; s=Settings(_env_file=None); assert s.resolved_brand_embedding_provider_mode == "zhipu"; assert s.brand_embedding_model == "embedding-3"; assert s.brand_embedding_dimensions == 2048; assert not s.wecom_auto_delivery_enabled' \
    </dev/null >/dev/null
  write_observed_image_source_manifest \
    "$candidate_reference" "$scratch/observed-image-source.sha256" \
    || { die 'candidate image source manifest could not be read'; return 1; }
  cmp -s "$scratch/observed-image-source.sha256" "$stage/image-source.sha256" \
    || die 'candidate image source differs from the complete manifest'
  observed=$(docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint alembic "$candidate_reference" \
    -c alembic.ini heads </dev/null)
  [[ "$observed" == "$ALEMBIC_HEAD (head)" ]] || die 'candidate Alembic head changed'
  docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint python "$candidate_reference" \
    -m pip check </dev/null >/dev/null
  cleanup_candidate_image
}

write_metadata() {
  python3 - "$stage/release-metadata.json" "$release_sha" "$main_fix_commit" \
    "$main_operator_commit" "$scheduler_cutoff_utc" "$candidate_repository" \
    "$transport_tag" "$candidate_reference" "$candidate_config_digest" \
    "$stage" <<'PY'
import hashlib
import json
import pathlib
import sys

(
    output, release, main_fix, main_operator, cutoff, repository, tag,
    reference, config_digest, raw_stage,
) = sys.argv[1:]
stage = pathlib.Path(raw_stage)
def digest(name: str) -> str:
    return hashlib.sha256((stage / name).read_bytes()).hexdigest()
commands = {
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
payload = {
    "schema_version": 1,
    "production_commit": "40e4dec0ae82569fc798355d4515ab0009697c6f",
    "release_ref": "refs/remotes/origin/release/brand-embedding-hotfix-20260904",
    "release_commit": release,
    "main_fix_commit": main_fix,
    "main_operator_commit": main_operator,
    "alembic_head": "20260901_0042",
    "scheduler_cutoff_utc": cutoff,
    "candidate_repository": repository,
    "transport_tag": tag,
    "candidate_reference": reference,
    "candidate_config_digest": config_digest,
    "source_sha256": digest("source.tar.gz"),
    "source_manifest_sha256": digest("source-manifest.tsv"),
    "image_archive_sha256": digest("backend-image.oci.tar.gz"),
    "image_source_sha256": digest("image-source.sha256"),
    "runtime_diff_sha256": digest("runtime-diff.tsv"),
    "audit_diff_sha256": digest("audit-diff.tsv"),
    "production_baseline_sha256": digest("production-baseline.json"),
    "builder_sha256": digest("build-brand-embedding-hotfix-offline-artifacts.sh"),
    "capture_sha256": digest("capture-brand-embedding-production-baseline.sh"),
    "operator_sha256": digest("brand-embedding-hotfix-offline-release-operator.sh"),
    "validator_sha256": digest("validate-brand-embedding-hotfix-offline-artifacts.py"),
    "app_services": list(commands),
    "service_commands": commands,
}
pathlib.Path(output).write_text(
    json.dumps(payload, separators=(",", ":"), sort_keys=True), encoding="utf-8"
)
PY
}

main() {
  parse_args "$@"
  repo_root=$(realpath -e -- "$(git rev-parse --show-toplevel)")
  scratch=$(mktemp -d /tmp/edu-ai-brand-embedding-build.XXXXXX)
  worktree="$scratch/worktree"
  stage="$scratch/stage"
  mkdir -m 700 "$stage"
  assert_authority
  create_worktree
  for name in "$BUILDER_NAME" "$CAPTURE_NAME" "$OPERATOR_NAME" "$VALIDATOR_NAME"; do
    git_clean -C "$repo_root" show "${release_sha}:${TASK_PATH}/${name}" >"$stage/$name"
  done
  chmod 600 "$stage/$BUILDER_NAME" "$stage/$CAPTURE_NAME" \
    "$stage/$OPERATOR_NAME" "$stage/$VALIDATOR_NAME"
  install -m 600 "$production_baseline" "$stage/production-baseline.json"
  python3 - "$stage/$VALIDATOR_NAME" "$stage/production-baseline.json" <<'PY'
import importlib.util
import pathlib
import sys

spec = importlib.util.spec_from_file_location("brand_hotfix_validator", sys.argv[1])
if spec is None or spec.loader is None:
    raise SystemExit("validator import failed")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.validate_baseline(pathlib.Path(sys.argv[2]))
PY
  capture_complete_diff
  validate_compose_entrypoints
  build_source_archive
  write_image_source_manifest
  candidate_repository=$(python3 - "$production_baseline" <<'PY'
import json
import pathlib
import sys
reference = json.loads(pathlib.Path(sys.argv[1]).read_bytes())["current_image_reference"]
print(reference.rsplit("@", 1)[0])
PY
  )
  [[ "$candidate_repository" =~ ^[a-z0-9.-]+(:[0-9]+)?(/[a-z0-9]+([._-][a-z0-9]+)*)*$ ]] \
    || die 'candidate repository derived from baseline is invalid'
  transport_tag="${candidate_repository}:brand-embedding-${release_sha:0:12}"
  build_and_probe_image
  write_metadata
  (
    cd "$stage"
    chmod 600 "${FINAL_MEMBERS[@]}"
    sha256sum "${FINAL_MEMBERS[@]}" | sort -k2 >artifacts.sha256
    chmod 600 artifacts.sha256
  )
  python3 "$stage/$VALIDATOR_NAME" "$stage"
  mkdir -m 700 "$output_dir"
  local member
  for member in artifacts.sha256 "${FINAL_MEMBERS[@]}"; do
    install -m 600 "$stage/$member" "$output_dir/$member"
  done
  python3 "$output_dir/$VALIDATOR_NAME" "$output_dir"
  printf 'brand_embedding_artifact_stage=%s\nrelease_ref=%s\nrelease_commit=%s\ncandidate_reference=%s\n' \
    "$output_dir" "$RELEASE_REF" "$release_sha" "$candidate_reference"
}

if [[ "${BRAND_HOTFIX_BUILDER_SOURCE_ONLY:-0}" != 1 ]]; then
  main "$@"
fi
