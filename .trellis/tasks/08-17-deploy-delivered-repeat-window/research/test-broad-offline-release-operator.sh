#!/usr/bin/env bash
# Local-only fake/state-machine checks. No Docker, network, database, provider,
# production path, image load, enqueue, or delivery operation is performed.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

readonly HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly OPERATOR="${HERE}/broad-offline-release-operator.sh"
readonly VALIDATOR="${HERE}/validate-broad-offline-artifacts.py"
test_root=$(mktemp -d /tmp/edu-ai-broad-operator-test.XXXXXX)
chmod 700 "$test_root"
chown 0:0 "$test_root"
foreign_target=""

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
require_text() {
  if ! grep -Fq -- "$2" "$1"; then
    sed -n '1,160p' "$1" >&2
    fail "missing text '$2' in $1"
  fi
}
reject_text() { ! grep -Fq -- "$2" "$1" || fail "unexpected text '$2' in $1"; }

cleanup() {
  if [[ -n "${foreign_target:-}" && "$foreign_target" == /dev/shm/edu-ai-broad-target.* && -d "$foreign_target" && ! -L "$foreign_target" ]]; then
    find "$foreign_target" -xdev -depth -delete
  fi
  if [[ -n "${test_root:-}" && "$test_root" == /tmp/edu-ai-broad-operator-test.* ]]; then
    find "$test_root" -depth -delete
  fi
}
trap cleanup EXIT

run_fake_case() {
  local name=$1 fail_at=$2 seven_state=$3 expected_rc=$4
  local recovery_fail=${5:-none}
  local case_dir="${test_root}/${name}" rc
  mkdir -m 700 "$case_dir"
  set +e
  (
    set -Eeuo pipefail
    export BROAD_OFFLINE_SOURCE_ONLY=1
    # shellcheck source=broad-offline-release-operator.sh
    source "$OPERATOR"
    fake_seven_state=$seven_state
    fake_recovery_fail=$recovery_fail
    event_file="${case_dir}/events"
    : >"$event_file"
    fake_event() { printf '%s\n' "$1" >>"$event_file"; }
    fake_phase() {
      fake_event "phase:$1"
      if [[ "$fail_at" == "$1" ]]; then return 42; fi
    }
    phase_preflight_and_load() { fake_phase preflight; }
    claim_single_invocation() { fake_phase single-invocation; }
    acquire_release_lock() { fake_phase lock; }
    phase_quiesce() { writers_stopped=1; fake_phase quiesce; }
    phase_backup() { backup_ready=1; fake_phase backup; }
    phase_normalize_six() { env_normalized=1; fake_phase normalize-six; }
    phase_install_candidate() {
      tags_changed=1
      overlay_changed=1
      fake_phase install-candidate
      if [[ "$fail_at" == signal ]]; then
        kill -TERM "$BASHPID"
      fi
    }
    phase_migrate_and_probe() { fake_phase migrate-probe; }
    phase_activate_seven() { env_activated=1; fake_phase activate-seven; }
    phase_restore_candidate() { fake_phase restore-candidate; }
    phase_accept() { fake_phase accept; }
    candidate_seven_is_zero() { [[ "$fake_seven_state" == zero ]]; }
    restore_scoring_six() { fake_event recovery:score-six; [[ "$fake_recovery_fail" != env ]] || return 70; }
    restore_prior_payload() { ((backup_ready == 0)) || fake_event recovery:prior-payload; [[ "$fake_recovery_fail" != tag-source ]] || return 71; }
    restore_prior_services() { fake_event recovery:prior-services; [[ "$fake_recovery_fail" != start ]] || return 72; }
    stop_all_app_services() { fake_event recovery:stop-all-eight; [[ "$fake_recovery_fail" != stop ]] || return 73; }
    assert_recovery_complete() { fake_event recovery:final-gate; [[ "$fake_recovery_fail" != final-gate ]] || return 74; }
    cleanup_local_artifacts() { :; }
    install_traps
    run_release
  ) >"${case_dir}/stdout" 2>"${case_dir}/stderr"
  rc=$?
  set -e
  if [[ "$rc" != "$expected_rc" ]]; then
    sed -n '1,160p' "${case_dir}/stderr" >&2
    fail "$name exit $rc, expected $expected_rc"
  fi
  [[ ! -s "${case_dir}/stdout" ]] || fail "$name leaked phase output to stdout"
}

