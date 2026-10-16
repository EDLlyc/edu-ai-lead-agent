#!/usr/bin/env bash
# Activate builtin-phrase overlays.
# Recreates acquisition-api on the API image, upgrades Alembic 0062 -> 0063, recreates
# content-worker and content-scheduler on the worker image (shell APP_IMAGE only; .release.env
# stays on the API digest), then swaps the admin console. Waits out content slot windows.
# Does not send a message. Failure restores the previous images and, if the migration ran,
# downgrades it. Nothing uses --remove-orphans.
# Usage (root): activate.sh <backup-dir> <api-image-id> <worker-image-id> <dist-admin dir> <js name>
set -Eeuo pipefail
cd /opt/edu-ai-lead-agent
backup="$1"; api_cand="$2"; worker_cand="$3"; dist="$4"; js="$5"
repo=offline.local/edu-ai/edu-ai-lead-agent-backend
api_base=sha256:98b9d189dd623b0ff7a8818c481b30e044a911402508c48b43f7c10a1359acfe
worker_base=sha256:a3a3e7f766646415caf89688961e2289daa04fae5a8b0445ca1059f6da485a06
c=edu-ai-lead-agent-acquisition-api-1
w=edu-ai-lead-agent-content-worker-1
s=edu-ai-lead-agent-content-scheduler-1
pg=edu-ai-lead-agent-postgres-1
www=/var/www/edu-ai-admin
compose=(docker compose -p edu-ai-lead-agent --env-file .env --env-file .release.env)
test "$(id -u)" = 0
test "$(docker inspect $c --format '{{.Image}}')" = "$api_base"
test "$(docker inspect $w --format '{{.Image}}')" = "$worker_base"
test "$(docker inspect $s --format '{{.Image}}')" = "$worker_base"
docker image inspect "$repo@$api_cand" >/dev/null
docker image inspect "$repo@$worker_cand" >/dev/null
test -f "$dist/assets/$js"
in_window() { hm=$(TZ=Asia/Shanghai date +%H%M)
  for span in "0555 0640" "1055 1140" "1655 1740"; do set -- $span
    if [ "$hm" -ge "$1" ] && [ "$hm" -le "$2" ]; then return 0; fi; done; return 1; }
