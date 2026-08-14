#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly IMAGE="${CI_NODE_IMAGE:?CI_NODE_IMAGE is required}"
readonly INVOKED_AS="$(basename "$0")"
readonly NETWORK="${CI_NODE_NETWORK:-none}"

if [[ ! "${IMAGE}" =~ ^node:20\.[0-9]+\.[0-9]+-bookworm-slim@sha256:[0-9a-f]{64}$ ]]; then
    printf 'ci_node_failed reason=invalid_digest_toolchain_image\n' >&2
    exit 2
fi

case "${NETWORK}" in
    bridge|none) ;;
    *) printf 'ci_node_failed reason=invalid_network\n' >&2; exit 2 ;;
esac

if [[ "${INVOKED_AS}" == "ci-node.sh" ]]; then
    [[ "$#" -gt 0 ]] \
        || { printf 'ci_node_failed reason=missing_command\n' >&2; exit 2; }
    command_name="$1"
    shift
else
    command_name="${INVOKED_AS}"
fi

case "${command_name}" in
    node|npm|npx) ;;
    *) printf 'ci_node_failed reason=command_not_allowed\n' >&2; exit 2 ;;
esac

case "${PWD}" in
    "${PROJECT_ROOT}") container_workdir="/workspace" ;;
    "${PROJECT_ROOT}"/*) container_workdir="/workspace/${PWD#"${PROJECT_ROOT}"/}" ;;
    *) printf 'ci_node_failed reason=working_directory_outside_project\n' >&2; exit 2 ;;
esac

docker_args=(
    run --rm -i
    --user "$(id -u):$(id -g)" \
    --env HOME=/tmp/ci-home \
    --volume "${PROJECT_ROOT}:/workspace" \
    --network "${NETWORK}" \
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
        printf 'ci_node_failed reason=invalid_env_mask_target\n' >&2
        exit 2
    fi
    if [[ -f "${host_env_path}" ]]; then
        docker_args+=(
            --mount "type=bind,source=/dev/null,target=/workspace/${env_path},readonly"
        )
    fi
done

exec docker "${docker_args[@]}" "${IMAGE}" "${command_name}" "$@"
