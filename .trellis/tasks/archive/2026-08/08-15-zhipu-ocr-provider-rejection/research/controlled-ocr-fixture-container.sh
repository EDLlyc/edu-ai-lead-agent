#!/usr/bin/env bash
# Evidence-preserving wrapper for one explicitly authorized OCR fixture attempt.
# This file does not authorize a call; it only makes a separately authorized
# invocation observable and fail closed.

set -Eeuo pipefail
umask 077

readonly SCHEMA_VERSION=1
readonly RUNNER_CONTAINER_PATH=/controlled-ocr-fixture-runner.py
readonly FIXTURE_CONTAINER_PATH=/controlled-ocr-fixture.png

safe_die() {
  printf '%s\n' '{"schema_version":1,"outcome":"fail","typed_error_code":"orchestrator_preflight_failed"}' >&2
  return 2
}

require_absolute_regular_0600() {
  local path=$1
  local metadata
  [[ $path == /* && $path != / && ! -L $path && -f $path ]] || return 1
  metadata=$(stat -Lc '%a:%F' -- "$path") || return 1
  [[ $metadata == '600:regular file' ]]
}

require_absolute_directory_0700() {
  local path=$1
  local metadata real
  [[ $path == /* && $path != / && ! -L $path && -d $path ]] || return 1
  metadata=$(stat -Lc '%a:%F' -- "$path") || return 1
  real=$(realpath -e -- "$path") || return 1
  [[ $metadata == '700:directory' && $real == "$path" ]]
}

docker_call() {
  env -i PATH=/usr/bin:/bin HOME=/root /usr/bin/docker "$@" </dev/null
}

write_container_evidence() {
  local stdout_path=$1 stderr_path=$2 evidence_path=$3
  local wait_exit=$4 inspect_exit=$5 inspect_status=$6 inspect_oom=$7
  EVIDENCE_STDOUT=$stdout_path \
    EVIDENCE_STDERR=$stderr_path \
    EVIDENCE_PATH=$evidence_path \
    EVIDENCE_WAIT_EXIT=$wait_exit \
    EVIDENCE_INSPECT_EXIT=$inspect_exit \
    EVIDENCE_INSPECT_STATUS=$inspect_status \
    EVIDENCE_INSPECT_OOM=$inspect_oom \
    python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

stdout_path = Path(os.environ["EVIDENCE_STDOUT"])
stderr_path = Path(os.environ["EVIDENCE_STDERR"])
evidence_path = Path(os.environ["EVIDENCE_PATH"])
stdout = stdout_path.read_bytes()
stderr = stderr_path.read_bytes()
lines = stdout.splitlines()
if len(lines) != 1 or not stdout.endswith(b"\n") or len(stdout) > 4096:
    raise SystemExit(2)
try:
    report = json.loads(lines[0])
except (UnicodeDecodeError, json.JSONDecodeError):
    raise SystemExit(2)
expected_keys = [
    "schema_version",
    "stage",
    "http_attempts",
    "outcome",
    "typed_error_code",
    "issue_codes",
    "exact_ordered",
    "accepted_line_count",
]
if list(report) != expected_keys or report["schema_version"] != 1:
    raise SystemExit(2)
if report["stage"] not in {
    "adapter_construction", "before_request", "request_started",
    "response_returned", "validation", "terminal",
}:
    raise SystemExit(2)
if type(report["http_attempts"]) is not int or report["http_attempts"] not in {0, 1}:
    raise SystemExit(2)
if report["outcome"] not in {"pass", "fail"}:
    raise SystemExit(2)
if type(report["typed_error_code"]) is not str:
    raise SystemExit(2)
if (
    type(report["issue_codes"]) is not list
    or any(type(value) is not str for value in report["issue_codes"])
    or type(report["exact_ordered"]) is not bool
    or type(report["accepted_line_count"]) is not int
):
    raise SystemExit(2)
wait_exit = int(os.environ["EVIDENCE_WAIT_EXIT"])
inspect_exit = int(os.environ["EVIDENCE_INSPECT_EXIT"])
if wait_exit != inspect_exit:
    raise SystemExit(2)
passed = (
    report["outcome"] == "pass"
    and report["typed_error_code"] == ""
    and report["http_attempts"] == 1
    and report["exact_ordered"] is True
    and report["accepted_line_count"] == 3
    and wait_exit == 0
)
if (report["outcome"] == "pass") != passed:
    raise SystemExit(2)
if report["outcome"] == "fail" and wait_exit == 0:
    raise SystemExit(2)
if os.environ["EVIDENCE_INSPECT_STATUS"] != "exited":
    raise SystemExit(2)
if os.environ["EVIDENCE_INSPECT_OOM"] not in {"true", "false"}:
    raise SystemExit(2)
evidence = {
    "schema_version": 1,
    "runner_report": report,
    "container_exit_code": inspect_exit,
    "wait_exit_code": wait_exit,
    "container_status": "exited",
    "oom_killed": os.environ["EVIDENCE_INSPECT_OOM"] == "true",
    "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
    "stdout_bytes": len(stdout),
    "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
    "stderr_bytes": len(stderr),
}
payload = json.dumps(evidence, ensure_ascii=True, separators=(",", ":")) + "\n"
descriptor = os.open(evidence_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="ascii") as stream:
    stream.write(payload)
    stream.flush()
    os.fsync(stream.fileno())
PY
}

write_cleanup_evidence() {
  local evidence_path=$1 cleanup_path=$2
  CLEANUP_CONTAINER_EVIDENCE=$evidence_path CLEANUP_EVIDENCE=$cleanup_path python3 - <<'PY'
import json
import os
from pathlib import Path

container_path = Path(os.environ["CLEANUP_CONTAINER_EVIDENCE"])
cleanup_path = Path(os.environ["CLEANUP_EVIDENCE"])
container = json.loads(container_path.read_text(encoding="ascii"))
payload = {
    "schema_version": 1,
    "container_evidence_sha256": __import__("hashlib").sha256(
        container_path.read_bytes()
    ).hexdigest(),
    "container_removed": True,
    "fixture_removed": True,
    "stderr_sha256": container["stderr_sha256"],
    "stderr_bytes": container["stderr_bytes"],
}
descriptor = os.open(cleanup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="ascii") as stream:
    stream.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    stream.flush()
    os.fsync(stream.fileno())
print(json.dumps({
    "schema_version": 1,
    "runner_report": container["runner_report"],
    "container_exit_code": container["container_exit_code"],
    "stderr_sha256": container["stderr_sha256"],
    "stderr_bytes": container["stderr_bytes"],
    "container_removed": True,
    "fixture_removed": True,
}, ensure_ascii=True, separators=(",", ":")))
PY
}

main() {
  local image='' env_file='' fixture='' evidence_dir='' runner=''
  local -a expected_lines=()
  while (($#)); do
    case $1 in
      --image|--env-file|--fixture|--evidence-dir|--runner|--expected-line)
        if (($# < 2)); then safe_die; return 2; fi
        case $1 in
          --image) image=$2 ;;
          --env-file) env_file=$2 ;;
          --fixture) fixture=$2 ;;
          --evidence-dir) evidence_dir=$2 ;;
          --runner) runner=$2 ;;
          --expected-line) expected_lines+=("$2") ;;
        esac
        shift 2
        ;;
      *) safe_die; return 2 ;;
    esac
  done
  [[ $image =~ ^sha256:[0-9a-f]{64}$ ]] || { safe_die; return 2; }
  require_absolute_regular_0600 "$env_file" || { safe_die; return 2; }
  require_absolute_regular_0600 "$fixture" || { safe_die; return 2; }
  require_absolute_regular_0600 "$runner" || { safe_die; return 2; }
  require_absolute_directory_0700 "$evidence_dir" || { safe_die; return 2; }
  [[ $(basename -- "$fixture") =~ ^controlled-ocr-fixture-[A-Za-z0-9._-]+\.(png|jpg|jpeg)$ ]] || { safe_die; return 2; }
  ((${#expected_lines[@]} == 3)) || { safe_die; return 2; }
  local line
  for line in "${expected_lines[@]}"; do
    [[ -n $line && ${#line} -le 160 && $line != *$'\n'* && $line != *$'\r'* ]] || { safe_die; return 2; }
  done

  local stdout_path="$evidence_dir/runner.stdout.jsonl"
  local stderr_path="$evidence_dir/runner.stderr"
  local container_evidence="$evidence_dir/container-evidence.json"
  local cleanup_evidence="$evidence_dir/cleanup-evidence.json"
  [[ ! -e $stdout_path && ! -e $stderr_path && ! -e $container_evidence && ! -e $cleanup_evidence ]] || { safe_die; return 2; }
  : >"$stdout_path"
  : >"$stderr_path"
  chmod 0600 "$stdout_path" "$stderr_path"

  local container_name="controlled-ocr-fixture-$(date -u +%Y%m%dT%H%M%SZ)-$$"
  local -a runner_args=(
    "$RUNNER_CONTAINER_PATH" --fixture "$FIXTURE_CONTAINER_PATH"
  )
  for line in "${expected_lines[@]}"; do
    runner_args+=(--expected-line "$line")
  done
  local -a create_args=(
    create
    --name "$container_name"
    --network none
    --read-only
    --cap-drop ALL
    --security-opt no-new-privileges:true
    --env-file "$env_file"
    --mount "type=bind,src=$runner,dst=$RUNNER_CONTAINER_PATH,readonly"
    --mount "type=bind,src=$fixture,dst=$FIXTURE_CONTAINER_PATH,readonly"
    --entrypoint python
    "$image"
    "${runner_args[@]}"
  )
  local container_id
  container_id=$(docker_call "${create_args[@]}") || { safe_die; return 2; }
  [[ $container_id =~ ^[0-9a-f]{12,64}$ ]] || { safe_die; return 2; }
  docker_call start "$container_name" >/dev/null || { safe_die; return 2; }

  local wait_exit inspect_exit inspect_status inspect_oom
  wait_exit=$(docker_call wait "$container_name") || { safe_die; return 2; }
  inspect_exit=$(docker_call inspect --format '{{.State.ExitCode}}' "$container_name") || { safe_die; return 2; }
  inspect_status=$(docker_call inspect --format '{{.State.Status}}' "$container_name") || { safe_die; return 2; }
  inspect_oom=$(docker_call inspect --format '{{.State.OOMKilled}}' "$container_name") || { safe_die; return 2; }
  [[ $wait_exit =~ ^[0-9]+$ && $inspect_exit =~ ^[0-9]+$ ]] || { safe_die; return 2; }
  docker_call logs "$container_name" >"$stdout_path" 2>"$stderr_path" || { safe_die; return 2; }
  chmod 0600 "$stdout_path" "$stderr_path"

  write_container_evidence \
    "$stdout_path" "$stderr_path" "$container_evidence" \
    "$wait_exit" "$inspect_exit" "$inspect_status" "$inspect_oom" || { safe_die; return 2; }
  [[ -f $container_evidence && ! -L $container_evidence && $(stat -Lc '%a' "$container_evidence") == 600 ]] || { safe_die; return 2; }

  # Deletion is deliberately after complete, fsync'd, validated evidence. A
  # failure before here retains both the named container and fixture.
  docker_call rm "$container_name" >/dev/null || { safe_die; return 2; }
  [[ -f $fixture && ! -L $fixture ]] || { safe_die; return 2; }
  rm -f -- "$fixture"
  [[ ! -e $fixture ]] || { safe_die; return 2; }
  write_cleanup_evidence "$container_evidence" "$cleanup_evidence" || { safe_die; return 2; }
  [[ -f $cleanup_evidence && ! -L $cleanup_evidence && $(stat -Lc '%a' "$cleanup_evidence") == 600 ]] || { safe_die; return 2; }

  if [[ $inspect_exit == 0 ]]; then
    return 0
  fi
  return 1
}

if [[ ${CONTROLLED_OCR_ORCHESTRATOR_SOURCE_ONLY:-0} != 1 ]]; then
  main "$@"
fi
