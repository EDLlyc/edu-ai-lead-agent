#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

readonly APP_DIR="/opt/edu-ai-lead-agent"
readonly ENV_FILE="${APP_DIR}/.env"
readonly BACKUP_ROOT="/var/backups/edu-ai"
readonly MINIO_IMAGE="minio/mc:RELEASE.2025-04-16T18-13-26Z"
readonly TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"

if [[ ! -f "${ENV_FILE}" ]]; then
    printf 'backup_failed reason=missing_env\n' >&2
    exit 1
fi

env_value() {
    local key="$1"
    awk -F= -v wanted="${key}" '$1 == wanted { value = substr($0, index($0, "=") + 1) } END { if (value != "") print value }' "${ENV_FILE}"
}

readonly MINIO_ROOT_USER="$(env_value MINIO_ROOT_USER)"
readonly MINIO_ROOT_PASSWORD="$(env_value MINIO_ROOT_PASSWORD)"
readonly MINIO_BUCKET="$(env_value MINIO_BUCKET)"

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
    container="$(docker compose ps -q "${service}")"
    if [[ -z "${container}" ]] || [[ "$(docker inspect -f '{{.State.Status}}' "${container}")" != "running" ]]; then
        printf 'backup_failed reason=service_not_running service=%s\n' "${service}" >&2
        exit 1
    fi
done

postgres_dump="${BACKUP_ROOT}/postgres/edu-ai-${TIMESTAMP}.dump"
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "${postgres_dump}"
sha256sum "${postgres_dump}" > "${postgres_dump}.sha256"
sha256sum -c "${postgres_dump}.sha256" >/dev/null

minio_container="$(docker compose ps -q minio)"
minio_network="$(docker inspect -f '{{range $network, $_ := .NetworkSettings.Networks}}{{println $network}}{{end}}' "${minio_container}" | head -n 1)"
minio_backup_dir="${BACKUP_ROOT}/minio/${TIMESTAMP}"
install -d -m 700 "${minio_backup_dir}"
docker run --rm \
    --network "${minio_network}" \
    --user 0:0 \
    --entrypoint /bin/sh \
    -e "MC_ACCESS_KEY=${MINIO_ROOT_USER}" \
    -e "MC_SECRET_KEY=${MINIO_ROOT_PASSWORD}" \
    -e "MC_BUCKET=${MINIO_BUCKET}" \
    -v "${minio_backup_dir}:/backup" \
    "${MINIO_IMAGE}" \
    -c '/usr/bin/mc alias set local http://minio:9000 "$MC_ACCESS_KEY" "$MC_SECRET_KEY" >/dev/null && /usr/bin/mc mirror --preserve --quiet "local/$MC_BUCKET" /backup'
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

find "${BACKUP_ROOT}/postgres" -mindepth 1 -maxdepth 1 -type f -mtime +7 -delete
find "${BACKUP_ROOT}/brand-materials" -mindepth 1 -maxdepth 1 -type f -mtime +7 -delete
find "${BACKUP_ROOT}/minio" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf -- {} +

printf 'backup_completed timestamp=%s postgres_bytes=%s minio_files=%s brand_bytes=%s\n' \
    "${TIMESTAMP}" \
    "$(stat -c '%s' "${postgres_dump}")" \
    "$(find "${minio_backup_dir}" -type f ! -name SHA256SUMS | wc -l)" \
    "$(stat -c '%s' "${brand_archive}")"
