#!/usr/bin/env bash
# Local-only static and failure-injection checks for default-off-release-driver.sh.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

readonly TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly DRIVER="${TEST_DIR}/default-off-release-driver.sh"
readonly PROJECT_ROOT="$(cd "${TEST_DIR}/../../../.." && pwd)"
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
require_text 'readonly SOURCE_INSTALL_TMP_ROOT="\$\{BACKUP_ROOT\}"'
require_text 'readonly COMPOSE_PROJECT="edu-ai-lead-agent"'
require_text 'readonly COMPOSE_FILE="\$\{APP_DIR\}/compose.yaml"'
require_text 'readonly SHARED_ACTIVE_TAG="\$\{COMPOSE_PROJECT\}-backend:local"'
require_text 'readonly SERVICE_ACTIVE_TAG_SUFFIX="latest"'
require_text 'readonly FORBIDDEN_SERVICE_TAG_SUFFIX="local"'
require_text 'service_active_tag\(\)'
require_text 'service_forbidden_local_tag\(\)'
require_text 'assert_candidate_tag_is_isolated\(\)'
require_text 'write_active_tag_inventory\(\)'
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
require_text 'readonly API_ENTRYPOINT_MODULE="app.api_main"'
require_text 'readonly -a LONG_LIVED_ENTRYPOINT_MODULES='
require_text 'importlib.import_module\(sys.argv\[1\]\)'
require_text 'importlib.import_module\(name\) for name in names'
require_text 'docker_call exec -i "\$postgres_id"'
require_text 'assert_safe_window'
require_text 'assert_exact_vectors'
require_text 'assert_safe_logs'
require_text 'expected_current_day_vector'
require_text 'candidate and previous source path sets differ'
require_text 'image bundle tag membership mismatch'
require_text 'OCI index descriptor does not match candidate image id'
require_text 'classic image config digest does not match candidate image id'
require_text 'validate_candidate_source_manifest\(\)'
require_text 'assert_candidate_source_manifest\(\)'
require_text 'validate_source_archive_modes\(\)'
require_text 'validate_extracted_source_modes\(\)'
require_text 'validate_destination_mode_evidence\(\)'
require_text 'capture_destination_source_modes\(\)'
require_text 'is_source_install_tmp_path\(\)'
require_text 'assert_install_tmp_directory\(\)'
require_text 'assert_source_install_tmp_root_preflight\(\)'
require_text 'assert_source_install_tmp_root_preflight "\$SOURCE_INSTALL_TMP_ROOT" "\$APP_DIR"'
require_text 'cleanup_source_install_tmp_directory\(\)'
require_text '^[[:space:]]{4}cleanup_source_install_tmp_directory[[:space:]]'
require_text 'install_candidate_source_files\(\)'
require_text 'install -o "\$app_owner" -g "\$app_group" -m "\$preserved_mode"'
require_text 'mv -T -- "\$install_tmp_path" "\$destination_path"'
require_text 'cmp -s -- "\$source_path" "\$destination_path"'
require_text 'printf "%s\\0" alembic.ini pyproject.toml'
require_text 'export LC_ALL=C'
require_text 'sort -z \| xargs -0 -r sha256sum'
require_text 'tags_changed=1'
require_text 'active-tag-inventory.txt'
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
reject_text 'source_install_tmp_parent=\$\(dirname -- "\$destination_root"\)'
reject_text '\$\{COMPOSE_PROJECT\}-\$\{service\}:local'
reject_text 'app\.acquisition_scheduler_main'
reject_text '20260815_0021_add_image_ocr_delivery_fields'
reject_text 'alembic heads \| grep -Fx'
require_text 'heads\.stdout\.splitlines\(\)==\[f"\{expected\} \(head\)"\]'
require_text 'splitlines\(\)\)==1; heads=subprocess\.run'

assert_previous_line=$(rg -n '^  assert_previous_source$' "$DRIVER" | cut -d: -f1)
tmp_root_preflight_line=$(rg -n '^  assert_source_install_tmp_root_preflight "\$SOURCE_INSTALL_TMP_ROOT" "\$APP_DIR"$' "$DRIVER" | cut -d: -f1)
lock_line=$(rg -n '^  exec \{lock_fd\}>"\$BACKUP_LOCK"$' "$DRIVER" | cut -d: -f1)
quiesce_line=$(rg -n '^  quiesce_writers$' "$DRIVER" | cut -d: -f1)
[[ -n "$assert_previous_line" && -n "$quiesce_line" && "$assert_previous_line" -lt "$quiesce_line" ]] \
  || fail destination_mode_capture_not_before_first_stop
[[ -n "$tmp_root_preflight_line" && -n "$lock_line" \
  && "$tmp_root_preflight_line" -lt "$lock_line" && "$lock_line" -lt "$quiesce_line" ]] \
  || fail trusted_tmp_root_or_lock_not_before_first_stop

python3 - "$DRIVER" "${PROJECT_ROOT}/compose.yaml" <<'PY'
import json
import pathlib
import re
import sys

driver = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
compose_lines = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
service = None
commands = {}
app_runtime_services = []
for line in compose_lines:
    service_match = re.fullmatch(r"  ([a-z0-9-]+):", line)
    if service_match is not None:
        service = service_match.group(1)
        continue
    if line == "    <<: *app-runtime" and service is not None:
        app_runtime_services.append(service)
        continue
    command_match = re.fullmatch(r"    command: (\[.*\])", line)
    if service is not None and command_match is not None:
        commands[service] = json.loads(command_match.group(1))

services_match = re.search(
    r"^readonly -a APP_SERVICES=\(\n(.*?)^\)",
    driver,
    re.MULTILINE | re.DOTALL,
)
if services_match is None:
    raise SystemExit("driver APP_SERVICES constant is absent")
expected_services = tuple(
    line.strip() for line in services_match.group(1).splitlines() if line.strip()
)
compose_app_services = tuple(
    service for service in app_runtime_services if service != "backend-migrate"
)
if (
    len(expected_services) != 8
    or len(set(expected_services)) != 8
    or expected_services != compose_app_services
):
    raise SystemExit("driver application services differ from Compose app-runtime services")
if any(service not in commands for service in expected_services):
    raise SystemExit("Compose long-lived entrypoint command is absent")
api_command = commands["acquisition-api"]
if api_command[:4] != ["python", "-m", "uvicorn", "app.api_main:app"]:
    raise SystemExit("Compose API entrypoint drift")
compose_modules = tuple(commands[service][2] for service in expected_services[1:])
if any(commands[service][:2] != ["python", "-m"] or len(commands[service]) != 3 for service in expected_services[1:]):
    raise SystemExit("Compose long-lived module command drift")
api_match = re.search(r'^readonly API_ENTRYPOINT_MODULE="([^"]+)"$', driver, re.MULTILINE)
modules_match = re.search(
    r"^readonly -a LONG_LIVED_ENTRYPOINT_MODULES=\(\n(.*?)^\)",
    driver,
    re.MULTILINE | re.DOTALL,
)
if api_match is None or modules_match is None:
    raise SystemExit("driver entrypoint constants are absent")
driver_modules = tuple(line.strip() for line in modules_match.group(1).splitlines() if line.strip())
if (
    api_match.group(1) != api_command[3].split(":", 1)[0]
    or len(driver_modules) != len(expected_services) - 1
    or driver_modules != compose_modules
):
    raise SystemExit("driver entrypoint constants differ from Compose")
PY

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

manifest_root="${test_root}/image-source-manifests"
mkdir -m 700 "$manifest_root"
python3 - "$manifest_root" <<'PY'
import hashlib
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
paths = [
    "alembic.ini",
    "alembic/env.py",
    *(f"app/generated/file{index:03d}.py" for index in range(1, 163)),
    "pyproject.toml",
]


def digest(path):
    return hashlib.sha256(f"content:{path}\n".encode()).hexdigest()


def write(name, entries):
    (root / name).write_text(
        "".join(f"{value}  {path}\n" for path, value in sorted(entries)),
        encoding="utf-8",
    )


exact = [(path, digest(path)) for path in paths]
write("expected.sha256", exact)
write("image-source-files.sha256", exact)
write("observed-exact.sha256", exact)
write(
    "legacy-163.sha256",
    [entry for entry in exact if entry[0] not in {"alembic.ini", "pyproject.toml"}],
)
write(
    "missing-root.sha256",
    [
        ("app/generated/000.py", digest("app/generated/000.py"))
        if path == "alembic.ini"
        else (path, value)
        for path, value in exact
    ],
)
write(
    "root-hash.sha256",
    [(path, "0" * 64 if path == "alembic.ini" else value) for path, value in exact],
)
write(
    "extra.sha256",
    [
        ("app/generated/extra.py", digest("app/generated/extra.py"))
        if path == "app/generated/file162.py"
        else (path, value)
        for path, value in exact
    ],
)
write(
    "whitespace.sha256",
    [
        ("app/generated/bad path.py", value)
        if path == "app/generated/file001.py"
        else (path, value)
        for path, value in exact
    ],
)
write("duplicate.sha256", [*exact[:-1], exact[-2]])
write(
    "traversal.sha256",
    [
        ("app/../escape.py", value)
        if path == "app/generated/file001.py"
        else (path, value)
        for path, value in exact
    ],
)
write(
    "absolute.sha256",
    [
        ("/app/generated/file001.py", value)
        if path == "app/generated/file001.py"
        else (path, value)
        for path, value in exact
    ],
)
write(
    "backslash.sha256",
    [
        (r"app/generated/bad\name.py", value)
        if path == "app/generated/file001.py"
        else (path, value)
        for path, value in exact
    ],
)
write(
    "newline.sha256",
    [
        ("app/generated/bad\nname.py", value)
        if path == "app/generated/file001.py"
        else (path, value)
        for path, value in exact
    ],
)
write(
    "out-of-scope.sha256",
    [
        ("tests/file001.py", value)
        if path == "app/generated/file001.py"
        else (path, value)
        for path, value in exact
    ],
)
write(
    "suffix.sha256",
    [
        ("app/generated/file001.txt", value)
        if path == "app/generated/file001.py"
        else (path, value)
        for path, value in exact
    ],
)
write(
    "uppercase-hash.sha256",
    [(path, value.upper() if path == "alembic.ini" else value) for path, value in exact],
)
write(
    "short-hash.sha256",
    [(path, value[:-1] if path == "alembic.ini" else value) for path, value in exact],
)
(root / "unordered.sha256").write_text(
    "".join(f"{value}  {path}\n" for path, value in reversed(exact)),
    encoding="utf-8",
)
PY

