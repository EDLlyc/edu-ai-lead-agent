#!/usr/bin/env bash
# Activate the acquisition-worker overlay: recreate ONLY acquisition-worker on the new image (shell APP_IMAGE
# override; .release.env stays on the API digest), then swap the admin console build.
# Waits until no acquisition job is running. Any failure restores the previous image and console.
# Nothing here sends a message or calls a model. No --remove-orphans.
# Usage (root): activate.sh <backup-dir> <candidate-image-id sha256:...> <dist-admin dir> <new js file name>
set -Eeuo pipefail
cd /opt/edu-ai-lead-agent
backup="$1"; cand="$2"; dist="$3"; js="$4"
repo=offline.local/edu-ai/edu-ai-lead-agent-backend
base=sha256:da05208214aa273084fd2bccb9ce86dbdc1c0ee2069a855706a5d058686e2df7
w=edu-ai-lead-agent-acquisition-worker-1; pg=edu-ai-lead-agent-postgres-1
www=/var/www/edu-ai-admin
compose=(docker compose -p edu-ai-lead-agent --env-file .env --env-file .release.env)
# acquisition-worker was created while .env still said preview.15 and never reads the scoring version;
# pin it so recreating this one service does not drift its environment (shell env beats --env-file).
export CONTENT_SCORING_VERSION=scoring-v1-preview.15-gov-yaowen-topic-gate
test "$(id -u)" = 0; test "$(docker inspect $w --format '{{.Image}}')" = "$base"
docker image inspect "$repo@$cand" >/dev/null; test -f "$dist/assets/$js"
running() { docker exec $pg sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -tAc "select count(*) from acquisition_jobs where status = '"'"'running'"'"'"'; }
n=0; while [ "$(running)" != 0 ]; do n=$((n+1)); [ "$n" -le 60 ] || { echo "job_wait_timeout"; exit 3; }; sleep 10; done
echo "no_running_job $(TZ=Asia/Shanghai date +%H:%M:%S)"
cp -a compose.yaml "$backup/compose.yaml.before"; cp -a .env "$backup/.env.before"; cp -a .release.env "$backup/.release.env.before"
rm -rf "$backup/www.before"; cp -a "$www" "$backup/www.before"
env_hash() { docker inspect $w --format '{{json .Config.Env}}' | python3 -c 'import json,sys,hashlib
for e in sorted(json.load(sys.stdin)): print(e.split("=",1)[0], hashlib.sha256(e.encode()).hexdigest()[:12])'; }
env_hash > "$backup/env-before.txt"
swapped=0
rollback() { status=$?; trap - ERR; echo "ROLLBACK status=$status" >&2
  if [ "$swapped" = 1 ]; then rm -rf "$www"; cp -a "$backup/www.before" "$www"; fi
  APP_IMAGE="$repo@$base" "${compose[@]}" up -d --no-deps --no-build --pull never --force-recreate acquisition-worker || true
  sleep 10; test "$(docker inspect $w --format '{{.State.Running}}')" = true
  test "$(docker inspect $w --format '{{.Image}}')" = "$base"; exit "$status"; }
trap rollback ERR

APP_IMAGE="$repo@$cand" "${compose[@]}" config -q
APP_IMAGE="$repo@$cand" "${compose[@]}" up -d --no-deps --no-build --pull never --force-recreate acquisition-worker
sleep 10
test "$(docker inspect $w --format '{{.State.Running}}')" = true
test "$(docker inspect $w --format '{{.Image}}')" = "$cand"
env_hash > "$backup/env-after.txt"; diff "$backup/env-before.txt" "$backup/env-after.txt"
test "$(docker inspect $w --format '{{.RestartCount}}')" = 0
test "$(docker inspect edu-ai-lead-agent-acquisition-api-1 --format '{{.Image}}')" != "$cand"
# grep -c exits 1 on zero matches, and set -E would fire the ERR trap inside the substitution
test "$(grep -c "^APP_IMAGE=$repo@$cand" .release.env || true)" = 0
bad="$(docker logs --since 60s $w 2>&1 | grep -c -E 'Traceback|CRITICAL' || true)"; test "$bad" = 0

rm -rf "$www.new"; cp -a "$dist" "$www.new"
chown -R root:root "$www.new"; find "$www.new" -type d -exec chmod 755 {} +; find "$www.new" -type f -exec chmod 644 {} +
mv "$www" "$www.old"; mv "$www.new" "$www"; swapped=1
nginx -t >/dev/null 2>&1
H=(--resolve ops.xiaosaiai.com:443:127.0.0.1)
test "$(curl -sk "${H[@]}" -o /tmp/admin-index.html -w '%{http_code}' https://ops.xiaosaiai.com/admin/)" = 200
grep -q "$js" /tmp/admin-index.html; rm -f /tmp/admin-index.html
test "$(curl -sk "${H[@]}" -o /dev/null -w '%{http_code}' https://ops.xiaosaiai.com/api/v1/admin/auth/me)" = 401
test "$(curl -sk "${H[@]}" -o /dev/null -w '%{http_code}' https://ops.xiaosaiai.com/assets/$js)" = 200
rm -rf "$www.old"
trap - ERR
printf 'acquisition_skip_activated image=%s backup=%s\n' "$cand" "$backup"
