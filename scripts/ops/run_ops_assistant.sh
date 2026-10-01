#!/usr/bin/env bash
# Start the ops assistant page on http://127.0.0.1:4190 (local only).
#
# Needs: the SSH tunnel (scripts/ops/ops_db_tunnel.sh) for the read-only database role, and a
# model key in ~/.config/edu-ai/model.env (0600), for example a key created only for local tools:
#   AI_PLATFORM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
#   AI_PLATFORM_API_KEY=...
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${EDU_AI_PYTHON:-$HOME/anaconda3/envs/edu-ai/bin/python}"
for file in "$HOME/.config/edu-ai/ops-db.${OPS_TARGET:-production}.env" "$HOME/.config/edu-ai/model.env"; do
  if [[ ! -r "$file" ]]; then
    echo "missing $file (see scripts/ops/README.md)" >&2
    exit 2
  fi
  set -a
  # shellcheck disable=SC1090
  . "$file"
  set +a
done
cd "$ROOT/backend"
exec "$PYTHON" -m app.ops_assistant_main --serve "$@"