run_manifest_validation() {
  RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
    source "$1"
    validate_candidate_source_manifest "$2" "$3" 165
  ' bash "$DRIVER" "$1" "${manifest_root}/expected.sha256" >/dev/null 2>&1
}

run_manifest_validation "${manifest_root}/observed-exact.sha256" \
  || fail image_source_exact_165_rejected
for rejected_manifest in \
  legacy-163 missing-root root-hash extra whitespace duplicate traversal absolute \
  backslash newline out-of-scope suffix uppercase-hash short-hash unordered
do
  if run_manifest_validation "${manifest_root}/${rejected_manifest}.sha256"; then
    fail "image_source_${rejected_manifest}_accepted"
  fi
done

run_fake_runtime_manifest() {
  MANIFEST_OUTPUT=$1 RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
      source "$1"
      stage_dir=$2
      candidate_id="sha256:$(printf c%.0s {1..64})"
      expected_image_source_file_count=165
      docker_call() {
        [[ "$#" == 14 ]] || return 71
        [[ "$1:$2:$3:$4:$5:$6:$7" == "run:--rm:--network:none:--read-only:--cap-drop:ALL" ]] || return 72
        [[ "$8" == "--security-opt" && "$9" == "no-new-privileges:true" ]] || return 73
        [[ "${10}" == "--entrypoint" && "${11}" == "sh" ]] || return 74
        [[ "${12}" == "$candidate_id" && "${13}" == "-c" ]] || return 75
        [[ "${14}" == '"'"'export LC_ALL=C;'"'"'* ]] || return 76
        [[ "${14}" == *'"'"'printf "%s\0" alembic.ini pyproject.toml'"'"'* ]] || return 77
        [[ "${14}" == *'"'"'find app alembic -type f'"'"'* ]] || return 78
        [[ "${14}" == *'"'"'sort -z | xargs -0 -r sha256sum'"'"' ]] || return 79
        cat "$MANIFEST_OUTPUT"
      }
      assert_candidate_source_manifest
      [[ -z "$image_source_manifest_tmp" ]]
    ' bash "$DRIVER" "$manifest_root" >/dev/null 2>&1
}

run_fake_runtime_manifest "${manifest_root}/observed-exact.sha256" \
  || fail image_source_fake_runtime_exact
if run_fake_runtime_manifest "${manifest_root}/legacy-163.sha256"; then
  fail image_source_fake_runtime_legacy_163_accepted
fi

manifest_cleanup_path="/tmp/edu-ai-release-driver-image-source.cleanup-${BASHPID}"
: >"$manifest_cleanup_path"
RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  image_source_manifest_tmp=$2
  cleanup_local_artifacts
  [[ ! -e "$image_source_manifest_tmp" ]]
' bash "$DRIVER" "$manifest_cleanup_path" >/dev/null 2>&1 \
  || fail image_source_exit_cleanup

source_mode_root="${test_root}/source-modes"
mkdir -m 700 "$source_mode_root"
python3 - "$source_mode_root" <<'PY'
import io
import gzip
import pathlib
import sys
import tarfile

root = pathlib.Path(sys.argv[1])
(root / "paths-two").write_text("plain.txt\nscript.py\n", encoding="utf-8")
(root / "paths-one").write_text("file.py\n", encoding="utf-8")
(root / "paths-directory").write_text("dir/file.py\n", encoding="utf-8")


def archive(name, entries, directories=()):
    with tarfile.open(root / f"{name}.tar.gz", mode="w:gz") as output:
        for path, mode in directories:
            member = tarfile.TarInfo(path)
            member.type = tarfile.DIRTYPE
            member.mode = mode
            member.uid = member.gid = 0
            member.mtime = 0
            output.addfile(member)
        for path, mode in entries:
            payload = f"payload:{path}\n".encode()
            member = tarfile.TarInfo(path)
            member.mode = mode
            member.uid = member.gid = 0
            member.mtime = 0
            member.size = len(payload)
            output.addfile(member, io.BytesIO(payload))


def replace_first_header_mode(name, mode):
    archive_path = root / f"{name}.tar.gz"
    raw = bytearray(gzip.decompress(archive_path.read_bytes()))
    raw[100:108] = f"{mode:07o}\0".encode("ascii")
    raw[148:156] = b"        "
    checksum = sum(raw[:512])
    raw[148:156] = f"{checksum:06o}\0 ".encode("ascii")
    archive_path.write_bytes(gzip.compress(bytes(raw), mtime=0))


archive("canonical", [("plain.txt", 0o644), ("script.py", 0o755)])
archive("group-write", [("plain.txt", 0o664), ("script.py", 0o775)])
archive("directory-canonical", [("dir/file.py", 0o644)], [("dir", 0o755)])
archive("directory-group-write", [("dir/file.py", 0o664)], [("dir", 0o775)])
for name, mode in (
    ("mode-0600", 0o600),
    ("mode-0700", 0o700),
    ("world-write-0666", 0o666),
    ("world-write-0777", 0o777),
    ("setuid", 0o4755),
    ("setgid", 0o2755),
    ("sticky", 0o1755),
    ("unknown", 0o655),
    ("type-bits-regular", 0o100644),
):
    archive(name, [("file.py", mode)])
for name, mode in (
    ("directory-mode-0700", 0o700),
    ("directory-world-write", 0o777),
    ("directory-setuid", 0o4755),
    ("directory-setgid", 0o2755),
    ("directory-sticky", 0o1755),
    ("directory-type-bits", 0o40755),
):
    archive(name, [("dir/file.py", 0o644)], [("dir", mode)])
archive("root-directory-world-write", [("file.py", 0o644)], [("./", 0o777)])
replace_first_header_mode("type-bits-regular", 0o100644)
replace_first_header_mode("directory-type-bits", 0o40755)
PY

run_source_mode_validation() {
  RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
    source "$1"
    validate_source_archive_modes "$2" "$3" "$4" "$5"
  ' bash "$DRIVER" "$1" "$2" "$3" "$4" >/dev/null 2>&1
}

for positive_mode_archive in canonical group-write; do
  evidence="${source_mode_root}/${positive_mode_archive}.modes"
  run_source_mode_validation \
    "${source_mode_root}/${positive_mode_archive}.tar.gz" \
    "${source_mode_root}/paths-two" "$evidence" 2 \
    || fail "source_mode_${positive_mode_archive}_rejected"
  [[ "$(<"$evidence")" == $'0644\tplain.txt\n0755\tscript.py' ]] \
    || fail "source_mode_${positive_mode_archive}_canonical_evidence"
done

for positive_directory_archive in directory-canonical directory-group-write; do
  evidence="${source_mode_root}/${positive_directory_archive}.modes"
  run_source_mode_validation \
    "${source_mode_root}/${positive_directory_archive}.tar.gz" \
    "${source_mode_root}/paths-directory" "$evidence" 1 \
    || fail "source_mode_${positive_directory_archive}_rejected"
  [[ "$(<"$evidence")" == $'0644\tdir/file.py' ]] \
    || fail "source_mode_${positive_directory_archive}_canonical_evidence"
done

for rejected_mode_archive in \
  mode-0600 mode-0700 world-write-0666 world-write-0777 setuid setgid sticky unknown \
  type-bits-regular
do
  if run_source_mode_validation \
    "${source_mode_root}/${rejected_mode_archive}.tar.gz" \
    "${source_mode_root}/paths-one" \
    "${source_mode_root}/${rejected_mode_archive}.modes" 1
  then
    fail "source_mode_${rejected_mode_archive}_accepted"
  fi
done


for rejected_directory_archive in \
  directory-mode-0700 directory-world-write directory-setuid directory-setgid \
  directory-sticky directory-type-bits
do
  if run_source_mode_validation \
    "${source_mode_root}/${rejected_directory_archive}.tar.gz" \
    "${source_mode_root}/paths-directory" \
    "${source_mode_root}/${rejected_directory_archive}.modes" 1
  then
    fail "source_mode_${rejected_directory_archive}_accepted"
  fi
done
if run_source_mode_validation \
  "${source_mode_root}/root-directory-world-write.tar.gz" \
  "${source_mode_root}/paths-one" \
  "${source_mode_root}/root-directory-world-write.modes" 1
then
  fail source_mode_root_directory_world_write_accepted
fi

extracted_mode_root="${source_mode_root}/extracted"
mkdir -m 700 "$extracted_mode_root"
printf 'plain\n' >"${extracted_mode_root}/plain.txt"
printf 'script\n' >"${extracted_mode_root}/script.py"
chmod 664 "${extracted_mode_root}/plain.txt"
chmod 775 "${extracted_mode_root}/script.py"
RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  validate_extracted_source_modes "$2" "$3" "$4" 2
' bash "$DRIVER" "$extracted_mode_root" "${source_mode_root}/paths-two" \
  "${source_mode_root}/group-write.modes" >/dev/null 2>&1 \
  || fail extracted_source_mode_group_write_rejected

printf '0664\tplain.txt\n0755\tscript.py\n' >"${source_mode_root}/bad-evidence-mode"
printf '0755\tscript.py\n0644\tplain.txt\n' >"${source_mode_root}/bad-evidence-order"
printf '0644\tplain.txt\n0644\tplain.txt\n' >"${source_mode_root}/bad-evidence-duplicate"
printf '0644\t../plain.txt\n0755\tscript.py\n' >"${source_mode_root}/bad-evidence-traversal"
printf '0644\t/plain.txt\n0755\tscript.py\n' >"${source_mode_root}/bad-evidence-absolute"
printf '0644\tplain.txt\n' >"${source_mode_root}/bad-evidence-missing"
for rejected_evidence in \
  bad-evidence-mode bad-evidence-order bad-evidence-duplicate \
  bad-evidence-traversal bad-evidence-absolute bad-evidence-missing
