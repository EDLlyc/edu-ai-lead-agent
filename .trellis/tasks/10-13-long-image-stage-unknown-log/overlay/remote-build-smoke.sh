#!/usr/bin/env bash
# Build the producer logging overlay on the production host and smoke it with networking disabled.
# Usage (root): remote-build-smoke.sh <staged-dir-with-Dockerfile-and-app/>
# Touches no running container, no env file and no schema.
set -Eeuo pipefail
src="$1"
test "$(id -u)" = 0
cd /opt/edu-ai-lead-agent
commit="${FIX_COMMIT:?}"
tag="offline.local/edu-ai/edu-ai-lead-agent-backend:infographic-stage-log-$commit"
want=f4c86c5868eb2952682f38f9c3e581d1115194ae949c9b093e5ebc23bcdc3a98
stage="$(mktemp -d /opt/edu-ai-lead-agent/backups/infographic-stage-log-20261013.XXXXXX)"
chmod 700 "$stage"; cp -a "$src/." "$stage/"; chown -R 0:0 "$stage"; rm -rf "$src"
f=app/application/services/wecom_news_infographic.py
test "$(sha256sum "$stage/$f" | cut -d' ' -f1)" = "$want"; chmod 644 "$stage/$f"
docker build --network none --pull=false --build-arg "FIX_COMMIT=$commit" -t "$tag" -f "$stage/Dockerfile" "$stage" >/dev/null
image_id="$(docker image inspect "$tag" --format '{{.Id}}')"
docker run --rm -i --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp -e PYTHONDONTWRITEBYTECODE=1 "$tag" python - <<'PY'
import importlib
importlib.import_module("app.wecom_news_infographic_main")
from types import SimpleNamespace
from app.application.services import wecom_news_infographic as m
from app.core.errors import ImageProviderRejectedError
e = ImageProviderRejectedError(http_status=400, response_kind="json")
assert m._safe_error_code(e) == "image_provider_rejected"
assert (m._safe_http_status(e), m._safe_response_kind(e)) == (400, "json")
assert m._safe_error_code(RuntimeError("secret")) is None
assert m._safe_http_status(SimpleNamespace(http_status=True)) is None
print("overlay_import_and_helpers_ok")
PY
printf 'build_smoke_ok stage=%s image_id=%s tag=%s\n' "$stage" "$image_id" "$tag"