n=0; while in_window; do n=$((n+1)); [ "$n" -le 240 ] || { echo "window_wait_timeout"; exit 3; }; sleep 30; done
echo "window_clear $(TZ=Asia/Shanghai date +%H:%M:%S)"
test "$(docker exec $pg sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -tAc "select version_num from alembic_version"')" = 20261015_0062
docker exec $pg sh -c 'pg_dump -U $POSTGRES_USER -d $POSTGRES_DB -Fc' > "$backup/db-before.dump"
test "$(stat -c %s "$backup/db-before.dump")" -gt 1000000; chmod 600 "$backup/db-before.dump"
cp -a compose.yaml "$backup/compose.yaml.before"; cp -a .env "$backup/.env.before"; cp -a .release.env "$backup/.release.env.before"
rm -rf "$backup/www.before"; cp -a "$www" "$backup/www.before"
env_hash() { docker inspect "$1" --format '{{json .Config.Env}}' | python3 -c 'import json,sys,hashlib
for e in sorted(json.load(sys.stdin)): print(e.split("=",1)[0], hashlib.sha256(e.encode()).hexdigest()[:12])'; }
env_hash "$c" > "$backup/env-before.txt"
env_hash "$w" > "$backup/worker-env-before.txt"
env_hash "$s" > "$backup/scheduler-env-before.txt"
swapped=0; migrated=0; workers=0
rollback() { status=$?; trap - ERR; echo "ROLLBACK status=$status" >&2
  if [ "$workers" = 1 ]; then
    APP_IMAGE="$repo@$worker_base" "${compose[@]}" up -d --no-deps --no-build --pull never --force-recreate content-worker content-scheduler || true
  fi
  if [ "$migrated" = 1 ]; then docker exec $c sh -c "cd /app && alembic -c alembic.ini downgrade 20261015_0062" || true; fi
  cp -a "$backup/compose.yaml.before" compose.yaml; cp -a "$backup/.env.before" .env
  cp -a "$backup/.release.env.before" .release.env; chmod 600 compose.yaml .env .release.env
  if [ "$swapped" = 1 ]; then rm -rf "$www"; cp -a "$backup/www.before" "$www"; fi
  "${compose[@]}" up -d --no-deps --no-build --pull never --force-recreate acquisition-api || true
  sleep 15
  test "$(docker inspect $c --format '{{.State.Running}}')" = true
  test "$(docker inspect $c --format '{{.Image}}')" = "$api_base"
  test "$(docker inspect $w --format '{{.Image}}')" = "$worker_base"
  test "$(docker inspect $s --format '{{.Image}}')" = "$worker_base"
  exit "$status"; }
trap rollback ERR

sed -i "s#^APP_IMAGE=.*#APP_IMAGE=$repo@$api_cand#" .release.env; chmod 600 .release.env
"${compose[@]}" config -q
"${compose[@]}" up -d --no-deps --no-build --pull never --force-recreate acquisition-api
for i in $(seq 1 40); do
  [ "$(docker inspect $c --format '{{.State.Health.Status}}' 2>/dev/null)" = healthy ] && break; sleep 3; done
test "$(docker inspect $c --format '{{.State.Health.Status}}')" = healthy
test "$(docker inspect $c --format '{{.Image}}')" = "$api_cand"
env_hash "$c" > "$backup/env-after.txt"; diff "$backup/env-before.txt" "$backup/env-after.txt"
test "$(docker inspect $w --format '{{.Image}}')" = "$worker_base"
test "$(docker inspect $s --format '{{.Image}}')" = "$worker_base"
migrated=1
docker exec $c sh -c "cd /app && alembic -c alembic.ini upgrade head" 2>&1 | tail -5
test "$(docker exec $pg sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -tAc "select version_num from alembic_version"')" = 20261016_0063
test "$(docker exec $pg sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -tAc "select count(*) from builtin_phrase_versions"')" = 0

# Shell APP_IMAGE overrides .release.env for this one command, so the workers do not jump onto the API image.
workers=1
APP_IMAGE="$repo@$worker_cand" "${compose[@]}" up -d --no-deps --no-build --pull never --force-recreate content-worker content-scheduler
sleep 8
test "$(docker inspect $w --format '{{.State.Running}}')" = true
test "$(docker inspect $s --format '{{.State.Running}}')" = true
test "$(docker inspect $w --format '{{.Image}}')" = "$worker_cand"
test "$(docker inspect $s --format '{{.Image}}')" = "$worker_cand"
test "$(docker inspect $c --format '{{.Image}}')" = "$api_cand"
test "$(grep '^APP_IMAGE=' .release.env)" = "APP_IMAGE=$repo@$api_cand"
env_hash "$w" > "$backup/worker-env-after.txt"; diff "$backup/worker-env-before.txt" "$backup/worker-env-after.txt"
env_hash "$s" > "$backup/scheduler-env-after.txt"; diff "$backup/scheduler-env-before.txt" "$backup/scheduler-env-after.txt"
test "$(docker inspect $w --format '{{.RestartCount}}')" = 0
test "$(docker inspect $s --format '{{.RestartCount}}')" = 0
test "$(docker inspect $c --format '{{.RestartCount}}')" = 0
bad="$(docker logs --since 90s $c 2>&1 | grep -c -E 'Traceback|CRITICAL' || true)"; test "$bad" = 0
bad="$(docker logs --since 90s $w 2>&1 | grep -c -E 'Traceback|CRITICAL' || true)"; test "$bad" = 0
bad="$(docker logs --since 90s $s 2>&1 | grep -c -E 'Traceback|CRITICAL' || true)"; test "$bad" = 0

rm -rf "$www.new"; cp -a "$dist" "$www.new"
chown -R root:root "$www.new"; find "$www.new" -type d -exec chmod 755 {} +; find "$www.new" -type f -exec chmod 644 {} +
mv "$www" "$www.old"; mv "$www.new" "$www"; swapped=1
nginx -t >/dev/null 2>&1
H=(--resolve ops.xiaosaiai.com:443:127.0.0.1)
test "$(curl -sk "${H[@]}" -o /tmp/admin-index.html -w '%{http_code}' https://ops.xiaosaiai.com/admin/)" = 200
grep -q "$js" /tmp/admin-index.html; rm -f /tmp/admin-index.html
test "$(curl -sk "${H[@]}" -o /dev/null -w '%{http_code}' https://ops.xiaosaiai.com/api/v1/admin/auth/me)" = 401
test "$(curl -sk "${H[@]}" -o /dev/null -w '%{http_code}' https://ops.xiaosaiai.com/api/v1/admin/builtin-phrases)" = 401
test "$(curl -sk "${H[@]}" -o /dev/null -w '%{http_code}' https://ops.xiaosaiai.com/assets/$js)" = 200
rm -rf "$www.old"
trap - ERR
printf 'builtin_phrases_activated api=%s worker=%s backup=%s\n' "$api_cand" "$worker_cand" "$backup"
