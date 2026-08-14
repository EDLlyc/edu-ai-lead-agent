#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

readonly APP_DIR="/opt/edu-ai-lead-agent"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly ENV_FILE="${APP_DIR}/.env"
readonly BACKUP_ROOT="/var/backups/edu-ai"
readonly BACKUP_LOCK="/var/lock/edu-ai-backup.lock"
readonly MINIO_IMAGE="minio/mc:RELEASE.2025-04-16T18-13-26Z"
readonly TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"

exec {backup_lock_fd}>"${BACKUP_LOCK}"
if ! flock --nonblock "${backup_lock_fd}"; then
    printf 'backup_failed reason=backup_lock_busy\n' >&2
    exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
    printf 'backup_failed reason=missing_env\n' >&2
    exit 1
fi

release_common="${SCRIPT_DIR}/edu-ai-release-common.sh"
if [[ ! -f "${release_common}" ]]; then
    # The systemd unit historically invokes an installed /usr/local/sbin copy. Keep that
    # entrypoint compatible while the active, checksum-verified runtime owns the helper.
    release_common="${APP_DIR}/scripts/edu-ai-release-common.sh"
fi
[[ -f "${release_common}" ]] || {
    printf 'backup_failed reason=missing_release_helper\n' >&2
    exit 1
}
source "${release_common}"

readonly MINIO_ROOT_USER="$(edu_ai_env_value "${ENV_FILE}" MINIO_ROOT_USER)"
readonly MINIO_ROOT_PASSWORD="$(edu_ai_env_value "${ENV_FILE}" MINIO_ROOT_PASSWORD)"
readonly MINIO_BUCKET="$(edu_ai_env_value "${ENV_FILE}" MINIO_BUCKET)"

for value in MINIO_ROOT_USER MINIO_ROOT_PASSWORD MINIO_BUCKET; do
    if [[ -z "${!value}" ]]; then
        printf 'backup_failed reason=missing_minio_configuration field=%s\n' "${value}" >&2
        exit 1
    fi
done

cd "${APP_DIR}"
install -d -m 700 "${BACKUP_ROOT}" \
    "${BACKUP_ROOT}/postgres" \
    "${BACKUP_ROOT}/minio" \
    "${BACKUP_ROOT}/brand-materials"

for service in postgres minio; do
    container="$(edu_ai_compose ps -q "${service}")"
    if [[ -z "${container}" ]] || [[ "$(docker inspect -f '{{.State.Status}}' "${container}")" != "running" ]]; then
        printf 'backup_failed reason=service_not_running service=%s\n' "${service}" >&2
        exit 1
    fi
done

postgres_dump="${BACKUP_ROOT}/postgres/edu-ai-${TIMESTAMP}.dump"
edu_ai_compose exec -T postgres sh -c \
    'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "${postgres_dump}"
sha256sum "${postgres_dump}" > "${postgres_dump}.sha256"
sha256sum -c "${postgres_dump}.sha256" >/dev/null

minio_container="$(edu_ai_compose ps -q minio)"
minio_network="$(docker inspect -f '{{range $network, $_ := .NetworkSettings.Networks}}{{println $network}}{{end}}' "${minio_container}" | head -n 1)"
minio_backup_dir="${BACKUP_ROOT}/minio/${TIMESTAMP}"
install -d -m 700 "${minio_backup_dir}"
minio_env_file="$(mktemp "${BACKUP_ROOT}/.minio-env.XXXXXX")"
cleanup_minio_env() {
    rm -f -- "${minio_env_file}"
}
trap cleanup_minio_env EXIT
{
    printf 'MC_ACCESS_KEY=%s\n' "${MINIO_ROOT_USER}"
    printf 'MC_SECRET_KEY=%s\n' "${MINIO_ROOT_PASSWORD}"
    printf 'MC_BUCKET=%s\n' "${MINIO_BUCKET}"
} > "${minio_env_file}"
chmod 600 "${minio_env_file}"
docker run --rm \
    --network "${minio_network}" \
    --user 0:0 \
    --entrypoint /bin/sh \
    --env-file "${minio_env_file}" \
    -v "${minio_backup_dir}:/backup" \
    "${MINIO_IMAGE}" \
    -c '/usr/bin/mc alias set local http://minio:9000 "$MC_ACCESS_KEY" "$MC_SECRET_KEY" >/dev/null && /usr/bin/mc mirror --preserve --quiet "local/$MC_BUCKET" /backup >/dev/null'
