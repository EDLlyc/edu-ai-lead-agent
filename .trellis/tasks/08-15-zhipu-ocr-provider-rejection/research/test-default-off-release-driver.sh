#!/usr/bin/env bash
# Local-only static and failure-injection checks for default-off-release-driver.sh.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

readonly TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly DRIVER="${TEST_DIR}/default-off-release-driver.sh"
test_root=$(mktemp -d /tmp/edu-ai-release-driver-test.XXXXXX)
trap 'rm -rf -- "$test_root"' EXIT

fail() {
  printf 'test_failed reason=%s\n' "$1" >&2
  exit 1
}

require_text() {
  local pattern=$1
  LC_ALL=C grep -Eq -- "$pattern" "$DRIVER" || fail "missing_static_gate_${pattern}"
}

reject_text() {
  local pattern=$1
  if LC_ALL=C grep -Eq -- "$pattern" "$DRIVER"; then
    fail "forbidden_static_action_${pattern}"
  fi
}

bash -n "$DRIVER"
[[ "$(stat -c '%a' "$DRIVER")" == "600" ]] || fail driver_mode
[[ "$(grep -Ec '^[[:space:]]*env -i .* /usr/bin/docker compose' "$DRIVER")" == "1" ]] || fail compose_wrapper_count
[[ "$(grep -Ec '^[[:space:]]*docker (compose|run|exec|image|inspect|start|stop|container)' "$DRIVER")" == "0" ]] || fail direct_docker_escape
require_text 'readonly APP_DIR="/opt/edu-ai-lead-agent"'
require_text 'readonly COMPOSE_PROJECT="edu-ai-lead-agent"'
require_text 'readonly COMPOSE_FILE="\$\{APP_DIR\}/compose.yaml"'
require_text '--project-directory "\$APP_DIR"'
require_text '--env-file "\$PRIMARY_ENV"'
require_text '--env-file "\$RELEASE_ENV"'
require_text 'env -i PATH="\$SAFE_PATH" HOME=/root /usr/bin/docker'
require_text 'exec \{lock_fd\}>"\$BACKUP_LOCK"'
require_text 'flock --nonblock "\$lock_fd"'
require_text 'backup_ready=0'
require_text 'tags_changed=0'
require_text 'overlay_changed=0'
require_text 'completed=0'
require_text 'trap on_err ERR'
require_text 'trap on_exit EXIT'
require_text "trap 'on_signal HUP 129' HUP"
require_text "trap 'on_signal INT 130' INT"
require_text "trap 'on_signal TERM 143' TERM"
require_text 'from app.api_main import app as api_app'
require_text 'docker_call exec -i "\$postgres_id"'
require_text 'assert_safe_window'
require_text 'assert_exact_vectors'
require_text 'assert_safe_logs'
require_text 'expected_current_day_vector'
require_text 'candidate and previous source path sets differ'
require_text 'image bundle tag membership mismatch'
require_text 'tags_changed=1'
require_text 'source_path="\$\{release_extract_dir\}/\$\{path\}"'
require_text 'recreate_service wecom-dispatcher'
reject_text '(^|[[:space:]])ssh([[:space:]]|$)'
reject_text 'docker[[:space:]]+build'
reject_text 'compose_call[[:space:]]+build'
reject_text 'IMAGE_(DIVERSITY|OCR)_ENABLED=true'
reject_text '(^|[[:space:]])(curl|wget)([[:space:]]|$)'
reject_text 'scripts/edu-ai-backup\.sh'
reject_text 'runuser'
reject_text 'source\.tar\.gz" -C "\$APP_DIR"'

