#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly BACKEND_DIR="${PROJECT_ROOT}/backend"
readonly TEMP_DIR="$(mktemp -d)"

restore_locks() {
    for lock_name in runtime.lock dev.lock; do
        if [[ -f "${TEMP_DIR}/${lock_name}" ]]; then
            cp "${TEMP_DIR}/${lock_name}" \
                "${BACKEND_DIR}/requirements/${lock_name}"
        fi
    done
    rm -rf -- "${TEMP_DIR}"
}
trap restore_locks EXIT

for lock_name in runtime.lock dev.lock; do
    [[ -f "${BACKEND_DIR}/requirements/${lock_name}" ]] || {
        printf 'python_lock_drift reason=missing_lock file=%s\n' "${lock_name}" >&2
        exit 1
    }
    cp "${BACKEND_DIR}/requirements/${lock_name}" "${TEMP_DIR}/${lock_name}"
done

(
    cd "${BACKEND_DIR}"
    CUSTOM_COMPILE_COMMAND="make python-lock" "${PROJECT_ROOT}/scripts/compile-python-locks.sh" \
        >/dev/null
)

status=0
for lock_name in runtime.lock dev.lock; do
    if ! cmp -s "${TEMP_DIR}/${lock_name}" "${BACKEND_DIR}/requirements/${lock_name}"; then
        printf 'python_lock_drift file=%s remediation=make_python-lock\n' "${lock_name}" >&2
        diff -u "${TEMP_DIR}/${lock_name}" "${BACKEND_DIR}/requirements/${lock_name}" >&2 || true
        status=1
    fi
    cp "${TEMP_DIR}/${lock_name}" "${BACKEND_DIR}/requirements/${lock_name}"
done

if (( status != 0 )); then
    exit "${status}"
fi

printf 'python_lock_check result=ok\n'
