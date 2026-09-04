#!/usr/bin/env bash
set -Eeuo pipefail

unset CDPATH GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_COMMON_DIR GIT_CONFIG_COUNT
unset GIT_CONFIG_GLOBAL GIT_CONFIG_PARAMETERS GIT_CONFIG_SYSTEM GIT_DIR
unset GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_TRACE GIT_TRACE_CURL
unset GIT_TRACE_PACKET GIT_TRACE_PERFORMANCE GIT_TRACE_SETUP GIT_WORK_TREE
unset GNUMAKEFLAGS MAKEFLAGS MAKEFILES MFLAGS
for git_config_override in "${!GIT_CONFIG_KEY_@}" "${!GIT_CONFIG_VALUE_@}"; do
    unset "${git_config_override}"
done

readonly PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly IMAGE_REPOSITORY="${RELEASE_IMAGE_REPOSITORY:-}"
readonly SSH_HOST="${RELEASE_SSH_HOST:-}"
readonly DRY_RUN="${RELEASE_DRY_RUN:-false}"
readonly SOURCE_REMOTE="origin"
readonly SOURCE_BRANCH="${RELEASE_SOURCE_REF-main}"
readonly SOURCE_HEAD_REF="refs/heads/${SOURCE_BRANCH}"
readonly SOURCE_TRACKING_REF="refs/remotes/${SOURCE_REMOTE}/${SOURCE_BRANCH}"
readonly SOURCE_URL="https://codeup.aliyun.com/601cdb1a841cc46b7c49b115/marketingUseOnly/edu-ai-lead-agent.git"
readonly SOURCE_SSH_URL="git@codeup.aliyun.com:601cdb1a841cc46b7c49b115/marketingUseOnly/edu-ai-lead-agent.git"
readonly SOURCE_SSH_ALIAS="codeup-edu-ai"
readonly SOURCE_SSH_ALIAS_URL="git@codeup-edu-ai:601cdb1a841cc46b7c49b115/marketingUseOnly/edu-ai-lead-agent.git"
readonly DEPLOY_RUNNER_ID="developer-pc"
readonly REMOTE_DEPLOY_ENTRYPOINT="/usr/local/sbin/edu-ai-deploy"
readonly -a SSH_OPTIONS=(
    -o BatchMode=yes
    -o StrictHostKeyChecking=yes
    -o PasswordAuthentication=no
    -o KbdInteractiveAuthentication=no
    -o NumberOfPasswordPrompts=0
    -o ConnectTimeout=10
    -o ServerAliveInterval=30
    -o ServerAliveCountMax=3
)

temporary_root=""
worktree=""
remote_dir=""
release_commit=""
compose_started="false"
resolved_image_reference=""
verified_artifact_dir=""
remote_deploy_started="false"
remote_deploy_finished="false"

fail() {
    printf 'release_prod_failed code=%s\n' "$1" >&2
    exit 2
}

fail_source() {
    local source_code="$1"
    local main_compatibility_code="$2"
    if [[ "${SOURCE_BRANCH}" == "main" ]]; then
        fail "${main_compatibility_code}"
    fi
    fail "${source_code}"
}

emit() {
    printf 'release_prod event=%s' "$1"
    shift
    if [[ "$#" -gt 0 ]]; then
        printf ' %s' "$@"
    fi
    printf '\n'
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "missing_command_$1"
}