do
  if RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
    source "$1"
    validate_extracted_source_modes "$2" "$3" "$4" 2
  ' bash "$DRIVER" "$extracted_mode_root" "${source_mode_root}/paths-two" \
    "${source_mode_root}/${rejected_evidence}" >/dev/null 2>&1
  then
    fail "source_mode_${rejected_evidence}_accepted"
  fi
done

overlay_destination="${source_mode_root}/overlay-destination"
mkdir -m 700 "$overlay_destination"
cp -- "${extracted_mode_root}/plain.txt" "${overlay_destination}/plain.txt"
cp -- "${extracted_mode_root}/script.py" "${overlay_destination}/script.py"
chmod 600 "${overlay_destination}/plain.txt"
chmod 700 "${overlay_destination}/script.py"
overlay_install_log="${source_mode_root}/install.actions"
overlay_owner=$(stat -c '%U' "$overlay_destination")
overlay_group=$(stat -c '%G' "$overlay_destination")
trusted_install_root="${source_mode_root}/trusted-install-root"
mkdir -m 700 "$trusted_install_root"
chown 0:0 "$trusted_install_root"
export TEST_INSTALL_ROOT="$trusted_install_root"

# Production-shaped topology: the application lives below a non-root-owned
# mode-0750 parent, while the explicit trusted temp root is root:root 0700 on
# the same filesystem. The old dirname(APP_DIR) derivation must fail.
topology_root="${source_mode_root}/install-topology"
topology_opt="${topology_root}/opt-equivalent"
topology_app="${topology_opt}/edu-ai-lead-agent"
topology_trusted="${topology_root}/backups/edu-ai/releases"
mkdir -m 700 -p "$topology_app" "$topology_trusted"
chmod 750 "$topology_opt" "$topology_app"
chown 65534:65534 "$topology_opt" "$topology_app"
chown 0:0 "$topology_trusted"
chmod 700 "$topology_trusted"
RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  assert_source_install_tmp_root_preflight "$2" "$3"
' bash "$DRIVER" "$topology_trusted" "$topology_app" >/dev/null 2>&1 \
  || fail production_topology_trusted_root_rejected
if RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  assert_trusted_install_tmp_root "$2" "$3"
' bash "$DRIVER" "$topology_opt" "$topology_app" >/dev/null 2>&1
then
  fail old_derived_app_parent_trusted
fi

topology_source="${topology_root}/candidate"
mkdir -m 700 "$topology_source"
printf 'candidate topology\n' >"${topology_source}/file.py"
printf 'active topology\n' >"${topology_app}/file.py"
chmod 664 "${topology_source}/file.py"
chmod 600 "${topology_app}/file.py"
chown 65534:65534 "${topology_app}/file.py"
printf '0644\tfile.py\n' >"${topology_root}/candidate.modes"
topology_owner=$(stat -c '%U' "$topology_app")
topology_group=$(stat -c '%G' "$topology_app")
: >"${topology_root}/destination.modes"
RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  source_modes_file=$2
  expected_source_file_count=1
  capture_destination_source_modes "$3" "$4" "$5" "$6"
  release_extract_dir=$7
  destination_modes_file=$6
  install_candidate_source_files "$3" "$4" "$5" "$8"
' bash "$DRIVER" "${topology_root}/candidate.modes" "$topology_app" \
  "$topology_owner" "$topology_group" "${topology_root}/destination.modes" \
  "$topology_source" "$topology_trusted" >/dev/null 2>&1 \
  || fail production_topology_atomic_install_rejected
[[ "$(<"${topology_app}/file.py")" == "candidate topology" \
  && "$(stat -c '%a' "${topology_app}/file.py")" == 600 \
  && "$(stat -c '%u:%g' "${topology_app}/file.py")" == "65534:65534" ]] \
  || fail production_topology_atomic_install_drift
if find "$topology_trusted" -mindepth 1 -maxdepth 1 -type d \
  -name '.edu-ai-source-install.*' -print -quit | grep -q .; then
  fail production_topology_temp_not_cleaned
fi

# Trusted-root negatives: absent/symlink/non-root/0750/1777/different-device.
topology_symlink="${topology_root}/trusted-symlink"
ln -s "$topology_trusted" "$topology_symlink"
topology_nonroot="${topology_root}/trusted-nonroot"
topology_nonroot_0750="${topology_root}/trusted-nonroot-0750"
topology_world="${topology_root}/trusted-world"
mkdir -m 700 "$topology_nonroot" "$topology_nonroot_0750" "$topology_world"
chown 65534:65534 "$topology_nonroot" "$topology_nonroot_0750"
chmod 750 "$topology_nonroot_0750"
chmod 1777 "$topology_world"
for rejected_trusted_root in \
  "${topology_root}/missing" "$topology_symlink" "$topology_nonroot" \
  "$topology_nonroot_0750" "$topology_world"
do
  if RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
    source "$1"
    assert_trusted_install_tmp_root "$2" "$3"
  ' bash "$DRIVER" "$rejected_trusted_root" "$topology_app" >/dev/null 2>&1
  then
    fail trusted_root_unsafe_topology_accepted
  fi
done
TRUSTED_ROOT="$topology_trusted" RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  stat() {
    if [[ "$1" == "-c" && "$2" == "%d" && "$3" == "$TRUSTED_ROOT" ]]; then
      printf "999999\n"
      return 0
    fi
    command stat "$@"
  }
  assert_trusted_install_tmp_root "$TRUSTED_ROOT" "$2"
' bash "$DRIVER" "$topology_app" >/dev/null 2>&1 \
  && fail trusted_root_different_device_accepted

# Backup directories do not collide with the reserved temp prefix. Every
# reserved-prefix object blocks preflight, and a scan error fails closed.
mkdir -m 700 "${topology_trusted}/20260816T081242Z-zhipu-ocr-default-off"
RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  assert_source_install_tmp_root_preflight "$2" "$3"
' bash "$DRIVER" "$topology_trusted" "$topology_app" >/dev/null 2>&1 \
  || fail backup_directory_conflicted_with_temp_prefix
mkdir -m 700 "${topology_trusted}/.edu-ai-source-install.STALE1"
if RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  assert_source_install_tmp_root_preflight "$2" "$3"
' bash "$DRIVER" "$topology_trusted" "$topology_app" >/dev/null 2>&1
then
  fail stale_install_temp_preflight_accepted
fi
rmdir -- "${topology_trusted}/.edu-ai-source-install.STALE1"

printf 'stale\n' >"${topology_trusted}/.edu-ai-source-install.FILE01"
if RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  assert_source_install_tmp_root_preflight "$2" "$3"
' bash "$DRIVER" "$topology_trusted" "$topology_app" >/dev/null 2>&1
then
  fail stale_install_temp_file_preflight_accepted
fi
rm -f -- "${topology_trusted}/.edu-ai-source-install.FILE01"

ln -s -- "${topology_trusted}/20260816T081242Z-zhipu-ocr-default-off" \
  "${topology_trusted}/.edu-ai-source-install.LINK01"
if RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  assert_source_install_tmp_root_preflight "$2" "$3"
' bash "$DRIVER" "$topology_trusted" "$topology_app" >/dev/null 2>&1
then
  fail stale_install_temp_symlink_preflight_accepted
fi
rm -f -- "${topology_trusted}/.edu-ai-source-install.LINK01"

mkdir -m 700 "${topology_trusted}/.edu-ai-source-install.long-residue"
if RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  assert_source_install_tmp_root_preflight "$2" "$3"
' bash "$DRIVER" "$topology_trusted" "$topology_app" >/dev/null 2>&1
then
  fail stale_install_temp_long_prefix_preflight_accepted
fi
rmdir -- "${topology_trusted}/.edu-ai-source-install.long-residue"

if RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  find() { return 73; }
  assert_source_install_tmp_root_preflight "$2" "$3"
' bash "$DRIVER" "$topology_trusted" "$topology_app" >/dev/null 2>&1
then
  fail trusted_root_scan_error_accepted
fi

RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  is_source_install_tmp_path "$2" "${2}/.edu-ai-source-install.AbC123"
  ! is_source_install_tmp_path "$2" "${2}/20260816T081242Z-zhipu-ocr-default-off"
  ! is_source_install_tmp_path "$2" "${2}/.edu-ai-source-install.BAD!?!"
  ! is_source_install_tmp_path "$2" "${2}/.edu-ai-source-install.abc/xy"
  ! is_source_install_tmp_path "$2" "${2}/.edu-ai-source-install.too-long"
' bash "$DRIVER" "$topology_trusted" >/dev/null 2>&1 \
  || fail install_temp_name_contract

# Cleanup removes only a physical direct generated child. It preserves backup
# directories, unrelated entries and anything reached through a symlink root.
cleanup_temp="${topology_trusted}/.edu-ai-source-install.Cln123"
cleanup_unrelated="${topology_trusted}/unrelated-directory"
mkdir -m 700 "$cleanup_temp" "$cleanup_unrelated"
printf 'payload\n' >"${cleanup_temp}/payload"
RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  cleanup_source_install_tmp_directory "$2" "$3"
' bash "$DRIVER" "$topology_trusted" "$cleanup_temp" >/dev/null 2>&1 \
  || fail install_temp_cleanup_rejected
[[ ! -e "$cleanup_temp" \
  && -d "${topology_trusted}/20260816T081242Z-zhipu-ocr-default-off" \
  && -d "$cleanup_unrelated" ]] || fail install_temp_cleanup_scope_drift

symlink_cleanup_temp="${topology_trusted}/.edu-ai-source-install.Keep01"
mkdir -m 700 "$symlink_cleanup_temp"
RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  cleanup_source_install_tmp_directory "$2" "${2}/.edu-ai-source-install.Keep01"
' bash "$DRIVER" "$topology_symlink" >/dev/null 2>&1 \
  || fail install_temp_symlink_root_cleanup_call_failed
