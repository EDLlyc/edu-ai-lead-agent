#!/usr/bin/env bash
# Forward 127.0.0.1:15432 on this machine to the production database, which listens only on the
# server's own 127.0.0.1:5432. Nothing is exposed publicly; the traffic rides the SSH session.
# Use it with the SELECT-only role from ops_readonly_role.py (never the application's account).
#
#   scripts/ops/ops_db_tunnel.sh        # foreground; Ctrl-C closes the tunnel
set -euo pipefail

LOCAL_PORT="${OPS_TUNNEL_PORT:-15432}"
exec ssh -N \
  -o BatchMode=yes \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L "127.0.0.1:${LOCAL_PORT}:127.0.0.1:5432" \
  edu-ai-production
