#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
readonly ORCHESTRATOR="$SCRIPT_DIR/controlled-ocr-fixture-container.sh"
readonly TEMP_ROOT=$(mktemp -d -t controlled-ocr-container-test.XXXXXX)

CURRENT_CASE='setup'
FAKE_ACTION_LOG=''

emit_redacted_file_diagnostic() {
  local label=$1 path=$2 digest bytes
  [[ -f $path && ! -L $path ]] || return 0
  digest=$(sha256sum -- "$path") || digest='unavailable'
  digest=${digest%% *}
  bytes=$(stat -Lc '%s' -- "$path") || bytes='unavailable'
  printf 'test_failure_file label=%s bytes=%s sha256=%s\n' "$label" "$bytes" "$digest" >&2
}

emit_failure_diagnostics() {
  local status=$1 actions='unavailable'
  if [[ -f ${FAKE_ACTION_LOG:-} && ! -L ${FAKE_ACTION_LOG:-} ]]; then
    actions=$(<"$FAKE_ACTION_LOG")
    [[ $actions =~ ^([a-z-]+,)*$ ]] || actions='redacted'
  fi
  printf 'test_failed case=%s status=%s actions=%s\n' "$CURRENT_CASE" "$status" "$actions" >&2
  emit_redacted_file_diagnostic final_stdout "$TEMP_ROOT/$CURRENT_CASE/final.stdout"
  emit_redacted_file_diagnostic final_stderr "$TEMP_ROOT/$CURRENT_CASE/final.stderr"
}

cleanup_test_root() {
  local status=$?
  trap - EXIT
  set +e
  if ((status != 0)); then
    emit_failure_diagnostics "$status"
  fi
  rm -rf -- "$TEMP_ROOT"
  exit "$status"
}

trap cleanup_test_root EXIT

export CONTROLLED_OCR_ORCHESTRATOR_SOURCE_ONLY=1
# shellcheck source=controlled-ocr-fixture-container.sh
source "$ORCHESTRATOR"

FAKE_MODE='pass'
FAKE_EVIDENCE_DIR=''

assert_exact_argv() {
  local -n expected_ref=$1
  shift
  local -a actual=("$@")
  ((${#actual[@]} == ${#expected_ref[@]})) || return 90
  local index
  for index in "${!expected_ref[@]}"; do
    [[ ${actual[index]} == "${expected_ref[index]}" ]] || return 90
  done
}

read_fake_container_name() {
  local name_path="$FAKE_EVIDENCE_DIR/container-name"
  [[ -f $name_path && ! -L $name_path ]] || return 90
  REPLY=$(<"$name_path")
  [[ $REPLY =~ ^controlled-ocr-fixture-[0-9]{8}T[0-9]{6}Z-[0-9]+$ ]] || return 90
}

docker_call() {
  (($# >= 1)) || return 90
  local action=$1
  shift
  printf '%s,' "$action" >>"$FAKE_ACTION_LOG"
  local -a expected=()
  local container_name
  case $action in
    create)
      (($# == 27)) || return 90
      container_name=${2-}
      [[ $container_name =~ ^controlled-ocr-fixture-[0-9]{8}T[0-9]{6}Z-[0-9]+$ ]] || return 90
      local case_root=${FAKE_EVIDENCE_DIR%/evidence}
      [[ $case_root/evidence == "$FAKE_EVIDENCE_DIR" ]] || return 90
      expected=(
        --name "$container_name"
        --network none
        --read-only
        --cap-drop ALL
        --security-opt no-new-privileges:true
        --env-file "$case_root/environment"
        --mount "type=bind,src=$case_root/runner.py,dst=/controlled-ocr-fixture-runner.py,readonly"
        --mount "type=bind,src=$case_root/controlled-ocr-fixture-case.png,dst=/controlled-ocr-fixture.png,readonly"
        --entrypoint python
        sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
        /controlled-ocr-fixture-runner.py
        --fixture /controlled-ocr-fixture.png
        --expected-line '赛先生科学'
        --expected-line '人工智能'
        --expected-line '理解智能如何学习与反馈'
      )
      assert_exact_argv expected "$@" || return 90
      [[ ! -e $FAKE_EVIDENCE_DIR/container-name ]] || return 90
      printf '%s\n' "$container_name" >"$FAKE_EVIDENCE_DIR/container-name" || return 90
      printf '%064d\n' 1
      ;;
    start)
      read_fake_container_name || return 90
      expected=("$REPLY")
      assert_exact_argv expected "$@" || return 90
      ;;
    wait)
      read_fake_container_name || return 90
      expected=("$REPLY")
      assert_exact_argv expected "$@" || return 90
      if [[ $FAKE_MODE == runner-fail ]]; then printf '1\n'; else printf '0\n'; fi
      ;;
    inspect)
      read_fake_container_name || return 90
      container_name=$REPLY
      (($# == 3)) || return 90
      expected=(--format "${2-}" "$container_name")
      assert_exact_argv expected "$@" || return 90
      case ${2-} in
        '{{.State.ExitCode}}')
          if [[ $FAKE_MODE == runner-fail ]]; then printf '1\n'; else printf '0\n'; fi
          ;;
        '{{.State.Status}}') printf 'exited\n' ;;
        '{{.State.OOMKilled}}') printf 'false\n' ;;
        *) return 91 ;;
      esac
      ;;
    logs)
      read_fake_container_name || return 90
      expected=("$REPLY")
      assert_exact_argv expected "$@" || return 90
      if [[ $FAKE_MODE == malformed ]]; then
        printf '%s\n%s\n' '{}' '{}'
      elif [[ $FAKE_MODE == runner-fail ]]; then
        printf '%s\n' '{"schema_version":1,"stage":"response_returned","http_attempts":1,"outcome":"fail","typed_error_code":"invalid_provider_output","issue_codes":["image_ocr_contract_label_unknown"],"exact_ordered":false,"accepted_line_count":0}'
      else
        printf '%s\n' '{"schema_version":1,"stage":"terminal","http_attempts":1,"outcome":"pass","typed_error_code":"","issue_codes":[],"exact_ordered":true,"accepted_line_count":3}'
      fi
      printf '%s' 'private-stderr-sentinel' >&2
      ;;
    rm)
      read_fake_container_name || return 90
      expected=("$REPLY")
      assert_exact_argv expected "$@" || return 90
      [[ -s $FAKE_EVIDENCE_DIR/container-evidence.json ]] || return 90
      ;;
    *) return 92 ;;
  esac
}

