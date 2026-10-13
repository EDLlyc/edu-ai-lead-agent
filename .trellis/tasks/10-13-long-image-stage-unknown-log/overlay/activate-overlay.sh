#!/usr/bin/env bash
# Recreate ONLY wecom-infographic-producer on the logging overlay image.
# Run as root under /var/lock/edu-ai-deploy.lock, outside slot windows.
# Usage: activate-overlay.sh <stage-dir> <candidate-image-id sha256:...>
# No env file is edited. APP_IMAGE and CONTENT_SCORING_VERSION are overridden for this one
# `compose up` only, so the producer keeps its running scoring env value and the other
# services keep the .release.env image.
set -Eeuo pipefail
cd /opt/edu-ai-lead-agent
backup="$1"; candidate_id="$2"
repo=offline.local/edu-ai/edu-ai-lead-agent-backend
base_id=sha256:da05208214aa273084fd2bccb9ce86dbdc1c0ee2069a855706a5d058686e2df7
svc=wecom-infographic-producer
c=edu-ai-lead-agent-$svc-1
want=f4c86c5868eb2952682f38f9c3e581d1115194ae949c9b093e5ebc23bcdc3a98
compose=(docker compose -p edu-ai-lead-agent --env-file .env --env-file .release.env --profile infographic)

test "$(id -u)" = 0
test -d "$backup" && test ! -L "$backup" && test "$(stat -c '%a:%u:%g' "$backup")" = 700:0:0
test "$(docker inspect $c --format '{{.Image}}')" = "$base_id"
docker image inspect "$repo@$candidate_id" >/dev/null
hm=$(TZ=Asia/Shanghai date +%H%M)
for w in "0555 0640" "1055 1140" "1655 1740"; do set -- $w
  if [ "$hm" -ge "$1" ] && [ "$hm" -le "$2" ]; then echo "slot_window_refuse now=$hm"; exit 3; fi
done
running_ver="$(docker exec $c printenv CONTENT_SCORING_VERSION)"
env_hash() { docker inspect $c --format '{{json .Config.Env}}' | python3 -c 'import json,sys,hashlib
for e in sorted(json.load(sys.stdin)): print(e.split("=",1)[0], hashlib.sha256(e.encode()).hexdigest()[:12])'; }
env_hash > "$backup/env-before.txt"
in_flight() { docker exec edu-ai-lead-agent-postgres-1 psql -X -U edu_ai -d edu_ai -At -v ON_ERROR_STOP=1 -c "select count(*) from news_infographic_jobs where status not in ('ready','sent','failed','result_unknown','skipped','cancelled','rejected','delivered','expired','superseded');"; }

recreate() { APP_IMAGE="$repo@$1" CONTENT_SCORING_VERSION="$running_ver" \
  "${compose[@]}" up -d --no-deps --no-build --pull never --force-recreate "$svc"; }
rollback() {
  status=$?; trap - ERR
  recreate "$base_id" || true
  sleep 5
  test "$(docker inspect $c --format '{{.State.Running}}')" = true
  test "$(docker inspect $c --format '{{.Image}}')" = "$base_id"
  printf 'infographic_stage_log_rolled_back status=%s\n' "$status" >&2
  exit "$status"
}
trap rollback ERR

test "$(in_flight)" = 0
"${compose[@]}" stop -t 60 "$svc"
test "$(in_flight)" = 0
recreate "$candidate_id"
sleep 20
test "$(docker inspect $c --format '{{.State.Running}}')" = true
test "$(docker inspect $c --format '{{.RestartCount}}')" = 0
test "$(docker inspect $c --format '{{.Image}}')" = "$candidate_id"
test "$(docker exec $c sha256sum /app/app/application/services/wecom_news_infographic.py | cut -d' ' -f1)" = "$want"
env_hash > "$backup/env-after.txt"
test "$(diff "$backup/env-before.txt" "$backup/env-after.txt" | wc -l)" = 0
bad_lines="$(docker logs --since 30s $c 2>&1 | grep -c -E 'Traceback|CRITICAL' || true)"
test "$bad_lines" = 0
trap - ERR
printf 'infographic_stage_log_activated services=1 image=%s backup=%s\n' "$candidate_id" "$backup"
