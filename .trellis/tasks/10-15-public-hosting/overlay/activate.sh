#!/usr/bin/env bash
# Recreate ONLY acquisition-api on the cookie-domain overlay image (the only service that serves
# /api/v1/admin). Scheduler/workers are untouched; .release.env APP_IMAGE moves to the overlay so a
# later plain recreate of acquisition-api cannot silently revert it (the overlay differs from the
# running base only by config.py + admin.py, an additive optional setting).
# Usage (root): activate.sh <backup-dir> <candidate-image-id sha256:...> <cookie-domain>
set -Eeuo pipefail
cd /opt/edu-ai-lead-agent
backup="$1"; cand="$2"; domain="$3"
repo=offline.local/edu-ai/edu-ai-lead-agent-backend
base=sha256:a3a3e7f766646415caf89688961e2289daa04fae5a8b0445ca1059f6da485a06
c=edu-ai-lead-agent-acquisition-api-1
compose=(docker compose -p edu-ai-lead-agent --env-file .env --env-file .release.env)
test "$(id -u)" = 0; test "$(docker inspect $c --format '{{.Image}}')" = "$base"
docker image inspect "$repo@$cand" >/dev/null
hm=$(TZ=Asia/Shanghai date +%H%M)
for w in "0555 0640" "1055 1140" "1655 1740"; do set -- $w
  if [ "$hm" -ge "$1" ] && [ "$hm" -le "$2" ]; then echo "slot_window_refuse now=$hm"; exit 3; fi
done
ts="$(date -u +%Y%m%dT%H%M%SZ)"
cp -a compose.yaml "$backup/compose.yaml.before"; cp -a .env "$backup/.env.before"; cp -a .release.env "$backup/.release.env.before"
env_hash() { docker inspect $c --format '{{json .Config.Env}}' | python3 -c 'import json,sys,hashlib
for e in sorted(json.load(sys.stdin)): print(e.split("=",1)[0], hashlib.sha256(e.encode()).hexdigest()[:12])'; }
env_hash > "$backup/env-before.txt"

restore_files() { cp -a "$backup/compose.yaml.before" compose.yaml; cp -a "$backup/.env.before" .env
  cp -a "$backup/.release.env.before" .release.env; chmod 600 compose.yaml .env .release.env; }
rollback() { status=$?; trap - ERR; echo "ROLLBACK status=$status" >&2; restore_files
  "${compose[@]}" up -d --no-deps --no-build --pull never --force-recreate acquisition-api || true
  sleep 15; test "$(docker inspect $c --format '{{.State.Running}}')" = true
  test "$(docker inspect $c --format '{{.Image}}')" = "$base"; exit "$status"; }
trap rollback ERR

# 1) compose.yaml: pass the new optional setting to acquisition-api only
test "$(grep -c '^      ADMIN_SECRET_KEY:' compose.yaml)" = 1
grep -q 'ADMIN_SESSION_COOKIE_DOMAIN' compose.yaml && { echo "compose already patched"; exit 4; }
sed -i '/^      ADMIN_SECRET_KEY:/a\      ADMIN_SESSION_COOKIE_DOMAIN: ${ADMIN_SESSION_COOKIE_DOMAIN:-}' compose.yaml
# 2) .env / .release.env
grep -q '^ADMIN_SESSION_COOKIE_DOMAIN=' .env || printf 'ADMIN_SESSION_COOKIE_DOMAIN=%s\n' "$domain" >> .env
sed -i "s#^APP_IMAGE=.*#APP_IMAGE=$repo@$cand#" .release.env
chmod 600 compose.yaml .env .release.env
"${compose[@]}" config -q
# 3) recreate acquisition-api only (no deps => no migration run)
"${compose[@]}" up -d --no-deps --no-build --pull never --force-recreate acquisition-api
for i in $(seq 1 40); do
  [ "$(docker inspect $c --format '{{.State.Health.Status}}' 2>/dev/null)" = healthy ] && break; sleep 3; done
test "$(docker inspect $c --format '{{.State.Health.Status}}')" = healthy
test "$(docker inspect $c --format '{{.RestartCount}}')" = 0
test "$(docker inspect $c --format '{{.Image}}')" = "$cand"
env_hash > "$backup/env-after.txt"
# only expected change: the one new name
diff "$backup/env-before.txt" "$backup/env-after.txt" | grep '^[<>]' | awk '{print $1, $2}' > "$backup/env-diff.txt" || true
cat "$backup/env-diff.txt"
test "$(grep -c '^< ' "$backup/env-diff.txt" || true)" = 0
test "$(grep -c '^> ' "$backup/env-diff.txt")" = 1; grep -q '^> ADMIN_SESSION_COOKIE_DOMAIN' "$backup/env-diff.txt"
test "$(docker exec $c printenv ADMIN_SESSION_COOKIE_DOMAIN)" = "$domain"
bad="$(docker logs --since 40s $c 2>&1 | grep -c -E 'Traceback|CRITICAL' || true)"; test "$bad" = 0
# 4) behaviour: the cookie must carry Domain= and Path=/ (login with a wrong password sets nothing, so
#    check the settings object inside the live container instead of authenticating)
docker exec $c python -c "
from app.core.config import Settings; from app.api.v1.routes import admin
s=Settings(); assert s.admin_session_cookie_domain=='$domain' and admin._cookie_path(s)=='/'; print('live_cookie_settings_ok')"
trap - ERR
printf 'admin_cookie_domain_activated image=%s backup=%s\n' "$cand" "$backup"