[[ -d "$symlink_cleanup_temp" ]] || fail install_temp_symlink_root_cleanup_followed
rmdir -- "$symlink_cleanup_temp" "$cleanup_unrelated"

capture_destination_modes() {
  local destination_root=$1
  local candidate_modes=$2
  local expected_count=$3
  local output_modes=$4
  local destination_owner destination_group
  destination_owner=$(stat -c '%U' "$destination_root")
  destination_group=$(stat -c '%G' "$destination_root")
  : >"$output_modes"
  RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
    source "$1"
    source_modes_file=$2
    expected_source_file_count=$3
    capture_destination_source_modes "$4" "$5" "$6" "$7"
  ' bash "$DRIVER" "$candidate_modes" "$expected_count" "$destination_root" \
    "$destination_owner" "$destination_group" "$output_modes" >/dev/null 2>&1
}

assert_no_install_temp_dirs() {
  if find "$TEST_INSTALL_ROOT" -maxdepth 1 -type d \
    -name '.edu-ai-source-install.*' -print -quit | grep -q .; then
    fail install_temporary_directory_not_cleaned
  fi
}

cleanup_test_install_temp_dirs() {
  find "$TEST_INSTALL_ROOT" -maxdepth 1 -type d -name '.edu-ai-source-install.*' \
    -exec rm -rf -- {} +
}

destination_modes="${source_mode_root}/destination-strict.modes"
capture_destination_modes \
  "$overlay_destination" "${source_mode_root}/group-write.modes" 2 "$destination_modes" \
  || fail strict_destination_mode_capture_rejected
[[ "$(<"$destination_modes")" == $'0644\t0600\tplain.txt\n0755\t0700\tscript.py' ]] \
  && fail strict_destination_mode_evidence_legacy_grammar_accepted
expected_destination_modes=$(printf \
  '0644\t0600\t%s\t%s\tplain.txt\n0755\t0700\t%s\t%s\tscript.py' \
  "$overlay_owner" "$overlay_group" "$overlay_owner" "$overlay_group")
[[ "$(<"$destination_modes")" == "$expected_destination_modes" ]] \
  || fail strict_destination_mode_evidence

printf '0644\t0664\t%s\t%s\tplain.txt\n0755\t0700\t%s\t%s\tscript.py\n' \
  "$overlay_owner" "$overlay_group" "$overlay_owner" "$overlay_group" \
  >"${source_mode_root}/bad-destination-mode"
printf '0755\t0600\t%s\t%s\tplain.txt\n0755\t0700\t%s\t%s\tscript.py\n' \
  "$overlay_owner" "$overlay_group" "$overlay_owner" "$overlay_group" \
  >"${source_mode_root}/bad-destination-semantic"
printf '0755\t0700\t%s\t%s\tscript.py\n0644\t0600\t%s\t%s\tplain.txt\n' \
  "$overlay_owner" "$overlay_group" "$overlay_owner" "$overlay_group" \
  >"${source_mode_root}/bad-destination-order"
printf '0644\t0600\t%s\t%s\tplain.txt\n0644\t0600\t%s\t%s\tplain.txt\n' \
  "$overlay_owner" "$overlay_group" "$overlay_owner" "$overlay_group" \
  >"${source_mode_root}/bad-destination-duplicate"
printf '0644\t0600\t%s\t%s\t../plain.txt\n0755\t0700\t%s\t%s\tscript.py\n' \
  "$overlay_owner" "$overlay_group" "$overlay_owner" "$overlay_group" \
  >"${source_mode_root}/bad-destination-traversal"
printf '0644\t0600\t%s\t%s\tplain.txt\n' "$overlay_owner" "$overlay_group" \
  >"${source_mode_root}/bad-destination-missing"
printf '0644\t0600\tinvalid-owner\t%s\tplain.txt\n0755\t0700\t%s\t%s\tscript.py\n' \
  "$overlay_group" "$overlay_owner" "$overlay_group" \
  >"${source_mode_root}/bad-destination-owner"
for rejected_destination_evidence in \
  bad-destination-mode bad-destination-semantic bad-destination-order \
  bad-destination-duplicate bad-destination-traversal bad-destination-missing \
  bad-destination-owner
do
  if RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
    source "$1"
    validate_destination_mode_evidence "$2" "$3" 2 "$4" "$5"
  ' bash "$DRIVER" "${source_mode_root}/group-write.modes" \
    "${source_mode_root}/${rejected_destination_evidence}" \
    "$overlay_owner" "$overlay_group" >/dev/null 2>&1
  then
    fail "source_mode_${rejected_destination_evidence}_accepted"
  fi
done

ACTION_LOG="$overlay_install_log" RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  release_extract_dir=$2
  source_modes_file=$3
  destination_modes_file=$4
  expected_source_file_count=2
  expected_destination=$5
  expected_owner=$6
  expected_group=$7
  install() {
    [[ "$#" == 9 ]] || return 91
    [[ "$1" == "-o" && "$2" == "$expected_owner" && "$3" == "-g" && "$4" == "$expected_group" ]] || return 92
    [[ "${7}" == "--" ]] || return 93
    case "${9}" in
      "${TEST_INSTALL_ROOT}/.edu-ai-source-install."??????/payload) ;;
      *) return 94 ;;
    esac
    printf "%s %s\n" "$6" "${8##*/}" >>"$ACTION_LOG"
    /usr/bin/install "$@"
  }
  install_candidate_source_files "$5" "$6" "$7" "$TEST_INSTALL_ROOT"
' bash "$DRIVER" "$extracted_mode_root" "${source_mode_root}/group-write.modes" \
  "$destination_modes" "$overlay_destination" "$overlay_owner" "$overlay_group" >/dev/null 2>&1 \
  || fail strict_overlay_install_rejected
[[ "$(<"$overlay_install_log")" == $'0600 plain.txt\n0700 script.py' ]] \
  || fail strict_overlay_install_arguments
[[ "$(stat -c '%a' "${overlay_destination}/plain.txt")" == "600" ]] \
  || fail strict_overlay_plain_mode_not_preserved
[[ "$(stat -c '%a' "${overlay_destination}/script.py")" == "700" ]] \
  || fail strict_overlay_script_mode_not_preserved
cmp -s "${extracted_mode_root}/plain.txt" "${overlay_destination}/plain.txt" \
  || fail strict_overlay_plain_content_not_installed
cmp -s "${extracted_mode_root}/script.py" "${overlay_destination}/script.py" \
  || fail strict_overlay_script_content_not_installed
assert_no_install_temp_dirs "$overlay_destination"

# Canonical production destinations are also valid and remain exact.
printf 'old plain\n' >"${overlay_destination}/plain.txt"
printf 'old script\n' >"${overlay_destination}/script.py"
chmod 644 "${overlay_destination}/plain.txt"
chmod 755 "${overlay_destination}/script.py"
canonical_destination_modes="${source_mode_root}/destination-canonical.modes"
capture_destination_modes \
  "$overlay_destination" "${source_mode_root}/group-write.modes" 2 "$canonical_destination_modes" \
  || fail canonical_destination_mode_capture_rejected
RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  release_extract_dir=$2
  source_modes_file=$3
  destination_modes_file=$4
  expected_source_file_count=2
  install_candidate_source_files "$5" "$6" "$7" "$TEST_INSTALL_ROOT"
' bash "$DRIVER" "$extracted_mode_root" "${source_mode_root}/group-write.modes" \
  "$canonical_destination_modes" "$overlay_destination" "$overlay_owner" "$overlay_group" \
  >/dev/null 2>&1 || fail canonical_destination_overlay_rejected
[[ "$(stat -c '%a' "${overlay_destination}/plain.txt")" == "644" ]] \
  || fail canonical_destination_plain_mode_not_preserved
[[ "$(stat -c '%a' "${overlay_destination}/script.py")" == "755" ]] \
  || fail canonical_destination_script_mode_not_preserved
assert_no_install_temp_dirs "$overlay_destination"

# A successful no-op install cannot satisfy the temporary-file and post-copy gates.
chmod 600 "${overlay_destination}/plain.txt"
chmod 700 "${overlay_destination}/script.py"
capture_destination_modes \
  "$overlay_destination" "${source_mode_root}/group-write.modes" 2 "$destination_modes" \
  || fail noop_destination_mode_capture_rejected
if RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  release_extract_dir=$2
  source_modes_file=$3
  destination_modes_file=$4
  expected_source_file_count=2
  install() {
    [[ "$#" == 9 ]] || return 95
    return 0
  }
  install_candidate_source_files "$5" "$6" "$7" "$TEST_INSTALL_ROOT"
' bash "$DRIVER" "$extracted_mode_root" "${source_mode_root}/group-write.modes" \
  "$destination_modes" "$overlay_destination" "$overlay_owner" "$overlay_group" >/dev/null 2>&1
then
  fail overlay_noop_install_accepted
fi
cleanup_test_install_temp_dirs

# Changing a valid destination mode after preflight is a TOCTOU failure.
chmod 644 "${overlay_destination}/plain.txt"
if RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  release_extract_dir=$2
  source_modes_file=$3
  destination_modes_file=$4
  expected_source_file_count=2
  install() { :; }
  install_candidate_source_files "$5" "$6" "$7" "$TEST_INSTALL_ROOT"
' bash "$DRIVER" "$extracted_mode_root" "${source_mode_root}/group-write.modes" \
  "$destination_modes" "$overlay_destination" "$overlay_owner" "$overlay_group" >/dev/null 2>&1
then
  fail overlay_destination_mode_toctou_accepted
fi

# Ownership captured before quiesce is also revalidated before installation.
chmod 600 "${overlay_destination}/plain.txt"
chmod 700 "${overlay_destination}/script.py"
chown "$overlay_owner:$overlay_group" \
  "${overlay_destination}/plain.txt" "${overlay_destination}/script.py"
capture_destination_modes \
  "$overlay_destination" "${source_mode_root}/group-write.modes" 2 "$destination_modes" \
  || fail ownership_toctou_destination_mode_capture_rejected
