#!/usr/bin/env bash
# Local-only fake/state-machine checks. No Docker, network, database, provider,
# production path, image load, enqueue, or delivery operation is performed.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

readonly HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly OPERATOR="${HERE}/baseline-7ba-offline-release-operator.sh"
readonly VALIDATOR="${HERE}/validate-image-fallback-offline-artifacts.py"
test_root=$(mktemp -d /tmp/edu-ai-image-fallback-operator-test.XXXXXX)
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
  if [[ -n "${foreign_target:-}" && "$foreign_target" == /dev/shm/edu-ai-image-fallback-target.* && -d "$foreign_target" && ! -L "$foreign_target" ]]; then
    find "$foreign_target" -xdev -depth -delete
  fi
  if [[ -n "${test_root:-}" && "$test_root" == /tmp/edu-ai-image-fallback-operator-test.* ]]; then
    find "$test_root" -depth -delete
  fi
}
trap cleanup EXIT

export IMAGE_FALLBACK_OFFLINE_SOURCE_ONLY=1
# shellcheck source=baseline-7ba-offline-release-operator.sh
source "$OPERATOR"

run_fake_case() {
  local name=$1 fail_at=$2 vector_state=$3 expected_rc=$4
  local recovery_fail=${5:-none}
  local case_dir="${test_root}/${name}" rc
  mkdir -m 700 "$case_dir"
  set +e
  (
    set -Eeuo pipefail
    fake_vector_state=$vector_state
    fake_recovery_fail=$recovery_fail
    expected_durable_vector=1:1
    expected_provider_vector=2:2
    expected_source_vector=3:3
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
    phase_install_candidate() {
      tags_changed=1
      overlay_changed=1
      fake_phase install-candidate
      if [[ "$fail_at" == signal ]]; then
        kill -TERM "$BASHPID"
      fi
    }
    phase_migrate_and_probe() { fake_phase migrate-probe; }
    phase_restore_candidate() { fake_phase restore-candidate; }
    phase_accept() { fake_phase accept; }
    restore_prior_payload() { ((backup_ready == 0)) || fake_event recovery:prior-payload; [[ "$fake_recovery_fail" != tag-source ]] || return 71; }
    restore_prior_services() { fake_event recovery:prior-services; [[ "$fake_recovery_fail" != start ]] || return 72; }
    stop_all_app_services() { fake_event recovery:stop-all-eight; [[ "$fake_recovery_fail" != stop ]] || return 73; }
    durable_vector() { [[ "$fake_vector_state" == stable ]] && printf '1:1\n' || printf '9:9\n'; }
    provider_vector() { printf '2:2\n'; }
    source_vector() { printf '3:3\n'; }
    zero_work_vector() { printf '0:0:0:0:0:0:0\n'; }
    legacy_prompt_vector() { printf '0:0:0\n'; }
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
  run_fake_case success none stable 0
  require_text "${test_root}/success/events" "phase:accept"
  reject_text "${test_root}/success/events" "recovery:"

  run_fake_case early preflight stable 42
  reject_text "${test_root}/early/events" "recovery:"

  run_fake_case mid install-candidate stable 42
  require_text "${test_root}/mid/events" "recovery:stop-all-eight"
  require_text "${test_root}/mid/events" "recovery:prior-payload"
  require_text "${test_root}/mid/events" "recovery:prior-services"

  run_fake_case late-stable restore-candidate stable 42
  require_text "${test_root}/late-stable/events" "recovery:stop-all-eight"
  require_text "${test_root}/late-stable/events" "recovery:prior-payload"
  require_text "${test_root}/late-stable/events" "recovery:prior-services"

  run_fake_case late-work restore-candidate drift 42
  require_text "${test_root}/late-work/events" "recovery:stop-all-eight"
  reject_text "${test_root}/late-work/events" "recovery:prior-payload"
  reject_text "${test_root}/late-work/events" "recovery:prior-services"

  run_fake_case signal signal stable 143
  require_text "${test_root}/signal/events" "recovery:stop-all-eight"
  require_text "${test_root}/signal/events" "recovery:prior-payload"
  require_text "${test_root}/signal/events" "recovery:prior-services"

  run_fake_case recovery-tag-source install-candidate stable 125 tag-source
  require_text "${test_root}/recovery-tag-source/events" "recovery:stop-all-eight"
  run_fake_case recovery-start install-candidate stable 125 start
  require_text "${test_root}/recovery-start/events" "recovery:stop-all-eight"
  run_fake_case recovery-stop restore-candidate drift 125 stop
  run_fake_case recovery-final-gate install-candidate stable 125 final-gate
  require_text "${test_root}/recovery-final-gate/events" "recovery:stop-all-eight"
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

  mkdir -m 700 "$root/.image-fallback-stale"
  if initialize_trusted_workspace "$root" "$target" >/dev/null 2>&1; then fail "stale trusted workspace was accepted"; fi
  rmdir "$root/.image-fallback-stale"
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
    foreign_target=$(mktemp -d /dev/shm/edu-ai-image-fallback-target.XXXXXX)
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
  [[ -z "$(find "$root" -mindepth 1 -maxdepth 1 -name '.image-fallback-*' -print -quit)" ]] || fail "source install left a image-fallback release sibling"
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

assert_safe_window_contract() (
  minimum_safe_seconds=900
  scheduler_safe_until_utc=$(date -u -d '+1 hour' '+%Y-%m-%dT%H:%M:%SZ')
  assert_safe_window

  scheduler_safe_until_utc=$(date -u -d '+899 seconds' '+%Y-%m-%dT%H:%M:%SZ')
  if assert_safe_window >/dev/null 2>&1; then
    fail "safe-window deadline below the minimum was accepted"
  fi

  scheduler_safe_until_utc=2026-02-30T00:00:00Z
  if assert_safe_window >/dev/null 2>&1; then
    fail "invalid safe-window UTC timestamp was accepted"
  fi
)

assert_observed_startup_gate() {
  IMAGE_FALLBACK_OFFLINE_SOURCE_ONLY=1 bash -Eeuo pipefail -c '
    # shellcheck source=baseline-7ba-offline-release-operator.sh
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

assert_minio_inventory_contract() (
  local output="${test_root}/minio.sha256" run_seen=0 expected_arg script requested_root
  local volume=edu_ai_minio_data
  local mountpoint=/var/lib/docker/volumes/edu_ai_minio_data/_data
  local inventory_root="${test_root}/minio-inventory-root" run_mode=synthetic mount_mode=exact
  local -a expected_run
  mkdir -m 700 "$inventory_root"
  candidate_id="sha256:$(printf '1%.0s' {1..64})"
  expected_run=(
    run --rm --pull never --network none --read-only
    --cap-drop ALL --cap-add DAC_READ_SEARCH --security-opt no-new-privileges:true
    --user 0:0 --pids-limit 64 --memory 512m --cpus 1
    --mount "type=volume,src=${volume},dst=/inventory-data,readonly"
    --entrypoint python "$candidate_id" -c
  )
  docker_call() {
    if [[ "$1" == inspect ]]; then
      if [[ "$mount_mode" == duplicate ]]; then
        printf 'volume\t%s\t%s\ttrue\nvolume\t%s\t%s\ttrue\n' "$volume" "$mountpoint" "$volume" "$mountpoint"
      else
        printf 'volume\t%s\t%s\ttrue\n' "$volume" "$mountpoint"
      fi
      return
    fi
    if [[ "$1" == volume && "$2" == inspect ]]; then
      if [[ "$mount_mode" == mismatch ]]; then
        printf '%s\t%s-other\n' "$volume" "$mountpoint"
      else
        printf '%s\t%s\n' "$volume" "$mountpoint"
      fi
      return
    fi
    for expected_arg in "${expected_run[@]}"; do
      [[ "${1-}" == "$expected_arg" ]] || return 91
      shift
    done
    script=${1-}
    shift
    [[ "$script" == *'os.scandir(directory_fd)'* && "$script" == *'dir_fd=directory_fd'* \
      && "$script" == *'os.O_NOFOLLOW'* && "$script" == *'os.O_NONBLOCK'* \
      && "$script" == *'identity(final_directory) != identity(initial_directory)'* \
      && "$script" == *'MinIO inventory rejected'* ]] || return 92
    [[ "$#" == 6 && "$1" == /inventory-data && "$2" == 1000000 \
      && "$3" == 1099511627776 && "$4" == 64 && "$5" == 4096 && "$6" == 1048576 ]] \
      || return 93
    requested_root=$1
    shift
    run_seen=1
    case "$run_mode" in
      synthetic) printf '%064d\t0\tLi9vYmplY3Q=\n' 0 ;;
      actual) python3 -c "$script" "$inventory_root" "$@" ;;
      empty) : ;;
      malformed) printf 'not-an-inventory-row\n' ;;
      fail) return 94 ;;
      *) return 95 ;;
    esac
  }
  write_minio_inventory minio-container "$output"
  [[ "$run_seen" == 1 && -f "$output" && "$validated_minio_volume_name" == "$volume" ]] \
    || fail "safe candidate-image MinIO inventory run was not exact"
  unlink -- "$output"

  run_mode=empty
  if write_minio_inventory minio-container "$output" >/dev/null 2>&1; then
    fail "empty MinIO inventory was accepted"
  fi
  [[ ! -e "$output" ]] || fail "empty MinIO inventory left partial evidence"

  run_mode=malformed
  if write_minio_inventory minio-container "$output" >/dev/null 2>&1; then
    fail "malformed MinIO inventory was accepted"
  fi
  [[ ! -e "$output" ]] || fail "malformed MinIO inventory left partial evidence"

  printf 'safe-object\n' >"$inventory_root/object"
  mkdir -m 700 "$inventory_root/.minio.sys"
  printf 'internal-before\n' >"$inventory_root/.minio.sys/internal"
  run_mode=actual
  write_minio_inventory minio-container "$output"
  [[ "$(wc -l <"$output" | tr -d '[:space:]')" == 1 ]] \
    || fail "MinIO control metadata entered the business-object inventory"
  local object_manifest_sha
  object_manifest_sha=$(sha256sum "$output" | awk '{print $1}')
  unlink -- "$output"
  printf 'internal-after\n' >"$inventory_root/.minio.sys/internal"
  write_minio_inventory minio-container "$output"
  [[ "$(sha256sum "$output" | awk '{print $1}')" == "$object_manifest_sha" ]] \
    || fail "MinIO control metadata rotation changed the business-object inventory"
  unlink -- "$output"
  printf 'changed-object\n' >"$inventory_root/object"
  write_minio_inventory minio-container "$output"
  [[ "$(sha256sum "$output" | awk '{print $1}')" != "$object_manifest_sha" ]] \
    || fail "MinIO business-object drift did not change the inventory"
  unlink -- "$output"
  ln -s object "$inventory_root/link"
  if write_minio_inventory minio-container "$output" >/dev/null 2>&1; then
    fail "MinIO inventory accepted a symlink"
  fi
  [[ ! -e "$output" ]] || fail "symlink rejection left partial MinIO evidence"
  unlink -- "$inventory_root/link"
  mkfifo "$inventory_root/fifo"
  if write_minio_inventory minio-container "$output" >/dev/null 2>&1; then
    fail "MinIO inventory accepted a special file"
  fi
  [[ ! -e "$output" ]] || fail "special-file rejection left partial MinIO evidence"
  unlink -- "$inventory_root/fifo"

  mount_mode=duplicate
  if write_minio_inventory minio-container "$output" >/dev/null 2>&1; then
    fail "duplicate MinIO /data mounts were accepted"
  fi
  mount_mode=mismatch
  if write_minio_inventory minio-container "$output" >/dev/null 2>&1; then
    fail "MinIO volume mountpoint mismatch was accepted"
  fi
  mount_mode=exact
  run_mode=fail
  if write_minio_inventory minio-container "$output" >/dev/null 2>&1; then
    fail "MinIO inventory command failure was not propagated"
  fi
  [[ ! -e "$output" ]] || fail "failed MinIO inventory left partial evidence"
)

