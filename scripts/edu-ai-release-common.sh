#!/usr/bin/env bash

# Shared shell helpers for root-owned production scripts. This file is sourced after each caller
# enables strict mode; it never prints configuration values.

edu_ai_compose() {
    local -a command=(docker compose --env-file .env)
    if [[ -f .release.env ]]; then
        command+=(--env-file .release.env)
    fi
    "${command[@]}" "$@"
}

edu_ai_psql_scalar() {
    local query="$1"
    local encoded_query
    encoded_query="$(printf '%s' "${query}" | base64 --wrap=0)"
    edu_ai_compose exec -T postgres sh -c \
        'printf %s "$1" | base64 -d | psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At' \
        sh "${encoded_query}" \
        | tr -d '\r'
}

edu_ai_env_value() {
    local file="$1"
    local key="$2"
    [[ "${key}" =~ ^[A-Z][A-Z0-9_]*$ ]] || return 2
    awk -F= -v wanted="${key}" \
        '$1 == wanted { value = substr($0, index($0, "=") + 1) } END { print value }' \
        "${file}"
}

edu_ai_sha256_value() {
    sha256sum "$1" | awk '{print $1}'
}
