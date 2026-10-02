#!/usr/bin/env bash
# Start one of the local stdio MCP servers for Claude Code (or any MCP client).
#
#   scripts/ops/run_mcp.sh ops                      # read-only ops tools (needs the tunnel for production)
#   scripts/ops/run_mcp.sh ops --transport http     # the same over Streamable HTTP on 127.0.0.1:8765
#                                                   # (token from ~/.config/edu-ai/ops-mcp.token)
#   scripts/ops/run_mcp.sh repair                   # copy repair tools on the offline fixture draft
#   scripts/ops/run_mcp.sh repair --copy-run-id ID  # repair tools on a real run's latest draft
#   scripts/ops/run_mcp.sh workbench                # read-only research workbench (offline fixture)
#
# OPS_TARGET=production (default) reads ~/.config/edu-ai/ops-db.production.env; OPS_TARGET=local
# reads the local development role. The connection string never enters the repository.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${EDU_AI_PYTHON:-$HOME/anaconda3/envs/edu-ai/bin/python}"
TARGET="${OPS_TARGET:-production}"
SERVER="${1:?usage: run_mcp.sh ops|repair|workbench [args]}"
shift

load_ops_env() {
  local file="$HOME/.config/edu-ai/ops-db.${TARGET}.env"
  if [[ ! -r "$file" ]]; then
    echo "missing $file; run scripts/ops/ops_readonly_role.py --target ${TARGET}" >&2
    exit 2
  fi
  set -a
  # shellcheck disable=SC1090
  . "$file"
  set +a
}

cd "$ROOT/backend"
export APP_ENV=development AI_PROVIDER_MODE=fake
case "$SERVER" in
  ops)
    load_ops_env
    if [[ " $* " == *" --transport http "* && -z "${OPS_MCP_TOKEN:-}" ]]; then
      token_file="$HOME/.config/edu-ai/ops-mcp.token"
      if [[ ! -r "$token_file" ]]; then
        echo "missing $token_file (see scripts/ops/README.md, HTTP 方式)" >&2
        exit 2
      fi
      OPS_MCP_TOKEN="$(<"$token_file")"
      export OPS_MCP_TOKEN
    fi
    exec "$PYTHON" -m app.ops_mcp_main "$@"
    ;;
  repair)
    if [[ " $* " == *" --copy-run-id "* ]]; then
      load_ops_env
    fi
    exec "$PYTHON" -m app.copy_repair_mcp_main "$@"
    ;;
  workbench)
    exec "$PYTHON" -m app.agent_mcp_main "$@"
    ;;
  *)
    echo "unknown server: $SERVER" >&2
    exit 2
    ;;
esac