chown 65534:65534 "${overlay_destination}/script.py"
if RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  release_extract_dir=$2
  source_modes_file=$3
  destination_modes_file=$4
  expected_source_file_count=2
  install_candidate_source_files "$5" "$6" "$7" "$TEST_INSTALL_ROOT"
' bash "$DRIVER" "$extracted_mode_root" "${source_mode_root}/group-write.modes" \
  "$destination_modes" "$overlay_destination" "$overlay_owner" "$overlay_group" >/dev/null 2>&1
then
  fail overlay_destination_ownership_toctou_accepted
fi
chown "$overlay_owner:$overlay_group" "${overlay_destination}/script.py"

# Atomic `mv -T` replaces, rather than follows, a final-component symlink
# introduced after the last mode/owner check.
race_source="${source_mode_root}/atomic-race-source"
race_destination="${source_mode_root}/atomic-race-destination"
race_external="${source_mode_root}/atomic-race-external.txt"
mkdir -m 700 "$race_source" "$race_destination"
printf 'candidate race\n' >"${race_source}/file.py"
printf 'active race\n' >"${race_destination}/file.py"
printf 'external sentinel\n' >"$race_external"
chmod 664 "${race_source}/file.py"
chmod 600 "${race_destination}/file.py"
printf '0644\tfile.py\n' >"${source_mode_root}/atomic-race.candidate.modes"
race_destination_modes="${source_mode_root}/atomic-race.destination.modes"
capture_destination_modes \
  "$race_destination" "${source_mode_root}/atomic-race.candidate.modes" 1 \
  "$race_destination_modes" || fail atomic_race_destination_mode_capture_rejected
RACE_EXTERNAL="$race_external" RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  release_extract_dir=$2
  source_modes_file=$3
  destination_modes_file=$4
  expected_source_file_count=1
  mv() {
    [[ "$#" == 4 && "$1" == "-T" && "$2" == "--" ]] || return 96
    rm -f -- "$4"
    ln -s -- "$RACE_EXTERNAL" "$4"
    /usr/bin/mv "$@"
  }
  install_candidate_source_files "$5" "$6" "$7" "$TEST_INSTALL_ROOT"
' bash "$DRIVER" "$race_source" "${source_mode_root}/atomic-race.candidate.modes" \
  "$race_destination_modes" "$race_destination" "$overlay_owner" "$overlay_group" \
  >/dev/null 2>&1 || fail atomic_race_overlay_rejected
[[ ! -L "${race_destination}/file.py" \
  && "$(<"${race_destination}/file.py")" == "candidate race" \
  && "$(stat -c '%a' "${race_destination}/file.py")" == "600" \
  && "$(<"$race_external")" == "external sentinel" ]] \
  || fail atomic_race_followed_destination_symlink
assert_no_install_temp_dirs "$race_destination"

# Generated install directories must stay under the exact destination parent
# and remain root:root mode 0700 before both install and replacement.
tmp_contract_source="${source_mode_root}/tmp-contract-source"
tmp_contract_destination="${source_mode_root}/tmp-contract-destination"
mkdir -m 700 "$tmp_contract_source" "$tmp_contract_destination"
printf 'candidate tmp\n' >"${tmp_contract_source}/file.py"
printf 'active tmp\n' >"${tmp_contract_destination}/file.py"
chmod 664 "${tmp_contract_source}/file.py"
chmod 600 "${tmp_contract_destination}/file.py"
printf '0644\tfile.py\n' >"${source_mode_root}/tmp-contract.candidate.modes"
tmp_contract_modes="${source_mode_root}/tmp-contract.destination.modes"
capture_destination_modes \
  "$tmp_contract_destination" "${source_mode_root}/tmp-contract.candidate.modes" 1 \
  "$tmp_contract_modes" || fail tmp_contract_destination_mode_capture_rejected
unsafe_tmp_dir="${test_root}/.edu-ai-source-install.BADTMP"
mkdir -m 700 "$unsafe_tmp_dir"
UNSAFE_TMP_DIR="$unsafe_tmp_dir" RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  release_extract_dir=$2
  source_modes_file=$3
  destination_modes_file=$4
  expected_source_file_count=1
  mktemp() {
    [[ "$1" == "-d" ]] || return 97
    printf "%s\n" "$UNSAFE_TMP_DIR"
  }
  install_candidate_source_files "$5" "$6" "$7" "$TEST_INSTALL_ROOT"
' bash "$DRIVER" "$tmp_contract_source" "${source_mode_root}/tmp-contract.candidate.modes" \
  "$tmp_contract_modes" "$tmp_contract_destination" "$overlay_owner" "$overlay_group" \
  >/dev/null 2>&1 && fail unsafe_install_tmp_path_accepted
rm -rf -- "$unsafe_tmp_dir"
[[ "$(<"${tmp_contract_destination}/file.py")" == "active tmp" ]] \
  || fail unsafe_install_tmp_path_modified_destination

unowned_tmp_dir="${trusted_install_root}/.edu-ai-source-install.BADOWN"
mkdir -m 700 "$unowned_tmp_dir"
chown 65534:65534 "$unowned_tmp_dir"
UNOWNED_TMP_DIR="$unowned_tmp_dir" RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  release_extract_dir=$2
  source_modes_file=$3
  destination_modes_file=$4
  expected_source_file_count=1
  mktemp() {
    [[ "$1" == "-d" ]] || return 98
    printf "%s\n" "$UNOWNED_TMP_DIR"
  }
  install_candidate_source_files "$5" "$6" "$7" "$TEST_INSTALL_ROOT"
' bash "$DRIVER" "$tmp_contract_source" "${source_mode_root}/tmp-contract.candidate.modes" \
  "$tmp_contract_modes" "$tmp_contract_destination" "$overlay_owner" "$overlay_group" \
  >/dev/null 2>&1 && fail unowned_install_tmp_path_accepted
chown 0:0 "$unowned_tmp_dir"
rm -rf -- "$unowned_tmp_dir"
[[ "$(<"${tmp_contract_destination}/file.py")" == "active tmp" ]] \
  || fail unowned_install_tmp_path_modified_destination

# Every unsafe destination mode and executable-class mismatch fails at capture.
negative_source="${source_mode_root}/negative-source"
negative_destination="${source_mode_root}/negative-destination"
mkdir -m 700 "$negative_source" "$negative_destination"
printf 'candidate\n' >"${negative_source}/file.py"
printf 'active\n' >"${negative_destination}/file.py"
while IFS=$'\t' read -r case_name semantic_mode source_mode rejected_destination_mode; do
  chmod "$source_mode" "${negative_source}/file.py"
  chmod "$rejected_destination_mode" "${negative_destination}/file.py"
  printf '%s\tfile.py\n' "$semantic_mode" >"${source_mode_root}/${case_name}.candidate.modes"
  if capture_destination_modes \
    "$negative_destination" "${source_mode_root}/${case_name}.candidate.modes" 1 \
    "${source_mode_root}/${case_name}.destination.modes"
  then
    fail "destination_mode_${case_name}_accepted"
  fi
done <<'EOF'
nonexec-groupwrite	0644	644	664
exec-groupwrite	0755	755	775
nonexec-worldwrite	0644	644	666
exec-worldwrite	0755	755	777
setuid	0644	644	4600
setgid	0755	755	2700
sticky	0755	755	1700
unknown	0644	644	640
nonexec-as-exec	0644	644	700
exec-as-nonexec	0755	755	600
EOF

# Mixed strict/canonical destination modes remain exact per path.
mixed_source="${source_mode_root}/mixed-source"
mixed_destination="${source_mode_root}/mixed-destination"
mkdir -m 700 "$mixed_source" "$mixed_destination"
for mixed_path in nonexec-strict.txt nonexec-canonical.txt exec-strict.sh exec-canonical.sh; do
  printf 'candidate:%s\n' "$mixed_path" >"${mixed_source}/${mixed_path}"
  printf 'active:%s\n' "$mixed_path" >"${mixed_destination}/${mixed_path}"
done
chmod 644 "${mixed_source}/nonexec-strict.txt"
chmod 664 "${mixed_source}/nonexec-canonical.txt"
chmod 755 "${mixed_source}/exec-strict.sh"
chmod 775 "${mixed_source}/exec-canonical.sh"
chmod 600 "${mixed_destination}/nonexec-strict.txt"
chmod 644 "${mixed_destination}/nonexec-canonical.txt"
chmod 700 "${mixed_destination}/exec-strict.sh"
chmod 755 "${mixed_destination}/exec-canonical.sh"
printf '%s\n' \
  $'0755\texec-canonical.sh' \
  $'0755\texec-strict.sh' \
  $'0644\tnonexec-canonical.txt' \
  $'0644\tnonexec-strict.txt' >"${source_mode_root}/mixed.candidate.modes"
mixed_destination_modes="${source_mode_root}/mixed.destination.modes"
capture_destination_modes \
  "$mixed_destination" "${source_mode_root}/mixed.candidate.modes" 4 "$mixed_destination_modes" \
  || fail mixed_destination_mode_capture_rejected
RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  release_extract_dir=$2
  source_modes_file=$3
  destination_modes_file=$4
  expected_source_file_count=4
  install_candidate_source_files "$5" "$6" "$7" "$TEST_INSTALL_ROOT"
' bash "$DRIVER" "$mixed_source" "${source_mode_root}/mixed.candidate.modes" \
  "$mixed_destination_modes" "$mixed_destination" "$overlay_owner" "$overlay_group" \
  >/dev/null 2>&1 || fail mixed_destination_overlay_rejected
[[ "$(stat -c '%a' "${mixed_destination}/nonexec-strict.txt")" == 600 \
  && "$(stat -c '%a' "${mixed_destination}/nonexec-canonical.txt")" == 644 \
  && "$(stat -c '%a' "${mixed_destination}/exec-strict.sh")" == 700 \
  && "$(stat -c '%a' "${mixed_destination}/exec-canonical.sh")" == 755 ]] \
  || fail mixed_destination_modes_not_preserved
