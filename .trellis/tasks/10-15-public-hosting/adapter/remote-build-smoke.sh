#!/usr/bin/env bash
# Build the exhibit adapter image on the production host and smoke it offline.
# Usage (root): FIX_COMMIT=<sha> remote-build-smoke.sh <staged-dir with Dockerfile, smoke.py, backend/, TREE.sha256>
set -Eeuo pipefail
src="$1"; test "$(id -u)" = 0; cd /opt/edu-ai-lead-agent
commit="${FIX_COMMIT:?}"; tree="$(cat "$src/TREE.sha256")"
tag="offline.local/edu-ai/edu-ai-lead-agent-backend:visitor-display-$commit"
stage="$(mktemp -d /opt/edu-ai-lead-agent/backups/visitor-display-20261015.XXXXXX)"; chmod 700 "$stage"
cp -a "$src/." "$stage/"; chown -R 0:0 "$stage"; rm -rf "$src"
(cd "$stage/backend" && test "$(find app -type f | sort | xargs sha256sum | sha256sum | cut -d' ' -f1)" = "$tree")
find "$stage/backend" -type d -exec chmod 755 {} +; find "$stage/backend" -type f -exec chmod 644 {} +
docker build --network none --pull=false --build-arg "FIX_COMMIT=$commit" --build-arg "TREE_SHA256=$tree" -t "$tag" -f "$stage/Dockerfile" "$stage" >/dev/null
image_id="$(docker image inspect "$tag" --format '{{.Id}}')"
docker run --rm -i --network none --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp \
  -e PYTHONDONTWRITEBYTECODE=1 "$tag" python - < "$stage/smoke.py"
printf 'build_smoke_ok stage=%s image_id=%s tag=%s\n' "$stage" "$image_id" "$tag"