assert_fake_recovery() {
  run_fake_case success none zero 0
  require_text "${test_root}/success/events" "phase:accept"
  reject_text "${test_root}/success/events" "recovery:"

  run_fake_case early preflight zero 42
  reject_text "${test_root}/early/events" "recovery:prior-payload"
  reject_text "${test_root}/early/events" "recovery:prior-services"

  run_fake_case mid install-candidate zero 42
  require_text "${test_root}/mid/events" "recovery:prior-payload"
  require_text "${test_root}/mid/events" "recovery:prior-services"
  reject_text "${test_root}/mid/events" "recovery:score-six"

  run_fake_case late-zero restore-candidate zero 42
  require_text "${test_root}/late-zero/events" "recovery:score-six"
  require_text "${test_root}/late-zero/events" "recovery:prior-payload"
  require_text "${test_root}/late-zero/events" "recovery:prior-services"
  reject_text "${test_root}/late-zero/events" "recovery:stop-all-eight"

  run_fake_case late-work restore-candidate work 42
  require_text "${test_root}/late-work/events" "recovery:stop-all-eight"
  reject_text "${test_root}/late-work/events" "recovery:score-six"
  reject_text "${test_root}/late-work/events" "recovery:prior-payload"
  reject_text "${test_root}/late-work/events" "recovery:prior-services"

  run_fake_case signal signal zero 143
  require_text "${test_root}/signal/events" "recovery:prior-payload"
  require_text "${test_root}/signal/events" "recovery:prior-services"

  run_fake_case recovery-env restore-candidate zero 125 env
  require_text "${test_root}/recovery-env/events" "recovery:stop-all-eight"
  run_fake_case recovery-tag-source install-candidate zero 125 tag-source
  require_text "${test_root}/recovery-tag-source/events" "recovery:stop-all-eight"
  run_fake_case recovery-start install-candidate zero 125 start
  require_text "${test_root}/recovery-start/events" "recovery:stop-all-eight"
  run_fake_case recovery-stop restore-candidate work 125 stop
  run_fake_case recovery-final-gate install-candidate zero 125 final-gate
  require_text "${test_root}/recovery-final-gate/events" "recovery:stop-all-eight"
}

assert_scoring_transitions() {
  local target_root="${test_root}/scoring-target" trusted_root="${test_root}/scoring-trusted"
  local env_file="${target_root}/scoring.env"
  export BROAD_OFFLINE_SOURCE_ONLY=1
  # shellcheck source=broad-offline-release-operator.sh
  source "$OPERATOR"
  mkdir -m 700 "$target_root" "$trusted_root"
  chown 0:0 "$target_root" "$trusted_root"
  initialize_trusted_workspace "$trusted_root" "$target_root"
  printf 'FIRST=preserved\nCONTENT_SCORING_VERSION=%s\nLAST=preserved\n' "$SCORING_SIX" >"$env_file"
  chmod 600 "$env_file"
  atomic_scoring_transition "$SCORING_SIX" "$SCORING_SEVEN" 0 "$env_file" "$workspace_temp_dir"
  [[ "$(env_value "$env_file" CONTENT_SCORING_VERSION)" == "$SCORING_SEVEN" ]] || fail "scoring activation failed"
  require_text "$env_file" FIRST=preserved
  require_text "$env_file" LAST=preserved
  [[ "$(stat -c '%a' "$env_file")" == 600 ]] || fail "scoring transition changed mode"

  printf 'FIRST=preserved' >"$env_file"
  atomic_scoring_transition "$SCORING_SIX" "$SCORING_SIX" 1 "$env_file" "$workspace_temp_dir"
  [[ "$(env_value "$env_file" CONTENT_SCORING_VERSION)" == "$SCORING_SIX" ]] || fail "absent scoring normalization failed"
  require_text "$env_file" FIRST=preserved

  printf 'CONTENT_SCORING_VERSION=%s\nCONTENT_SCORING_VERSION=%s\n' "$SCORING_SIX" "$SCORING_SIX" >"$env_file"
  if atomic_scoring_transition "$SCORING_SIX" "$SCORING_SEVEN" 0 "$env_file" "$workspace_temp_dir" >/dev/null 2>&1; then
    fail "duplicate scoring owner was accepted"
  fi
  assert_container_scoring_env_json "$SCORING_SEVEN" fixture \
    "[\"CONTENT_SCORING_VERSION=${SCORING_SEVEN}\",\"OTHER=kept\"]"
  if assert_container_scoring_env_json "$SCORING_SEVEN" fixture '[]' >/dev/null 2>&1; then fail "absent container scoring env was accepted"; fi
  if assert_container_scoring_env_json "$SCORING_SEVEN" fixture \
    "[\"CONTENT_SCORING_VERSION=${SCORING_SEVEN}\",\"CONTENT_SCORING_VERSION=${SCORING_SEVEN}\"]" >/dev/null 2>&1; then
    fail "duplicate container scoring env was accepted"
  fi

  local transition="${test_root}/transition" additions
  mkdir -m 700 "$transition"
  printf 'backend/app/api_main.py\ncompose.yaml\n' >"$transition/previous"
  printf 'backend/app/agent_workbench_runtime.py\nbackend/app/api_main.py\ncompose.yaml\n' >"$transition/candidate"
  additions="$transition/additions"
  validate_source_transition "$transition/previous" "$transition/candidate" "$additions" 2 3
  [[ "$(<"$additions")" == backend/app/agent_workbench_runtime.py ]] || fail "safe candidate addition was not classified"
  printf 'backend/app/api_main.py\n' >"$transition/deletion"
  if validate_source_transition "$transition/previous" "$transition/deletion" "$transition/deletion.additions" 2 1 >/dev/null 2>&1; then
    fail "candidate source deletion was accepted"
  fi
  printf 'backend/app/api_main.py\nbackend/tests/test_agent.py\ncompose.yaml\n' >"$transition/unsafe"
  if validate_source_transition "$transition/previous" "$transition/unsafe" "$transition/unsafe.additions" 2 3 >/dev/null 2>&1; then
    fail "unsafe candidate-only test addition was accepted"
  fi

  local rollback_root="${transition}/rollback" rollback_path=backend/app/new_agent.py
  local rollback_file="${rollback_root}/${rollback_path}" rollback_digest
  mkdir -p "${rollback_root}/backend/app"
  printf 'candidate-only\n' >"$rollback_file"
  chmod 600 "$rollback_file"
  rollback_digest=$(sha256sum "$rollback_file" | awk '{print $1}')
  printf '%s\n' "$rollback_path" >"$transition/rollback.additions"
  printf 'addition\t0644\t600\t%s\t%s\t%s\n' "$(id -u)" "$(id -g)" "$rollback_path" >"$transition/rollback.evidence"
  printf '%s  %s\n' "$rollback_digest" "$rollback_path" >"$transition/rollback.manifest"
  remove_candidate_additions_from "$rollback_root" "$transition/rollback.additions" \
    "$transition/rollback.evidence" "$transition/rollback.manifest"
  [[ ! -e "$rollback_file" ]] || fail "candidate-only rollback file survived"
  cleanup_trusted_workspace "$trusted_root" "$workspace_temp_dir" "$target_root"
  workspace_temp_dir=""
}

