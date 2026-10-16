#!/usr/bin/env bash
# Build the API and content-worker overlays on the production host and smoke them offline.
# Touches nothing that is running. Usage (root): FIX_COMMIT=<label> remote-build-smoke.sh <staged dir>
set -Eeuo pipefail
src="$1"; test "$(id -u)" = 0; cd /opt/edu-ai-lead-agent
commit="${FIX_COMMIT:?}"
repo=offline.local/edu-ai/edu-ai-lead-agent-backend
api_base=sha256:98b9d189dd623b0ff7a8818c481b30e044a911402508c48b43f7c10a1359acfe
worker_base=sha256:a3a3e7f766646415caf89688961e2289daa04fae5a8b0445ca1059f6da485a06
api=edu-ai-lead-agent-acquisition-api-1
worker=edu-ai-lead-agent-content-worker-1
test "$(docker inspect $api --format '{{.Image}}')" = "$api_base"
test "$(docker inspect $worker --format '{{.Image}}')" = "$worker_base"
test "$(docker inspect edu-ai-lead-agent-content-scheduler-1 --format '{{.Image}}')" = "$worker_base"
while read -r sum rel; do test "$(docker exec $api sha256sum /app/$rel | cut -c1-8)" = "$sum"; done < "$src/api/base-hashes.txt"
while read -r sum rel; do test "$(docker exec $worker sha256sum /app/$rel | cut -c1-8)" = "$sum"; done < "$src/worker/base-hashes.txt"
stage="$(mktemp -d /opt/edu-ai-lead-agent/backups/builtin-phrases-20261016.XXXXXX)"
chmod 700 "$stage"; cp -a "$src/." "$stage/"; chown -R 0:0 "$stage"; rm -rf "$src"
find "$stage" -type d -exec chmod 755 {} +; find "$stage" -type f -exec chmod 644 {} +
build() {
  local name="$1" base_tag="$2"
  docker build --network none --pull=false --build-arg "FIX_COMMIT=$commit" -t "$base_tag" -f "$stage/$name/Dockerfile" "$stage/$name" >/dev/null
  local image_id
  image_id="$(docker image inspect "$base_tag" --format '{{.Id}}')"
  docker run --rm -i --network none --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp \
    -e PYTHONDONTWRITEBYTECODE=1 "$base_tag" python - < "$stage/$name/smoke.py"
  printf '%s_image=%s\n' "$name" "$image_id"
}
build api "$repo:builtin-phrases-api-$commit"
build worker "$repo:builtin-phrases-worker-$commit"
printf 'build_smoke_ok stage=%s\n' "$stage"