run_failure_case() {
  local name=$1
  local backup=$2
  local tags=$3
  local overlay=$4
  local expected=$5
  local action_log="${test_root}/${name}.actions"
  local rc

  set +e
  ACTION_LOG="$action_log" BACKUP_VALUE="$backup" TAGS_VALUE="$tags" \
    OVERLAY_VALUE="$overlay" RELEASE_DRIVER_SOURCE_ONLY=1 \
    bash -c '
      source "$1"
      log() { :; }
      cleanup_local_artifacts() { :; }
      enter_app_dir() { :; }
      restore_overlay_for_recovery() { printf "overlay\n" >>"$ACTION_LOG"; }
      restore_tags_for_recovery() { printf "tags\n" >>"$ACTION_LOG"; }
      restore_services_for_recovery() { printf "services\n" >>"$ACTION_LOG"; }
      backup_ready=$BACKUP_VALUE
      tags_changed=$TAGS_VALUE
      overlay_changed=$OVERLAY_VALUE
      services_quiesced=1
      completed=0
      recovery_running=0
      install_traps
      false
    ' bash "$DRIVER" >/dev/null 2>&1
  rc=$?
  set -e
  [[ "$rc" == "1" ]] || fail "${name}_exit_${rc}"
  [[ "$(<"$action_log")" == "$expected" ]] || fail "${name}_actions"
}

# Early: the first stop happened but no backup exists. Recovery must not read it.
run_failure_case early 0 0 0 'services'
# Mid: the backup is complete and active tags changed, but no host overlay began.
run_failure_case mid 1 1 0 $'tags\nservices'
# Late: code/markers and tags both changed; restore overlay, tags, then services.
run_failure_case late 1 1 1 $'overlay\ntags\nservices'

signal_log="${test_root}/term.actions"
set +e
ACTION_LOG="$signal_log" RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  log() { :; }
  cleanup_local_artifacts() { :; }
  enter_app_dir() { :; }
  restore_services_for_recovery() { printf "services\n" >>"$ACTION_LOG"; }
  services_quiesced=1
  completed=0
  install_traps
  kill -TERM "$BASHPID"
' bash "$DRIVER" >/dev/null 2>&1
signal_rc=$?
set -e
[[ "$signal_rc" == "143" ]] || fail "term_exit_${signal_rc}"
[[ "$(<"$signal_log")" == "services" ]] || fail term_recovery_actions

incomplete_log="${test_root}/incomplete.actions"
set +e
ACTION_LOG="$incomplete_log" RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  log() { :; }
  cleanup_local_artifacts() { :; }
  enter_app_dir() { :; }
  restore_tags_for_recovery() { printf "tags\n" >>"$ACTION_LOG"; return 9; }
  restore_services_for_recovery() { printf "services\n" >>"$ACTION_LOG"; }
  backup_ready=1
  tags_changed=1
  services_quiesced=1
  completed=0
  install_traps
  false
' bash "$DRIVER" >/dev/null 2>&1
incomplete_rc=$?
set -e
[[ "$incomplete_rc" == "125" ]] || fail "incomplete_recovery_exit_${incomplete_rc}"
[[ "$(<"$incomplete_log")" == 'tags' ]] || fail incomplete_recovery_actions

