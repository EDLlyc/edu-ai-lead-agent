#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

readonly DEFAULT_APP_DIR="/opt/edu-ai-lead-agent"
readonly APP_DIR_INPUT="${EDU_AI_PRODUCTION_CHECK_APP_DIR:-${DEFAULT_APP_DIR}}"
readonly STANDARD_RELEASE_STATE="/var/lib/edu-ai/releases/current.json"
readonly -a PRODUCTION_PROFILE_ARGS=(
    --profile governance
    --profile content
    --profile official-account-weekly-dag
    --profile official-account-local
    --profile wechat-official-account-draft
    --profile wecom
)
readonly -a APPLICATION_SERVICES=(
    acquisition-api
    acquisition-scheduler
    acquisition-worker
    governance-scheduler
    governance-worker
    content-scheduler
    content-worker
    official-account-weekly-dag-worker
    official-account-weekly-scheduler
    official-account-local-worker
    wechat-official-account-draft-worker
    wecom-dispatcher
)

usage_failure() {
    printf 'runtime_health=failed check=%s reason=%s\n' "$1" "$2" >&2
    exit 2
}

runtime_failure() {
    printf 'runtime_health=failed check=%s reason=%s\n' "$1" "$2" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || usage_failure prerequisites "missing_$1"
}

require_regular_file() {
    [[ -f "$1" && ! -L "$1" ]] || runtime_failure prerequisites "missing_$2"
}

validate_app_dir() {
    [[ "${APP_DIR_INPUT}" == /* && "${#APP_DIR_INPUT}" -le 512 ]] \
        || usage_failure usage invalid_app_dir
    [[ "${APP_DIR_INPUT}" =~ ^/[A-Za-z0-9._/-]+$ ]] \
        || usage_failure usage invalid_app_dir
    [[ "${APP_DIR_INPUT}" != "/" \
        && "${APP_DIR_INPUT}" != *//* \
        && "${APP_DIR_INPUT}" != */./* \
        && "${APP_DIR_INPUT}" != */../* \
        && "${APP_DIR_INPUT}" != */. \
        && "${APP_DIR_INPUT}" != */.. \
        && -d "${APP_DIR_INPUT}" \
        && ! -L "${APP_DIR_INPUT}" ]] \
        || usage_failure usage invalid_app_dir
    local resolved
    resolved="$(cd -- "${APP_DIR_INPUT}" && pwd -P)" \
        || usage_failure usage invalid_app_dir
    [[ "${resolved}" == "${APP_DIR_INPUT%/}" ]] \
        || usage_failure usage invalid_app_dir
    printf '%s\n' "${resolved}"
}

compose_read() {
    edu_ai_compose "${PRODUCTION_PROFILE_ARGS[@]}" "$@"
}

container_id_for_service() {
    local service="$1"
    local output
    output="$(compose_read ps -q "${service}" 2>/dev/null)" \
        || runtime_failure services compose_ps_failed
    [[ "${output}" =~ ^[0-9a-f]{12,64}$ ]] \
        || runtime_failure services "container_count_${service}"
    printf '%s\n' "${output}"
}