assert_trusted_storage_contracts() {
  local root="${test_root}/trusted-root" target="${test_root}/trusted-target"
  local saved_workspace
  mkdir -m 700 "$root" "$target"
  chown 0:0 "$root" "$target"
  assert_trusted_root_metadata "$root" "$target"

  chmod 755 "$root"
  if assert_trusted_root_metadata "$root" "$target" >/dev/null 2>&1; then fail "permissive trusted root was accepted"; fi
  chmod 700 "$root"
  chown 1:1 "$root"
  if assert_trusted_root_metadata "$root" "$target" >/dev/null 2>&1; then fail "non-root trusted root owner was accepted"; fi
  chown 0:0 "$root"
  ln -s "$root" "${test_root}/trusted-root-link"
  if assert_trusted_root_metadata "${test_root}/trusted-root-link" "$target" >/dev/null 2>&1; then fail "symlink trusted root was accepted"; fi

  mkdir -m 700 "$root/.broad-stale"
  if initialize_trusted_workspace "$root" "$target" >/dev/null 2>&1; then fail "stale trusted workspace was accepted"; fi
  rmdir "$root/.broad-stale"
  initialize_trusted_workspace "$root" "$target"
  assert_trusted_workspace_contract "$root" "$workspace_temp_dir" "$target"
  chmod 755 "$workspace_temp_dir"
  if assert_trusted_workspace_contract "$root" "$workspace_temp_dir" "$target" >/dev/null 2>&1; then fail "permissive workspace was accepted"; fi
  chmod 700 "$workspace_temp_dir"
  saved_workspace="${workspace_temp_dir}.saved"
  mv "$workspace_temp_dir" "$saved_workspace"
  ln -s "$saved_workspace" "$workspace_temp_dir"
  if assert_trusted_workspace_contract "$root" "$workspace_temp_dir" "$target" >/dev/null 2>&1; then fail "symlink workspace was accepted"; fi
  unlink "$workspace_temp_dir"
  mv "$saved_workspace" "$workspace_temp_dir"
  mkdir -m 700 "$workspace_temp_dir/nested"
  printf 'cleanup-evidence\n' >"$workspace_temp_dir/nested/file"
  cleanup_trusted_workspace "$root" "$workspace_temp_dir" "$target"
  [[ ! -e "$workspace_temp_dir" ]] || fail "trusted workspace cleanup left a sibling"
  workspace_temp_dir=""

  create_unique_backup_directory "$root" 20260817T010203Z
  if create_unique_backup_directory "$root" 20260817T010203Z >/dev/null 2>&1; then fail "backup directory collision was accepted"; fi

  if [[ -d /dev/shm && "$(stat -c '%d' /dev/shm)" != "$(stat -c '%d' "$root")" ]]; then
    foreign_target=$(mktemp -d /dev/shm/edu-ai-broad-target.XXXXXX)
    chmod 700 "$foreign_target"
    if assert_trusted_root_metadata "$root" "$foreign_target" >/dev/null 2>&1; then fail "cross-device trusted root was accepted"; fi
    rmdir "$foreign_target"
    foreign_target=""
  fi
}