for signal_case in HUP:129 INT:130; do
  signal_name=${signal_case%%:*}
  expected_rc=${signal_case##*:}
  signal_log="${test_root}/${signal_name}.actions"
  set +e
  ACTION_LOG="$signal_log" SIGNAL_NAME="$signal_name" RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
    source "$1"
    log() { :; }
    cleanup_local_artifacts() { :; }
    enter_app_dir() { :; }
    restore_services_for_recovery() { printf "services\n" >>"$ACTION_LOG"; }
    services_quiesced=1
    completed=0
    install_traps
    kill -s "$SIGNAL_NAME" "$BASHPID"
  ' bash "$DRIVER" >/dev/null 2>&1
  signal_rc=$?
  set -e
  [[ "$signal_rc" == "$expected_rc" ]] || fail "${signal_name}_exit_${signal_rc}"
  [[ "$(<"$signal_log")" == "services" ]] || fail "${signal_name}_recovery_actions"
done

explicit_exit_log="${test_root}/explicit-exit.actions"
set +e
ACTION_LOG="$explicit_exit_log" RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  log() { :; }
  cleanup_local_artifacts() { :; }
  enter_app_dir() { :; }
  restore_services_for_recovery() { printf "services\n" >>"$ACTION_LOG"; }
  services_quiesced=1
  install_traps
  exit 23
' bash "$DRIVER" >/dev/null 2>&1
explicit_exit_rc=$?
set -e
[[ "$explicit_exit_rc" == "23" ]] || fail "explicit_exit_${explicit_exit_rc}"
[[ "$(<"$explicit_exit_log")" == "services" ]] || fail explicit_exit_recovery

layer_failure_log="${test_root}/layer-failure.actions"
set +e
ACTION_LOG="$layer_failure_log" RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  log() { :; }
  cleanup_local_artifacts() { :; }
  enter_app_dir() { :; }
  restore_overlay_for_recovery() { printf "overlay\n" >>"$ACTION_LOG"; return 9; }
  restore_tags_for_recovery() { printf "tags\n" >>"$ACTION_LOG"; }
  restore_services_for_recovery() { printf "services\n" >>"$ACTION_LOG"; }
  backup_ready=1
  overlay_changed=1
  tags_changed=1
  services_quiesced=1
  install_traps
  false
' bash "$DRIVER" >/dev/null 2>&1
layer_failure_rc=$?
set -e
[[ "$layer_failure_rc" == "125" ]] || fail "layer_failure_exit_${layer_failure_rc}"
[[ "$(<"$layer_failure_log")" == $'overlay\ntags' ]] || fail layer_failure_started_services

lock_log="${test_root}/lock.actions"
lock_file="${test_root}/backup.lock"
set +e
ACTION_LOG="$lock_log" LOCK_FILE="$lock_file" RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  log() { :; }
  cleanup_local_artifacts() { :; }
  enter_app_dir() { :; }
  restore_services_for_recovery() {
    if flock --nonblock "$LOCK_FILE" -c true; then
      printf "unlocked\n" >>"$ACTION_LOG"
      return 1
    fi
    printf "locked\n" >>"$ACTION_LOG"
  }
  exec {held_fd}>"$LOCK_FILE"
  flock --nonblock "$held_fd"
  services_quiesced=1
  install_traps
  false
' bash "$DRIVER" >/dev/null 2>&1
lock_rc=$?
set -e
[[ "$lock_rc" == "1" ]] || fail "lock_exit_${lock_rc}"
[[ "$(<"$lock_log")" == "locked" ]] || fail lock_not_held_during_recovery

bundle_root="${test_root}/bundle"
mkdir -m 700 "$bundle_root"
config_digest=$(printf 'a%.0s' {1..64})
printf '{}\n' >"${bundle_root}/${config_digest}.json"
printf '[{"Config":"%s.json","RepoTags":["edu-ai-lead-agent-backend:candidate"],"Layers":[]}]\n' "$config_digest" >"${bundle_root}/manifest.json"
tar -czf "${test_root}/backend-image.tar.gz" -C "$bundle_root" "${config_digest}.json" manifest.json
RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  stage_dir=$2
  candidate_tag=edu-ai-lead-agent-backend:candidate
  candidate_id="sha256:$3"
  previous_image_id="sha256:$(printf b%.0s {1..64})"
  tags_changed=0
  docker_call() { [[ "$1:$2:$tags_changed" == "image:load:1" ]]; }
  assert_active_tags() { :; }
  assert_candidate_image() { :; }
  load_candidate_bundle
  [[ "$tags_changed" == 1 ]]
' bash "$DRIVER" "$test_root" "$config_digest" >/dev/null 2>&1 || fail bundle_phase_arming

unsafe_manifest="${test_root}/unsafe-source.sha256"
printf '%064d  ../escape.py\n' 0 >"$unsafe_manifest"
if RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  validate_source_manifest "$2" "$3" 1
' bash "$DRIVER" "$unsafe_manifest" "${test_root}/unsafe.paths" >/dev/null 2>&1; then
  fail unsafe_source_manifest_accepted
fi

printf 'test_passed cases=static,early,mid,late,hup,int,term,explicit-exit,incomplete-recovery,layer-failure,lock-lifetime,bundle-phase,unsafe-manifest\n'