assert_stale_migration_cleanup_contract() (
  local expected_cid state=exited removed=0 multiple=0
  local fixture_image=$PREVIOUS_IMAGE_ID fixture_restarts=0
  local fixture_project=$COMPOSE_PROJECT fixture_service=backend-migrate fixture_number=1
  expected_cid=$(printf 'a%.0s' {1..64})
  compose_call() {
    [[ "$#" == 4 && "$1" == ps && "$2" == -a && "$3" == -q && "$4" == backend-migrate ]] || return 81
    if ((removed == 1)); then return 0; fi
    printf '%s\n' "$expected_cid"
    if ((multiple == 1)); then printf '%s\n' "$(printf 'b%.0s' {1..64})"; fi
  }
  docker_call() {
    case "$1" in
      inspect)
        [[ "$2" == "$expected_cid" && "$3" == --format && -n "${4-}" ]] || return 82
        printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
          "$fixture_image" "$state" "$fixture_restarts" "$fixture_project" \
          "$fixture_service" "$fixture_number"
        ;;
      rm)
        [[ "$2" == "$expected_cid" && "$#" == 2 ]] || return 83
        removed=1
        ;;
      *) return 84 ;;
    esac
  }
  remove_stale_migration_container
  [[ "$removed" == 1 ]] || fail "reviewed exited migration one-shot was not removed"
  removed=0
  state=running
  if remove_stale_migration_container >/dev/null 2>&1; then
    fail "running migration container was accepted as stale"
  fi
  [[ "$removed" == 0 ]] || fail "unsafe migration container was removed"
  state=exited
  fixture_image="sha256:$(printf 'c%.0s' {1..64})"
  if remove_stale_migration_container >/dev/null 2>&1; then
    fail "foreign-image migration container was accepted"
  fi
  fixture_image=$PREVIOUS_IMAGE_ID
  fixture_project=foreign-project
  if remove_stale_migration_container >/dev/null 2>&1; then
    fail "foreign-label migration container was accepted"
  fi
  fixture_project=$COMPOSE_PROJECT
  fixture_restarts=1
  if remove_stale_migration_container >/dev/null 2>&1; then
    fail "restarted migration container was accepted"
  fi
  fixture_restarts=0
  multiple=1
  if remove_stale_migration_container >/dev/null 2>&1; then
    fail "multiple migration containers were accepted"
  fi
)

