#!/usr/bin/env bash
# Offline/static tests for the broad artifact builder. No Docker build, image
# load/save, network command, remote transfer, or production action is run.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077
export LC_ALL=C

readonly HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly BUILDER="${HERE}/build-broad-offline-artifacts.sh"
readonly OPERATOR="${HERE}/broad-offline-release-operator.sh"
readonly PROJECT_ROOT=$(cd -- "${HERE}/../../../.." && pwd -P)
test_root=$(mktemp -d /tmp/edu-ai-broad-builder-test.XXXXXX)

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
require_text() { grep -Fq -- "$2" "$1" || fail "missing text '$2'"; }
reject_text() { ! grep -Fq -- "$2" "$1" || fail "unexpected text '$2'"; }
require_regex() { grep -Eq -- "$2" "$1" || fail "missing pattern '$2'"; }
reject_regex() { ! grep -Eq -- "$2" "$1" || fail "unexpected pattern '$2'"; }

cleanup_test() {
  if [[ -n "${test_root:-}" && "$test_root" == /tmp/edu-ai-broad-builder-test.* && -d "$test_root" && ! -L "$test_root" ]]; then
    find "$test_root" -depth -delete
  fi
}
trap cleanup_test EXIT

export BROAD_BUILDER_SOURCE_ONLY=1
# shellcheck source=build-broad-offline-artifacts.sh
source "$BUILDER"
readonly ORIGINAL_GIT_CALL=$(declare -f git_call)
readonly ORIGINAL_DOCKER_CALL=$(declare -f docker_call)
scratch_root=$test_root

assert_arguments() {
  local output="${test_root}/output"
  parse_args --release-sha 0123456789abcdef0123456789abcdef01234567 --output-dir "$output"
  [[ "$release_sha" == 0123456789abcdef0123456789abcdef01234567 && "$requested_output_dir" == "$output" ]] \
    || fail "valid arguments were not parsed"
  if parse_args --release-sha 0123456 >/dev/null 2>&1; then fail "short SHA was accepted"; fi
  if parse_args --release-sha 0123456789abcdef0123456789abcdef01234567 --unknown value >/dev/null 2>&1; then
    fail "unknown argument was accepted"
  fi
  if parse_args --release-sha 0123456789abcdef0123456789abcdef01234567 --output-dir relative >/dev/null 2>&1; then
    fail "relative output directory was accepted"
  fi
}

assert_fake_authority_and_clean_gate() {
  local expected=0123456789abcdef0123456789abcdef01234567
  fake_origin_sha=$expected
  fake_origin_url='git@codeup-edu-ai:601cdb1a841cc46b7c49b115/marketingUseOnly/edu-ai-lead-agent.git'
  fake_dirty=0
  fake_attached=0
  git_call() {
    local command=${3-}
    case "$command" in
      config) printf '%s\n' "$fake_origin_url" ;;
      rev-parse) printf '%s\n' "$fake_origin_sha" ;;
      cat-file) return 0 ;;
      symbolic-ref) ((fake_attached == 1)) ;;
      status) ((fake_dirty == 0)) || printf ' M backend/app/api_main.py\n' ;;
      *) fail "unexpected fake git command: $command" ;;
    esac
  }
  assert_release_authority /fixture "$expected"
  fake_origin_sha=89abcdef0123456789abcdef0123456789abcdef
  if assert_release_authority /fixture "$expected" >/dev/null 2>&1; then
    fail "origin/main SHA mismatch was accepted"
  fi
  fake_origin_sha=$expected
  fake_origin_url='git@github.com:EDLlyc/edu-ai-lead-agent.git'
  if assert_release_authority /fixture "$expected" >/dev/null 2>&1; then
    fail "non-Codeup origin was accepted"
  fi
  fake_origin_url='git@codeup-edu-ai:601cdb1a841cc46b7c49b115/marketingUseOnly/edu-ai-lead-agent.git'
  assert_clean_detached_worktree /fixture "$expected"
  fake_dirty=1
  if assert_clean_detached_worktree /fixture "$expected" >/dev/null 2>&1; then
    fail "dirty detached worktree was accepted"
  fi
  fake_dirty=0
  fake_attached=1
  if assert_clean_detached_worktree /fixture "$expected" >/dev/null 2>&1; then
    fail "attached release worktree was accepted"
  fi
  eval "$ORIGINAL_GIT_CALL"
}

assert_detached_bytes_only() {
  local repository="${test_root}/git-fixture" detached="${test_root}/git-detached"
  local destination="${test_root}/copied" commit blob
  mkdir -p "${repository}/backend/app"
  git -C "$repository" init -q
  git -C "$repository" config user.name fixture
  git -C "$repository" config user.email fixture@example.invalid
  printf 'committed-byte\n' >"${repository}/backend/app/payload.py"
  git -C "$repository" add backend/app/payload.py
  git -C "$repository" commit -q -m fixture
  commit=$(git -C "$repository" rev-parse HEAD)
  blob=$(git -C "$repository" rev-parse HEAD:backend/app/payload.py)
  create_clean_detached_worktree "$repository" "$commit" "$detached"
  printf 'dirty-caller-byte\n' >"${repository}/backend/app/payload.py"
  copy_committed_file "$detached" "$destination" backend/app/payload.py 100644 "$blob"
  [[ "$(<"${destination}/backend/app/payload.py")" == committed-byte ]] \
    || fail "dirty caller byte entered normalized source"
  assert_clean_detached_worktree "$detached" "$commit"
  printf 'dirty-detached-byte\n' >"${detached}/backend/app/payload.py"
  if assert_clean_detached_worktree "$detached" "$commit" >/dev/null 2>&1; then
    fail "dirty release bytes passed the final clean gate"
  fi
  git -C "$repository" worktree remove --force "$detached"
}

