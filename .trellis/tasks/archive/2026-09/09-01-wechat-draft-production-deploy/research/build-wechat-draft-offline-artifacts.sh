#!/usr/bin/env bash
# Build a checksum-bound linux/amd64 source/image stage from an already-fetched Codeup commit.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077
export LC_ALL=C

readonly SAFE_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
readonly SOURCE_URL="https://codeup.aliyun.com/601cdb1a841cc46b7c49b115/marketingUseOnly/edu-ai-lead-agent.git"
readonly TASK_PATH=".trellis/tasks/09-01-wechat-draft-production-deploy/research"
readonly BUILDER_PATH="${TASK_PATH}/build-wechat-draft-offline-artifacts.sh"
readonly OPERATOR_PATH="${TASK_PATH}/wechat-draft-offline-release-operator.sh"
readonly VALIDATOR_PATH="${TASK_PATH}/validate-wechat-draft-offline-artifacts.py"
readonly ALEMBIC_HEAD="20260901_0042"
readonly -a SOURCE_PATHS=(
  backend deploy infra scripts compose.yaml .env.example .gitattributes .gitignore
  AGENTS.md Makefile README.md environment.yml
)
readonly -a RUNTIME_MODULES=(
  app.api_main app.scheduler_main app.worker_main
  app.governance_scheduler_main app.governance_worker_main
  app.content_scheduler_main app.content_worker_main app.wecom_dispatcher_main
  app.wechat_official_account_draft_main
)
readonly -a FINAL_MEMBERS=(
  backend-image.tar.gz backend-image.tar.gz.sha256 production-baseline.json release-metadata.json
  source-files.sha256 source.tar.gz source.tar.gz.sha256
  validate-wechat-draft-offline-artifacts.py wechat-draft-offline-release-operator.sh
)

release_sha=""
release_ref="refs/remotes/origin/main"
output_dir=""
production_baseline=""
repo_root=""
scratch=""
worktree=""
stage=""
built_candidate_id=""

