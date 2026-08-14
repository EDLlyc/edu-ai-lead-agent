#!/usr/bin/env bash
set -Eeuo pipefail

readonly DEPLOY_ENTRYPOINT="/opt/edu-ai-lead-agent/deploy/release/deploy.py"

[[ -f "${DEPLOY_ENTRYPOINT}" ]] || {
    printf 'deployment_entrypoint_failed code=active_deployer_missing\n' >&2
    exit 2
}

exec python3 "${DEPLOY_ENTRYPOINT}" "$@"