assert_exact_path_sets() {
  local base="${test_root}/base-paths" candidate="${test_root}/candidate-paths"
  local additions="${test_root}/additions" removed="${test_root}/removed"
  local base_image="${test_root}/base-image-paths" candidate_image="${test_root}/candidate-image-paths"
  local image_additions="${test_root}/image-additions" path

  load_tree_map "$PROJECT_ROOT" "$BASE_COMMIT" BASE "${test_root}/base-tree.index"
  [[ "${BASE_MODE[compose.yaml]-}" == 100644 && "${BASE_BLOB[compose.yaml]-}" =~ ^[0-9a-f]{40}$ ]] \
    || fail "NUL-delimited c66 tree metadata was not parsed"
  write_base_source_paths "$PROJECT_ROOT" "$base"
  [[ "$(wc -l <"$base" | tr -d '[:space:]')" == 307 ]] || fail "c66 base is not exact 307"
  [[ "${#EXPECTED_SOURCE_ADDITIONS[@]}" == 14 ]] || fail "reviewed addition list is not exact 14"
  { cat "$base"; printf '%s\n' "${EXPECTED_SOURCE_ADDITIONS[@]}"; } | LC_ALL=C sort -u >"$candidate"
  validate_reviewed_path_sets "$base" "$candidate" "$additions" 307 321
  [[ "$(wc -l <"$candidate" | tr -d '[:space:]')" == 321 ]] || fail "source allowlist is not exact 321"
  [[ "$(wc -l <"$additions" | tr -d '[:space:]')" == 14 ]] || fail "source additions are not exact 14"
  while IFS= read -r path; do assert_safe_addition_path "$path"; done <"$additions"
  if assert_safe_addition_path backend/tests/test_agent_workbench.py >/dev/null 2>&1; then
    fail "test-only source addition was accepted"
  fi
  if assert_safe_addition_path backend/app/escape.txt >/dev/null 2>&1; then
    fail "non-Python/HTML source addition was accepted"
  fi
  if assert_safe_source_path ../backend/app/escape.py >/dev/null 2>&1; then
    fail "traversal source path was accepted"
  fi
  if assert_safe_source_path frontend/src/app/App.tsx >/dev/null 2>&1; then
    fail "frontend source entered the runtime allowlist"
  fi
  tail -n +2 "$candidate" >"$removed"
  if validate_reviewed_path_sets "$base" "$removed" "${removed}.additions" 307 320 >/dev/null 2>&1; then
    fail "c66 source removal was accepted"
  fi

  write_image_scope_paths "$PROJECT_ROOT" "$BASE_COMMIT" "$base_image"
  [[ "$(wc -l <"$base_image" | tr -d '[:space:]')" == 165 ]] || fail "c66 image scope is not exact 165"
  {
    cat "$base_image"
    printf '%s\n' "${EXPECTED_SOURCE_ADDITIONS[@]}" | sed 's#^backend/##'
  } | LC_ALL=C sort -u >"$candidate_image"
  validate_reviewed_path_sets "$base_image" "$candidate_image" "$image_additions" 165 179
  [[ "$(wc -l <"$candidate_image" | tr -d '[:space:]')" == 179 ]] || fail "image source scope is not exact 179"
  [[ "$(wc -l <"$image_additions" | tr -d '[:space:]')" == 14 ]] || fail "image source additions are not exact 14"
}