assert_source_install_contracts() {
  local root="${test_root}/install-trusted" destination="${test_root}/install-destination"
  local source="${test_root}/install-source" evidence additions manifest digest
  local uid gid race_destination
  mkdir -m 700 "$root" "$destination" "$source"
  mkdir -p "$destination/backend/app" "$source/backend/app"
  chmod 700 "$destination/backend" "$destination/backend/app" "$source/backend" "$source/backend/app"
  chown -R 0:0 "$root" "$destination" "$source"
  initialize_trusted_workspace "$root" "$destination"
  uid=$(id -u)
  gid=$(id -g)
  trusted_mktemp_file evidence install-evidence "$root" "$workspace_temp_dir" "$destination"
  printf 'prior\n' >"$destination/backend/app/existing.py"
  printf 'candidate-existing\n' >"$source/backend/app/existing.py"
  printf 'candidate-addition\n' >"$source/backend/app/new_agent.py"
  chmod 600 "$destination/backend/app/existing.py"
  chmod 644 "$source/backend/app/existing.py" "$source/backend/app/new_agent.py"
  printf 'existing\t0644\t600\t%s\t%s\tbackend/app/existing.py\n' "$uid" "$gid" >"$evidence"
  printf 'addition\t0644\t600\t%s\t%s\tbackend/app/new_agent.py\n' "$uid" "$gid" >>"$evidence"
  install_reviewed_source_tree "$source" 1 "$destination" "$root" "$workspace_temp_dir" "$evidence"
  require_text "$destination/backend/app/existing.py" candidate-existing
  require_text "$destination/backend/app/new_agent.py" candidate-addition
  [[ "$(stat -c '%a:%u:%g' "$destination/backend/app/new_agent.py")" == "600:${uid}:${gid}" ]] || fail "candidate addition install metadata drifted"

  additions="$workspace_temp_dir/installed-additions"
  manifest="$workspace_temp_dir/installed-manifest"
  printf 'backend/app/new_agent.py\n' >"$additions"
  digest=$(sha256sum "$destination/backend/app/new_agent.py" | awk '{print $1}')
  printf '%s  backend/app/new_agent.py\n' "$digest" >"$manifest"
  remove_candidate_additions_from "$destination" "$additions" "$evidence" "$manifest"
  [[ ! -e "$destination/backend/app/new_agent.py" ]] || fail "installed candidate addition survived rollback"

  mkdir -m 700 "$destination/backend/app/safe" "$source/backend/app/link"
  ln -s "$destination/backend/app/safe" "$destination/backend/app/link"
  printf 'unsafe-parent\n' >"$source/backend/app/link/new.py"
  chmod 644 "$source/backend/app/link/new.py"
  printf 'addition\t0644\t600\t%s\t%s\tbackend/app/link/new.py\n' "$uid" "$gid" >"$evidence"
  if install_reviewed_source_tree "$source" 1 "$destination" "$root" "$workspace_temp_dir" "$evidence" >/dev/null 2>&1; then
    fail "nested symlink destination parent was accepted"
  fi
  unlink "$destination/backend/app/link"

  mkdir -m 700 "$destination/backend/app/owner" "$source/backend/app/owner"
  printf 'bad-owner\n' >"$source/backend/app/owner/new.py"
  chmod 644 "$source/backend/app/owner/new.py"
  chown 1:1 "$destination/backend/app/owner"
  printf 'addition\t0644\t600\t%s\t%s\tbackend/app/owner/new.py\n' "$uid" "$gid" >"$evidence"
  if install_reviewed_source_tree "$source" 1 "$destination" "$root" "$workspace_temp_dir" "$evidence" >/dev/null 2>&1; then
    fail "non-uniform destination parent owner was accepted"
  fi
  chown 0:0 "$destination/backend/app/owner"

  mkdir -m 700 "$destination/backend/app/mode" "$source/backend/app/mode"
  printf 'bad-mode\n' >"$source/backend/app/mode/new.py"
  chmod 644 "$source/backend/app/mode/new.py"
  chmod 777 "$destination/backend/app/mode"
  printf 'addition\t0644\t600\t%s\t%s\tbackend/app/mode/new.py\n' "$uid" "$gid" >"$evidence"
  if install_reviewed_source_tree "$source" 1 "$destination" "$root" "$workspace_temp_dir" "$evidence" >/dev/null 2>&1; then
    fail "group/world-writable destination parent was accepted"
  fi
  chmod 700 "$destination/backend/app/mode"

  race_destination="$destination/backend/app/race.py"
  printf 'prior-race\n' >"$race_destination"
  printf 'candidate-race\n' >"$source/backend/app/race.py"
  chmod 600 "$race_destination"
  chmod 644 "$source/backend/app/race.py"
  printf 'existing\t0644\t600\t%s\t%s\tbackend/app/race.py\n' "$uid" "$gid" >"$evidence"
  (
    trusted_mktemp_file() {
      local output_name=$1 prefix=$2 workspace=$4 created
      created=$(mktemp "${workspace}/${prefix}.XXXXXX")
      chmod 600 "$created"
      chown 0:0 "$created"
      printf -v "$output_name" '%s' "$created"
      mv "$race_destination" "${race_destination}.before-race"
      printf 'raced\n' >"$race_destination"
      chmod 600 "$race_destination"
    }
    if install_reviewed_source_tree "$source" 1 "$destination" "$root" "$workspace_temp_dir" "$evidence" >/dev/null 2>&1; then
      exit 1
    fi
  ) || fail "destination TOCTOU replacement was accepted"
  mv "${race_destination}.before-race" "$race_destination"

  cleanup_trusted_workspace "$root" "$workspace_temp_dir" "$destination"
  workspace_temp_dir=""
  [[ -z "$(find "$root" -mindepth 1 -maxdepth 1 -name '.broad-*' -print -quit)" ]] || fail "source install left a broad-release sibling"
}