cleanup_minio_env
trap - EXIT
(
    cd "${minio_backup_dir}"
    find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
    sha256sum -c SHA256SUMS >/dev/null
)

brand_archive="${BACKUP_ROOT}/brand-materials/brand-materials-${TIMESTAMP}.tar.gz"
tar --create --gzip --file "${brand_archive}" \
    --directory "${APP_DIR}/private" \
    --numeric-owner --owner=0 --group=0 \
    brand-materials
sha256sum "${brand_archive}" > "${brand_archive}.sha256"
sha256sum -c "${brand_archive}.sha256" >/dev/null

release_evidence_dir="${BACKUP_ROOT}/releases/${TIMESTAMP}"
install -d -m 700 "${BACKUP_ROOT}/releases" "${release_evidence_dir}"
release_commit="unknown"
release_image="unknown"
if [[ -f .release-commit ]]; then
    release_commit="$(sed -n '1p' .release-commit)"
fi
if [[ -f .release.env ]]; then
    release_image="$(edu_ai_env_value .release.env APP_IMAGE)"
fi
if [[ "${release_commit}" != "unknown" ]] \
    && [[ ! "${release_commit}" =~ ^[0-9a-f]{40}$ ]]; then
    printf 'backup_failed reason=invalid_release_commit\n' >&2
    exit 1
fi
if [[ "${release_image}" != "unknown" ]] \
    && [[ ! "${release_image}" =~ ^[^@[:space:]]+@sha256:[0-9a-f]{64}$ ]]; then
    printf 'backup_failed reason=invalid_release_image\n' >&2
    exit 1
fi
backup_evidence_tmp="$(mktemp "${release_evidence_dir}/backup-evidence.txt.XXXXXX")"
{
    printf 'schema_version=1\n'
    printf 'backup_id=%s\n' "${TIMESTAMP}"
    printf 'release_commit=%s\n' "${release_commit}"
    printf 'release_image=%s\n' "${release_image}"
    printf 'postgres_file=%s\n' "$(basename "${postgres_dump}")"
    printf 'postgres_sha256=%s\n' "$(edu_ai_sha256_value "${postgres_dump}")"
    printf 'minio_file_count=%s\n' \
        "$(find "${minio_backup_dir}" -type f ! -name SHA256SUMS | wc -l)"
    printf 'minio_manifest_sha256=%s\n' \
        "$(edu_ai_sha256_value "${minio_backup_dir}/SHA256SUMS")"
    printf 'brand_file=%s\n' "$(basename "${brand_archive}")"
    printf 'brand_sha256=%s\n' "$(edu_ai_sha256_value "${brand_archive}")"
} > "${backup_evidence_tmp}"
install -o root -g root -m 600 "${backup_evidence_tmp}" \
    "${release_evidence_dir}/backup-evidence.txt"
rm -f "${backup_evidence_tmp}"

find "${BACKUP_ROOT}/postgres" -mindepth 1 -maxdepth 1 -type f -mtime +7 -delete
find "${BACKUP_ROOT}/brand-materials" -mindepth 1 -maxdepth 1 -type f -mtime +7 -delete
find "${BACKUP_ROOT}/minio" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf -- {} +

printf 'backup_completed backup_id=%s postgres_bytes=%s minio_files=%s brand_bytes=%s\n' \
    "${TIMESTAMP}" \
    "$(stat -c '%s' "${postgres_dump}")" \
    "$(find "${minio_backup_dir}" -type f ! -name SHA256SUMS | wc -l)" \
    "$(stat -c '%s' "${brand_archive}")"