inspect_application_service() {
    local service="$1"
    local container_id="$2"
    local expected_image="$3"
    local result
    result="$(docker inspect "${container_id}" 2>/dev/null | python3 -c '
import json
import re
import sys

expected = sys.argv[1]
try:
    value = json.load(sys.stdin)
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ValueError
    item = value[0]
    state = item["State"]
    config = item["Config"]
    status = state["Status"]
    health = state.get("Health", {}).get("Status")
    restarts = item.get("RestartCount", 0)
    image_id = item["Image"]
    configured_image = config["Image"]
    if configured_image != expected:
        print("configured_image_mismatch")
    elif status != "running":
        print("not_running")
    elif health not in (None, "healthy"):
        print("unhealthy")
    elif not isinstance(restarts, int) or isinstance(restarts, bool) or restarts != 0:
        print("restart_count_nonzero")
    elif not isinstance(image_id, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        print("image_id_invalid")
    else:
        print("ok " + image_id)
except (KeyError, TypeError, ValueError, json.JSONDecodeError):
    print("inspection_invalid")
' "${expected_image}")" || runtime_failure services "inspect_failed_${service}"
    [[ "${result}" == "ok sha256:"[0-9a-f][0-9a-f]* ]] \
        || runtime_failure services "${result}_${service}"
    printf '%s\n' "${result#ok }"
}

inspect_dependency_service() {
    local service="$1"
    local container_id="$2"
    local result
    result="$(docker inspect "${container_id}" 2>/dev/null | python3 -c '
import json
import sys

try:
    value = json.load(sys.stdin)
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ValueError
    item = value[0]
    state = item["State"]
    restarts = item.get("RestartCount", 0)
    if state["Status"] != "running":
        print("not_running")
    elif state.get("Health", {}).get("Status") != "healthy":
        print("unhealthy")
    elif not isinstance(restarts, int) or isinstance(restarts, bool) or restarts != 0:
        print("restart_count_nonzero")
    else:
        print("ok")
except (KeyError, TypeError, ValueError, json.JSONDecodeError):
    print("inspection_invalid")
')" || runtime_failure dependencies "inspect_failed_${service}"
    [[ "${result}" == "ok" ]] \
        || runtime_failure dependencies "${result}_${service}"
}

inspect_local_image() {
    local image="$1"
    local commit="$2"
    local result
    result="$(docker image inspect "${image}" 2>/dev/null | python3 -c '
import json
import re
import sys

commit = sys.argv[1]
try:
    value = json.load(sys.stdin)
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ValueError
    item = value[0]
    image_id = item["Id"]
    labels = item["Config"]["Labels"]
    if not isinstance(image_id, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        print("image_id_invalid")
    elif not isinstance(labels, dict) or labels.get("org.opencontainers.image.revision") != commit:
        print("revision_label_mismatch")
    else:
        print("ok " + image_id)
except (KeyError, TypeError, ValueError, json.JSONDecodeError):
    print("inspection_invalid")
' "${commit}")" || runtime_failure image local_image_inspect_failed
    [[ "${result}" == "ok sha256:"[0-9a-f][0-9a-f]* ]] \
        || runtime_failure image "${result}"
    printf '%s\n' "${result#ok }"
}

parse_expected_head() {
    python3 - "$1" <<'PY'
import json
import re
import sys
from pathlib import Path

try:
    pairs = json.loads(
        Path(sys.argv[1]).read_text(encoding="utf-8"),
        object_pairs_hook=lambda values: values
        if len({key for key, _value in values}) == len(values)
        else (_ for _ in ()).throw(ValueError()),
    )
    document = dict(pairs)
    head = document["alembic_head"]
    if not isinstance(head, str) or re.fullmatch(r"[0-9]{8}_[0-9]{4}", head) is None:
        raise ValueError
except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
    raise SystemExit(1)
print(head)
PY
}

validate_api_response() {
    python3 -c '
import json
import sys

try:
    value = json.load(sys.stdin)
except (TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)
if not isinstance(value, dict):
    raise SystemExit(1)
if value.get("status") != "ok" or value.get("environment") != "production":
    raise SystemExit(1)
'
}

main() {
    [[ "$#" -eq 0 ]] || usage_failure usage positional_arguments_forbidden
    (( EUID == 0 )) || usage_failure prerequisites root_required
    local command_name
    for command_name in awk base64 curl docker python3 tr; do
        require_command "${command_name}"
    done

    local app_dir
    app_dir="$(validate_app_dir)"
    cd -- "${app_dir}"
    require_regular_file .env environment_file
    require_regular_file .release-commit release_commit
    require_regular_file .release.env release_environment
    require_regular_file compose.yaml compose_file
    require_regular_file deploy/release/migration-compatibility.json migration_declaration
    require_regular_file scripts/edu-ai-release-common.sh release_common
    source scripts/edu-ai-release-common.sh

    local release_commit release_image expected_head actual_head
    release_commit="$(python3 -c '
import re
from pathlib import Path
try:
    value = Path(".release-commit").read_text(encoding="utf-8")
except (OSError, UnicodeError):
    raise SystemExit(1)
if re.fullmatch(r"[0-9a-f]{40}\n?", value) is None:
    raise SystemExit(1)
print(value.strip())
')" || runtime_failure markers invalid_release_commit
    release_image="$(edu_ai_env_value .release.env APP_IMAGE)"
    [[ "${release_image}" =~ ^[a-z0-9.-]+(:[0-9]+)?(/[a-z0-9]+([._-][a-z0-9]+)*){2,}@sha256:[0-9a-f]{64}$ ]] \
        || runtime_failure markers invalid_release_image
    expected_head="$(parse_expected_head deploy/release/migration-compatibility.json)" \
        || runtime_failure schema invalid_migration_declaration

    printf 'runtime_release_marker_commit=%s\n' "${release_commit}"
    printf 'runtime_image_reference=%s\n' "${release_image}"

    local -a missing_metadata=()
    [[ -f .release-manifest.json && ! -L .release-manifest.json ]] \
        || missing_metadata+=(release-manifest)
    [[ -f "${STANDARD_RELEASE_STATE}" && ! -L "${STANDARD_RELEASE_STATE}" ]] \
        || missing_metadata+=(current-release-state)
    if (( ${#missing_metadata[@]} == 0 )); then
        printf 'standard_release_provenance=metadata_present_not_validated\n'
    else
        local joined_metadata
        joined_metadata="$(IFS=,; printf '%s' "${missing_metadata[*]}")"
        printf 'standard_release_provenance=incomplete missing=%s\n' "${joined_metadata}"
    fi

    local dependency dependency_id
    for dependency in postgres minio; do
        dependency_id="$(container_id_for_service "${dependency}")"
        inspect_dependency_service "${dependency}" "${dependency_id}"
    done
    printf 'dependency_health=ok dependency_count=2\n'

    local common_image_id="" service service_id service_image_id
    for service in "${APPLICATION_SERVICES[@]}"; do
        service_id="$(container_id_for_service "${service}")"
        service_image_id="$(inspect_application_service \
            "${service}" "${service_id}" "${release_image}")"
        if [[ -z "${common_image_id}" ]]; then
            common_image_id="${service_image_id}"
        elif [[ "${service_image_id}" != "${common_image_id}" ]]; then
            runtime_failure services "common_image_id_mismatch_${service}"
        fi
    done
    local local_image_id
    local_image_id="$(inspect_local_image "${release_image}" "${release_commit}")"
    [[ "${local_image_id}" == "${common_image_id}" ]] \
        || runtime_failure image local_image_id_mismatch
    printf 'service_health=ok service_count=%s\n' "${#APPLICATION_SERVICES[@]}"
    printf 'runtime_image_id=%s\n' "${common_image_id}"

    actual_head="$(edu_ai_psql_scalar 'SELECT version_num FROM alembic_version' 2>/dev/null)" \
        || runtime_failure schema schema_query_failed
    [[ "${actual_head}" == "${expected_head}" ]] \
        || runtime_failure schema schema_head_mismatch
    printf 'schema_alignment=ok\n'

    local api_response
    api_response="$(curl --fail --silent --max-time 5 \
        --max-filesize 65536 http://127.0.0.1:8000/healthz)" \
        || runtime_failure api request_failed
    printf '%s' "${api_response}" | validate_api_response \
        || runtime_failure api invalid_response
    printf 'api_health=ok\n'

    local queue_counts queued live_running stale_running ambiguous
    queue_counts="$(edu_ai_psql_scalar "
SELECT concat_ws('|',
  count(*) FILTER (WHERE status = 'queued'),
  count(*) FILTER (
    WHERE status = 'running'
      AND lease_expires_at IS NOT NULL
      AND lease_expires_at > now()
  ),
  count(*) FILTER (
    WHERE status = 'running'
      AND (lease_expires_at IS NULL OR lease_expires_at <= now())
  ),
  count(*) FILTER (
    WHERE status IN ('partial', 'delivery_unknown')
       OR text_status = 'unknown'
       OR image_status = 'unknown'
  )
) FROM wecom_delivery_jobs
" 2>/dev/null)" || runtime_failure queue aggregate_query_failed
    [[ "${queue_counts}" =~ ^[0-9]+\|[0-9]+\|[0-9]+\|[0-9]+$ ]] \
        || runtime_failure queue aggregate_result_invalid
    IFS='|' read -r queued live_running stale_running ambiguous <<< "${queue_counts}"
    local queue_state=idle
    if (( stale_running > 0 || ambiguous > 0 )); then
        queue_state=ambiguous
    elif (( queued > 0 || live_running > 0 )); then
        queue_state=active
    fi
    printf 'queue_state=%s queued=%s live_running=%s stale_running=%s ambiguous=%s\n' \
        "${queue_state}" "${queued}" "${live_running}" \
        "${stale_running}" "${ambiguous}"
    (( stale_running == 0 && ambiguous == 0 )) \
        || runtime_failure queue stale_or_ambiguous

    printf 'runtime_health=ok\n'
}

main "$@"
