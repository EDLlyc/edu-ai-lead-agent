#!/usr/bin/env bash
# Build the reviewed image-fallback release source/image artifacts from an already-fetched
# authoritative Codeup commit. This script never fetches, pulls, pushes,
# transfers, connects to production, or reads payload bytes from the caller's
# worktree.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077
export LC_ALL=C

readonly PATHSET_BASE_COMMIT="c66aa6217d137033118c552f3db11b2a1121d082"
readonly PREVIOUS_COMMIT="7ba25d3eeb290d3f784ae449a5b6ad360a8def58"
readonly RELEASE_COMMIT="cbc27b2491e4ebd49e6cc58692b065268e2887db"
readonly DEPENDENCY_BASE_ID="sha256:50fd2519fbc5aa204c45e76cb685d01aaea1656b998d3ed96c9ab6671b3b9374"
readonly EXPECTED_RUNTIME_LOCK_SHA256="3be154ff0e7f741b9f74d516baf739a4a38571218670b47dd1031f9dc1b44915"
readonly EXPECTED_DOCKERFILE_SHA256="d4c2823d9354a7a5c31c2885317cd46b5c764d6afb964306c4204f7ed063fd1f"
readonly EXPECTED_BASE_PYPROJECT_SHA256="c6c8e92b901e75cc4095d28dd81cd9265382ba133827875edb9ddbc6160824e1"
readonly EXPECTED_FINAL_PYPROJECT_SHA256="c6c8e92b901e75cc4095d28dd81cd9265382ba133827875edb9ddbc6160824e1"
readonly EXPECTED_COMPOSE_SHA256="6a314a61fbf11bbbc433b2feb5a164de54de401f38becdc791fab926c5b73cff"
readonly EXPECTED_OPENAPI_SHA256="eaa3cccf1802553879ec21fb447086d2adcc01afa657be885401dc3ae9a0b5f4"
readonly EXPECTED_SOURCE_FILE_COUNT=321
readonly EXPECTED_PATHSET_BASE_SOURCE_FILE_COUNT=307
readonly EXPECTED_PREVIOUS_SOURCE_FILE_COUNT=321
readonly EXPECTED_IMAGE_SOURCE_FILE_COUNT=179
readonly EXPECTED_PREVIOUS_IMAGE_SOURCE_FILE_COUNT=179
readonly EXPECTED_ALEMBIC_HEAD="20260815_0021"
readonly SOURCE_URL="https://codeup.aliyun.com/601cdb1a841cc46b7c49b115/marketingUseOnly/edu-ai-lead-agent.git"
readonly DOCKER_SOCKET="unix:///var/run/docker.sock"
readonly TARGET_PLATFORM="linux/amd64"
readonly SAFE_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH="$SAFE_PATH"
readonly TASK_RESEARCH_PATH=".trellis/tasks/08-17-deploy-image-output-fallback/research"
readonly BUILDER_REPO_PATH="${TASK_RESEARCH_PATH}/build-image-fallback-offline-artifacts.sh"
readonly OPERATOR_REPO_PATH="${TASK_RESEARCH_PATH}/baseline-7ba-offline-release-operator.sh"
readonly VALIDATOR_REPO_PATH="${TASK_RESEARCH_PATH}/validate-image-fallback-offline-artifacts.py"

readonly -a SOURCE_PATHSPECS=(
  backend deploy infra scripts compose.yaml .env.example .gitattributes
  .gitignore AGENTS.md Makefile README.md environment.yml
)
readonly -a RUNTIME_PATHSET_ADDITIONS=(
  backend/app/agent_mcp_main.py
  backend/app/agent_workbench_api_main.py
  backend/app/agent_workbench_runtime.py
  backend/app/api/v1/routes/agent_workbench.py
  backend/app/application/ports/agent_workbench.py
  backend/app/application/services/agent_tools.py
  backend/app/application/services/agent_workbench.py
  backend/app/application/services/agent_workbench_graph.py
  backend/app/core/agent_workbench_config.py
  backend/app/domain/agent_workbench.py
  backend/app/infrastructure/agent_workbench_fixture.py
  backend/app/infrastructure/ai/agent_workbench.py
  backend/app/infrastructure/db/agent_workbench.py
  backend/app/schemas/agent_workbench.py
)
readonly -a EXPECTED_SOURCE_DIFF=(
  backend/app/application/services/material_package.py
  backend/app/domain/image_fallback.py
  backend/app/infrastructure/ai/image_generation.py
  backend/tests/unit/test_image_fallback.py
  backend/tests/unit/test_image_generation.py
  backend/tests/unit/test_material_package.py
  backend/tests/unit/test_wecom_delivery.py
)
readonly -a EXPECTED_RUNTIME_DIFF=(
  app/application/services/material_package.py
  app/domain/image_fallback.py
  app/infrastructure/ai/image_generation.py
)
readonly -a SUPPORTED_RUNTIME_MODULES=(
  app.api_main app.scheduler_main app.worker_main
  app.governance_scheduler_main app.governance_worker_main
  app.content_scheduler_main app.content_worker_main
  app.wecom_dispatcher_main
)
readonly -a RELEASE_LABEL_KEYS=(
  org.opencontainers.image.revision
  io.trellis.dependency-base.digest
  io.trellis.dependency-input.base-pyproject-sha256
  io.trellis.dependency-input.final-pyproject-sha256
  io.trellis.dependency-input.runtime-lock-sha256
  io.trellis.dependency-input.dockerfile-sha256
  io.trellis.release.source-archive-sha256
  io.trellis.release.source-manifest-sha256
  io.trellis.release.image-source-manifest-sha256
)
readonly -a ARTIFACT_TARGETS=(
  backend-image.tar.gz backend-image.tar.gz.sha256
  baseline-7ba-offline-release-operator.sh image-source-files.sha256
  image-validation.txt source-files.sha256 source.tar.gz
  source.tar.gz.sha256 validate-image-fallback-offline-artifacts.py
)
readonly -a STAGE_MEMBERS=(artifacts.sha256 "${ARTIFACT_TARGETS[@]}")

declare -A BASE_MODE=()
declare -A BASE_BLOB=()
declare -A RELEASE_MODE=()
declare -A RELEASE_BLOB=()

release_sha=""
authority_sha=""
requested_output_dir=""
requested_output_parent_identity=""
repo_root=""
script_path=""
scratch_root=""
release_worktree=""
artifact_stage=""
final_output_dir=""
final_output_identity=""
final_output_incomplete=0
candidate_tag=""
candidate_id=""
source_sha256=""
source_manifest_sha256=""
image_source_manifest_sha256=""
image_bundle_sha256=""
build_created=""
cleanup_armed=1