CURRENT_CASE='diagnostic-probe'
diagnostic_root="$TEMP_ROOT/$CURRENT_CASE"
mkdir -m 0700 "$diagnostic_root"
FAKE_ACTION_LOG="$diagnostic_root/actions"
printf '%s' 'create,' >"$FAKE_ACTION_LOG"
printf '%s' 'safe-stdout' >"$diagnostic_root/final.stdout"
printf '%s' 'private-stderr-sentinel' >"$diagnostic_root/final.stderr"
emit_failure_diagnostics 97 2>"$diagnostic_root/reported"
grep -F 'test_failed case=diagnostic-probe status=97 actions=create,' "$diagnostic_root/reported" >/dev/null
[[ $(grep -c -F 'test_failure_file label=' "$diagnostic_root/reported") == 2 ]]
! grep -F 'private-stderr-sentinel' "$diagnostic_root/reported" >/dev/null

CURRENT_CASE='argv-probe'
expected_probe=(--name fixed --network none)
assert_exact_argv expected_probe --name fixed --network none
if assert_exact_argv expected_probe --name fixed --network; then
  exit 93
fi
if assert_exact_argv expected_probe --network none --name fixed; then
  exit 94
fi

prepare_case() {
  local root=$1
  mkdir -m 0700 "$root" "$root/evidence"
  printf '%s\n' 'AI_PROVIDER_MODE=zhipu' >"$root/environment"
  printf '%s\n' 'runner' >"$root/runner.py"
  printf '%s\n' 'png' >"$root/controlled-ocr-fixture-case.png"
  chmod 0600 "$root/environment" "$root/runner.py" "$root/controlled-ocr-fixture-case.png"
}

invoke_case() {
  local root=$1
  main \
    --image 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' \
    --env-file "$root/environment" \
    --fixture "$root/controlled-ocr-fixture-case.png" \
    --evidence-dir "$root/evidence" \
    --runner "$root/runner.py" \
    --expected-line '赛先生科学' \
    --expected-line '人工智能' \
    --expected-line '理解智能如何学习与反馈'
}

