#!/usr/bin/env bash
# Build the chosen-password API overlay on the production host and smoke it offline.
# Usage (root): FIX_COMMIT=<sha> remote-build-smoke.sh <staged dir with Dockerfile, smoke.py, app/> <hashes file>
# <hashes file>: lines "sha8 relative/path" = the expected sha256 prefix of each base file in the RUNNING image.
set -Eeuo pipefail
src="$1"; test "$(id -u)" = 0; cd /opt/edu-ai-lead-agent
commit="${FIX_COMMIT:?}"
base=sha256:e2372099fc74a822f5eafc49c6fba6c9a22829a8b6a79142886f480d5158f255
c=edu-ai-lead-agent-acquisition-api-1
tag="offline.local/edu-ai/edu-ai-lead-agent-backend:account-password-$commit"
test "$(docker inspect $c --format '{{.Image}}')" = "$base"
while read -r sum rel; do
  test "$(docker exec $c sha256sum /app/app/$rel | cut -c1-8)" = "$sum"
done < "$src/base-hashes.txt"
stage="$(mktemp -d /opt/edu-ai-lead-agent/backups/account-password-20261015.XXXXXX)"
chmod 700 "$stage"; cp -a "$src/." "$stage/"; chown -R 0:0 "$stage"; rm -rf "$src"
find "$stage/app" -type d -exec chmod 755 {} +; find "$stage/app" -type f -exec chmod 644 {} +
docker build --network none --pull=false --build-arg "FIX_COMMIT=$commit" -t "$tag" -f "$stage/Dockerfile" "$stage" >/dev/null
image_id="$(docker image inspect "$tag" --format '{{.Id}}')"
docker run --rm -i --network none --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp \
  -e PYTHONDONTWRITEBYTECODE=1 "$tag" python - < "$stage/smoke.py"
printf 'build_smoke_ok stage=%s image_id=%s tag=%s\n' "$stage" "$image_id" "$tag"