assert_recovery_deadline_independence() {
  (
    local service
    declare -A OLD_CONTAINER_IDS=()
    scheduler_safe_until_utc=1970-01-01T00:00:00Z
    assert_safe_window() { return 99; }
    sleep() { :; }
    assert_startup_observed_zero() { :; }
    docker_call() { :; }
    compose_call() { :; }
    wait_for_service() { :; }
    assert_running_release() { :; }
    assert_safe_logs() { :; }
    for service in "${RESTORE_ORDER[@]}"; do OLD_CONTAINER_IDS["$service"]="prior-${service}"; done
    restore_prior_services
  ) || fail "expired deployment deadline blocked prior-service recovery"
}

assert_observed_startup_gate() {
  BROAD_OFFLINE_SOURCE_ONLY=1 bash -Eeuo pipefail -c '
    # shellcheck source=broad-offline-release-operator.sh
    source "$1"
    observed_work="0:0:0:0:0:0:0"
    observed_legacy="0:0:0"
    zero_work_vector() { printf "%s\n" "$observed_work"; }
    legacy_prompt_vector() { printf "%s\n" "$observed_legacy"; }
    assert_startup_observed_zero fixture
    observed_work="1:0:0:0:0:0:0"
    if assert_startup_observed_zero fixture >/dev/null 2>&1; then
      exit 1
    fi
    observed_work="0:0:0:0:0:0:0"
    observed_legacy="0:1:0"
    if assert_startup_observed_zero fixture >/dev/null 2>&1; then
      exit 1
    fi
  ' _ "$OPERATOR" || fail "observed startup gate accepted actionable or legacy work"
}

assert_immutable_rollback_tag_contract() {
  (
    rollback_tag_prefix=edu-ai-lead-agent-backend:rollback-20260817T010203Z
    docker_call() {
      [[ "$1" == image && "$2" == inspect && "$4" == --format ]] || return 91
      printf '%s\n' "$PREVIOUS_IMAGE_ID"
    }
    assert_rollback_tags
    [[ "$(rollback_tag_for_service content-worker)" == \
      edu-ai-lead-agent-backend:rollback-20260817T010203Z-content-worker ]] \
      || exit 92
    docker_call() { printf '%s\n' sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff; }
    if assert_rollback_tags >/dev/null 2>&1; then exit 93; fi
  ) || fail "immutable rollback tags were not fail-closed"
}

assert_candidate_provenance_contract() {
  local image_id="sha256:$(printf '1%.0s' {1..64})"
  local dependency_id="sha256:$(printf '2%.0s' {1..64})"
  local archive_sha manifest_sha image_source_sha commit
  archive_sha=$(printf '3%.0s' {1..64})
  manifest_sha=$(printf '4%.0s' {1..64})
  image_source_sha=$(printf '5%.0s' {1..64})
  commit=$(printf '6%.0s' {1..40})
  candidate_id=$image_id
  candidate_commit=$commit
  expected_dependency_base_id=$dependency_id
  source_sha256=$archive_sha
  source_manifest_sha256=$manifest_sha
  image_source_manifest_sha256=$image_source_sha
  assert_candidate_provenance_values "$image_id" "$commit" "$dependency_id" \
    "$EXPECTED_BASE_PYPROJECT_SHA256" "$EXPECTED_FINAL_PYPROJECT_SHA256" \
    "$EXPECTED_RUNTIME_LOCK_SHA256" "$EXPECTED_DOCKERFILE_SHA256" \
    "$archive_sha" "$manifest_sha" "$image_source_sha"
  if assert_candidate_provenance_values "$image_id" "$commit" "$dependency_id" \
    "$EXPECTED_BASE_PYPROJECT_SHA256" "$EXPECTED_FINAL_PYPROJECT_SHA256" \
    "$EXPECTED_RUNTIME_LOCK_SHA256" "$EXPECTED_DOCKERFILE_SHA256" \
    "$(printf '9%.0s' {1..64})" "$manifest_sha" "$image_source_sha" >/dev/null 2>&1; then
    fail "wrong source archive provenance label was accepted"
  fi
  if assert_candidate_provenance_values "$image_id" "$commit" "$dependency_id" \
    "$EXPECTED_BASE_PYPROJECT_SHA256" "$EXPECTED_FINAL_PYPROJECT_SHA256" \
    "$EXPECTED_RUNTIME_LOCK_SHA256" "$EXPECTED_DOCKERFILE_SHA256" \
    "$archive_sha" "$(printf '9%.0s' {1..64})" "$image_source_sha" >/dev/null 2>&1; then
    fail "wrong source manifest provenance label was accepted"
  fi
  if assert_candidate_provenance_values "$image_id" "$commit" "$dependency_id" \
    "$EXPECTED_BASE_PYPROJECT_SHA256" "$EXPECTED_FINAL_PYPROJECT_SHA256" \
    "$EXPECTED_RUNTIME_LOCK_SHA256" "$EXPECTED_DOCKERFILE_SHA256" \
    "$archive_sha" "$manifest_sha" "$(printf '9%.0s' {1..64})" >/dev/null 2>&1; then
    fail "wrong image-source provenance label was accepted"
  fi
}

