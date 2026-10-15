#!/usr/bin/env bash
# Recreate ONLY acquisition-api on the chosen-password overlay and swap the admin console build.
# Waits for the end of a content slot window (05:55-06:40, 10:55-11:40, 16:55-17:40 CST) instead of refusing.
# Usage (root): activate.sh <backup-dir> <candidate-image-id sha256:...> <dist-admin dir> <new js file name>
# Rollback on any failure: restore compose/.env/.release.env, recreate acquisition-api on the previous image,
# restore the previous console build.
set -Eeuo pipefail
cd /opt/edu-ai-lead-agent
backup="$1"; cand="$2"; dist="$3"; js="$4"
repo=offline.local/edu-ai/edu-ai-lead-agent-backend
base=sha256:e2372099fc74a822f5eafc49c6fba6c9a22829a8b6a79142886f480d5158f255
c=edu-ai-lead-agent-acquisition-api-1
www=/var/www/edu-ai-admin
compose=(docker compose -p edu-ai-lead-agent --env-file .env --env-file .release.env)
test "$(id -u)" = 0; test "$(docker inspect $c --format '{{.Image}}')" = "$base"
docker image inspect "$repo@$cand" >/dev/null; test -f "$dist/assets/$js"
in_window() { hm=$(TZ=Asia/Shanghai date +%H%M)
  for w in "0555 0640" "1055 1140" "1655 1740"; do set -- $w
    if [ "$hm" -ge "$1" ] && [ "$hm" -le "$2" ]; then return 0; fi; done; return 1; }
n=0; while in_window; do n=$((n+1)); [ "$n" -le 240 ] || { echo "window_wait_timeout"; exit 3; }; sleep 30; done
echo "window_clear $(TZ=Asia/Shanghai date +%H:%M:%S)"
cp -a compose.yaml "$backup/compose.yaml.before"; cp -a .env "$backup/.env.before"; cp -a .release.env "$backup/.release.env.before"
rm -rf "$backup/www.before"; cp -a "$www" "$backup/www.before"
env_hash() { docker inspect $c --format '{{json .Config.Env}}' | python3 -c 'import json,sys,hashlib
for e in sorted(json.load(sys.stdin)): print(e.split("=",1)[0], hashlib.sha256(e.encode()).hexdigest()[:12])'; }
env_hash > "$backup/env-before.txt"
swapped=0
rollback() { status=$?; trap - ERR; echo "ROLLBACK status=$status" >&2
  cp -a "$backup/compose.yaml.before" compose.yaml; cp -a "$backup/.env.before" .env
  cp -a "$backup/.release.env.before" .release.env; chmod 600 compose.yaml .env .release.env
  if [ "$swapped" = 1 ]; then rm -rf "$www"; cp -a "$backup/www.before" "$www"; fi
  "${compose[@]}" up -d --no-deps --no-build --pull never --force-recreate acquisition-api || true
  sleep 15; test "$(docker inspect $c --format '{{.State.Running}}')" = true
  test "$(docker inspect $c --format '{{.Image}}')" = "$base"; exit "$status"; }
trap rollback ERR

sed -i "s#^APP_IMAGE=.*#APP_IMAGE=$repo@$cand#" .release.env; chmod 600 .release.env
"${compose[@]}" config -q
"${compose[@]}" up -d --no-deps --no-build --pull never --force-recreate acquisition-api
for i in $(seq 1 40); do
  [ "$(docker inspect $c --format '{{.State.Health.Status}}' 2>/dev/null)" = healthy ] && break; sleep 3; done
test "$(docker inspect $c --format '{{.State.Health.Status}}')" = healthy
test "$(docker inspect $c --format '{{.RestartCount}}')" = 0
test "$(docker inspect $c --format '{{.Image}}')" = "$cand"
env_hash > "$backup/env-after.txt"; diff "$backup/env-before.txt" "$backup/env-after.txt"   # no env change at all
bad="$(docker logs --since 40s $c 2>&1 | grep -c -E 'Traceback|CRITICAL' || true)"; test "$bad" = 0
docker exec $c python -c "
from app.domain.admin_auth import check_new_password, AdminInputError
check_new_password('19900101', username='x')
try: check_new_password('12345678', username='x')
except AdminInputError: print('live_policy_ok')
else: raise SystemExit('common password accepted')"

# console build
rm -rf "$www.new"; cp -a "$dist" "$www.new"
chown -R root:root "$www.new"; find "$www.new" -type d -exec chmod 755 {} +; find "$www.new" -type f -exec chmod 644 {} +
mv "$www" "$www.old"; mv "$www.new" "$www"; swapped=1
nginx -t >/dev/null 2>&1
code=$(curl -sk --resolve ops.xiaosaiai.com:443:127.0.0.1 -o /tmp/admin-index.html -w '%{http_code}' https://ops.xiaosaiai.com/admin/)
test "$code" = 200; grep -q "$js" /tmp/admin-index.html; rm -f /tmp/admin-index.html
test "$(curl -sk --resolve ops.xiaosaiai.com:443:127.0.0.1 -o /dev/null -w '%{http_code}' https://ops.xiaosaiai.com/api/v1/admin/auth/me)" = 401
test "$(curl -sk --resolve ops.xiaosaiai.com:443:127.0.0.1 -o /dev/null -w '%{http_code}' https://ops.xiaosaiai.com/assets/$js)" = 200
rm -rf "$www.old"
trap - ERR
printf 'account_password_activated image=%s backup=%s\n' "$cand" "$backup"
