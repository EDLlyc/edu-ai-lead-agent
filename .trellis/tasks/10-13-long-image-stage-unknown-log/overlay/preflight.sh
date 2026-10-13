#!/usr/bin/env bash
# Read-only pre-flight for the producer logging overlay. Writes nothing, prints no secret values.
set -Eeuo pipefail
cd /opt/edu-ai-lead-agent
c=edu-ai-lead-agent-wecom-infographic-producer-1
base=sha256:da05208214aa273084fd2bccb9ce86dbdc1c0ee2069a855706a5d058686e2df7
printf 'now_cst=%s\n' "$(TZ=Asia/Shanghai date '+%F %T')"
printf 'image=%s running=%s restarts=%s\n' "$(docker inspect $c --format '{{.Image}}')" \
  "$(docker inspect $c --format '{{.State.Running}}')" "$(docker inspect $c --format '{{.RestartCount}}')"
[ "$(docker inspect $c --format '{{.Image}}')" = "$base" ] && echo base_ok || echo base_MISMATCH
printf 'prod_file_sha=%s\n' "$(docker exec $c sha256sum /app/app/application/services/wecom_news_infographic.py | cut -d' ' -f1)"
printf 'errors_has_AppError=%s\n' "$(docker exec $c grep -c '^class AppError' /app/app/core/errors.py)"
echo "--- compose would build the producer with these env names differing from the running one (names only):"
docker compose -p edu-ai-lead-agent --env-file .env --env-file .release.env --profile infographic \
  config --format json | python3 -c '
import json,sys
cfg=json.load(sys.stdin)["services"]["wecom-infographic-producer"]
want={k:str(v) for k,v in (cfg.get("environment") or {}).items()}
print("compose_image_is_APP_IMAGE=", cfg.get("image","")[-20:])
print("compose_command=", cfg.get("command"))
open("/tmp/_want_env.json","w").write(json.dumps(want))
'
docker inspect $c --format '{{json .Config.Env}}' | python3 -c '
import json,sys
have=dict(e.split("=",1) for e in json.load(sys.stdin))
want=json.load(open("/tmp/_want_env.json"))
diff=sorted(k for k in set(want)|set(have) if k in want and have.get(k)!=want[k])
print("env_value_differs_names=",diff)
print("compose_only_names=",sorted(k for k in want if k not in have))
'
rm -f /tmp/_want_env.json
docker exec edu-ai-lead-agent-postgres-1 psql -X -U edu_ai -d edu_ai -At -c \
  "select 'infographic_in_flight='||count(*) from news_infographic_jobs where status not in ('ready','sent','failed','result_unknown','skipped','cancelled','rejected','delivered','expired','superseded');" || true
docker exec edu-ai-lead-agent-postgres-1 psql -X -U edu_ai -d edu_ai -At -c \
  "select status||'='||count(*) from news_infographic_jobs where created_at>now()-interval '3 days' group by status order by 1;" || true