assert_stage_shape() {
  local fixture="${test_root}/stage" member
  mkdir -m 700 "$fixture"
  for member in "${STAGE_MEMBERS[@]}"; do : >"${fixture}/${member}"; done
  install -m 600 "$OPERATOR" "${fixture}/broad-offline-release-operator.sh"
  install -m 600 "$VALIDATOR" "${fixture}/validate-broad-offline-artifacts.py"
  candidate_commit=$(printf '6%.0s' {1..40})
  candidate_id="sha256:$(printf '1%.0s' {1..64})"
  candidate_tag="edu-ai-lead-agent-backend:broad-${candidate_commit:0:12}"
  expected_dependency_base_id=$DEPENDENCY_BASE_ID
  printf '%s\n' \
    "release_sha=${candidate_commit}" \
    "candidate_tag=${candidate_tag}" \
    "candidate_id=${candidate_id}" \
    "dependency_base_id=${DEPENDENCY_BASE_ID}" \
    "runtime_lock_sha256=${EXPECTED_RUNTIME_LOCK_SHA256}" \
    "dockerfile_sha256=${EXPECTED_DOCKERFILE_SHA256}" \
    "base_pyproject_sha256=${EXPECTED_BASE_PYPROJECT_SHA256}" \
    "final_pyproject_sha256=${EXPECTED_FINAL_PYPROJECT_SHA256}" \
    'production_dependency_delta=none' 'dev_dependency_delta=mcp==2.0.0' \
    'pytest_pythonpath=.' 'supported_mcp_imports=0' 'candidate_mcp_distribution=absent' \
    "source_file_count=${EXPECTED_SOURCE_FILE_COUNT}" \
    "image_source_file_count=${EXPECTED_IMAGE_SOURCE_FILE_COUNT}" \
    "alembic_head=${EXPECTED_ALEMBIC_HEAD}" \
    'runtime_probe=non-root,read-only,network-none,cap-drop-all,no-new-privileges' \
    'scoring_compatibility=.6/v3,.7/v4' \
    'production_workbench=absent' \
    'rootfs_dependency_base_prefix=exact' \
    >"${fixture}/image-validation.txt"
  chmod 600 "${fixture}"/*
  (
    cd "$fixture"
    sha256sum source.tar.gz >source.tar.gz.sha256
    sha256sum backend-image.tar.gz >backend-image.tar.gz.sha256
    sha256sum backend-image.tar.gz backend-image.tar.gz.sha256 \
      broad-offline-release-operator.sh image-source-files.sha256 \
      image-validation.txt source-files.sha256 source.tar.gz \
      source.tar.gz.sha256 validate-broad-offline-artifacts.py \
      >artifacts.sha256
  )
  chmod 600 "${fixture}"/*
  stage_dir=$fixture
  source_sha256=$(sha256sum "${fixture}/source.tar.gz" | awk '{print $1}')
  source_manifest_sha256=$(sha256sum "${fixture}/source-files.sha256" | awk '{print $1}')
  image_bundle_sha256=$(sha256sum "${fixture}/backend-image.tar.gz" | awk '{print $1}')
  image_source_manifest_sha256=$(sha256sum "${fixture}/image-source-files.sha256" | awk '{print $1}')
  operator_sha256=$(sha256sum "${fixture}/broad-offline-release-operator.sh" | awk '{print $1}')
  validator_sha256=$(sha256sum "${fixture}/validate-broad-offline-artifacts.py" | awk '{print $1}')
  assert_stage_and_artifacts
  : >"${fixture}/unexpected"
  chmod 600 "${fixture}/unexpected"
  if assert_stage_and_artifacts >/dev/null 2>&1; then fail "extra stage member was accepted"; fi
}

write_source_fixture() {
  local root=$1
  mkdir -p "$root/tree/backend/requirements"
  printf 'services: {}\n' >"$root/tree/compose.yaml"
  printf '[alembic]\n' >"$root/tree/backend/alembic.ini"
  printf '[project]\nname="fixture"\n' >"$root/tree/backend/pyproject.toml"
  printf 'fixture==1\n' >"$root/tree/backend/requirements/runtime.lock"
  find "$root/tree" -type d -exec chmod 755 {} +
  find "$root/tree" -type f -exec chmod 644 {} +
  (
    cd "$root/tree"
    find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sed 's#  \./#  #' >"$root/source-files.sha256"
    tar -czf "$root/source.tar.gz" compose.yaml backend
  )
}

assert_artifact_validator() {
  local fixture="${test_root}/source-fixture" count image_fixture config_hex image_id image_tag
  local layer_diff
  mkdir -m 700 "$fixture"
  write_source_fixture "$fixture"
  count=$(wc -l <"$fixture/source-files.sha256" | tr -d '[:space:]')
  python3 "$VALIDATOR" source --archive "$fixture/source.tar.gz" \
    --manifest "$fixture/source-files.sha256" --expected-count "$count" \
    --paths-output "$fixture/paths" --modes-output "$fixture/modes"
  [[ "$(wc -l <"$fixture/paths" | tr -d '[:space:]')" == "$count" ]] || fail "source path evidence count mismatch"

  chmod 600 "$fixture/tree/compose.yaml"
  tar -C "$fixture/tree" -czf "$fixture/bad-file-mode.tar.gz" compose.yaml backend
  if python3 "$VALIDATOR" source --archive "$fixture/bad-file-mode.tar.gz" \
    --manifest "$fixture/source-files.sha256" --expected-count "$count" \
    --paths-output "$fixture/bad-mode.paths" --modes-output "$fixture/bad-mode.modes" >/dev/null 2>&1; then
    fail "0600 candidate archive member was accepted"
  fi
  chmod 644 "$fixture/tree/compose.yaml"
  chmod 700 "$fixture/tree/backend"
  tar -C "$fixture/tree" -czf "$fixture/bad-directory-mode.tar.gz" compose.yaml backend
  if python3 "$VALIDATOR" source --archive "$fixture/bad-directory-mode.tar.gz" \
    --manifest "$fixture/source-files.sha256" --expected-count "$count" \
    --paths-output "$fixture/bad-dir.paths" --modes-output "$fixture/bad-dir.modes" >/dev/null 2>&1; then
    fail "0700 candidate archive directory was accepted"
  fi
  chmod 755 "$fixture/tree/backend"

  mkdir -p "$fixture/bad"
  ln -s /etc/passwd "$fixture/bad/link"
  tar -C "$fixture/bad" -czf "$fixture/bad.tar.gz" link
  printf '%064d  link\n' 0 >"$fixture/bad.sha256"
  if python3 "$VALIDATOR" source --archive "$fixture/bad.tar.gz" \
    --manifest "$fixture/bad.sha256" --expected-count 1 \
    --paths-output "$fixture/bad.paths" --modes-output "$fixture/bad.modes" >/dev/null 2>&1; then
    fail "source symlink archive was accepted"
  fi

  image_fixture="${test_root}/image-fixture"
  mkdir -p "${image_fixture}/layer/root"
  printf 'layer-payload\n' >"${image_fixture}/layer/root/file"
  tar -C "${image_fixture}/layer/root" -cf "${image_fixture}/layer/layer.tar" file
  layer_diff=$(sha256sum "${image_fixture}/layer/layer.tar" | awk '{print $1}')
  printf '{"architecture":"amd64","os":"linux","rootfs":{"type":"layers","diff_ids":["sha256:%s"]}}\n' \
    "$layer_diff" >"${image_fixture}/config.json"
  config_hex=$(sha256sum "${image_fixture}/config.json" | awk '{print $1}')
  image_id="sha256:${config_hex}"
  image_tag=edu-ai-lead-agent-backend:broad-1234567
  mv "${image_fixture}/config.json" "${image_fixture}/${config_hex}.json"
  printf '[{"Config":"%s.json","RepoTags":["%s"],"Layers":["layer/layer.tar"]}]\n' \
    "$config_hex" "$image_tag" >"${image_fixture}/manifest.json"
  tar -C "$image_fixture" -czf "${image_fixture}/bundle.tar.gz" \
    manifest.json "${config_hex}.json" layer/layer.tar
  python3 "$VALIDATOR" image --bundle "${image_fixture}/bundle.tar.gz" \
    --expected-tag "$image_tag" --expected-image-id "$image_id"
  printf 'tampered-layer\n' >>"${image_fixture}/layer/layer.tar"
  tar -C "$image_fixture" -czf "${image_fixture}/bad-layer-bundle.tar.gz" \
    manifest.json "${config_hex}.json" layer/layer.tar
  if python3 "$VALIDATOR" image --bundle "${image_fixture}/bad-layer-bundle.tar.gz" \
    --expected-tag "$image_tag" --expected-image-id "$image_id" >/dev/null 2>&1; then
    fail "classic image layer/rootfs diff-id drift was accepted"
  fi
  printf 'unexpected\n' >"${image_fixture}/extra"
  tar -C "$image_fixture" -czf "${image_fixture}/bad-bundle.tar.gz" \
    manifest.json "${config_hex}.json" layer/layer.tar extra
  if python3 "$VALIDATOR" image --bundle "${image_fixture}/bad-bundle.tar.gz" \
    --expected-tag "$image_tag" --expected-image-id "$image_id" >/dev/null 2>&1; then
    fail "image bundle with an extra member was accepted"
  fi
}

assert_static_contract() {
  require_text "$OPERATOR" 'PREVIOUS_COMMIT="f20db2060abcfd49b6236137838473ac6f0b7dd4"'
  require_text "$OPERATOR" 'PREVIOUS_IMAGE_ID="sha256:ce67385749cc14ee845d3a6fbdd92404df59902adc579534df5d01b6e1a4e8da"'
  require_text "$OPERATOR" 'EXPECTED_RUNTIME_LOCK_SHA256="3be154ff0e7f741b9f74d516baf739a4a38571218670b47dd1031f9dc1b44915"'
  require_text "$OPERATOR" 'EXPECTED_DOCKERFILE_SHA256="d4c2823d9354a7a5c31c2885317cd46b5c764d6afb964306c4204f7ed063fd1f"'
  require_text "$OPERATOR" 'EXPECTED_SOURCE_FILE_COUNT=321'
  require_text "$OPERATOR" 'EXPECTED_IMAGE_SOURCE_FILE_COUNT=179'
  require_text "$OPERATOR" "--format '{{.Os}}/{{.Architecture}}'"
  require_text "$OPERATOR" '--entrypoint alembic backend-migrate -c alembic.ini upgrade head'
  require_text "$OPERATOR" 'compose_call up -d --no-build --no-deps --force-recreate "$service"'
  require_text "$OPERATOR" 'INCIDENT: retained candidate and .7'
  require_text "$OPERATOR" 'supported production entrypoint imports dev-only mcp'
  require_text "$OPERATOR" 'io.trellis.release.source-archive-sha256'
  require_text "$OPERATOR" 'io.trellis.release.source-manifest-sha256'
  require_text "$OPERATOR" 'io.trellis.release.image-source-manifest-sha256'
  require_text "$OPERATOR" 'assert_trusted_backup_root'
  require_text "$OPERATOR" '600:${expected_env_uid}:${expected_env_gid}'
  require_text "$OPERATOR" "runtime_env=\$(docker_call inspect \"\$cid\" --format '{{json .Config.Env}}'"
  require_text "$OPERATOR" 'first="$(durable_vector)|$(provider_vector)|$(source_vector)|$(zero_work_vector)|$(legacy_prompt_vector)"'
  require_text "$OPERATOR" 'assert_startup_observed_zero "before $service"'
  require_text "$OPERATOR" 'assert_startup_observed_zero "after $service start"'
  require_text "$OPERATOR" '"$(zero_work_vector)" == "0:0:0:0:0:0:0" && "$(legacy_prompt_vector)" == "0:0:0"'
  require_text "$OPERATOR" "r.business_date=(now() AT TIME ZONE 'Asia/Shanghai')::date"
  require_text "$OPERATOR" "j.available_at<=now()"
  reject_text "$OPERATOR" 'assert_startup_projection_zero'
  require_text "$OPERATOR" 'rollback-tag-inventory.txt'
  require_text "$OPERATOR" 'assert_rollback_tags'
  reject_text "$OPERATOR" 'compose_call up --no-build backend-migrate'
  reject_text "$OPERATOR" 'python -m app.seed_sources'
  reject_text "$OPERATOR" 'make release-prod'
}

assert_c66_allowlist() {
  local manifest="${test_root}/c66-paths" count
  git -C "${HERE}/../../../.." ls-tree -r --name-only \
    c66aa6217d137033118c552f3db11b2a1121d082 -- \
    backend deploy infra scripts compose.yaml .env.example .gitattributes \
    .gitignore AGENTS.md Makefile README.md environment.yml \
    | LC_ALL=C sort >"$manifest"
  count=$(wc -l <"$manifest" | tr -d '[:space:]')
  [[ "$count" == 307 ]] || fail "c66 runtime allowlist is not exact 307"
  ! grep -Eq '^(frontend|reports|private|\.trellis)/' "$manifest" || fail "c66 runtime allowlist crossed a forbidden root"
}

bash -n "$OPERATOR" "$0"
python3 -m py_compile "$VALIDATOR"
assert_static_contract
assert_c66_allowlist
assert_artifact_validator
assert_fake_recovery
assert_scoring_transitions
assert_trusted_storage_contracts
assert_source_install_contracts
assert_recovery_deadline_independence
assert_observed_startup_gate
assert_immutable_rollback_tag_contract
assert_candidate_provenance_contract
assert_stage_shape
printf 'PASS: broad offline operator static, artifact, trusted-root, install/rollback, config, and fail-closed recovery checks\n'
