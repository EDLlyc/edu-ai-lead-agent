#!/usr/bin/env bash
# Build the admin-cookie-domain API overlay on the production host and smoke it offline.
# Usage (root): FIX_COMMIT=<sha> remote-build-smoke.sh <staged dir with Dockerfile, smoke.py, app/>
# Verifies the running base files first (so the overlay only replaces what we expect), touches no
# running container, env file or schema.
set -Eeuo pipefail
src="$1"; test "$(id -u)" = 0; cd /opt/edu-ai-lead-agent
commit="${FIX_COMMIT:?}"
base=sha256:a3a3e7f766646415caf89688961e2289daa04fae5a8b0445ca1059f6da485a06
c=edu-ai-lead-agent-acquisition-api-1
tag="offline.local/edu-ai/edu-ai-lead-agent-backend:admin-cookie-domain-$commit"
# base files in the running containers must be the ones this overlay was written against
for svc in acquisition-api content-scheduler content-worker; do
  cn=edu-ai-lead-agent-$svc-1
  test "$(docker inspect $cn --format '{{.Image}}')" = "$base"
  cfg="$(docker exec $cn sha256sum /app/app/core/config.py | cut -c1-8)"
  adm="$(docker exec $cn sha256sum /app/app/api/v1/routes/admin.py | cut -c1-8)"
  test "$cfg" = bdc046bb && test "$adm" = 68aa6ace
done
stage="$(mktemp -d /opt/edu-ai-lead-agent/backups/admin-cookie-domain-20261015.XXXXXX)"
chmod 700 "$stage"; cp -a "$src/." "$stage/"; chown -R 0:0 "$stage"; rm -rf "$src"
test "$(sha256sum "$stage/app/core/config.py" | cut -c1-8)" = 960fd930
test "$(sha256sum "$stage/app/api/v1/routes/admin.py" | cut -c1-8)" = f6793f2d
find "$stage/app" -type d -exec chmod 755 {} +; find "$stage/app" -type f -exec chmod 644 {} +
docker build --network none --pull=false --build-arg "FIX_COMMIT=$commit" -t "$tag" -f "$stage/Dockerfile" "$stage" >/dev/null
image_id="$(docker image inspect "$tag" --format '{{.Id}}')"
docker run --rm -i --network none --read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp \
  -e PYTHONDONTWRITEBYTECODE=1 "$tag" python - < "$stage/smoke.py"
printf 'build_smoke_ok stage=%s image_id=%s tag=%s\n' "$stage" "$image_id" "$tag"