log() { printf '[wechat-draft-builder] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; return 1; }

cleanup() {
  local rc=$?
  if [[ -n "${worktree:-}" && -d "$worktree" && -n "${repo_root:-}" ]]; then
    git -C "$repo_root" worktree remove --force "$worktree" >/dev/null 2>&1 || true
  fi
  if [[ -n "${scratch:-}" && "$scratch" == /tmp/edu-ai-wechat-draft-build.* ]]; then
    find "$scratch" -depth -delete >/dev/null 2>&1 || true
  fi
  exit "$rc"
}
trap cleanup EXIT

usage() {
  printf '%s\n' \
    'Usage: build-wechat-draft-offline-artifacts.sh --release-sha HEX40 [--release-ref refs/remotes/origin/main|refs/remotes/origin/release/NAME] --production-baseline ABSOLUTE_MODE_0600_JSON --output-dir ABSENT_ABSOLUTE_DIR' >&2
}

parse_args() {
  while (($#)); do
    case "$1" in
      --release-sha) (($# >= 2)) || die "missing release SHA"; release_sha=$2; shift 2 ;;
      --release-ref) (($# >= 2)) || die "missing release ref"; release_ref=$2; shift 2 ;;
      --output-dir) (($# >= 2)) || die "missing output directory"; output_dir=$2; shift 2 ;;
      --production-baseline) (($# >= 2)) || die "missing production baseline"; production_baseline=$2; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown argument" ;;
    esac
  done
  [[ "$release_sha" =~ ^[0-9a-f]{40}$ ]] || die "release SHA must be lowercase HEX40"
  [[ "$release_ref" == refs/remotes/origin/main \
      || "$release_ref" =~ ^refs/remotes/origin/release/[a-z0-9][a-z0-9-]{0,63}$ ]] \
    || die "release ref is outside the reviewed Codeup namespace"
  [[ "$output_dir" == /* && "$output_dir" != */ && ! -e "$output_dir" && ! -L "$output_dir" ]] \
    || die "output directory must be an absent absolute path"
  [[ "$(basename -- "$output_dir")" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
    || die "output directory name is unsafe"
  local parent
  parent=$(dirname -- "$output_dir")
  [[ -d "$parent" && ! -L "$parent" && "$(realpath -e -- "$parent")" == "$parent" ]] \
    || die "output parent must be a physical directory"
  [[ "$production_baseline" == /* && -f "$production_baseline" && ! -L "$production_baseline" ]] \
    || die "production baseline must be a physical absolute file"
  [[ "$(stat -c '%a' "$production_baseline")" == 600 ]] \
    || die "production baseline must be mode 0600"
}

git_clean() {
  env -i PATH="$SAFE_PATH" HOME="$scratch" LC_ALL=C GIT_CONFIG_NOSYSTEM=1 \
    GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false git "$@"
}

assert_authority() {
  local origin origin_sha committed running
  origin=$(git_clean -C "$repo_root" config --get remote.origin.url)
  case "$origin" in
    git@codeup-edu-ai:601cdb1a841cc46b7c49b115/marketingUseOnly/edu-ai-lead-agent.git|\
    git@codeup.aliyun.com:601cdb1a841cc46b7c49b115/marketingUseOnly/edu-ai-lead-agent.git|\
    "$SOURCE_URL") ;;
    *) die "origin is not the reviewed Codeup repository" ;;
  esac
  origin_sha=$(git_clean -C "$repo_root" rev-parse --verify "${release_ref}^{commit}")
  [[ "$origin_sha" == "$release_sha" ]] || die "release SHA is not the fetched reviewed ref"
  committed=$(git_clean -C "$repo_root" show "${release_sha}:${BUILDER_PATH}" | sha256sum | awk '{print $1}')
  running=$(sha256sum "${repo_root}/${BUILDER_PATH}" | awk '{print $1}')
  [[ "$committed" == "$running" ]] || die "builder differs from the release commit"
}

create_worktree() {
  git_clean -C "$repo_root" worktree add --detach "$worktree" "$release_sha" >/dev/null
  [[ "$(git_clean -C "$worktree" rev-parse HEAD)" == "$release_sha" ]] \
    || die "detached worktree SHA mismatch"
  [[ -z "$(git_clean -C "$worktree" status --porcelain=v1 --untracked-files=all)" ]] \
    || die "detached worktree is dirty"
}

build_source() {
  local extract="$scratch/source-extract" path
  mkdir -m 700 "$extract"
  git_clean -C "$worktree" archive --format=tar "$release_sha" -- "${SOURCE_PATHS[@]}" \
    | gzip -n -c >"$stage/source.tar.gz"
  tar -xzf "$stage/source.tar.gz" -C "$extract" --no-same-owner --no-same-permissions
  (
    cd "$extract"
    find . -type f -print0 | sort -z | while IFS= read -r -d '' path; do
      sha256sum "${path#./}"
    done
  ) >"$stage/source-files.sha256"
  [[ -s "$stage/source-files.sha256" ]] || die "source manifest is empty"
  (
    cd "$stage"
    sha256sum source.tar.gz >source.tar.gz.sha256
  )
}

build_image() {
  local tag=$1 created candidate_id module
  created=$(git_clean -C "$repo_root" show -s --format=%cI "$release_sha")
  env -i PATH="$SAFE_PATH" HOME="$scratch" LC_ALL=C DOCKER_BUILDKIT=0 \
    docker build --pull --platform linux/amd64 \
      --build-arg "CODEUP_COMMIT=${release_sha}" \
      --build-arg "SOURCE_URL=${SOURCE_URL}" \
      --build-arg "BUILD_CREATED=${created}" \
      --tag "$tag" "$worktree/backend" >&2 \
    || die "candidate image build failed"
  candidate_id=$(docker image inspect --format '{{.Id}}' "$tag")
  [[ "$candidate_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "candidate image ID is invalid"
  [[ "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$tag")" == "$release_sha" ]] \
    || die "candidate revision label changed"
  for module in "${RUNTIME_MODULES[@]}"; do
    docker run --rm --network none --read-only --cap-drop ALL \
      --security-opt no-new-privileges:true --entrypoint python "$tag" \
      -c "import ${module}" </dev/null >/dev/null
  done
  docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint python "$tag" -c \
    'from app.core.config import Settings; s=Settings(_env_file=None); assert not s.wechat_mp_draft_worker_enabled and not s.wechat_mp_draft_production_enabled' \
    </dev/null >/dev/null
  docker image save "$tag" | gzip -n -c >"$stage/backend-image.tar.gz"
  (
    cd "$stage"
    sha256sum backend-image.tar.gz >backend-image.tar.gz.sha256
  )
  built_candidate_id=$candidate_id
}

write_metadata() {
  local tag=$1 candidate_id=$2 source_sha source_manifest_sha image_sha operator_sha validator_sha baseline_sha
  source_sha=$(sha256sum "$stage/source.tar.gz" | awk '{print $1}')
  source_manifest_sha=$(sha256sum "$stage/source-files.sha256" | awk '{print $1}')
  image_sha=$(sha256sum "$stage/backend-image.tar.gz" | awk '{print $1}')
  operator_sha=$(sha256sum "$stage/wechat-draft-offline-release-operator.sh" | awk '{print $1}')
  validator_sha=$(sha256sum "$stage/validate-wechat-draft-offline-artifacts.py" | awk '{print $1}')
  baseline_sha=$(sha256sum "$stage/production-baseline.json" | awk '{print $1}')
  python3 - "$stage/release-metadata.json" "$release_sha" "$tag" "$candidate_id" \
    "$source_sha" "$source_manifest_sha" "$image_sha" "$operator_sha" "$validator_sha" "$baseline_sha" <<'PY'
import json
import pathlib
import sys

path, commit, tag, image_id, source, source_manifest, image, operator, validator, baseline = sys.argv[1:]
payload = {
    "schema_version": 1,
    "release_commit": commit,
    "candidate_tag": tag,
    "candidate_id": image_id,
    "alembic_head": "20260901_0042",
    "source_sha256": source,
    "source_manifest_sha256": source_manifest,
    "image_archive_sha256": image,
    "operator_sha256": operator,
    "production_baseline_sha256": baseline,
    "validator_sha256": validator,
    "runtime_modules": [
        "app.api_main", "app.scheduler_main", "app.worker_main",
        "app.governance_scheduler_main", "app.governance_worker_main",
        "app.content_scheduler_main", "app.content_worker_main",
        "app.wecom_dispatcher_main", "app.wechat_official_account_draft_main",
    ],
}
pathlib.Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

main() {
  parse_args "$@"
  repo_root=$(git rev-parse --show-toplevel)
  repo_root=$(realpath -e -- "$repo_root")
  scratch=$(mktemp -d /tmp/edu-ai-wechat-draft-build.XXXXXX)
  worktree="$scratch/worktree"
  stage="$scratch/stage"
  mkdir -m 700 "$stage"
  assert_authority
  create_worktree
  env -i PATH="$SAFE_PATH" HOME="$scratch" LC_ALL=C \
    docker compose -f "$worktree/compose.yaml" \
      --profile wechat-official-account-draft config --quiet
  build_source
  git_clean -C "$repo_root" show "${release_sha}:${OPERATOR_PATH}" >"$stage/wechat-draft-offline-release-operator.sh"
  git_clean -C "$repo_root" show "${release_sha}:${VALIDATOR_PATH}" >"$stage/validate-wechat-draft-offline-artifacts.py"
  install -m 600 "$production_baseline" "$stage/production-baseline.json"
  local tag="edu-ai-lead-agent-backend:wechat-draft-${release_sha:0:12}" candidate_id member
  build_image "$tag"
  candidate_id=$built_candidate_id
  write_metadata "$tag" "$candidate_id"
  (
    cd "$stage"
    sha256sum "${FINAL_MEMBERS[@]}" | sort -k2 >artifacts.sha256
    chmod 600 artifacts.sha256 "${FINAL_MEMBERS[@]}"
  )
  python3 "$stage/validate-wechat-draft-offline-artifacts.py" "$stage"
  mkdir -m 700 "$output_dir"
  for member in artifacts.sha256 "${FINAL_MEMBERS[@]}"; do
    install -m 600 "$stage/$member" "$output_dir/$member"
  done
  python3 "$output_dir/validate-wechat-draft-offline-artifacts.py" "$output_dir"
  printf 'artifact_stage=%s\nrelease_ref=%s\nrelease_commit=%s\ncandidate_tag=%s\ncandidate_id=%s\n' \
    "$output_dir" "$release_ref" "$release_sha" "$tag" "$candidate_id"
}

if [[ "${WECHAT_DRAFT_BUILDER_SOURCE_ONLY:-0}" != 1 ]]; then
  main "$@"
fi