assert_no_install_temp_dirs "$mixed_destination"

nested_source="${source_mode_root}/nested-source"
nested_destination="${source_mode_root}/nested-destination"
mkdir -m 700 -p "${nested_source}/dir" "${nested_destination}/real"
printf 'nested\n' >"${nested_source}/dir/file.py"
printf 'old\n' >"${nested_destination}/real/file.py"
chmod 644 "${nested_source}/dir/file.py" "${nested_destination}/real/file.py"
ln -s real "${nested_destination}/dir"
printf '0644\tdir/file.py\n' >"${source_mode_root}/nested.modes"
printf '0644\t0644\t%s\t%s\tdir/file.py\n' "$overlay_owner" "$overlay_group" \
  >"${source_mode_root}/nested.destination.modes"
if RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  release_extract_dir=$2
  source_modes_file=$3
  destination_modes_file=$4
  expected_source_file_count=1
  install() { return 94; }
  install_candidate_source_files "$5" "$6" "$7" "$TEST_INSTALL_ROOT"
' bash "$DRIVER" "$nested_source" "${source_mode_root}/nested.modes" \
  "${source_mode_root}/nested.destination.modes" "$nested_destination" \
  "$overlay_owner" "$overlay_group" >/dev/null 2>&1
then
  fail overlay_nested_destination_symlink_accepted
fi
[[ "$(<"${nested_destination}/real/file.py")" == "old" ]] \
  || fail overlay_nested_destination_symlink_modified_target

# Production-shaped 307-file mode matrix: every old exact-mode comparison
# differs, while semantic-class capture and preserved installation succeed.
synthetic_source="${source_mode_root}/synthetic-307-source"
synthetic_destination="${source_mode_root}/synthetic-307-destination"
synthetic_candidate_modes="${source_mode_root}/synthetic-307.candidate.modes"
mkdir -m 700 "$synthetic_source" "$synthetic_destination"
python3 - "$synthetic_source" "$synthetic_destination" "$synthetic_candidate_modes" <<'PY'
import os
import pathlib
import stat
import sys

source = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
evidence = pathlib.Path(sys.argv[3])
entries = [
    *(f"plain/file-{position:03d}.txt" for position in range(295)),
    *(f"script/file-{position:03d}.sh" for position in range(12)),
]
for root in (source, destination):
    (root / "plain").mkdir(mode=0o700)
    (root / "script").mkdir(mode=0o700)
for position, raw in enumerate(entries):
    executable = raw.startswith("script/")
    source_path = source / raw
    destination_path = destination / raw
    source_path.write_text(f"candidate:{position}\n", encoding="utf-8")
    destination_path.write_text(f"active:{position}\n", encoding="utf-8")
    source_path.chmod(0o775 if executable else 0o664)
    destination_path.chmod(0o700 if executable else 0o600)
evidence.write_text(
    "".join(f"{'0755' if raw.startswith('script/') else '0644'}\t{raw}\n" for raw in entries),
    encoding="utf-8",
)
assert sum(
    stat.S_IMODE((source / raw).stat().st_mode)
    != stat.S_IMODE((destination / raw).stat().st_mode)
    for raw in entries
) == 307
PY
synthetic_destination_modes="${source_mode_root}/synthetic-307.destination.modes"
capture_destination_modes \
  "$synthetic_destination" "$synthetic_candidate_modes" 307 "$synthetic_destination_modes" \
  || fail synthetic_307_destination_mode_capture_rejected
[[ "$(grep -c $'^0644\t0600\t' "$synthetic_destination_modes")" == 295 \
  && "$(grep -c $'^0755\t0700\t' "$synthetic_destination_modes")" == 12 ]] \
  || fail synthetic_307_destination_mode_counts
RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  release_extract_dir=$2
  source_modes_file=$3
  destination_modes_file=$4
  expected_source_file_count=307
  install_candidate_source_files "$5" "$6" "$7" "$TEST_INSTALL_ROOT"
' bash "$DRIVER" "$synthetic_source" "$synthetic_candidate_modes" \
  "$synthetic_destination_modes" "$synthetic_destination" "$overlay_owner" "$overlay_group" \
  >/dev/null 2>&1 || fail synthetic_307_overlay_rejected
python3 - "$synthetic_source" "$synthetic_destination" <<'PY'
import collections
import pathlib
import stat
import sys

source = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
observed = collections.Counter()
for source_path in sorted(path for path in source.rglob("*") if path.is_file()):
    relative = source_path.relative_to(source)
    destination_path = destination / relative
    assert source_path.read_bytes() == destination_path.read_bytes()
    observed[stat.S_IMODE(destination_path.stat().st_mode)] += 1
assert observed == {0o600: 295, 0o700: 12}
PY
assert_no_install_temp_dirs "$synthetic_destination"

full_gate_root="${test_root}/full-candidate-gate"
mkdir -m 700 -p "${full_gate_root}/backend"
printf '{}\n' >"${full_gate_root}/backend/openapi.json"
openapi_hash=$(printf '{}' | sha256sum | awk '{print $1}')
full_gate_log="${full_gate_root}/actions"
ACTION_LOG="$full_gate_log" MANIFEST_OUTPUT="${manifest_root}/observed-exact.sha256" \
  OPENAPI_HASH="$openapi_hash" \
  RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
    source "$1"
    stage_dir=$2
    release_extract_dir=$3
    candidate_tag=edu-ai-lead-agent-backend:candidate
    candidate_id="sha256:$(printf c%.0s {1..64})"
    candidate_commit=$(printf d%.0s {1..40})
    expected_dependency_base_id="sha256:$(printf e%.0s {1..64})"
    expected_pyproject_sha256=$(printf f%.0s {1..64})
    source_sha256=$(printf a%.0s {1..64})
    expected_image_source_file_count=165
    expected_modules=$(IFS=,; printf "%s" "${LONG_LIVED_ENTRYPOINT_MODULES[*]}")
    docker_call() {
      local operation="${1-}:${2-}"
      local entrypoint code
      case "$operation" in
        image:inspect)
          [[ "$#" == 5 && "$4" == "--format" ]] || return 61
          case "$5" in
            "{{.Id}}")
              [[ "$3" == "$candidate_tag" ]] || return 62
              printf "%s\n" "$candidate_id"
              printf "image-id\n" >>"$ACTION_LOG"
              ;;
            *org.opencontainers.image.revision*)
              [[ "$3" == "$candidate_id" ]] || return 63
              printf "%s\n" "$candidate_commit"
              printf "revision\n" >>"$ACTION_LOG"
              ;;
            *io.trellis.dependency-base.digest*)
              [[ "$3" == "$candidate_id" ]] || return 64
              printf "%s\n" "$expected_dependency_base_id"
              printf "dependency\n" >>"$ACTION_LOG"
              ;;
            *io.trellis.dependency-input.pyproject-sha256*)
              [[ "$3" == "$candidate_id" ]] || return 65
              printf "%s\n" "$expected_pyproject_sha256"
              printf "pyproject\n" >>"$ACTION_LOG"
              ;;
            *) return 1 ;;
          esac
          ;;
        run:--rm)
          [[ "$#" -ge 13 ]] || return 66
          [[ "$3:$4:$5:$6:$7:$8:$9" == "--network:none:--read-only:--cap-drop:ALL:--security-opt:no-new-privileges:true" ]] || return 67
          [[ "${10}" == "--entrypoint" && "${12}" == "$candidate_id" ]] || return 68
          entrypoint=${11}
          case "$entrypoint" in
            sh)
              [[ "$#" == 14 && "${13}" == "-c" ]] || return 69
              code=${14}
              case "$code" in
                *"/app/.release-source.sha256"*)
                  printf "%s\n" "$source_sha256"
                  printf "source\n" >>"$ACTION_LOG"
                  ;;
                *"printf \"%s\0\" alembic.ini pyproject.toml"*)
                  cat "$MANIFEST_OUTPUT" || return 81
                  printf "manifest\n" >>"$ACTION_LOG"
                  ;;
                *"/app/build/lib"*) printf "shadow\n" >>"$ACTION_LOG" ;;
                *) return 1 ;;
              esac
              ;;
            python)
              [[ "${13}" == "-c" ]] || return 70
              code=${14}
              case "$code" in
                *"importlib.import_module(sys.argv[1])"*)
                  [[ "$#" == 16 ]] || return 71
                  [[ "${15}" == "$API_ENTRYPOINT_MODULE" && "${16}" == "$expected_modules" ]] || return 72
                  [[ "$code" != *acquisition_scheduler_main* ]] || return 73
                  [[ "$code" == *'"'"'schema=api_app.openapi()'"'"'* ]] || return 74
                  printf "imports\n" >>"$ACTION_LOG"
                  ;;
                *ZhipuImageTextRecognizer*)
                  [[ "$#" == 14 ]] || return 75
                  printf "zhipu-construction\n" >>"$ACTION_LOG"
                  ;;
                *"hashlib,json"*)
                  [[ "$#" == 14 ]] || return 76
                  printf "%s\n" "$OPENAPI_HASH"
                  printf "openapi\n" >>"$ACTION_LOG"
                  ;;
                *'"'"'subprocess.run(["alembic","heads"]'"'"'*)
                  [[ "$#" == 15 && "${15}" == "$EXPECTED_ALEMBIC_HEAD" ]] || return 77
                  [[ "$code" == *'"'"'assert sum(line==marker'"'"'* ]] || return 78
                  [[ "$code" == *'"'"'heads.stdout.splitlines()==[f"{expected} (head)"]'"'"'* ]] || return 79
                  printf "alembic\n" >>"$ACTION_LOG"
                  ;;
                *) return 1 ;;
              esac
              ;;
            pip)
              [[ "${13}" == "check" && "$#" == 13 ]] || return 80
              printf "pip\n" >>"$ACTION_LOG"
              ;;
            *) return 1 ;;
          esac
          ;;
        *) return 1 ;;
      esac
    }
    assert_candidate_image
  ' bash "$DRIVER" "$manifest_root" "$full_gate_root" >/dev/null 2>&1 \
  || fail full_candidate_gate_fake_runtime
