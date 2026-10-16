#!/usr/bin/env bash
# Build the acquisition-worker overlay on the production host and smoke it offline (touches nothing running).
# Usage (root): FIX_COMMIT=<label> remote-build-smoke.sh <staged dir>
set -Eeuo pipefail
src="$1"; test "$(id -u)" = 0; cd /opt/edu-ai-lead-agent
commit="${FIX_COMMIT:?}"
base=sha256:da05208214aa273084fd2bccb9ce86dbdc1c0ee2069a855706a5d058686e2df7
w=edu-ai-lead-agent-acquisition-worker-1
tag="offline.local/edu-ai/edu-ai-lead-agent-backend:acquisition-skip-$commit"
test "$(docker inspect $w --format '{{.Image}}')" = "$base"
while read -r sum rel; do test "$(docker exec $w sha256sum /app/$rel | cut -c1-8)" = "$sum"; done < "$src/base-hashes.txt"
stage="$(mktemp -d /opt/edu-ai-lead-agent/backups/acquisition-skip-20261016.XXXXXX)"
chmod 700 "$stage"; cp -a "$src/." "$stage/"; chown -R 0:0 "$stage"; rm -rf "$src"
find "$stage" -type d -exec chmod 755 {} +; find "$stage" -type f -exec chmod 644 {} +
docker build --network none --pull=false --build-arg "FIX_COMMIT=$commit" -t "$tag" -f "$stage/Dockerfile" "$stage" >/dev/null
image_id="$(docker image inspect "$tag" --format '{{.Id}}')"
docker run --rm -i --network none --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp \
  -e PYTHONDONTWRITEBYTECODE=1 "$tag" python - < "$stage/smoke.py"
printf 'build_smoke_ok stage=%s image_id=%s\n' "$stage" "$image_id"
