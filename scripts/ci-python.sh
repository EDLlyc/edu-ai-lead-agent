#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly IMAGE="${CI_PYTHON_IMAGE:?CI_PYTHON_IMAGE is required}"
readonly INVOKED_AS="$(basename "$0")"
readonly COMPOSE_NETWORK="${CI_COMPOSE_NETWORK:-}"

if [[ ! "${IMAGE}" =~ ^edu-ai-lead-agent-ci-python:git-[0-9a-f]{12}$ ]]; then
    printf 'ci_python_failed reason=invalid_local_toolchain_image\n' >&2
    exit 2
fi

if [[ "${INVOKED_AS}" == "ci-python.sh" ]]; then
    [[ "$#" -gt 0 ]] \
        || { printf 'ci_python_failed reason=missing_command\n' >&2; exit 2; }
    command_name="$1"
    shift
else
    command_name="${INVOKED_AS}"
fi

case "${command_name}" in
    alembic|bash|mypy|pip-compile|pytest|python|ruff) ;;
    *) printf 'ci_python_failed reason=command_not_allowed\n' >&2; exit 2 ;;
esac

case "${PWD}" in
    "${PROJECT_ROOT}") container_workdir="/workspace" ;;
    "${PROJECT_ROOT}"/*) container_workdir="/workspace/${PWD#"${PROJECT_ROOT}"/}" ;;
    *) printf 'ci_python_failed reason=working_directory_outside_project\n' >&2; exit 2 ;;
esac

docker_args=(
    run --rm -i
    --user "$(id -u):$(id -g)" \
    --env HOME=/tmp/ci-home \
    --env PYTHONPATH=/workspace/backend \
    --volume "${PROJECT_ROOT}:/workspace" \
    --workdir "${container_workdir}" \
    --tmpfs /tmp:rw,noexec,nosuid,size=1g
)

for env_path in \
    .env \
    .env.local \
    backend/.env \
    frontend/.env \
    frontend/.env.local \
    frontend/.env.development \
    frontend/.env.development.local \
    frontend/.env.production \
    frontend/.env.production.local \
    frontend/.env.test \
    frontend/.env.test.local; do
    host_env_path="${PROJECT_ROOT}/${env_path}"
    if [[ -L "${host_env_path}" ]] || {
        [[ -e "${host_env_path}" ]] && [[ ! -f "${host_env_path}" ]]
    }; then
        printf 'ci_python_failed reason=invalid_env_mask_target\n' >&2
        exit 2
    fi
    if [[ -f "${host_env_path}" ]]; then
        docker_args+=(
            --mount "type=bind,source=/dev/null,target=/workspace/${env_path},readonly"
        )
    fi
done

if [[ -n "${COMPOSE_NETWORK}" ]]; then
    if [[ ! "${COMPOSE_NETWORK}" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]]; then
        printf 'ci_python_failed reason=invalid_compose_network\n' >&2
        exit 2
    fi
    docker_args+=(
        --network "${COMPOSE_NETWORK}"
        --env DATABASE_URL=postgresql+asyncpg://edu_ai:edu_ai_local_change_me@postgres:5432/edu_ai
        --env GOVERNANCE_CHECKPOINT_DATABASE_URL=postgresql://edu_ai:edu_ai_local_change_me@postgres:5432/edu_ai
        --env MINIO_ENDPOINT=http://minio:9000
        --env MINIO_BUCKET=edu-ai-materials
        --env MINIO_SECURE=false
        --env MINIO_ACCESS_KEY=edu_ai_minio
        --env MINIO_SECRET_KEY=edu_ai_minio_local_change_me
        --env AI_PROVIDER_MODE=disabled
        --env GOVERNANCE_ENABLED=false
        --env CONTENT_ENABLED=false
        --env WECOM_ENABLED=false
    )
else
    docker_args+=(--network none)
fi

exec docker "${docker_args[@]}" "${IMAGE}" "${command_name}" "$@"