[[ "$(<"$full_gate_log")" == $'image-id\nrevision\ndependency\npyproject\nsource\nmanifest\nimports\npip\nzhipu-construction\nshadow\nopenapi\nalembic' ]] \
  || fail full_candidate_gate_order

bundle_cases="${test_root}/bundle-cases.tsv"
python3 - "$test_root" "$bundle_cases" <<'PY'
import gzip
import hashlib
import io
import json
import pathlib
import sys
import tarfile

ROOT = pathlib.Path(sys.argv[1]) / "bundles"
CASES = pathlib.Path(sys.argv[2])
TAG = "edu-ai-lead-agent-backend:candidate"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG = "application/vnd.oci.image.config.v1+json"
OCI_LAYER = "application/vnd.oci.image.layer.v1.tar+gzip"
ROOT.mkdir(mode=0o700)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(payload):
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def layer_payload(name, body):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as inner:
        item = tarfile.TarInfo(name)
        item.mode = 0o644
        item.uid = item.gid = 0
        item.mtime = 0
        item.size = len(body)
        inner.addfile(item, io.BytesIO(body))
    return raw.getvalue(), gzip.compress(raw.getvalue(), mtime=0)


def add_file(archive, name, payload):
    item = tarfile.TarInfo(name)
    item.mode = 0o600
    item.uid = item.gid = 0
    item.mtime = 0
    item.size = len(payload)
    archive.addfile(item, io.BytesIO(payload))


def write_archive(path, files, *, oci, extra=()):
    with tarfile.open(path, mode="w:gz") as archive:
        if oci:
            for directory in ("blobs/", "blobs/sha256/"):
                item = tarfile.TarInfo(directory)
                item.type = tarfile.DIRTYPE
                item.mode = 0o700
                item.uid = item.gid = 0
                item.mtime = 0
                archive.addfile(item)
        for name, payload in files.items():
            add_file(archive, name, payload)
        for kind, name, payload in extra:
            if kind == "file":
                add_file(archive, name, payload)
            elif kind == "symlink":
                item = tarfile.TarInfo(name)
                item.type = tarfile.SYMTYPE
                item.linkname = payload.decode()
                item.mode = 0o777
                item.mtime = 0
                archive.addfile(item)
            else:
                raise AssertionError(kind)


first_raw, first_layer = layer_payload("app/first.txt", b"first layer\n")
second_raw, second_layer = layer_payload("app/second.txt", b"second layer\n")
config_payload = encoded(
    {
        "architecture": "amd64",
        "os": "linux",
        "rootfs": {
            "type": "layers",
            "diff_ids": [digest(first_raw), digest(second_raw)],
        },
    }
)
CONFIG_DIGEST = digest(config_payload)
LAYER_PAYLOADS = (first_layer, second_layer)
LAYER_DIGESTS = tuple(digest(payload) for payload in LAYER_PAYLOADS)


def build_oci(name, mutation=""):
    current_config_payload = config_payload
    if mutation == "config-layer-count":
        current_config_payload = encoded(
            {
                "architecture": "amd64",
                "os": "linux",
                "rootfs": {"type": "layers", "diff_ids": [digest(first_raw)]},
            }
        )
    if mutation == "config-platform":
        current_config_payload = encoded(
            {
                "architecture": "arm64",
                "os": "linux",
                "rootfs": {
                    "type": "layers",
                    "diff_ids": [digest(first_raw), digest(second_raw)],
                },
            }
        )
    if mutation == "config-diff-id":
        current_config_payload = encoded(
            {
                "architecture": "amd64",
                "os": "linux",
                "rootfs": {
                    "type": "layers",
                    "diff_ids": ["sha256:" + ("0" * 64), digest(second_raw)],
                },
            }
        )
    if mutation == "config-nonstandard-json":
        current_config_payload = (
            b'{"architecture":"amd64","os":"linux","rootfs":'
            b'{"type":"layers","diff_ids":['
            + encoded(digest(first_raw))
            + b','
            + encoded(digest(second_raw))
            + b']},"invalid":NaN}'
        )
    current_config_digest = digest(current_config_payload)
    config_descriptor = {
        "mediaType": OCI_CONFIG,
        "digest": current_config_digest,
        "size": len(current_config_payload),
    }
    layer_descriptors = [
        {"mediaType": OCI_LAYER, "digest": layer_digest, "size": len(payload)}
        for layer_digest, payload in zip(LAYER_DIGESTS, LAYER_PAYLOADS)
    ]
    if mutation == "config-size":
        config_descriptor["size"] += 1
    if mutation == "config-media":
        config_descriptor["mediaType"] = "application/json"
    if mutation == "config-extra-field":
        config_descriptor["annotations"] = {}
    if mutation == "layer-size":
        layer_descriptors[1]["size"] += 1
    if mutation == "layer-media":
        layer_descriptors[1]["mediaType"] = "application/octet-stream"
    if mutation == "layer-extra-field":
        layer_descriptors[1]["annotations"] = {}
    manifest = {
        "schemaVersion": 2,
        "mediaType": (
            "application/vnd.docker.distribution.manifest.v2+json"
            if mutation == "manifest-media-conflict"
            else OCI_MANIFEST
        ),
        "config": config_descriptor,
        "layers": layer_descriptors,
    }
    if mutation == "manifest-schema":
        manifest["schemaVersion"] = 1
    if mutation == "manifest-extra-field":
        manifest["annotations"] = {}
    manifest_payload = encoded(manifest)
    candidate = digest(manifest_payload)
    manifest_descriptor = {
        "mediaType": OCI_MANIFEST,
        "digest": candidate,
        "size": len(manifest_payload),
        "annotations": {
            "io.containerd.image.name": f"docker.io/library/{TAG}",
            "org.opencontainers.image.ref.name": TAG.rsplit(":", 1)[1],
        },
    }
    if mutation == "descriptor-digest":
        manifest_descriptor["digest"] = "sha256:" + ("0" * 64)
    if mutation == "descriptor-size":
        manifest_descriptor["size"] += 1
    if mutation == "descriptor-media":
        manifest_descriptor["mediaType"] = "application/octet-stream"
    if mutation == "descriptor-extra-field":
        manifest_descriptor["platform"] = {"architecture": "amd64", "os": "linux"}
    if mutation == "annotation-name":
        manifest_descriptor["annotations"]["io.containerd.image.name"] = (
            "docker.io/library/edu-ai-lead-agent-backend:local"
        )
    if mutation == "annotation-ref":
        manifest_descriptor["annotations"]["org.opencontainers.image.ref.name"] = "local"
    if mutation == "annotation-missing":
        del manifest_descriptor["annotations"]["org.opencontainers.image.ref.name"]
    if mutation == "annotation-extra":
        manifest_descriptor["annotations"]["unexpected"] = "value"
    index = {
        "schemaVersion": 2,
        "mediaType": OCI_INDEX,
        "manifests": [manifest_descriptor],
    }
    if mutation == "index-schema":
        index["schemaVersion"] = 1
    if mutation == "index-media":
        index["mediaType"] = "application/json"
    if mutation == "index-extra-field":
        index["annotations"] = {}
    if mutation == "index-extra-image":
        index["manifests"].append(dict(manifest_descriptor))
    config_path = "blobs/sha256/" + current_config_digest.removeprefix("sha256:")
    layer_paths = [
        "blobs/sha256/" + value.removeprefix("sha256:") for value in LAYER_DIGESTS
    ]
    docker_entry = {
        "Config": config_path,
        "RepoTags": ["edu-ai-lead-agent-backend:wrong"] if mutation == "tag" else [TAG],
        "Layers": list(reversed(layer_paths)) if mutation == "manifest-order" else layer_paths,
    }
    if mutation == "manifest-config-conflict":
        docker_entry["Config"] = layer_paths[0]
    files = {
        "manifest.json": encoded([docker_entry]),
        "index.json": encoded(index),
        "oci-layout": encoded(
            {"imageLayoutVersion": "0.9.0" if mutation == "layout-version" else "1.0.0"}
        ),
        "blobs/sha256/" + candidate.removeprefix("sha256:"): manifest_payload,
        config_path: current_config_payload,
        **dict(zip(layer_paths, LAYER_PAYLOADS)),
    }
    if mutation == "manifest-hash":
        files["blobs/sha256/" + candidate.removeprefix("sha256:")] += b"\n"
    if mutation == "config-hash":
        files[config_path] += b"\n"
    if mutation == "layer-hash":
        files[layer_paths[0]] += b"\n"
    if mutation == "layout-without-index":
        del files["index.json"]
    if mutation == "index-without-layout":
        del files["oci-layout"]
    if mutation == "dangling-blob":
        files["blobs/sha256/" + ("f" * 64)] = b"unused"
    extra = []
    if mutation == "unsafe-member":
        extra.append(("file", "../escape", b"unsafe"))
    if mutation == "duplicate-member":
        extra.append(("file", "manifest.json", files["manifest.json"]))
    if mutation == "nonregular-member":
        extra.append(("symlink", "escape-link", b"manifest.json"))
    path = ROOT / f"{name}.tar.gz"
    write_archive(path, files, oci=True, extra=extra)
    return path, candidate


def build_classic():
    classic_layer = first_raw
    config_name = CONFIG_DIGEST.removeprefix("sha256:") + ".json"
    layer_name = "layer.tar"
    files = {
        "manifest.json": encoded(
            [{"Config": config_name, "RepoTags": [TAG], "Layers": [layer_name]}]
        ),
        config_name: config_payload,
        layer_name: classic_layer,
    }
    path = ROOT / "classic-positive.tar.gz"
    write_archive(path, files, oci=False)
    return path