validate_inputs() {
    [[ "$#" -eq 0 ]] || fail positional_arguments_forbidden
    case "${DRY_RUN}" in
        true|false) ;;
        *) fail invalid_dry_run ;;
    esac
    case "${SOURCE_BRANCH}" in
        main) ;;
        release/*)
            [[ "${SOURCE_BRANCH}" =~ ^release/[a-z0-9]+(-[a-z0-9]+)*$ \
                && "${#SOURCE_BRANCH}" -le 128 ]] \
                || fail invalid_source_ref
            ;;
        *) fail invalid_source_ref ;;
    esac
    [[ "${IMAGE_REPOSITORY}" =~ ^[a-z0-9.-]+(:[0-9]+)?(/[a-z0-9]+([._-][a-z0-9]+)*){2,}$ ]] \
        || fail invalid_image_repository
    [[ "${SSH_HOST}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$ ]] \
        || fail invalid_ssh_host
    local forbidden
    for forbidden in \
        DOCKER_AUTH_CONFIG \
        REGISTRY_AUTH_FILE \
        RELEASE_PASSWORD \
        RELEASE_PRIVATE_KEY \
        RELEASE_REGISTRY_PASSWORD \
        RELEASE_SECRET \
        RELEASE_SSH_KEY_FILE \
        RELEASE_SSH_PASSWORD \
        RELEASE_TOKEN; do
        [[ ! -v "${forbidden}" ]] || fail forbidden_secret_input
    done
    local release_variable
    for release_variable in "${!RELEASE_@}"; do
        case "${release_variable}" in
            RELEASE_DRY_RUN|RELEASE_IMAGE_REPOSITORY|RELEASE_SOURCE_REF|RELEASE_SSH_HOST) ;;
            *) fail unsupported_release_environment ;;
        esac
    done
}

cached_source_identity() {
    local origin_url
    origin_url="$(git -C "${PROJECT_ROOT}" remote get-url "${SOURCE_REMOTE}")" \
        || fail origin_url_unavailable
    case "${origin_url}" in
        "${SOURCE_URL}"|"${SOURCE_SSH_URL}") ;;
        "${SOURCE_SSH_ALIAS_URL}") codeup_alias_preflight ;;
        *) fail origin_is_not_authoritative_codeup ;;
    esac
    release_commit="$(git -C "${PROJECT_ROOT}" rev-parse --verify \
        "${SOURCE_TRACKING_REF}^{commit}")" \
        || fail_source cached_source_ref_unavailable cached_origin_main_unavailable
    [[ "${release_commit}" =~ ^[0-9a-f]{40}$ ]] \
        || fail_source cached_source_ref_invalid cached_origin_main_invalid
    git -C "${PROJECT_ROOT}" cat-file -e "${release_commit}^{commit}" \
        || fail_source \
            cached_source_ref_object_missing cached_origin_main_object_missing
}

codeup_alias_preflight() {
    local configuration resolved_hostname resolved_port resolved_user
    configuration="$(ssh "${SSH_OPTIONS[@]}" -G "${SOURCE_SSH_ALIAS}" 2>/dev/null)" \
        || fail codeup_ssh_alias_unavailable
    resolved_hostname="$(printf '%s\n' "${configuration}" \
        | awk '$1 == "hostname" {print $2; exit}')"
    resolved_user="$(printf '%s\n' "${configuration}" \
        | awk '$1 == "user" {print $2; exit}')"
    resolved_port="$(printf '%s\n' "${configuration}" \
        | awk '$1 == "port" {print $2; exit}')"
    [[ "${resolved_hostname}" == "codeup.aliyun.com" \
        && "${resolved_user}" == "git" && "${resolved_port}" == "22" ]] \
        || fail codeup_ssh_alias_not_authoritative
    emit codeup_local_preflight alias_authoritative=true
}

capability_preflight() {
    local command_name
    for command_name in \
        awk bash cmp date docker find flock git install make mktemp scp sed sha256sum ssh ssh-keygen; do
        require_command "${command_name}"
    done
    local docker_endpoint docker_version compose_version
    docker_endpoint="$(docker context inspect --format '{{.Endpoints.docker.Host}}' \
        2>/dev/null)" || fail docker_context_unavailable
    [[ "${docker_endpoint}" == unix:///* ]] || fail nonlocal_docker_context
    docker_version="$(docker info --format '{{.ServerVersion}}' 2>/dev/null)" \
        || fail docker_daemon_unavailable
    [[ "${docker_version}" =~ ^[A-Za-z0-9][A-Za-z0-9._+~-]{0,127}$ ]] \
        || fail invalid_docker_version
    compose_version="$(docker compose version --short 2>/dev/null)" \
        || fail docker_compose_unavailable
    [[ "${compose_version}" =~ ^[A-Za-z0-9][A-Za-z0-9._+~-]{0,127}$ ]] \
        || fail invalid_compose_version
    emit local_docker_preflight \
        "server_version=${docker_version}" "compose_version=${compose_version}"
    ssh_configuration_preflight
}

ssh_configuration_preflight() {
    local configuration resolved_hostname resolved_port known_hosts_files lookup
    configuration="$(ssh "${SSH_OPTIONS[@]}" -G "${SSH_HOST}" 2>/dev/null)" \
        || fail ssh_config_unavailable
    resolved_hostname="$(printf '%s\n' "${configuration}" \
        | awk '$1 == "hostname" {print $2; exit}')"
    resolved_port="$(printf '%s\n' "${configuration}" \
        | awk '$1 == "port" {print $2; exit}')"
    [[ -n "${resolved_hostname}" && "${resolved_hostname}" != "${SSH_HOST}" ]] \
        || fail ssh_alias_not_resolved
    [[ "${resolved_port}" =~ ^[0-9]{1,5}$ ]] \
        && (( resolved_port >= 1 && resolved_port <= 65535 )) \
        || fail ssh_port_invalid
    known_hosts_files="$(printf '%s\n' "${configuration}" | awk '
        $1 == "userknownhostsfile" || $1 == "globalknownhostsfile" {
            for (field = 2; field <= NF; field++) print $field
        }
    ')"
    [[ -n "${HOME:-}" && "${HOME}" == /* ]] || fail home_directory_invalid
    lookup="${resolved_hostname}"
    if [[ "${resolved_port}" != "22" ]]; then
        lookup="[${resolved_hostname}]:${resolved_port}"
    fi
    local known_hosts_file known_host_found="false"
    while IFS= read -r known_hosts_file; do
        [[ -n "${known_hosts_file}" && "${known_hosts_file}" != "none" ]] || continue
        case "${known_hosts_file}" in
            '~/'*) known_hosts_file="${HOME}/${known_hosts_file#\~/}" ;;
            '%d/'*) known_hosts_file="${HOME}/${known_hosts_file#%d/}" ;;
        esac
        [[ -f "${known_hosts_file}" ]] || continue
        if ssh-keygen -F "${lookup}" -f "${known_hosts_file}" >/dev/null 2>&1; then
            known_host_found="true"
            break
        fi
    done <<< "${known_hosts_files}"
    [[ "${known_host_found}" == "true" ]] || fail ssh_known_host_missing
    emit ssh_local_preflight alias_resolved=true known_host=true
}

emit_plan() {
    local source_identity=codeup-origin-release
    if [[ "${SOURCE_BRANCH}" == "main" ]]; then
        source_identity=codeup-origin-main
    fi
    emit plan \
        "commit=${release_commit}" \
        "source=${source_identity}" \
        "source_ref=${SOURCE_HEAD_REF}" \
        stages=fetch,isolated-quality,cached-build,oci-digest,verified-artifacts,strict-ssh,root-deploy \
        mutation=false
}

valid_remote_dir() {
    [[ "${remote_dir}" =~ ^/tmp/edu-ai-release\.${release_commit}\.[A-Za-z0-9]+$ ]]
}

cleanup_remote() {
    [[ -n "${remote_dir}" ]] || return 0
    valid_remote_dir || return 0
    if [[ "${remote_deploy_started}" == "true" \
        && "${remote_deploy_finished}" != "true" ]]; then
        emit remote_cleanup_deferred deploy_status=unknown artifacts_retained=true
        return 0
    fi
    local bundle_name="release-bundle-${release_commit}.tar.gz"
    local members_name="release-bundle-${release_commit}.members.sha256"
    ssh "${SSH_OPTIONS[@]}" "${SSH_HOST}" \
        "rm -f -- ${remote_dir}/${bundle_name} ${remote_dir}/${members_name} ${remote_dir}/release-manifest.json; rmdir -- ${remote_dir}" \
        >/dev/null 2>&1 || true
    remote_dir=""
}

cleanup() {
    local status="$?"
    trap - EXIT
    set +e
    cleanup_remote
    if [[ "${compose_started}" == "true" && -n "${worktree}" && -d "${worktree}" ]]; then
        (
            cd "${worktree}" || exit 0
            docker compose down --volumes --remove-orphans >/dev/null 2>&1
        )
    fi
    if [[ -n "${worktree}" && -d "${worktree}" ]]; then
        git -C "${PROJECT_ROOT}" worktree remove --force "${worktree}" >/dev/null 2>&1
    fi
    if [[ -n "${temporary_root}" ]]; then
        case "${temporary_root}" in
            "${TMPDIR:-/tmp}"/edu-ai-release.*) rm -rf -- "${temporary_root}" ;;
        esac
    fi
    exit "${status}"
}

remote_preflight() {
    ssh "${SSH_OPTIONS[@]}" "${SSH_HOST}" true >/dev/null 2>&1 \
        || fail remote_ssh_preflight_failed
    ssh "${SSH_OPTIONS[@]}" "${SSH_HOST}" \
        "sudo -n ${REMOTE_DEPLOY_ENTRYPOINT} --help >/dev/null" \
        >/dev/null 2>&1 || fail remote_deployer_preflight_failed
    emit remote_preflight_completed host_alias_valid=true deploy_entrypoint=true
}

fetch_and_create_worktree() {
    local previous_commit="${release_commit}"
    GIT_TERMINAL_PROMPT=0 \
    GIT_ASKPASS=/bin/false \
    SSH_ASKPASS=/bin/false \
    GIT_SSH_COMMAND='ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no -o NumberOfPasswordPrompts=0 -o ConnectTimeout=10' \
        git -C "${PROJECT_ROOT}" fetch --quiet --no-tags "${SOURCE_REMOTE}" \
            "${SOURCE_HEAD_REF}:${SOURCE_TRACKING_REF}" </dev/null >/dev/null 2>&1 \
        || fail_source codeup_source_fetch_failed codeup_main_fetch_failed
    release_commit="$(git -C "${PROJECT_ROOT}" rev-parse --verify \
        "${SOURCE_TRACKING_REF}^{commit}")" \
        || fail_source fetched_source_ref_unavailable fetched_origin_main_unavailable
    [[ "${release_commit}" =~ ^[0-9a-f]{40}$ ]] \
        || fail_source fetched_source_ref_invalid fetched_origin_main_invalid
    git -C "${PROJECT_ROOT}" merge-base --is-ancestor \
        "${previous_commit}" "${release_commit}" \
        || fail_source codeup_source_not_fast_forward codeup_main_not_fast_forward
    temporary_root="$(mktemp -d "${TMPDIR:-/tmp}/edu-ai-release.XXXXXX")"
    worktree="${temporary_root}/source"
    git -C "${PROJECT_ROOT}" worktree add --detach "${worktree}" "${release_commit}" \
        >/dev/null
    [[ "$(git -C "${worktree}" rev-parse HEAD)" == "${release_commit}" ]] \
        || fail isolated_worktree_commit_mismatch
    [[ -z "$(git -C "${worktree}" status --porcelain)" ]] \
        || fail isolated_worktree_not_clean
    [[ -f "${PROJECT_ROOT}/scripts/release-prod.sh" \
        && ! -L "${PROJECT_ROOT}/scripts/release-prod.sh" ]] \
        || fail release_orchestrator_not_regular
    cmp -s "${PROJECT_ROOT}/scripts/release-prod.sh" \
        "${worktree}/scripts/release-prod.sh" \
        || fail release_orchestrator_not_committed
    emit source_isolated \
        "commit=${release_commit}" "source_ref=${SOURCE_HEAD_REF}"
}

prepare_toolchains_and_infrastructure() {
    local marker="${release_commit:0:12}"
    export CI_PYTHON_IMAGE="edu-ai-lead-agent-ci-python:git-${marker}"
    export CI_NODE_IMAGE="node:20.20.2-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0"
    unset APP_IMAGE
    export COMPOSE_FILE="${worktree}/compose.yaml"
    export COMPOSE_PROJECT_NAME="edu-ai-release-${marker}"
    export COMPOSE_DISABLE_ENV_FILE=true
    unset COMPOSE_ENV_FILES
    export COMPOSE_PROFILES=""
    export POSTGRES_PORT=0
    export MINIO_API_PORT=0
    export MINIO_CONSOLE_PORT=0
    export POSTGRES_DB=edu_ai
    export POSTGRES_USER=edu_ai
    export POSTGRES_PASSWORD=edu_ai_local_change_me
    export MINIO_ROOT_USER=edu_ai_minio
    export MINIO_ROOT_PASSWORD=edu_ai_minio_local_change_me
    export MINIO_BUCKET=edu-ai-materials
    export AI_PROVIDER_MODE=disabled
    export AI_PLATFORM_API_KEY=""
    export GOVERNANCE_ENABLED=false
    export GOVERNANCE_SCHEDULER_ENABLED=false
    export GOVERNANCE_WORKER_ENABLED=false
    export CONTENT_ENABLED=false
    export CONTENT_SCHEDULER_ENABLED=false
    export CONTENT_WORKER_ENABLED=false
    export CONTENT_SLOT_MODE_ENABLED=false
    export CONTENT_MORNING_ENABLED=false
    export CONTENT_NOON_ENABLED=false
    export CONTENT_EVENING_ENABLED=false
    export IMAGE_ENABLED=false
    export IMAGE_PROVIDER_MODE=disabled
    export IMAGE_SELECTOR_ENABLED=false
    export IMAGE_OCR_ENABLED=false
    export IMAGE_QUALITY_AUDIT_ENABLED=false
    export TOAPIS_API_KEY=""
    export COMFLY_API_KEY=""
    export WECOM_ENABLED=false
    export WECOM_AUTO_DELIVERY_ENABLED=false
    export WECOM_CORP_ID=""
    export WECOM_AGENT_ID=""
    export WECOM_CORP_SECRET=""
    export WECOM_GROUP_WEBHOOK_KEY=""
    export WECOM_DEFAULT_RECIPIENT_ID=""
    export WECOM_DEFAULT_RECIPIENT_NAME=""

    cd "${worktree}"
    docker build --pull --file backend/Dockerfile.ci \
        --tag "${CI_PYTHON_IMAGE}" backend
    mkdir -p .ci-bin
    ln -s ../scripts/ci-python.sh .ci-bin/python
    ln -s ../scripts/ci-node.sh .ci-bin/node
    ln -s ../scripts/ci-node.sh .ci-bin/npm
    export PATH="${worktree}/.ci-bin:${PATH}"
    python -c 'import sys; assert sys.version_info[:2] == (3, 11), sys.version'
    node -e 'if (process.versions.node !== "20.20.2") process.exit(1)'
    CI_NODE_NETWORK=bridge npm ci --prefix frontend

    compose_started="true"
    docker compose up -d --wait --wait-timeout 120 postgres minio
    docker compose run --rm --no-deps minio-init
    local postgres_id
    postgres_id="$(docker compose ps -q postgres)"
    [[ -n "${postgres_id}" ]] || fail release_postgres_container_missing
    export CI_COMPOSE_NETWORK
    CI_COMPOSE_NETWORK="$(docker inspect --format \
        '{{range $network, $_ := .NetworkSettings.Networks}}{{$network}}{{end}}' \
        "${postgres_id}")"
    [[ "${CI_COMPOSE_NETWORK}" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] \
        || fail release_compose_network_invalid
}

run_quality_gates() {
    cd "${worktree}"
    python deploy/release/release_tool.py verify-source \
        --commit "${release_commit}" --repository "${worktree}"
    scripts/ci-python.sh bash scripts/check-python-locks.sh
    make PY_RUN="${worktree}/scripts/ci-python.sh" backend-check
    make PY_RUN="${worktree}/scripts/ci-python.sh" release-tool-check
    make PY_RUN="${worktree}/scripts/ci-python.sh" frontend-check
    docker compose --profile governance --profile content --profile wecom config --quiet
    bash -n scripts/*.sh
    git diff --check
    python deploy/release/release_tool.py scan-committed-secrets \
        --commit "${release_commit}" --repository "${worktree}"
    emit quality_gates_completed "commit=${release_commit}"
}

build_push_and_resolve_image() {
    local marker="${release_commit:0:12}"
    local created="$1"
    local readable_image="${IMAGE_REPOSITORY}:git-${marker}"
    local cache_image="${IMAGE_REPOSITORY}:build-cache"
    local -a cache_args=()

    cd "${worktree}"
    if docker pull "${cache_image}" >/dev/null 2>&1; then
        cache_args=(--cache-from "${cache_image}")
        emit image_cache status=hit
    else
        emit image_cache status=miss
    fi
    docker build --pull "${cache_args[@]}" \
        --build-arg "CODEUP_COMMIT=${release_commit}" \
        --build-arg "SOURCE_URL=${SOURCE_URL}" \
        --build-arg "BUILD_CREATED=${created}" \
        --tag "${readable_image}" backend
    docker run --rm --network none --read-only \
        --tmpfs /tmp:rw,noexec,nosuid,size=16m --user app \
        "${readable_image}" python -m pip check
    docker run --rm --network none --read-only \
        --tmpfs /tmp:rw,noexec,nosuid,size=16m --user app \
        "${readable_image}" python -c \
        'import alembic, fastapi, minio, sqlalchemy; import app.api_main'

    exercise_application_image "${readable_image}" local-candidate

    docker push "${readable_image}"
    docker pull "${readable_image}" >/dev/null

    resolved_image_reference="$(
        docker image inspect "${readable_image}" \
            --format '{{range .RepoDigests}}{{println .}}{{end}}' \
            | awk -v prefix="${IMAGE_REPOSITORY}@" \
                'index($0,prefix)==1 {print; exit}'
    )"
    local digest="${resolved_image_reference#*@}"
    [[ "${resolved_image_reference}" == "${IMAGE_REPOSITORY}@${digest}" ]] \
        && [[ "${digest}" =~ ^sha256:[0-9a-f]{64}$ ]] \
        || fail registry_digest_resolution_failed
    docker pull "${resolved_image_reference}" >/dev/null
    [[ "$(docker image inspect "${resolved_image_reference}" --format \
        '{{index .Config.Labels "org.opencontainers.image.revision"}}')" \
        == "${release_commit}" ]] || fail registry_image_commit_label_mismatch
    [[ "$(docker image inspect "${resolved_image_reference}" --format \
        '{{index .Config.Labels "org.opencontainers.image.source"}}')" \
        == "${SOURCE_URL}" ]] || fail registry_image_source_label_mismatch
    [[ "$(docker image inspect "${resolved_image_reference}" --format \
        '{{index .Config.Labels "org.opencontainers.image.created"}}')" \
        == "${created}" ]] || fail registry_image_created_label_mismatch
    exercise_application_image "${resolved_image_reference}" registry-digest
    docker tag "${readable_image}" "${cache_image}"
    if docker push "${cache_image}" >/dev/null 2>&1; then
        emit image_cache_update status=updated
    else
        emit image_cache_update status=degraded
    fi
    emit image_digest_verified "commit=${release_commit}" "digest=${digest}"
}

exercise_application_image() {
    local image_reference="$1"
    local phase="$2"
    export APP_IMAGE="${image_reference}"
    docker compose run --rm --no-deps backend-migrate
    DOCTOR_PYTHON="${worktree}/.ci-bin/python" make doctor
    emit application_image_exercised "phase=${phase}"
}

build_and_verify_artifacts() {
    local created="$1"
    local image_reference="$2"
    local marker="${release_commit:0:12}"
    local gate_id="developer-pc-${marker}"
    local staged_artifact_dir="${worktree}/dist/release"
    local bundle="${staged_artifact_dir}/release-bundle-${release_commit}.tar.gz"
    local members="${staged_artifact_dir}/release-bundle-${release_commit}.members.sha256"
    local manifest="${staged_artifact_dir}/release-manifest.json"

    cd "${worktree}"
    python deploy/release/release_tool.py build-bundle \
        --commit "${release_commit}" \
        --repository "${worktree}" \
        --output-dir "${staged_artifact_dir}"
    python deploy/release/release_tool.py create-manifest \
        --commit "${release_commit}" \
        --repository "${worktree}" \
        --image "${image_reference}" \
        --source-url "${SOURCE_URL}" \
        --build-timestamp "${created}" \
        --bundle "${bundle}" \
        --gate "api-contract=${gate_id}" \
        --gate "backend=${gate_id}" \
        --gate "compose=${gate_id}" \
        --gate "doctor=${gate_id}" \
        --gate "frontend=${gate_id}" \
        --gate "image-runtime=${gate_id}" \
        --gate "lock-drift=${gate_id}" \
        --gate "secret-scan=${gate_id}" \
        --gate "shell-syntax=${gate_id}" \
        --output "${manifest}"
    python deploy/release/release_tool.py verify-bundle \
        --manifest "${manifest}" \
        --bundle "${bundle}" \
        --expected-commit "${release_commit}"
    [[ -f "${bundle}" && ! -L "${bundle}" ]] || fail release_bundle_missing
    [[ -f "${members}" && ! -L "${members}" ]] || fail member_manifest_missing
    [[ -f "${manifest}" && ! -L "${manifest}" ]] || fail release_manifest_missing
    [[ "$(find "${staged_artifact_dir}" -mindepth 1 -maxdepth 1 -type f | wc -l)" -eq 3 ]] \
        || fail unexpected_release_artifact
    python - "${manifest}" "${members}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
members = Path(sys.argv[2]).read_bytes()
actual = hashlib.sha256(members).hexdigest()
if actual != manifest["bundle"]["member_manifest_sha256"]:
    raise SystemExit("external member manifest checksum mismatch")
PY
    local git_common_dir evidence_root
    git_common_dir="$(git -C "${PROJECT_ROOT}" rev-parse --path-format=absolute --git-common-dir)" \
        || fail git_common_dir_unavailable
    evidence_root="${git_common_dir}/edu-ai-release-evidence/${release_commit}"
    install -d -m 0700 "${git_common_dir}/edu-ai-release-evidence" "${evidence_root}"
    verified_artifact_dir="$(mktemp -d "${evidence_root}/attempt.XXXXXX")"
    chmod 0700 "${verified_artifact_dir}"
    install -m 0600 "${bundle}" "${members}" "${manifest}" "${verified_artifact_dir}/"
    emit release_artifacts_verified \
        "commit=${release_commit}" files=3 local_evidence_retained=true
}

transfer_and_deploy() {
    local artifact_dir="$1"
    local bundle_name="release-bundle-${release_commit}.tar.gz"
    local members_name="release-bundle-${release_commit}.members.sha256"
    local response
    response="$(
        ssh "${SSH_OPTIONS[@]}" "${SSH_HOST}" \
            "umask 077; path=\$(mktemp -d /tmp/edu-ai-release.${release_commit}.XXXXXX) && printf 'REMOTE_DIR=%s\\n' \"\$path\""
    )"
    remote_dir="$(printf '%s\n' "${response}" | sed -n 's/^REMOTE_DIR=//p')"
    [[ "$(printf '%s\n' "${remote_dir}" | wc -l)" -eq 1 ]] \
        && valid_remote_dir || fail invalid_remote_inbox

    scp "${SSH_OPTIONS[@]}" -- \
        "${artifact_dir}/${bundle_name}" \
        "${artifact_dir}/${members_name}" \
        "${artifact_dir}/release-manifest.json" \
        "${SSH_HOST}:${remote_dir}/"
    remote_deploy_started="true"
    local deploy_status
    set +e
    ssh "${SSH_OPTIONS[@]}" "${SSH_HOST}" \
        "sudo -n ${REMOTE_DEPLOY_ENTRYPOINT} --manifest ${remote_dir}/release-manifest.json --bundle ${remote_dir}/${bundle_name} --expected-commit ${release_commit} --runner-id ${DEPLOY_RUNNER_ID}"
    deploy_status="$?"
    set -e
    if [[ "${deploy_status}" -eq 255 || "${deploy_status}" -ge 128 ]]; then
        fail remote_deploy_status_unknown
    fi
    remote_deploy_finished="true"
    [[ "${deploy_status}" -eq 0 ]] || fail remote_deploy_failed
    emit production_deploy_completed "commit=${release_commit}"
}

publish_verified_release() {
    local created="$1"
    build_push_and_resolve_image "${created}"
    build_and_verify_artifacts "${created}" "${resolved_image_reference}"
    transfer_and_deploy "${verified_artifact_dir}"
}

main() {
    cd "${PROJECT_ROOT}"
    validate_inputs "$@"
    capability_preflight
    cached_source_identity
    if [[ "${DRY_RUN}" == "true" ]]; then
        emit_plan
        return 0
    fi

    exec 9>"$(git rev-parse --git-path edu-ai-release.lock)"
    flock -n 9 || fail local_release_lock_held
    trap cleanup EXIT
    remote_preflight
    fetch_and_create_worktree
    prepare_toolchains_and_infrastructure
    run_quality_gates
    local created
    created="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    publish_verified_release "${created}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
