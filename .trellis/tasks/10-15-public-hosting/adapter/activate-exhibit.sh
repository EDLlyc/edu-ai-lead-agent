#!/usr/bin/env bash
# Start the exhibit data service (visitor-display) on the production host. Run as root in
# /opt/edu-ai-lead-agent after remote-build-smoke.sh. Additive only: touches no existing service.
# Creates a SELECT-only Postgres role, appends three new names to .env (backup first), starts the
# service on 127.0.0.1:18089 and smokes the snapshot endpoint. Never prints secret values.
set -Eeuo pipefail
test "$(id -u)" = 0; cd /opt/edu-ai-lead-agent
override="${1:?path to compose.visitor-display.yaml}"
image="offline.local/edu-ai/edu-ai-lead-agent-backend:visitor-display-${FIX_COMMIT:?}"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
docker image inspect "$image" >/dev/null
cp -a .env ".env.before-visitor-display-$ts"
install -m 600 -o root -g root "$override" compose.visitor-display.yaml
compose=(docker compose -p edu-ai-lead-agent --env-file .env --env-file .release.env -f compose.yaml -f compose.visitor-display.yaml --profile exhibit)
rollback() { echo "ROLLBACK: restoring .env" >&2; "${compose[@]}" rm -sf visitor-display >/dev/null 2>&1 || true
  cp -a ".env.before-visitor-display-$ts" .env; }
trap rollback ERR

have() { grep -q "^$1=" .env; }
if ! have VISITOR_DISPLAY_ASSET_SECRET; then printf 'VISITOR_DISPLAY_ASSET_SECRET=%s\n' "$(openssl rand -hex 32)" >> .env; fi
ro_pw="$(openssl rand -hex 24)"
if ! have VISITOR_DISPLAY_DB_USER; then
  # SELECT-only role (tables now and later); password goes via stdin, never on a command line.
  docker exec -i edu-ai-lead-agent-postgres-1 sh -c 'psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='visitor_ro') THEN CREATE ROLE visitor_ro LOGIN; END IF;
END \$\$;
ALTER ROLE visitor_ro WITH LOGIN PASSWORD '$ro_pw' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION CONNECTION LIMIT 10;
ALTER ROLE visitor_ro SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE "$(grep '^POSTGRES_DB=' .env | cut -d= -f2-)" TO visitor_ro;
GRANT USAGE ON SCHEMA public TO visitor_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO visitor_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO visitor_ro;
SQL
  printf 'VISITOR_DISPLAY_DB_USER=visitor_ro\nVISITOR_DISPLAY_DB_PASSWORD=%s\n' "$ro_pw" >> .env
fi
chmod 600 .env

VISITOR_DISPLAY_IMAGE="$image" "${compose[@]}" up -d --no-deps --no-build --pull never visitor-display
for i in $(seq 1 30); do
  code="$(curl -s -o /tmp/vd-snapshot.json -w '%{http_code}' http://127.0.0.1:18089/api/v1/visitor-display/snapshot || true)"
  [ "$code" = 200 ] && break; sleep 2
done
echo "snapshot_http=$code bytes=$(wc -c < /tmp/vd-snapshot.json)"
test "$code" = 200
python3 - <<'PY'
import json; d = json.load(open('/tmp/vd-snapshot.json'))
print('snapshot_keys=', sorted(d)[:12] if isinstance(d, dict) else type(d).__name__)
PY
rm -f /tmp/vd-snapshot.json
# operator routes must not exist on this process
for p in /api/v1/admin/auth/me /api/v1/visitor-display/operator; do
  printf 'probe %s -> %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:18089$p")"; done
docker ps --filter name=visitor-display --format '{{.Names}} {{.Status}}'
trap - ERR
echo "exhibit_service_ok backup=.env.before-visitor-display-$ts"