cases = []
positive_path, positive_candidate = build_oci("oci-positive")
cases.append(("oci-positive", positive_path, TAG, positive_candidate, "pass"))
cases.append(("candidate-is-config", positive_path, TAG, CONFIG_DIGEST, "fail"))
classic_path = build_classic()
cases.append(("classic-positive", classic_path, TAG, CONFIG_DIGEST, "pass"))
for mutation in (
    "descriptor-digest",
    "descriptor-size",
    "descriptor-media",
    "descriptor-extra-field",
    "annotation-name",
    "annotation-ref",
    "annotation-missing",
    "annotation-extra",
    "index-schema",
    "index-media",
    "index-extra-field",
    "layout-version",
    "manifest-hash",
    "manifest-schema",
    "manifest-extra-field",
    "manifest-media-conflict",
    "config-hash",
    "config-size",
    "config-media",
    "config-extra-field",
    "config-platform",
    "config-layer-count",
    "config-diff-id",
    "config-nonstandard-json",
    "layer-hash",
    "layer-size",
    "layer-media",
    "layer-extra-field",
    "tag",
    "index-extra-image",
    "manifest-order",
    "manifest-config-conflict",
    "layout-without-index",
    "index-without-layout",
    "dangling-blob",
    "unsafe-member",
    "duplicate-member",
    "nonregular-member",
):
    path, candidate = build_oci(mutation, mutation)
    cases.append((mutation, path, TAG, candidate, "fail"))
with CASES.open("w", encoding="utf-8") as handle:
    for case in cases:
        handle.write("|".join(map(str, case)) + "\n")
PY

while IFS='|' read -r bundle_case bundle_path bundle_tag bundle_id bundle_expected; do
  if [[ "$bundle_expected" == pass ]]; then
    RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
      source "$1"
      validate_candidate_bundle "$2" "$3" "$4"
    ' bash "$DRIVER" "$bundle_path" "$bundle_tag" "$bundle_id" >/dev/null \
      || fail "bundle_${bundle_case}_rejected"
  elif RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
    source "$1"
    validate_candidate_bundle "$2" "$3" "$4"
  ' bash "$DRIVER" "$bundle_path" "$bundle_tag" "$bundle_id" >/dev/null 2>&1; then
    fail "bundle_${bundle_case}_accepted"
  fi
done <"$bundle_cases"

oci_bundle_path=$(awk -F '|' '$1 == "oci-positive" {print $2}' "$bundle_cases")
oci_candidate_id=$(awk -F '|' '$1 == "oci-positive" {print $4}' "$bundle_cases")
cp -- "$oci_bundle_path" "${test_root}/backend-image.tar.gz"
RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  stage_dir=$2
  candidate_tag=edu-ai-lead-agent-backend:candidate
  candidate_id=$3
  previous_image_id="sha256:$(printf b%.0s {1..64})"
  tags_changed=0
  docker_call() { [[ "$1:$2:$tags_changed" == "image:load:1" ]]; }
  assert_active_tags() { :; }
  assert_candidate_image() { :; }
  load_candidate_bundle
  [[ "$tags_changed" == 1 ]]
' bash "$DRIVER" "$test_root" "$oci_candidate_id" >/dev/null 2>&1 || fail bundle_phase_arming

tag_contract_root="${test_root}/tag-contract"
mkdir -m 700 "$tag_contract_root"
TAG_CONTRACT_ROOT="$tag_contract_root" RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  old_id="sha256:$(printf b%.0s {1..64})"
  candidate_id="sha256:$(printf c%.0s {1..64})"
  previous_image_id=$old_id
  declare -A tag_ids=()
  tag_ids["edu-ai-lead-agent-backend:local"]=$old_id
  for service in "${TAG_SERVICES[@]}"; do
    tag_ids["edu-ai-lead-agent-${service}:latest"]=$old_id
  done
  docker_call() {
    local operation="${1-}:${2-}"
    local source target
    case "$operation" in
      image:inspect)
        target=$3
        [[ -n "${tag_ids[$target]+present}" ]] || return 1
        printf "%s\n" "${tag_ids[$target]}"
        ;;
      image:tag)
        source=$3
        target=$4
        tag_ids["$target"]=$source
        printf "%s %s\n" "$source" "$target" >>"${TAG_CONTRACT_ROOT}/tag-actions"
        ;;
      *) return 1 ;;
    esac
  }
  assert_active_tags "$old_id"
  candidate_tag=edu-ai-lead-agent-backend:candidate
  assert_candidate_tag_is_isolated
  candidate_tag=edu-ai-lead-agent-content-worker:latest
  if assert_candidate_tag_is_isolated >/dev/null 2>&1; then exit 41; fi
  candidate_tag=edu-ai-lead-agent-content-worker:local
  if assert_candidate_tag_is_isolated >/dev/null 2>&1; then exit 42; fi
  candidate_tag=edu-ai-lead-agent-backend:candidate
  write_active_tag_inventory "${TAG_CONTRACT_ROOT}/active-tags" "$old_id"
  [[ "$(wc -l <"${TAG_CONTRACT_ROOT}/active-tags")" == 10 ]]
  grep -Fx "shared edu-ai-lead-agent-backend:local $old_id" "${TAG_CONTRACT_ROOT}/active-tags" >/dev/null
  for service in "${TAG_SERVICES[@]}"; do
    grep -Fx "$service edu-ai-lead-agent-${service}:latest $old_id" "${TAG_CONTRACT_ROOT}/active-tags" >/dev/null
    [[ -z "${tag_ids[edu-ai-lead-agent-${service}:local]+present}" ]]
  done
  retag_candidate
  [[ "${tag_ids[edu-ai-lead-agent-backend:local]}" == "$candidate_id" ]]
  for service in "${TAG_SERVICES[@]}"; do
    [[ "${tag_ids[edu-ai-lead-agent-${service}:latest]}" == "$candidate_id" ]]
    [[ -z "${tag_ids[edu-ai-lead-agent-${service}:local]+present}" ]]
  done
  restore_tags_for_recovery
  assert_active_tags "$old_id"
  [[ "$(wc -l <"${TAG_CONTRACT_ROOT}/tag-actions")" == 20 ]]
' bash "$DRIVER" >/dev/null 2>&1 || fail mixed_active_tag_contract

run_exact_tag_recovery_case() {
  local name=$1
  local overlay=$2
  local expected_actions=$3
  local action_log="${test_root}/${name}-exact-tag.actions"
  ACTION_LOG="$action_log" OVERLAY_VALUE="$overlay" RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
    source "$1"
    old_id="sha256:$(printf b%.0s {1..64})"
    new_id="sha256:$(printf c%.0s {1..64})"
    previous_image_id=$old_id
    declare -A tag_ids=()
    tag_ids["edu-ai-lead-agent-backend:local"]=$new_id
    for service in "${TAG_SERVICES[@]}"; do
      tag_ids["edu-ai-lead-agent-${service}:latest"]=$new_id
    done
    docker_call() {
      local operation="${1-}:${2-}"
      local source target
      case "$operation" in
        image:inspect)
          target=$3
          [[ -n "${tag_ids[$target]+present}" ]] || return 1
          printf "%s\n" "${tag_ids[$target]}"
          ;;
        image:tag)
          source=$3
          target=$4
          tag_ids["$target"]=$source
          ;;
        *) return 1 ;;
      esac
    }
    log() { :; }
    enter_app_dir() { :; }
    restore_overlay_for_recovery() { printf "overlay\n" >>"$ACTION_LOG"; }
    restore_services_for_recovery() {
      assert_active_tags "$previous_image_id"
      for service in "${TAG_SERVICES[@]}"; do
        [[ "${tag_ids[edu-ai-lead-agent-${service}:latest]}" == "$previous_image_id" ]]
        [[ -z "${tag_ids[edu-ai-lead-agent-${service}:local]+present}" ]]
      done
      printf "services\n" >>"$ACTION_LOG"
    }
    backup_ready=1
    tags_changed=1
    overlay_changed=$OVERLAY_VALUE
    services_quiesced=1
    recovery_running=0
    recover 77
    [[ "$recovered" == 1 ]]
    assert_active_tags "$previous_image_id"
  ' bash "$DRIVER" >/dev/null 2>&1 || fail "${name}_exact_tag_recovery"
  [[ "$(<"$action_log")" == "$expected_actions" ]] || fail "${name}_exact_tag_order"
}

run_exact_tag_recovery_case mid 0 'services'
run_exact_tag_recovery_case late 1 $'overlay\nservices'

unsafe_manifest="${test_root}/unsafe-source.sha256"
printf '%064d  ../escape.py\n' 0 >"$unsafe_manifest"
if RELEASE_DRIVER_SOURCE_ONLY=1 bash -c '
  source "$1"
  validate_source_manifest "$2" "$3" 1
' bash "$DRIVER" "$unsafe_manifest" "${test_root}/unsafe.paths" >/dev/null 2>&1; then
  fail unsafe_source_manifest_accepted
fi

printf 'test_passed cases=static,source-mode-canonical-groupwrite-positive,source-mode-special-worldwrite-unknown-negative,source-mode-extracted-evidence,destination-mode-evidence-owner-path-count-order-negative,trusted-backup-root-production-topology,trusted-root-missing-symlink-owner-mode-device-stale-negative,destination-mode-strict-canonical-positive,destination-mode-group-world-special-class-negative,destination-mode-mode-owner-toctou,atomic-final-symlink-race,tmp-root-owner-mode-cleanup,mixed-destination-preserve,synthetic-307-groupwrite-to-restrictive-preserve,nested-symlink,compose-entrypoint-binding,full-candidate-gate-fake-runtime,early,mid,late,hup,int,term,explicit-exit,incomplete-recovery,layer-failure,lock-lifetime,image-source-165,image-source-legacy-163-real-boundary,image-source-root-hash-extra-whitespace-duplicate-traversal-absolute-backslash-newline-scope-suffix-hash-order,image-source-runtime-args-cleanup,oci-positive,classic-positive,candidate-vs-config,descriptor-config-layer-integrity,rootfs-diff-id,strict-json,index-annotation-tag-binding,oci-schema-media-fields,paired-format-markers,tag-index-manifest-conflicts,unsafe-duplicate-nonregular-dangling,bundle-phase,mixed-tags,mid-exact-tags,late-exact-tags,unsafe-manifest\n'
