#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

readonly APP_DIR="/opt/edu-ai-lead-agent"
readonly EVIDENCE_DIR="/var/lib/edu-ai"
readonly EVIDENCE_FILE="${EVIDENCE_DIR}/deployment-evidence.txt"

cd "${APP_DIR}"
install -d -m 700 "${EVIDENCE_DIR}"

psql_scalar() {
    docker compose exec -T postgres sh -c \
        "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -Atc '$1'" \
        | tr -d '\r'
}

tmp_file="$(mktemp "${EVIDENCE_FILE}.XXXXXX")"
trap 'rm -f "${tmp_file}"' EXIT

{
    printf 'generated_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'release_commit=%s\n' "$(sed -n '1p' .release-commit)"
    printf 'migration_version=%s\n' "$(psql_scalar 'SELECT version_num FROM alembic_version')"
    printf 'active_sources=%s\n' "$(psql_scalar 'SELECT count(*) FROM sources WHERE active_version_id IS NOT NULL')"
    printf 'daily_topic_selections=%s\n' "$(psql_scalar 'SELECT count(*) FROM daily_topic_selections')"
    printf 'material_packages=%s\n' "$(psql_scalar 'SELECT count(*) FROM material_packages')"
    printf 'wecom_delivery_jobs=%s\n' "$(psql_scalar 'SELECT count(*) FROM wecom_delivery_jobs')"
    printf 'running_services=%s\n' "$(docker compose ps --format '{{.Service}}={{.State}}' | tr '\n' ',')"
    printf 'backup_timer_enabled=%s\n' "$(systemctl is-enabled edu-ai-backup.timer)"
    printf 'backup_timer_active=%s\n' "$(systemctl is-active edu-ai-backup.timer)"
    printf 'backup_root_mode=%s\n' "$(stat -c '%a %U:%G' /var/backups/edu-ai)"
    printf 'firewall_status=%s\n' "$(ufw status | sed -n '1p')"
} > "${tmp_file}"

install -o root -g root -m 600 "${tmp_file}" "${EVIDENCE_FILE}"
trap - EXIT
rm -f "${tmp_file}"
printf 'evidence_updated file=deployment-evidence.txt\n'