assert_stage_shape() {
  local fixture="${test_root}/stage" member
  mkdir -m 700 "$fixture"
  for member in "${STAGE_MEMBERS[@]}"; do : >"${fixture}/${member}"; done
  install -m 600 "$OPERATOR" "${fixture}/baseline-7ba-offline-release-operator.sh"
  install -m 600 "$VALIDATOR" "${fixture}/validate-image-fallback-offline-artifacts.py"
  candidate_commit=$(printf '6%.0s' {1..40})
  candidate_id="sha256:$(printf '1%.0s' {1..64})"
  candidate_tag="edu-ai-lead-agent-backend:image-fallback-${candidate_commit:0:12}"
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
    'production_dependency_delta=none' 'pyproject_delta=none' \
    'compose_openapi_alembic_delta=none' 'supported_mcp_imports=0' \
    'candidate_mcp_distribution=absent' \
    "source_file_count=${EXPECTED_SOURCE_FILE_COUNT}" \
    "image_source_file_count=${EXPECTED_IMAGE_SOURCE_FILE_COUNT}" \
    "alembic_head=${EXPECTED_ALEMBIC_HEAD}" \
    'runtime_probe=non-root,read-only,network-none,cap-drop-all,no-new-privileges' \
    'runtime_config=.7/v4,ocr=true,diversity=true' \
    'runtime_diff=3-reviewed-blobs' \
    'production_workbench=absent' \
    'rootfs_dependency_base_prefix=exact' \
    >"${fixture}/image-validation.txt"
  chmod 600 "${fixture}"/*
  (
    cd "$fixture"
    sha256sum source.tar.gz >source.tar.gz.sha256
    sha256sum backend-image.tar.gz >backend-image.tar.gz.sha256
    sha256sum backend-image.tar.gz backend-image.tar.gz.sha256 \
      baseline-7ba-offline-release-operator.sh image-source-files.sha256 \
      image-validation.txt source-files.sha256 source.tar.gz \
      source.tar.gz.sha256 validate-image-fallback-offline-artifacts.py \
      >artifacts.sha256
  )
  chmod 600 "${fixture}"/*
  stage_dir=$fixture
  source_sha256=$(sha256sum "${fixture}/source.tar.gz" | awk '{print $1}')
  source_manifest_sha256=$(sha256sum "${fixture}/source-files.sha256" | awk '{print $1}')
  image_bundle_sha256=$(sha256sum "${fixture}/backend-image.tar.gz" | awk '{print $1}')
  image_source_manifest_sha256=$(sha256sum "${fixture}/image-source-files.sha256" | awk '{print $1}')
  operator_sha256=$(sha256sum "${fixture}/baseline-7ba-offline-release-operator.sh" | awk '{print $1}')
  validator_sha256=$(sha256sum "${fixture}/validate-image-fallback-offline-artifacts.py" | awk '{print $1}')
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
  image_tag=edu-ai-lead-agent-backend:image-fallback-1234567
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
  require_text "$OPERATOR" 'export LC_ALL=C'
  require_text "$OPERATOR" 'export PATH="$SAFE_PATH"'
  require_text "$OPERATOR" 'PREVIOUS_COMMIT="7ba25d3eeb290d3f784ae449a5b6ad360a8def58"'
  require_text "$OPERATOR" 'PREVIOUS_IMAGE_ID="sha256:7627186cf1650a63bbe2e5e136e2364970a9383f756a62ed7db8c6e5cb50b21c"'
  require_text "$OPERATOR" 'CANDIDATE_COMMIT="cbc27b2491e4ebd49e6cc58692b065268e2887db"'
  require_text "$OPERATOR" 'EXPECTED_RUNTIME_LOCK_SHA256="3be154ff0e7f741b9f74d516baf739a4a38571218670b47dd1031f9dc1b44915"'
  require_text "$OPERATOR" 'EXPECTED_DOCKERFILE_SHA256="d4c2823d9354a7a5c31c2885317cd46b5c764d6afb964306c4204f7ed063fd1f"'
  require_text "$OPERATOR" 'EXPECTED_SOURCE_FILE_COUNT=321'
  require_text "$OPERATOR" 'EXPECTED_IMAGE_SOURCE_FILE_COUNT=179'
  require_text "$OPERATOR" "--format '{{.Os}}/{{.Architecture}}'"
  require_text "$OPERATOR" '--entrypoint alembic backend-migrate -c alembic.ini upgrade head'
  require_text "$OPERATOR" 'compose_call up -d --no-build --no-deps --force-recreate "$service"'
  require_text "$OPERATOR" 'INCIDENT: protected or stable-zero vector drifted; all application services remain stopped'
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
  require_text "$OPERATOR" 'root_nonexec_count" == 306 && "$root_exec_count" == 12 && "$app_metadata_count" == 3'
  require_text "$OPERATOR" 'assert_safe_window() {'
  reject_text "$OPERATOR" 'assert_startup_projection_zero'
  require_text "$OPERATOR" 'rollback-tag-inventory.txt'
  require_text "$OPERATOR" 'assert_rollback_tags'
  require_text "$OPERATOR" 'remove_stale_migration_container'
  reject_text "$OPERATOR" 'a backend migration container already exists'
  require_text "$OPERATOR" 'write_minio_inventory "$minio_id" "${backup_dir}/minio.sha256"'
  require_text "$OPERATOR" 'write_minio_inventory "$minio_id" "${runtime_evidence_dir}/minio.sha256"'
  require_text "$OPERATOR" 'unlink -- "$destination_evidence_file"'
  reject_text "$OPERATOR" 'cd /data && find'
  reject_text "$OPERATOR" 'CONTENT_SCORING_VERSION=scoring-v1-preview.6'
  require_text "$OPERATOR" "--env 'IMAGE_ENABLED=true'"
  require_text "$OPERATOR" "--env 'IMAGE_PROVIDER_MODE=fake'"
  require_text "$OPERATOR" "--env 'IMAGE_OCR_ENABLED=true'"
  require_text "$OPERATOR" "--env 'IMAGE_DIVERSITY_ENABLED=true'"
  require_text "$OPERATOR" 's.image_enabled is True and s.image_provider_mode=="fake" and s.image_ocr_enabled is True and s.image_diversity_enabled is True'
  reject_text "$OPERATOR" 'compose_call up --no-build backend-migrate'
  reject_text "$OPERATOR" 'python -m app.seed_sources'
  reject_text "$OPERATOR" 'make release-prod'
}

assert_candidate_settings_probe_arguments() (
  local calls="${test_root}/candidate-settings-probe.args"
  local -a actual expected_prefix
  expected_source_vector=10:38:10
  expected_durable_vector=40:40
  expected_provider_vector=30:30
  candidate_id=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
  : >"$calls"
  source_vector() { printf '%s\n' "$expected_source_vector"; }
  durable_vector() { printf '%s\n' "$expected_durable_vector"; }
  provider_vector() { printf '%s\n' "$expected_provider_vector"; }
  zero_work_vector() { printf '0:0:0:0:0:0:0\n'; }
  legacy_prompt_vector() { printf '0:0:0\n'; }
  remove_stale_migration_container() { :; }
  compose_call() {
    case "${1-}" in
      run) return 0 ;;
      ps) return 0 ;;
      *) fail "unexpected compose call in candidate settings probe: ${1-}" ;;
    esac
  }
  sql_scalar() {
    [[ "$1" == 'SELECT version_num FROM alembic_version' ]] \
      || fail "unexpected SQL in candidate settings probe"
    printf '%s\n' "$EXPECTED_ALEMBIC_HEAD"
  }
  docker_call() { printf '%s\n' "$@" >"$calls"; }

  phase_migrate_and_probe
  mapfile -t actual <"$calls"
  expected_prefix=(
    run --rm --network none --read-only --cap-drop ALL
    --security-opt no-new-privileges:true
    --env "CONTENT_SCORING_VERSION=${SCORING_ACTIVE}"
    --env IMAGE_ENABLED=true
    --env IMAGE_PROVIDER_MODE=fake
    --env IMAGE_OCR_ENABLED=true
    --env IMAGE_DIVERSITY_ENABLED=true
    --entrypoint python "$candidate_id" -c
  )
  ((${#actual[@]} == ${#expected_prefix[@]} + 1)) \
    || fail "candidate settings probe argument count drifted"
  for index in "${!expected_prefix[@]}"; do
    [[ "${actual[$index]}" == "${expected_prefix[$index]}" ]] \
      || fail "candidate settings probe argument order drifted at $index"
  done
  [[ "${actual[-1]}" == *'s.image_enabled is True'* \
      && "${actual[-1]}" == *'s.image_provider_mode=="fake"'* \
      && "${actual[-1]}" == *'s.image_ocr_enabled is True'* \
      && "${actual[-1]}" == *'s.image_diversity_enabled is True'* ]] \
    || fail "candidate settings assertion drifted"
)

assert_previous_source_metadata_contract() (
  local app_uid=4242 app_gid=4343
  [[ "$(previous_source_metadata_class 0644 600 0 0 backend/app/api_main.py "$app_uid" "$app_gid")" == root-nonexec ]]
  [[ "$(previous_source_metadata_class 0755 700 0 0 scripts/release-prod.sh "$app_uid" "$app_gid")" == root-exec ]]
  [[ "$(previous_source_metadata_class 0644 664 "$app_uid" "$app_gid" .gitattributes "$app_uid" "$app_gid")" == app-metadata ]]
  [[ "$(previous_source_metadata_class 0644 664 "$app_uid" "$app_gid" .gitignore "$app_uid" "$app_gid")" == app-metadata ]]
  [[ "$(previous_source_metadata_class 0644 664 "$app_uid" "$app_gid" AGENTS.md "$app_uid" "$app_gid")" == app-metadata ]]
  assert_previous_source_metadata_distribution 306 12 3
  if previous_source_metadata_class 0644 664 "$app_uid" "$app_gid" backend/app/api_main.py "$app_uid" "$app_gid" >/dev/null 2>&1; then
    fail "group-writable application source was accepted"
  fi
  if previous_source_metadata_class 0644 644 0 0 README.md "$app_uid" "$app_gid" >/dev/null 2>&1; then
    fail "unreviewed root-owned source mode was accepted"
  fi
  if previous_source_metadata_class 0644 644 "$app_uid" "$app_gid" .gitattributes "$app_uid" "$app_gid" >/dev/null 2>&1; then
    fail "app-owned metadata mode drift was accepted"
  fi
  if previous_source_metadata_class 0644 664 9999 "$app_gid" .gitattributes "$app_uid" "$app_gid" >/dev/null 2>&1; then
    fail "app-owned metadata uid drift was accepted"
  fi
  if previous_source_metadata_class 0644 664 "$app_uid" 9999 .gitignore "$app_uid" "$app_gid" >/dev/null 2>&1; then
    fail "app-owned metadata group drift was accepted"
  fi
  if assert_previous_source_metadata_distribution 305 13 3 >/dev/null 2>&1; then
    fail "root source class distribution drift was accepted"
  fi
  if assert_previous_source_metadata_distribution 306 11 4 >/dev/null 2>&1; then
    fail "app metadata distribution drift was accepted"
  fi
)

assert_exact_source_diff_contract() {
  local fixture="${test_root}/source-diff" previous candidate changed path
  mkdir -m 700 "$fixture"
  previous="${fixture}/previous.sha256"
  candidate="${fixture}/candidate.sha256"
  changed="${fixture}/changed"
  : >"$previous"
  : >"$candidate"
  for path in "${EXPECTED_SOURCE_DIFF[@]}"; do
    printf '%064d  %s\n' 0 "$path" >>"$previous"
    printf '%064d  %s\n' 1 "$path" >>"$candidate"
  done
  printf '%064d  compose.yaml\n' 0 >>"$previous"
  printf '%064d  compose.yaml\n' 0 >>"$candidate"
  assert_exact_source_diff "$previous" "$candidate" "$changed"
  sed -i 's/^0\{64\}  compose.yaml$/2  compose.yaml/' "$candidate"
  if assert_exact_source_diff "$previous" "$candidate" "$changed" >/dev/null 2>&1; then
    fail "unexpected eighth source delta was accepted"
  fi
}

bash -n "$OPERATOR" "$0"
python3 -m py_compile "$VALIDATOR"
assert_static_contract
assert_candidate_settings_probe_arguments
assert_previous_source_metadata_contract
assert_exact_source_diff_contract
assert_artifact_validator
assert_fake_recovery
assert_trusted_storage_contracts
assert_source_install_contracts
assert_safe_window_contract
assert_recovery_deadline_independence
assert_observed_startup_gate
assert_immutable_rollback_tag_contract
assert_candidate_provenance_contract
assert_minio_inventory_contract
assert_stale_migration_cleanup_contract
assert_stage_shape
printf 'PASS: 7ba offline operator static, artifact, trusted-root, install/rollback, and fail-closed recovery checks\n'