log() { printf '[image-fallback-artifact-builder] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; return 1; }

usage() {
  cat >&2 <<'EOF'
Usage: build-image-fallback-offline-artifacts.sh \
  --authority-sha HEX40 \
  --release-sha cbc27b2491e4ebd49e6cc58692b065268e2887db \
  [--output-dir ABSOLUTE_NEW_DIR]

The authority SHA must equal the already-fetched Codeup origin/main and contain
the exact application release SHA. The optional output path must not exist. On success,
the script prints the protected artifact directory, candidate tag/ID, and
artifact hashes. It performs no fetch, pull, push, SSH, transfer, or deployment.
EOF
}

parse_args() {
  release_sha=""
  authority_sha=""
  requested_output_dir=""
  requested_output_parent_identity=""
  while (($#)); do
    case "$1" in
      --release-sha)
        (($# >= 2)) || { die "missing value for --release-sha"; return 2; }
        release_sha=$2
        shift 2
        ;;
      --authority-sha)
        (($# >= 2)) || { die "missing value for --authority-sha"; return 2; }
        authority_sha=$2
        shift 2
        ;;
      --output-dir)
        (($# >= 2)) || { die "missing value for --output-dir"; return 2; }
        requested_output_dir=$2
        shift 2
        ;;
      -h|--help)
        usage
        return 64
        ;;
      *)
        die "unknown argument"
        return 2
        ;;
    esac
  done
  [[ "$release_sha" == "$RELEASE_COMMIT" ]] || { die "release SHA is not exact cbc27b2"; return 2; }
  [[ "$authority_sha" =~ ^[0-9a-f]{40}$ ]] || { die "authority SHA must be 40 lowercase hex characters"; return 2; }
  if [[ -n "$requested_output_dir" ]]; then
    [[ "$requested_output_dir" == /* && "$requested_output_dir" != */ && ! -e "$requested_output_dir" && ! -L "$requested_output_dir" ]] \
      || { die "output directory must be an absent canonical absolute path"; return 2; }
    [[ "$(basename -- "$requested_output_dir")" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
      || { die "output directory basename is unsafe"; return 2; }
    local output_parent
    output_parent=$(dirname -- "$requested_output_dir")
    [[ -d "$output_parent" && ! -L "$output_parent" && "$(realpath -e -- "$output_parent")" == "$output_parent" ]] \
      || { die "output directory parent must be a physical absolute directory"; return 2; }
    requested_output_parent_identity=$(stat -c '%d:%i:%a:%u:%g' "$output_parent") \
      || { die "output directory parent identity is unreadable"; return 2; }
  fi
}

git_call() {
  env -i PATH="$SAFE_PATH" HOME="${scratch_root:-/tmp}" LC_ALL=C \
    GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false \
    git "$@"
}

docker_call() {
  env -i PATH="$SAFE_PATH" HOME="$scratch_root/docker-home" LC_ALL=C \
    DOCKER_BUILDKIT=0 docker --host "$DOCKER_SOCKET" "$@"
}

runtime_run() {
  docker_call run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true "$@"
}

assert_release_authority() {
  local root=$1 expected_authority=$2 expected_release=$3 origin_url origin_sha
  origin_url=$(git_call -C "$root" config --get remote.origin.url)
  case "$origin_url" in
    git@codeup-edu-ai:601cdb1a841cc46b7c49b115/marketingUseOnly/edu-ai-lead-agent.git|\
    git@codeup.aliyun.com:601cdb1a841cc46b7c49b115/marketingUseOnly/edu-ai-lead-agent.git|\
    https://codeup.aliyun.com/601cdb1a841cc46b7c49b115/marketingUseOnly/edu-ai-lead-agent.git) ;;
    *) die "origin is not the reviewed Codeup repository"; return 1 ;;
  esac
  origin_sha=$(git_call -C "$root" rev-parse --verify 'refs/remotes/origin/main^{commit}')
  [[ "$origin_sha" =~ ^[0-9a-f]{40}$ && "$origin_sha" == "$expected_authority" ]] \
    || { die "authority SHA is not the already-fetched origin/main"; return 1; }
  [[ "$expected_release" == "$RELEASE_COMMIT" ]] || { die "application release identity drift"; return 1; }
  git_call -C "$root" cat-file -e "${PATHSET_BASE_COMMIT}^{commit}"
  git_call -C "$root" cat-file -e "${PREVIOUS_COMMIT}^{commit}"
  git_call -C "$root" cat-file -e "${expected_release}^{commit}"
  git_call -C "$root" merge-base --is-ancestor "$expected_release" "$origin_sha" \
    || { die "exact application release is not reachable from origin/main"; return 1; }
}

assert_builder_authority() {
  local root=$1 expected_sha=$2 expected_path actual_path path committed_hash actual_hash
  expected_path=$(realpath -e -- "${root}/${BUILDER_REPO_PATH}")
  actual_path=$(realpath -e -- "$script_path")
  [[ "$actual_path" == "$expected_path" ]] || { die "builder must run from its reviewed repository path"; return 1; }
  for path in "$BUILDER_REPO_PATH" "$OPERATOR_REPO_PATH" "$VALIDATOR_REPO_PATH"; do
    committed_hash=$(git_call -C "$root" show "${expected_sha}:${path}" | sha256sum | awk '{print $1}')
    actual_hash=$(sha256sum "${root}/${path}" | awk '{print $1}')
    [[ "$committed_hash" == "$actual_hash" ]] \
      || { die "release tooling differs from authoritative origin/main: $path"; return 1; }
  done
}

create_clean_detached_worktree() {
  local root=$1 expected_sha=$2 target=$3 head status
  git_call -C "$root" worktree add --detach "$target" "$expected_sha" >/dev/null
  head=$(git_call -C "$target" rev-parse --verify HEAD)
  [[ "$head" == "$expected_sha" ]] || { die "detached worktree SHA mismatch"; return 1; }
  if git_call -C "$target" symbolic-ref -q HEAD >/dev/null 2>&1; then
    die "release worktree is not detached"
    return 1
  fi
  status=$(git_call -C "$target" status --porcelain=v1 --untracked-files=all)
  [[ -z "$status" ]] || { die "release worktree is not clean"; return 1; }
}

assert_clean_detached_worktree() {
  local target=$1 expected_sha=$2 head status
  head=$(git_call -C "$target" rev-parse --verify HEAD)
  [[ "$head" == "$expected_sha" ]] || { die "release worktree SHA drift"; return 1; }
  if git_call -C "$target" symbolic-ref -q HEAD >/dev/null 2>&1; then
    die "release worktree became attached"
    return 1
  fi
  status=$(git_call -C "$target" status --porcelain=v1 --untracked-files=all)
  [[ -z "$status" ]] || { die "release worktree acquired dirty bytes"; return 1; }
}

assert_safe_source_path() {
  local value=$1 part
  [[ "$value" =~ ^[A-Za-z0-9._/-]+$ && "$value" != /* && "$value" != */ && "$value" != *//* ]] \
    || { die "source path syntax is unsafe"; return 1; }
  IFS=/ read -r -a parts <<<"$value"
  for part in "${parts[@]}"; do
    [[ -n "$part" && "$part" != . && "$part" != .. && "$part" != __pycache__ && "$part" != private ]] \
      || { die "source path component is unsafe"; return 1; }
  done
  case "$value" in
    .env.example|.gitattributes|.gitignore|AGENTS.md|Makefile|README.md|compose.yaml|environment.yml|\
    backend/*|deploy/*|infra/*|scripts/*) ;;
    *) die "source path is outside the reviewed runtime roots"; return 1 ;;
  esac
  case "$value" in
    .env|.release.env|frontend/*|output/*|reports/*|.trellis/*|*.fls|*.fdb_latexmk|*.xdv)
      die "source path is forbidden"
      return 1
      ;;
  esac
}

assert_safe_addition_path() {
  local value=$1
  assert_safe_source_path "$value"
  [[ "$value" == backend/app/*.py || "$value" == backend/app/*.html ]] \
    || { die "candidate-only path is outside backend/app Python/HTML scope"; return 1; }
}

load_tree_map() {
  local root=$1 commit=$2 prefix=$3 output_file=$4 record metadata path mode type blob
  git_call -C "$root" ls-tree -r -z "$commit" >"$output_file"
  while IFS= read -r -d '' record; do
    metadata=${record%%$'\t'*}
    path=${record#*$'\t'}
    IFS=' ' read -r mode type blob <<<"$metadata"
    [[ "$type" == blob ]] || continue
    if [[ "$prefix" == BASE ]]; then
      BASE_MODE["$path"]=$mode
      BASE_BLOB["$path"]=$blob
    else
      RELEASE_MODE["$path"]=$mode
      RELEASE_BLOB["$path"]=$blob
    fi
  done <"$output_file"
}

write_base_source_paths() {
  local root=$1 output=$2 raw
  raw="${output}.raw"
  git_call -C "$root" ls-tree -r -z --name-only "$PATHSET_BASE_COMMIT" -- "${SOURCE_PATHSPECS[@]}" >"$raw"
  tr '\0' '\n' <"$raw" | LC_ALL=C sort >"$output"
  [[ "$(wc -l <"$output" | tr -d '[:space:]')" == "$EXPECTED_PATHSET_BASE_SOURCE_FILE_COUNT" ]] \
    || { die "reviewed runtime pathset base is not exact 307"; return 1; }
}

write_image_scope_paths() {
  local root=$1 commit=$2 output=$3 prefix record value raw
  raw="${output}.raw"
  git_call -C "$root" ls-tree -r -z --name-only "$commit" -- \
    backend/alembic.ini backend/pyproject.toml backend/alembic backend/app >"$raw"
  : >"$output"
  while IFS= read -r -d '' record; do
    case "$record" in
      backend/alembic.ini|backend/pyproject.toml|backend/alembic/*.py|backend/alembic/*.html|backend/app/*.py|backend/app/*.html)
        value=${record#backend/}
        printf '%s\n' "$value" >>"$output"
        ;;
    esac
  done <"$raw"
  LC_ALL=C sort -o "$output" "$output"
}

validate_equal_path_sets() {
  local previous_paths=$1 candidate_paths=$2 expected_count=$3
  [[ "$(wc -l <"$previous_paths" | tr -d '[:space:]')" == "$expected_count" ]] \
    || { die "previous path count mismatch"; return 1; }
  [[ "$(wc -l <"$candidate_paths" | tr -d '[:space:]')" == "$expected_count" ]] \
    || { die "candidate path count mismatch"; return 1; }
  [[ "$(LC_ALL=C sort -u "$previous_paths")" == "$(<"$previous_paths")" ]] \
    || { die "previous paths are duplicate or unsorted"; return 1; }
  [[ "$(LC_ALL=C sort -u "$candidate_paths")" == "$(<"$candidate_paths")" ]] \
    || { die "candidate paths are duplicate or unsorted"; return 1; }
  cmp -- "$previous_paths" "$candidate_paths" >/dev/null \
    || { die "7ba and cbc runtime path sets differ"; return 1; }
}

assert_exact_runtime_diff() {
  local paths=$1 changed_output=$2 path expected
  : >"$changed_output"
  while IFS= read -r path; do
    [[ -n "${BASE_MODE[$path]+present}" && -n "${RELEASE_MODE[$path]+present}" ]] \
      || { die "runtime path missing from 7ba or cbc"; return 1; }
    [[ "${BASE_MODE[$path]}" == "${RELEASE_MODE[$path]}" ]] \
      || { die "runtime executable class changed"; return 1; }
    if [[ "${BASE_BLOB[$path]}" != "${RELEASE_BLOB[$path]}" ]]; then
      printf '%s\n' "$path" >>"$changed_output"
    fi
  done <"$paths"
  expected=$(printf '%s\n' "${EXPECTED_SOURCE_DIFF[@]}" | LC_ALL=C sort)
  [[ "$(<"$changed_output")" == "$expected" ]] \
    || { die "7ba to cbc source diff is not the exact seven reviewed application/test blobs"; return 1; }
}

assert_exact_image_diff() {
  local paths=$1 changed_output=$2 relative path expected
  : >"$changed_output"
  while IFS= read -r relative; do
    path="backend/${relative}"
    [[ -n "${BASE_BLOB[$path]+present}" && -n "${RELEASE_BLOB[$path]+present}" ]] \
      || { die "image source path missing from 7ba or cbc"; return 1; }
    if [[ "${BASE_BLOB[$path]}" != "${RELEASE_BLOB[$path]}" ]]; then
      printf '%s\n' "$relative" >>"$changed_output"
    fi
  done <"$paths"
  expected=$(printf '%s\n' "${EXPECTED_RUNTIME_DIFF[@]}" | LC_ALL=C sort)
  [[ "$(<"$changed_output")" == "$expected" ]] \
    || { die "7ba to cbc image/runtime diff is not the exact three reviewed blobs"; return 1; }
}

copy_committed_file() {
  local worktree=$1 destination_root=$2 path=$3 git_mode=$4 blob=$5
  local source destination install_mode observed_blob source_hash destination_hash
  assert_safe_source_path "$path"
  case "$git_mode" in
    100644) install_mode=0644 ;;
    100755) install_mode=0755 ;;
    *) die "tracked source mode is not a regular 0644/0755 class"; return 1 ;;
  esac
  source="${worktree}/${path}"
  destination="${destination_root}/${path}"
  [[ -f "$source" && ! -L "$source" && "$(realpath -e -- "$source")" == "${worktree}/${path}" ]] \
    || { die "detached source file is not a physical regular file"; return 1; }
  observed_blob=$(git_call -C "$worktree" hash-object --no-filters -- "$source")
  [[ "$observed_blob" == "$blob" ]] || { die "detached source bytes differ from the committed blob"; return 1; }
  install -D -m "$install_mode" -- "$source" "$destination"
  source_hash=$(sha256sum "$source" | awk '{print $1}')
  destination_hash=$(sha256sum "$destination" | awk '{print $1}')
  [[ "$source_hash" == "$destination_hash" ]] || { die "normalized copy differs from committed source"; return 1; }
}

write_checksum_manifest() {
  local tree=$1 paths_file=$2 output=$3 path digest
  : >"$output"
  while IFS= read -r path; do
    digest=$(sha256sum "${tree}/${path}" | awk '{print $1}')
    printf '%s  %s\n' "$digest" "$path" >>"$output"
  done <"$paths_file"
}

write_release_source_sidecar() {
  local output=$1 digest=$2
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || { die "source digest for release sidecar is invalid"; return 1; }
  printf '%s\n' "$digest" >"$output"
  [[ "$(wc -l <"$output" | tr -d '[:space:]')" == 1 && "$(wc -c <"$output" | tr -d '[:space:]')" == 65 && "$(<"$output")" == "$digest" ]] \
    || { die "release source sidecar is not exactly one digest line"; return 1; }
}

assert_dependency_compatibility() {
  local worktree=$1 base_pyproject="${scratch_root}/base-pyproject.toml"
  git_call -C "$repo_root" show "${PREVIOUS_COMMIT}:backend/pyproject.toml" >"$base_pyproject"
  [[ "$(sha256sum "$base_pyproject" | awk '{print $1}')" == "$EXPECTED_BASE_PYPROJECT_SHA256" ]] \
    || { die "base pyproject hash mismatch"; return 1; }
  [[ "$(sha256sum "${worktree}/backend/pyproject.toml" | awk '{print $1}')" == "$EXPECTED_FINAL_PYPROJECT_SHA256" ]] \
    || { die "final pyproject hash mismatch"; return 1; }
  [[ "$(sha256sum "${worktree}/backend/requirements/runtime.lock" | awk '{print $1}')" == "$EXPECTED_RUNTIME_LOCK_SHA256" ]] \
    || { die "runtime.lock hash mismatch"; return 1; }
  [[ "$(sha256sum "${worktree}/backend/Dockerfile" | awk '{print $1}')" == "$EXPECTED_DOCKERFILE_SHA256" ]] \
    || { die "Dockerfile hash mismatch"; return 1; }
  [[ "$(sha256sum "${worktree}/compose.yaml" | awk '{print $1}')" == "$EXPECTED_COMPOSE_SHA256" ]] \
    || { die "Compose hash mismatch"; return 1; }
  [[ "$(sha256sum "${worktree}/backend/openapi.json" | awk '{print $1}')" == "$EXPECTED_OPENAPI_SHA256" ]] \
    || { die "OpenAPI hash mismatch"; return 1; }
  for path in backend/pyproject.toml backend/requirements/runtime.lock backend/Dockerfile \
    compose.yaml backend/openapi.json backend/alembic.ini; do
    cmp -- "${worktree}/${path}" <(git_call -C "$repo_root" show "${PREVIOUS_COMMIT}:${path}") >/dev/null \
      || { die "protected release input changed from exact 7ba: $path"; return 1; }
  done
  git_call -C "$repo_root" diff --quiet "$PREVIOUS_COMMIT" "$release_sha" -- backend/alembic \
    || { die "Alembic tree changed from exact 7ba"; return 1; }
  python3 - "${worktree}/backend/app" "${SUPPORTED_RUNTIME_MODULES[@]}" <<'PY'
import ast
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
supported = {value.replace(".", "/") + ".py" for value in sys.argv[2:]}
importers = []
for path in sorted(root.rglob("*.py")):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            alias.name == "mcp" or alias.name.startswith("mcp.") for alias in node.names
        ):
            found = True
        if isinstance(node, ast.ImportFrom) and (
            node.module == "mcp" or (node.module or "").startswith("mcp.")
        ):
            found = True
    if found:
        importers.append(path.relative_to(root.parent).as_posix())
if importers != ["app/agent_mcp_main.py"]:
    raise SystemExit(f"unexpected mcp importers: {len(importers)}")
if supported & set(importers):
    raise SystemExit("a supported runtime module imports mcp")
PY
}

write_overlay_dockerfile() {
  local output=$1
  cat >"$output" <<'DOCKERFILE'
ARG DEPENDENCY_BASE_DIGEST
FROM ${DEPENDENCY_BASE_DIGEST}

ARG DEPENDENCY_BASE_DIGEST
ARG RELEASE_COMMIT
ARG BUILD_CREATED
ARG SOURCE_URL
ARG BASE_PYPROJECT_SHA256
ARG FINAL_PYPROJECT_SHA256
ARG RUNTIME_LOCK_SHA256
ARG DOCKERFILE_SHA256
ARG SOURCE_ARCHIVE_SHA256
ARG SOURCE_MANIFEST_SHA256
ARG IMAGE_SOURCE_MANIFEST_SHA256

LABEL org.opencontainers.image.created="${BUILD_CREATED}" \
      org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.revision="${RELEASE_COMMIT}" \
      io.trellis.dependency-base.digest="${DEPENDENCY_BASE_DIGEST}" \
      io.trellis.dependency-input.base-pyproject-sha256="${BASE_PYPROJECT_SHA256}" \
      io.trellis.dependency-input.final-pyproject-sha256="${FINAL_PYPROJECT_SHA256}" \
      io.trellis.dependency-input.runtime-lock-sha256="${RUNTIME_LOCK_SHA256}" \
      io.trellis.dependency-input.dockerfile-sha256="${DOCKERFILE_SHA256}" \
      io.trellis.release.source-archive-sha256="${SOURCE_ARCHIVE_SHA256}" \
      io.trellis.release.source-manifest-sha256="${SOURCE_MANIFEST_SHA256}" \
      io.trellis.release.image-source-manifest-sha256="${IMAGE_SOURCE_MANIFEST_SHA256}"

USER root
WORKDIR /app
RUN set -eu; \
    site_packages="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"; \
    rm -rf \
      /app/app \
      /app/alembic \
      /app/build \
      /app/edu_ai_lead_agent_backend.egg-info \
      "${site_packages}/app"; \
    rm -f \
      /app/alembic.ini \
      /app/pyproject.toml \
      /app/.release-source.sha256

COPY --chown=app:app pyproject.toml alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app
COPY --chown=app:app .release-source.sha256 ./.release-source.sha256

USER app
DOCKERFILE
  chmod 0600 "$output"
}

build_candidate_image() {
  local context=$1 dockerfile=$2 base_actual base_platform
  [[ -S /var/run/docker.sock ]] || { die "reviewed local Docker Unix socket is absent"; return 1; }
  install -d -m 0700 "${scratch_root}/docker-home"
  base_actual=$(docker_call image inspect "$DEPENDENCY_BASE_ID" --format '{{.Id}}')
  [[ "$base_actual" == "$DEPENDENCY_BASE_ID" ]] || { die "immutable dependency base is not already local"; return 1; }
  base_platform=$(docker_call image inspect "$DEPENDENCY_BASE_ID" --format '{{.Os}}/{{.Architecture}}')
  [[ "$base_platform" == "$TARGET_PLATFORM" ]] || { die "immutable dependency base is not linux/amd64"; return 1; }
  if docker_call image inspect "$candidate_tag" >/dev/null 2>&1; then
    die "isolated candidate tag already exists"
    return 1
  fi
  docker_call build --platform "$TARGET_PLATFORM" --network none --pull=false --no-cache \
    --file "$dockerfile" --tag "$candidate_tag" \
    --build-arg "DEPENDENCY_BASE_DIGEST=${DEPENDENCY_BASE_ID}" \
    --build-arg "RELEASE_COMMIT=${release_sha}" \
    --build-arg "BUILD_CREATED=${build_created}" \
    --build-arg "SOURCE_URL=${SOURCE_URL}" \
    --build-arg "BASE_PYPROJECT_SHA256=${EXPECTED_BASE_PYPROJECT_SHA256}" \
    --build-arg "FINAL_PYPROJECT_SHA256=${EXPECTED_FINAL_PYPROJECT_SHA256}" \
    --build-arg "RUNTIME_LOCK_SHA256=${EXPECTED_RUNTIME_LOCK_SHA256}" \
    --build-arg "DOCKERFILE_SHA256=${EXPECTED_DOCKERFILE_SHA256}" \
    --build-arg "SOURCE_ARCHIVE_SHA256=${source_sha256}" \
    --build-arg "SOURCE_MANIFEST_SHA256=${source_manifest_sha256}" \
    --build-arg "IMAGE_SOURCE_MANIFEST_SHA256=${image_source_manifest_sha256}" \
    "$context"
  candidate_id=$(docker_call image inspect "$candidate_tag" --format '{{.Id}}')
  [[ "$candidate_id" =~ ^sha256:[0-9a-f]{64}$ ]] || { die "candidate image ID is invalid"; return 1; }
}

assert_candidate_labels() {
  local key actual expected
  [[ "$(docker_call image inspect "$candidate_id" --format '{{.Os}}/{{.Architecture}}')" == "$TARGET_PLATFORM" ]] \
    || { die "candidate platform is not linux/amd64"; return 1; }
  for key in "${RELEASE_LABEL_KEYS[@]}"; do
    case "$key" in
      org.opencontainers.image.revision) expected=$release_sha ;;
      io.trellis.dependency-base.digest) expected=$DEPENDENCY_BASE_ID ;;
      io.trellis.dependency-input.base-pyproject-sha256) expected=$EXPECTED_BASE_PYPROJECT_SHA256 ;;
      io.trellis.dependency-input.final-pyproject-sha256) expected=$EXPECTED_FINAL_PYPROJECT_SHA256 ;;
      io.trellis.dependency-input.runtime-lock-sha256) expected=$EXPECTED_RUNTIME_LOCK_SHA256 ;;
      io.trellis.dependency-input.dockerfile-sha256) expected=$EXPECTED_DOCKERFILE_SHA256 ;;
      io.trellis.release.source-archive-sha256) expected=$source_sha256 ;;
      io.trellis.release.source-manifest-sha256) expected=$source_manifest_sha256 ;;
      io.trellis.release.image-source-manifest-sha256) expected=$image_source_manifest_sha256 ;;
      *) die "unknown release label key"; return 1 ;;
    esac
    actual=$(docker_call image inspect "$candidate_id" --format "{{index .Config.Labels \"${key}\"}}")
    [[ "$actual" == "$expected" ]] || { die "candidate provenance label mismatch"; return 1; }
  done
  [[ "$(docker_call image inspect "$candidate_id" --format '{{.Config.User}}')" == app ]] \
    || { die "candidate default user is not app"; return 1; }
}

assert_rootfs_base_prefix() {
  local base_json="${scratch_root}/base-rootfs.json" candidate_json="${scratch_root}/candidate-rootfs.json"
  docker_call image inspect "$DEPENDENCY_BASE_ID" --format '{{json .RootFS.Layers}}' >"$base_json"
  docker_call image inspect "$candidate_id" --format '{{json .RootFS.Layers}}' >"$candidate_json"
  python3 - "$base_json" "$candidate_json" <<'PY'
import json
import pathlib
import sys

base = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
candidate = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
if not isinstance(base, list) or not isinstance(candidate, list):
    raise SystemExit("rootfs layer inventory is invalid")
if not base or len(candidate) <= len(base) or candidate[: len(base)] != base:
    raise SystemExit("candidate rootfs does not retain the exact dependency-base prefix")
PY
}

assert_candidate_runtime() {
  local context=$1 validator=$2 observed="${scratch_root}/image-source-observed.sha256"
  local rendered_openapi="${scratch_root}/runtime-openapi.json" alembic_heads
  local modules_csv
  modules_csv=$(IFS=,; printf '%s' "${SUPPORTED_RUNTIME_MODULES[*]}")
  assert_candidate_labels
  assert_rootfs_base_prefix
  runtime_run --entrypoint sh "$candidate_id" -c \
    'set -eu; expected=$1; test "$(id -u)" -ne 0; test "$(id -un)" = app; test "$(wc -l </app/.release-source.sha256)" -eq 1; test "$(wc -c </app/.release-source.sha256)" -eq 65; test "$(cat /app/.release-source.sha256)" = "$expected"; test -z "$(find /app/app /app/alembic /app/alembic.ini /app/pyproject.toml /app/.release-source.sha256 \( ! -user app -o ! -group app \) -print -quit)"; if touch /app/.image-fallback-write-probe >/dev/null 2>&1; then exit 1; fi; test ! -e /app/build; test ! -e /app/edu_ai_lead_agent_backend.egg-info' \
    sh "$source_sha256"
  runtime_run --entrypoint python "$candidate_id" -c \
    'import importlib,sys; [importlib.import_module(value) for value in sys.argv[1].split(",")]' \
    "$modules_csv"
  runtime_run --entrypoint python "$candidate_id" -c \
    'import importlib.metadata as m; assert all((d.metadata.get("Name") or "").lower() != "mcp" for d in m.distributions())'
  runtime_run --entrypoint pip "$candidate_id" check
  runtime_run --entrypoint sh "$candidate_id" -c \
    'export LC_ALL=C; cd /app; test -f alembic.ini && test -f pyproject.toml && test -d app && test -d alembic; { printf "%s\0" alembic.ini pyproject.toml; find app alembic -type f \( -name "*.py" -o -name "*.html" \) -print0; } | sort -z | xargs -0 -r sha256sum' \
    >"$observed"
  python3 "$validator" image-source --observed "$observed" \
    --expected "${artifact_stage}/image-source-files.sha256" \
    --expected-count "$EXPECTED_IMAGE_SOURCE_FILE_COUNT"
  alembic_heads=$(runtime_run --entrypoint alembic "$candidate_id" -c alembic.ini heads)
  [[ "$alembic_heads" == "${EXPECTED_ALEMBIC_HEAD} (head)" ]] \
    || { die "candidate Alembic head mismatch"; return 1; }
  runtime_run --entrypoint python "$candidate_id" -c \
    'import json; from app.api_main import app; schema=app.openapi(); assert all("agent-workbench" not in path and "agent_workbench" not in path for path in schema.get("paths", {})); print(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True))' \
    >"$rendered_openapi"
  cmp -- "$rendered_openapi" "${release_worktree}/backend/openapi.json" \
    || { die "candidate production OpenAPI differs from the committed contract"; return 1; }
  ! grep -Eiq 'agent[-_]workbench' "${release_worktree}/compose.yaml" \
    || { die "Workbench entered production Compose"; return 1; }
  runtime_run \
    --env 'CONTENT_SCORING_VERSION=scoring-v1-preview.7-delivered-repeat-history' \
    --env 'IMAGE_ENABLED=true' \
    --env 'IMAGE_PROVIDER_MODE=fake' \
    --env 'IMAGE_OCR_ENABLED=true' \
    --env 'IMAGE_DIVERSITY_ENABLED=true' \
    --entrypoint python "$candidate_id" -c \
    'from app.core.config import Settings; from app.application.services.topic_selection import build_topic_scoring_config; s=Settings(); c=build_topic_scoring_config(s); assert c.version=="scoring-v1-preview.7-delivered-repeat-history" and c.effective_veto_rule_version=="topic-veto-v4-delivered-content" and s.image_enabled is True and s.image_provider_mode=="fake" and s.image_ocr_enabled is True and s.image_diversity_enabled is True'
}

write_image_validation() {
  local output=$1
  printf '%s\n' \
    "release_sha=${release_sha}" \
    "candidate_tag=${candidate_tag}" \
    "candidate_id=${candidate_id}" \
    "dependency_base_id=${DEPENDENCY_BASE_ID}" \
    "runtime_lock_sha256=${EXPECTED_RUNTIME_LOCK_SHA256}" \
    "dockerfile_sha256=${EXPECTED_DOCKERFILE_SHA256}" \
    "base_pyproject_sha256=${EXPECTED_BASE_PYPROJECT_SHA256}" \
    "final_pyproject_sha256=${EXPECTED_FINAL_PYPROJECT_SHA256}" \
    'production_dependency_delta=none' \
    'pyproject_delta=none' \
    'compose_openapi_alembic_delta=none' \
    'supported_mcp_imports=0' \
    'candidate_mcp_distribution=absent' \
    "source_file_count=${EXPECTED_SOURCE_FILE_COUNT}" \
    "image_source_file_count=${EXPECTED_IMAGE_SOURCE_FILE_COUNT}" \
    "alembic_head=${EXPECTED_ALEMBIC_HEAD}" \
    'runtime_probe=non-root,read-only,network-none,cap-drop-all,no-new-privileges' \
    'runtime_config=.7/v4,ocr=true,diversity=true' \
    'runtime_diff=3-reviewed-blobs' \
    'production_workbench=absent' \
    'rootfs_dependency_base_prefix=exact' \
    >"$output"
  chmod 0600 "$output"
}

assert_stage_shape() {
  local stage=$1 actual expected member targets expected_targets current_uid current_gid
  current_uid=$(id -u)
  current_gid=$(id -g)
  [[ -d "$stage" && ! -L "$stage" && "$(realpath -e -- "$stage")" == "$stage" \
      && "$(stat -c '%a:%u:%g' "$stage")" == "700:${current_uid}:${current_gid}" ]] \
    || { die "artifact directory is not protected"; return 1; }
  actual=$(find "$stage" -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort)
  expected=$(printf '%s\n' "${STAGE_MEMBERS[@]}" | LC_ALL=C sort)
  [[ "$actual" == "$expected" ]] || { die "artifact directory membership is not exact"; return 1; }
  for member in "${STAGE_MEMBERS[@]}"; do
    [[ -f "${stage}/${member}" && ! -L "${stage}/${member}" \
        && "$(realpath -e -- "${stage}/${member}")" == "${stage}/${member}" \
        && "$(stat -c '%a:%u:%g' "${stage}/${member}")" == "600:${current_uid}:${current_gid}" ]] \
      || { die "artifact member is not a mode-0600 regular file"; return 1; }
  done
  [[ "$(wc -l <"${stage}/artifacts.sha256" | tr -d '[:space:]')" == 9 ]] \
    || { die "artifact manifest is not exactly nine lines"; return 1; }
  targets=$(awk '/^[0-9a-f]{64}  [A-Za-z0-9._-]+$/ {print $2; next} {exit 1}' "${stage}/artifacts.sha256" | LC_ALL=C sort) \
    || { die "artifact manifest syntax is unsafe"; return 1; }
  expected_targets=$(printf '%s\n' "${ARTIFACT_TARGETS[@]}" | LC_ALL=C sort)
  [[ "$targets" == "$expected_targets" ]] || { die "artifact manifest target set mismatch"; return 1; }
  (cd "$stage" && sha256sum --strict -c artifacts.sha256 source.tar.gz.sha256 backend-image.tar.gz.sha256) >/dev/null
}

assemble_artifact_stage() {
  local generated=$1 output=$2 precreated=${3:-0} expected_parent_identity=${4:-}
  local member output_parent observed_parent_identity output_metadata
  output_parent=$(dirname -- "$output")
  if [[ "$precreated" == 1 ]]; then
    [[ -d "$output" && ! -L "$output" ]] \
      || { die "precreated artifact directory is absent or unsafe"; return 1; }
  else
    [[ ! -e "$output" && ! -L "$output" ]] \
      || { die "artifact output path appeared before creation"; return 1; }
    if [[ -n "$expected_parent_identity" ]]; then
      observed_parent_identity=$(stat -c '%d:%i:%a:%u:%g' "$output_parent") || return 1
      [[ "$observed_parent_identity" == "$expected_parent_identity" ]] \
        || { die "artifact output parent changed before creation"; return 1; }
    fi
    mkdir -m 0700 -- "$output" || { die "artifact output directory creation failed"; return 1; }
  fi
  if [[ "$output" == "$final_output_dir" ]]; then
    final_output_identity=$(stat -c '%d:%i' "$output") || return 1
    final_output_incomplete=1
  fi
  if [[ -n "$expected_parent_identity" ]]; then
    observed_parent_identity=$(stat -c '%d:%i:%a:%u:%g' "$output_parent") || return 1
    [[ "$observed_parent_identity" == "$expected_parent_identity" ]] \
      || { die "artifact output parent changed during creation"; return 1; }
  fi
  [[ -z "$(find "$output" -mindepth 1 -maxdepth 1 -print -quit)" ]] \
    || { die "artifact output directory is not empty"; return 1; }
  output_metadata=$(stat -c '%a:%u:%g' "$output")
  [[ "$output_metadata" == "700:$(id -u):$(id -g)" \
      && ! -L "$output" && "$(realpath -e -- "$output")" == "$output" ]] \
    || { die "artifact output directory metadata is unsafe"; return 1; }
  for member in "${ARTIFACT_TARGETS[@]}"; do
    install -m 0600 -- "${generated}/${member}" "${output}/${member}"
  done
  (
    cd "$output"
    sha256sum "${ARTIFACT_TARGETS[@]}" >artifacts.sha256
  )
  chmod 0600 "${output}/artifacts.sha256"
  assert_stage_shape "$output"
}

validate_completed_artifacts() {
  local stage=$1 validator observed_image_source
  validator="${stage}/validate-image-fallback-offline-artifacts.py"
  observed_image_source="${scratch_root}/image-source-observed.sha256"
  [[ -f "$observed_image_source" && ! -L "$observed_image_source" ]] \
    || { die "independent candidate image-source observation is absent"; return 1; }
  python3 "$validator" source --archive "${stage}/source.tar.gz" \
    --manifest "${stage}/source-files.sha256" \
    --expected-count "$EXPECTED_SOURCE_FILE_COUNT" \
    --paths-output "${scratch_root}/final-source-paths" \
    --modes-output "${scratch_root}/final-source-modes"
  python3 "$validator" image-source --observed "$observed_image_source" \
    --expected "${stage}/image-source-files.sha256" \
    --expected-count "$EXPECTED_IMAGE_SOURCE_FILE_COUNT"
  python3 "$validator" image --bundle "${stage}/backend-image.tar.gz" \
    --expected-tag "$candidate_tag" --expected-image-id "$candidate_id"
  assert_stage_shape "$stage"
}

cleanup() {
  local rc=$?
  trap - EXIT HUP INT TERM
  if ((final_output_incomplete == 1)) && [[ -n "${final_output_dir:-}" \
      && -n "${final_output_identity:-}" && -d "$final_output_dir" \
      && ! -L "$final_output_dir" \
      && "$(realpath -e -- "$final_output_dir")" == "$final_output_dir" \
      && "$(stat -c '%d:%i' "$final_output_dir")" == "$final_output_identity" ]]; then
    find "$final_output_dir" -xdev -depth -delete || true
  fi
  if [[ -n "${release_worktree:-}" && -d "$release_worktree" && -n "${repo_root:-}" ]]; then
    git_call -C "$repo_root" worktree remove --force "$release_worktree" >/dev/null 2>&1 || true
  fi
  if ((cleanup_armed)) && [[ -n "${scratch_root:-}" && "$scratch_root" == /tmp/edu-ai-image-fallback-builder.* && -d "$scratch_root" && ! -L "$scratch_root" ]]; then
    find "$scratch_root" -depth -delete
  fi
  exit "$rc"
}

build_artifacts() {
  local pathset_base_paths previous_paths candidate_paths changed_paths
  local previous_image_paths candidate_image_paths image_changed_paths
  local source_tree image_context source_paths_output source_modes_output
  local base_tree_index release_tree_index path relative git_mode
  local source_archive dockerfile top_level_file commit_epoch member
  local -a top_levels=()

  script_path=$(realpath -e -- "${BASH_SOURCE[0]}")
  repo_root=$(git -C "$(dirname -- "$script_path")" rev-parse --show-toplevel)
  repo_root=$(realpath -e -- "$repo_root")
  scratch_root=$(mktemp -d /tmp/edu-ai-image-fallback-builder.XXXXXX)
  chmod 0700 "$scratch_root"
  trap cleanup EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  release_worktree="${scratch_root}/release-worktree"
  artifact_stage="${scratch_root}/artifacts"
  source_tree="${scratch_root}/source-tree"
  image_context="${scratch_root}/image-context"
  install -d -m 0700 "$source_tree" "$image_context" "$artifact_stage" "${scratch_root}/docker-home"

  assert_release_authority "$repo_root" "$authority_sha" "$release_sha"
  assert_builder_authority "$repo_root" "$authority_sha"
  create_clean_detached_worktree "$repo_root" "$release_sha" "$release_worktree"
  assert_dependency_compatibility "$release_worktree"

  base_tree_index="${scratch_root}/base-tree.index"
  release_tree_index="${scratch_root}/release-tree.index"
  load_tree_map "$repo_root" "$PREVIOUS_COMMIT" BASE "$base_tree_index"
  load_tree_map "$repo_root" "$release_sha" RELEASE "$release_tree_index"

  pathset_base_paths="${scratch_root}/pathset-base-source-paths"
  previous_paths="${scratch_root}/previous-source-paths"
  candidate_paths="${scratch_root}/candidate-source-paths"
  changed_paths="${scratch_root}/changed-runtime-paths"
  write_base_source_paths "$repo_root" "$pathset_base_paths"
  { cat "$pathset_base_paths"; printf '%s\n' "${RUNTIME_PATHSET_ADDITIONS[@]}"; } \
    | LC_ALL=C sort -u >"$previous_paths"
  install -m 0600 "$previous_paths" "$candidate_paths"
  validate_equal_path_sets "$previous_paths" "$candidate_paths" "$EXPECTED_SOURCE_FILE_COUNT"
  assert_exact_runtime_diff "$candidate_paths" "$changed_paths"

  while IFS= read -r path; do
    assert_safe_source_path "$path"
  done <"$candidate_paths"

  previous_image_paths="${scratch_root}/previous-image-paths"
  candidate_image_paths="${scratch_root}/candidate-image-paths"
  image_changed_paths="${scratch_root}/changed-image-paths"
  write_image_scope_paths "$repo_root" "$PREVIOUS_COMMIT" "$previous_image_paths"
  write_image_scope_paths "$repo_root" "$release_sha" "$candidate_image_paths"
  validate_equal_path_sets "$previous_image_paths" "$candidate_image_paths" \
    "$EXPECTED_IMAGE_SOURCE_FILE_COUNT"
  assert_exact_image_diff "$candidate_image_paths" "$image_changed_paths"

  while IFS= read -r path; do
    git_mode=${RELEASE_MODE[$path]-}
    [[ -n "$git_mode" ]] || { die "release source path is not a tracked blob"; return 1; }
    copy_committed_file "$release_worktree" "$source_tree" "$path" "$git_mode" "${RELEASE_BLOB[$path]}"
  done <"$candidate_paths"
  find "$source_tree" -type d -exec chmod 0755 {} +
  write_checksum_manifest "$source_tree" "$candidate_paths" "${artifact_stage}/source-files.sha256"
  chmod 0600 "${artifact_stage}/source-files.sha256"
  source_manifest_sha256=$(sha256sum "${artifact_stage}/source-files.sha256" | awk '{print $1}')

  top_level_file="${scratch_root}/source-top-levels"
  awk -F/ '{print $1}' "$candidate_paths" | LC_ALL=C sort -u >"$top_level_file"
  mapfile -t top_levels <"$top_level_file"
  commit_epoch=$(git_call -C "$repo_root" show -s --format=%ct "$release_sha")
  [[ "$commit_epoch" =~ ^[0-9]{10}$ ]] || { die "release commit timestamp is invalid"; return 1; }
  build_created=$(date -u -d "@${commit_epoch}" '+%Y-%m-%dT%H:%M:%SZ')
  source_archive="${artifact_stage}/source.tar.gz"
  tar -C "$source_tree" --sort=name --format=gnu --mtime="@${commit_epoch}" \
    --owner=0 --group=0 --numeric-owner -cf - "${top_levels[@]}" | gzip -n -c >"$source_archive"
  chmod 0600 "$source_archive"
  source_sha256=$(sha256sum "$source_archive" | awk '{print $1}')
  (cd "$artifact_stage" && sha256sum source.tar.gz >source.tar.gz.sha256)
  chmod 0600 "${artifact_stage}/source.tar.gz.sha256"

  source_paths_output="${scratch_root}/validated-source-paths"
  source_modes_output="${scratch_root}/validated-source-modes"
  python3 "${repo_root}/${VALIDATOR_REPO_PATH}" source \
    --archive "$source_archive" --manifest "${artifact_stage}/source-files.sha256" \
    --expected-count "$EXPECTED_SOURCE_FILE_COUNT" \
    --paths-output "$source_paths_output" --modes-output "$source_modes_output"
  cmp -- "$source_paths_output" "$candidate_paths" \
    || { die "validated source paths differ from the reviewed allowlist"; return 1; }

  while IFS= read -r relative; do
    path="backend/${relative}"
    git_mode=${RELEASE_MODE[$path]-}
    [[ -n "$git_mode" ]] || { die "image source path is not a tracked blob"; return 1; }
    copy_committed_file "$release_worktree" "${scratch_root}/image-prefixed" "$path" "$git_mode" "${RELEASE_BLOB[$path]}"
    install -D -m "$( [[ "$git_mode" == 100755 ]] && printf 0755 || printf 0644 )" \
      "${scratch_root}/image-prefixed/${path}" "${image_context}/${relative}"
  done <"$candidate_image_paths"
  find "$image_context" -type d -exec chmod 0755 {} +
  write_checksum_manifest "$image_context" "$candidate_image_paths" "${artifact_stage}/image-source-files.sha256"
  chmod 0600 "${artifact_stage}/image-source-files.sha256"
  image_source_manifest_sha256=$(sha256sum "${artifact_stage}/image-source-files.sha256" | awk '{print $1}')
  write_release_source_sidecar "${image_context}/.release-source.sha256" "$source_sha256"
  dockerfile="${image_context}/Dockerfile.image-fallback-offline"
  write_overlay_dockerfile "$dockerfile"

  candidate_tag="edu-ai-lead-agent-backend:image-fallback-${release_sha:0:12}"
  build_candidate_image "$image_context" "$dockerfile"
  assert_candidate_runtime "$image_context" "${repo_root}/${VALIDATOR_REPO_PATH}"

  docker_call image save "$candidate_tag" | gzip -n -c >"${artifact_stage}/backend-image.tar.gz"
  chmod 0600 "${artifact_stage}/backend-image.tar.gz"
  image_bundle_sha256=$(sha256sum "${artifact_stage}/backend-image.tar.gz" | awk '{print $1}')
  (cd "$artifact_stage" && sha256sum backend-image.tar.gz >backend-image.tar.gz.sha256)
  chmod 0600 "${artifact_stage}/backend-image.tar.gz.sha256"
  python3 "${repo_root}/${VALIDATOR_REPO_PATH}" image \
    --bundle "${artifact_stage}/backend-image.tar.gz" \
    --expected-tag "$candidate_tag" --expected-image-id "$candidate_id"

  install -m 0600 "${repo_root}/${OPERATOR_REPO_PATH}" "${artifact_stage}/baseline-7ba-offline-release-operator.sh"
  install -m 0600 "${repo_root}/${VALIDATOR_REPO_PATH}" "${artifact_stage}/validate-image-fallback-offline-artifacts.py"
  write_image_validation "${artifact_stage}/image-validation.txt"
  for member in "${ARTIFACT_TARGETS[@]}"; do
    [[ -f "${artifact_stage}/${member}" ]] || { die "generated artifact is absent"; return 1; }
    chmod 0600 "${artifact_stage}/${member}"
  done

  assert_clean_detached_worktree "$release_worktree" "$release_sha"
  if [[ -n "$requested_output_dir" ]]; then
    final_output_dir=$requested_output_dir
    assemble_artifact_stage "$artifact_stage" "$final_output_dir" 0 \
      "$requested_output_parent_identity"
  else
    final_output_dir=$(mktemp -d "/tmp/edu-ai-image-fallback-artifacts-${release_sha:0:12}.XXXXXX")
    chmod 0700 "$final_output_dir"
    assemble_artifact_stage "$artifact_stage" "$final_output_dir" 1
  fi
  validate_completed_artifacts "$final_output_dir"
  final_output_incomplete=0
  cleanup_armed=1

  printf '%s\n' \
    "artifact_dir=${final_output_dir}" \
    "release_sha=${release_sha}" \
    "candidate_tag=${candidate_tag}" \
    "candidate_id=${candidate_id}" \
    "source_sha256=${source_sha256}" \
    "source_manifest_sha256=${source_manifest_sha256}" \
    "image_source_manifest_sha256=${image_source_manifest_sha256}" \
    "image_bundle_sha256=${image_bundle_sha256}"
}

main() {
  local parse_rc=0
  parse_args "$@" || parse_rc=$?
  if ((parse_rc == 64)); then return 0; fi
  ((parse_rc == 0)) || return "$parse_rc"
  build_artifacts
}

if [[ "${IMAGE_FALLBACK_BUILDER_SOURCE_ONLY:-0}" != 1 ]]; then
  main "$@"
fi