CURRENT_CASE='pass'
pass_root="$TEMP_ROOT/$CURRENT_CASE"
prepare_case "$pass_root"
FAKE_MODE=pass
FAKE_EVIDENCE_DIR="$pass_root/evidence"
FAKE_ACTION_LOG="$pass_root/actions"
: >"$FAKE_ACTION_LOG"
set +e
invoke_case "$pass_root" >"$pass_root/final.stdout" 2>"$pass_root/final.stderr"
pass_status=$?
set -e
[[ $pass_status == 0 ]]
[[ $(cat "$FAKE_ACTION_LOG") == create,start,wait,inspect,inspect,inspect,logs,rm, ]]
[[ ! -e $pass_root/controlled-ocr-fixture-case.png ]]
[[ -s $pass_root/evidence/container-evidence.json ]]
[[ -s $pass_root/evidence/cleanup-evidence.json ]]
[[ $(stat -Lc '%a' "$pass_root/evidence/runner.stderr") == 600 ]]
[[ $(cat "$pass_root/evidence/runner.stderr") == private-stderr-sentinel ]]
! grep -R -F 'private-stderr-sentinel' "$pass_root/final.stdout" "$pass_root/evidence/container-evidence.json" "$pass_root/evidence/cleanup-evidence.json"
python3 - "$pass_root/final.stdout" "$pass_root/evidence/container-evidence.json" <<'PY'
import json
import sys
from pathlib import Path
summary = json.loads(Path(sys.argv[1]).read_text(encoding="ascii"))
evidence = json.loads(Path(sys.argv[2]).read_text(encoding="ascii"))
assert summary["runner_report"]["outcome"] == "pass"
assert summary["stderr_bytes"] == len(b"private-stderr-sentinel")
assert evidence["container_exit_code"] == evidence["wait_exit_code"] == 0
assert evidence["runner_report"]["http_attempts"] == 1
PY

CURRENT_CASE='runner-fail'
fail_root="$TEMP_ROOT/$CURRENT_CASE"
prepare_case "$fail_root"
FAKE_MODE=runner-fail
FAKE_EVIDENCE_DIR="$fail_root/evidence"
FAKE_ACTION_LOG="$fail_root/actions"
: >"$FAKE_ACTION_LOG"
set +e
invoke_case "$fail_root" >"$fail_root/final.stdout" 2>"$fail_root/final.stderr"
fail_status=$?
set -e
[[ $fail_status == 1 ]]
[[ $(cat "$FAKE_ACTION_LOG") == create,start,wait,inspect,inspect,inspect,logs,rm, ]]
[[ ! -e $fail_root/controlled-ocr-fixture-case.png ]]
python3 - "$fail_root/evidence/container-evidence.json" <<'PY'
import json
import sys
from pathlib import Path
evidence = json.loads(Path(sys.argv[1]).read_text(encoding="ascii"))
assert evidence["container_exit_code"] == evidence["wait_exit_code"] == 1
assert evidence["runner_report"]["outcome"] == "fail"
assert evidence["runner_report"]["http_attempts"] == 1
PY

CURRENT_CASE='malformed'
malformed_root="$TEMP_ROOT/$CURRENT_CASE"
prepare_case "$malformed_root"
FAKE_MODE=malformed
FAKE_EVIDENCE_DIR="$malformed_root/evidence"
FAKE_ACTION_LOG="$malformed_root/actions"
: >"$FAKE_ACTION_LOG"
set +e
invoke_case "$malformed_root" >"$malformed_root/final.stdout" 2>"$malformed_root/final.stderr"
malformed_status=$?
set -e
[[ $malformed_status != 0 ]]
[[ $(cat "$FAKE_ACTION_LOG") == create,start,wait,inspect,inspect,inspect,logs, ]]
[[ -e $malformed_root/controlled-ocr-fixture-case.png ]]
[[ ! -e $malformed_root/evidence/container-evidence.json ]]
[[ $(cat "$malformed_root/evidence/runner.stderr") == private-stderr-sentinel ]]

CURRENT_CASE='missing'
missing_root="$TEMP_ROOT/$CURRENT_CASE"
prepare_case "$missing_root"
rm -f -- "$missing_root/controlled-ocr-fixture-case.png"
FAKE_MODE=pass
FAKE_EVIDENCE_DIR="$missing_root/evidence"
FAKE_ACTION_LOG="$missing_root/actions"
: >"$FAKE_ACTION_LOG"
set +e
invoke_case "$missing_root" >"$missing_root/final.stdout" 2>"$missing_root/final.stderr"
missing_status=$?
set -e
[[ $missing_status != 0 && ! -s $FAKE_ACTION_LOG ]]

printf '%s\n' 'test_passed cases=exact-argc-order,redacted-failure-diagnostics,named-no-rm,network-none,pass-evidence,typed-fail-evidence,stderr-hash-only,cleanup-after-evidence,malformed-retained,preflight-no-docker'
