#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

readonly APP_DIR="/opt/edu-ai-lead-agent"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly EVIDENCE_DIR="/var/lib/edu-ai"
readonly EVIDENCE_FILE="${EVIDENCE_DIR}/deployment-evidence.txt"

cd "${APP_DIR}"
install -d -m 700 "${EVIDENCE_DIR}"
source "${SCRIPT_DIR}/edu-ai-release-common.sh"

psql_scalar() {
    edu_ai_psql_scalar "$1"
}

safe_env_value() {
    local key="$1"
    edu_ai_env_value .env "${key}"
}

release_value() {
    local key="$1"
    edu_ai_env_value .release.env "${key}"
}

for required_file in .release-commit .release.env .release-manifest.json .release-runner; do
    [[ -f "${required_file}" ]] || {
        printf 'evidence_failed reason=missing_release_file file=%s\n' \
            "${required_file#./}" >&2
        exit 1
    }
done

release_commit="$(sed -n '1p' .release-commit)"
release_image="$(release_value APP_IMAGE)"
image_diversity_enabled="$(safe_env_value IMAGE_DIVERSITY_ENABLED)"
image_diversity_enabled="${image_diversity_enabled:-false}"
[[ "${release_commit}" =~ ^[0-9a-f]{40}$ ]] \
    || { printf 'evidence_failed reason=invalid_release_commit\n' >&2; exit 1; }
[[ "${release_image}" =~ ^[^@[:space:]]+@sha256:[0-9a-f]{64}$ ]] \
    || { printf 'evidence_failed reason=invalid_release_image\n' >&2; exit 1; }

tmp_file="$(mktemp "${EVIDENCE_FILE}.XXXXXX")"
trap 'rm -f "${tmp_file}"' EXIT

{
    printf 'generated_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'release_commit=%s\n' "${release_commit}"
    printf 'release_image=%s\n' "${release_image}"
    printf 'release_manifest_sha256=%s\n' \
        "$(edu_ai_sha256_value .release-manifest.json)"
    printf 'release_bundle_sha256=%s\n' "$(release_value RELEASE_BUNDLE_SHA256)"
    printf 'runner_id=%s\n' "$(sed -n '1p' .release-runner)"
    printf 'migration_version=%s\n' "$(psql_scalar 'SELECT version_num FROM alembic_version')"
    printf 'active_sources=%s\n' "$(psql_scalar 'SELECT count(*) FROM sources WHERE active_version_id IS NOT NULL')"
    printf 'daily_topic_selections=%s\n' "$(psql_scalar 'SELECT count(*) FROM daily_topic_selections')"
    printf 'content_slot_mode_enabled=%s\n' "$(safe_env_value CONTENT_SLOT_MODE_ENABLED)"
    printf 'content_morning_enabled=%s\n' "$(safe_env_value CONTENT_MORNING_ENABLED)"
    printf 'content_noon_enabled=%s\n' "$(safe_env_value CONTENT_NOON_ENABLED)"
    printf 'content_evening_enabled=%s\n' "$(safe_env_value CONTENT_EVENING_ENABLED)"
    printf 'wecom_slot_package_gap_seconds=%s\n' "$(safe_env_value WECOM_SLOT_PACKAGE_GAP_SECONDS)"
    printf 'image_diversity_enabled=%s\n' "${image_diversity_enabled}"
    printf 'image_diversity_plan_reservations=%s\n' "$(psql_scalar 'SELECT count(*) FROM image_visual_plan_reservations')"
    printf 'image_diversity_similarity_attempts=%s\n' "$(psql_scalar 'SELECT count(*) FROM image_similarity_attempts')"
    printf 'image_diversity_retry_artifacts=%s\n' "$(psql_scalar 'SELECT count(*) FROM image_artifacts WHERE diversity_retry_count = 1')"
    printf 'image_diversity_warning_artifacts=%s\n' "$(psql_scalar "SELECT count(*) FROM image_artifacts WHERE diversity_warning = 'near_duplicate_after_retry'")"
    printf 'content_slot_runs=%s\n' "$(psql_scalar 'SELECT count(*) FROM content_slot_runs')"
    printf 'content_slot_job_status_counts=%s\n' "$(psql_scalar 'SELECT jsonb_object_agg(status, count) FROM (SELECT status, count(*) AS count FROM content_slot_jobs GROUP BY status) AS counts')"
    printf 'wecom_delivery_windows=%s\n' "$(psql_scalar 'SELECT count(*) FROM wecom_delivery_windows')"
    printf 'wecom_window_gap_range=%s\n' "$(psql_scalar 'SELECT min(package_gap_seconds)::text || chr(58) || max(package_gap_seconds)::text FROM wecom_delivery_windows')"
    printf 'material_packages=%s\n' "$(psql_scalar 'SELECT count(*) FROM material_packages')"
    printf 'wecom_delivery_jobs=%s\n' "$(psql_scalar 'SELECT count(*) FROM wecom_delivery_jobs')"
    printf 'running_services=%s\n' \
        "$(edu_ai_compose ps --format '{{.Service}}={{.State}}' | tr '\n' ',')"
    printf 'backup_timer_enabled=%s\n' "$(systemctl is-enabled edu-ai-backup.timer)"
    printf 'backup_timer_active=%s\n' "$(systemctl is-active edu-ai-backup.timer)"
    printf 'backup_root_mode=%s\n' "$(stat -c '%a %U:%G' /var/backups/edu-ai)"
    printf 'firewall_status=%s\n' "$(ufw status | sed -n '1p')"
} > "${tmp_file}"

install -o root -g root -m 600 "${tmp_file}" "${EVIDENCE_FILE}"
trap - EXIT
rm -f "${tmp_file}"
printf 'evidence_updated file=deployment-evidence.txt\n'