assert_sidecar_and_dockerfile() {
  local digest=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  local sidecar="${test_root}/.release-source.sha256" dockerfile="${test_root}/Dockerfile.generated"
  local builder_labels="${test_root}/builder-labels" operator_labels="${test_root}/operator-labels"
  local expected_labels="${test_root}/expected-labels"
  write_release_source_sidecar "$sidecar" "$digest"
  [[ "$(wc -l <"$sidecar" | tr -d '[:space:]')" == 1 ]] || fail "release source sidecar is not one line"
  [[ "$(wc -c <"$sidecar" | tr -d '[:space:]')" == 65 ]] || fail "release source sidecar is not 65 bytes"
  [[ "$(<"$sidecar")" == "$digest" ]] || fail "release source sidecar contains the wrong digest"

  write_overlay_dockerfile "$dockerfile"
  require_text "$dockerfile" 'COPY --chown=app:app .release-source.sha256 ./.release-source.sha256'
  reject_text "$dockerfile" 'COPY --chown=app:app source-files.sha256'
  require_text "$dockerfile" 'ARG DEPENDENCY_BASE_DIGEST'
  require_text "$dockerfile" 'FROM ${DEPENDENCY_BASE_DIGEST}'
  require_text "$dockerfile" '"${site_packages}/app"'
  printf '%s\n' "${BROAD_LABEL_KEYS[@]}" | LC_ALL=C sort >"$expected_labels"
  grep -oE '(org\.opencontainers\.image\.revision|io\.trellis\.[A-Za-z0-9._-]+)=' "$dockerfile" \
    | sed 's/=$//' | LC_ALL=C sort -u >"$builder_labels"
  awk '/^assert_candidate_image\(\)/,/^}/' "$OPERATOR" \
    | grep -oE 'index \.Config\.Labels "[^"]+"' \
    | sed -E 's/^index \.Config\.Labels "([^"]+)"$/\1/' \
    | LC_ALL=C sort -u >"$operator_labels"
  cmp -- "$expected_labels" "$builder_labels" || fail "generated Dockerfile broad label names drifted"
  cmp -- "$expected_labels" "$operator_labels" || fail "builder label names differ from the broad operator"
}

assert_fake_docker_security_seam() {
  local calls="${test_root}/docker-calls"
  : >"$calls"
  docker_call() { printf '%s\n' "$*" >>"$calls"; }
  runtime_run --entrypoint true sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  require_text "$calls" 'run'
  require_text "$calls" '--network'
  require_text "$calls" 'none'
  require_text "$calls" '--read-only'
  require_text "$calls" '--cap-drop'
  require_text "$calls" 'ALL'
  require_text "$calls" 'no-new-privileges:true'
  eval "$ORIGINAL_DOCKER_CALL"
}

assert_stage_contract() {
  local generated="${test_root}/generated" stage="${test_root}/stage" member
  mkdir -m 700 "$generated"
  for member in "${ARTIFACT_TARGETS[@]}"; do printf 'fixture:%s\n' "$member" >"${generated}/${member}"; done
  (
    cd "$generated"
    sha256sum source.tar.gz >source.tar.gz.sha256
    sha256sum backend-image.tar.gz >backend-image.tar.gz.sha256
  )
  assemble_artifact_stage "$generated" "$stage"
  [[ "$(find "$stage" -mindepth 1 -maxdepth 1 -type f | wc -l | tr -d '[:space:]')" == 10 ]] \
    || fail "artifact directory is not exact 10 members"
  [[ "$(find "$stage" -mindepth 1 -maxdepth 1 -type f ! -perm 0600 | wc -l | tr -d '[:space:]')" == 0 ]] \
    || fail "artifact member mode is not exact 0600"
  [[ "$(wc -l <"${stage}/artifacts.sha256" | tr -d '[:space:]')" == 9 ]] \
    || fail "artifact checksum manifest is not exact 9 lines"
  printf 'extra\n' >"${stage}/unexpected"
  chmod 0600 "${stage}/unexpected"
  if assert_stage_shape "$stage" >/dev/null 2>&1; then fail "extra stage member was accepted"; fi
}

assert_offline_static_contract() {
  require_text "$BUILDER" 'readonly TARGET_PLATFORM="linux/amd64"'
  require_text "$BUILDER" 'docker_call build --platform "$TARGET_PLATFORM" --network none --pull=false --no-cache'
  require_text "$BUILDER" "--format '{{.Os}}/{{.Architecture}}'"
  require_text "$BUILDER" 'docker_call image save "$candidate_tag" | gzip -n -c'
  require_text "$BUILDER" 'create_clean_detached_worktree "$repo_root" "$release_sha"'
  require_text "$BUILDER" 'assert_builder_authority "$repo_root" "$release_sha"'
  require_text "$BUILDER" 'assert_clean_detached_worktree "$release_worktree" "$release_sha"'
  require_text "$BUILDER" 'candidate_mcp_distribution=absent'
  require_text "$BUILDER" 'production_workbench=absent'
  reject_regex "$BUILDER" '(^|[;&|][[:space:]]*)(git|git_call)([[:space:]]+-[^[:space:]]+)*[[:space:]]+(fetch|pull|push)'
  reject_regex "$BUILDER" '(^|[;&|][[:space:]]*)(docker|docker_call)[[:space:]]+(pull|push|login|load)'
  reject_regex "$BUILDER" '(^|[;&|][[:space:]])(ssh|scp|sftp|rsync|curl|wget|nc)[[:space:]]'
  reject_text "$BUILDER" 'make release-prod'
  reject_text "$BUILDER" 'docker image load'
  reject_text "$BUILDER" 'source-files.sha256 ./.release-source.sha256'
}

bash -n "$BUILDER" "$0"
assert_arguments
assert_fake_authority_and_clean_gate
assert_detached_bytes_only
assert_exact_path_sets
assert_sidecar_and_dockerfile
assert_fake_docker_security_seam
assert_stage_contract
assert_offline_static_contract
printf 'PASS: broad artifact builder authority, clean-source, 307+14/179 scope, sidecar, labels, offline runtime, and 10-member stage checks\n'
