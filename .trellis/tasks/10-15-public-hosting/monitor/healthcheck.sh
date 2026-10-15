#!/usr/bin/env bash
# Local liveness check for the public sites and the production line. Runs every 5 minutes from a
# systemd timer on the host. Read-only: it never restarts anything.
# Alerts (only on a state change, plus a reminder every 6 h while failing) go to the journal
# (`journalctl -t edu-ai-healthcheck`) and, if ALERT_WEBHOOK_URL is set in
# /etc/edu-ai-healthcheck.env, to that WeCom bot webhook. Use an ops-only group, NOT the formal
# news group. Limits: it runs on the same host, so it cannot see a security-group or network outage.
set -uo pipefail
[ -f /etc/edu-ai-healthcheck.env ] && . /etc/edu-ai-healthcheck.env
state=/var/lib/edu-ai-healthcheck; mkdir -p "$state"
problems=()
R="--resolve ops.xiaosaiai.com:443:127.0.0.1 --resolve pgc.xiaosaiai.com:443:127.0.0.1"
code() { curl -s -m 10 -o /dev/null -w '%{http_code}' "$@" || true; }

[ "$(code $R https://ops.xiaosaiai.com/admin/)" = 200 ] || problems+=("ops 后台页面打不开(nginx/证书)")
[ "$(code $R https://pgc.xiaosaiai.com/)" = 302 ] || problems+=("pgc 展台入口异常")
[ "$(code http://127.0.0.1:8000/api/v1/admin/auth/me)" = 401 ] || problems+=("后台接口 acquisition-api 无响应")
[ "$(code http://127.0.0.1:18089/api/v1/visitor-display/snapshot)" = 200 ] || problems+=("展台数据服务 visitor-display 无响应")
EXPECTED="${EXPECTED_CONTAINERS:-acquisition-api acquisition-scheduler acquisition-worker content-scheduler content-worker governance-scheduler governance-worker minio official-account-local-worker official-account-weekly-dag-worker official-account-weekly-scheduler postgres visitor-display wechat-official-account-draft-worker wecom-dispatcher wecom-infographic-producer}"
running="$(docker ps --format '{{.Names}}' 2>/dev/null)"
down=""; for n in $EXPECTED; do echo "$running" | grep -qx "edu-ai-lead-agent-$n-1" || down="$down $n"; done
[ -z "$down" ] || problems+=("容器未运行:$down")
used="$(df --output=pcent / | tail -1 | tr -dc 0-9)"
[ "${used:-0}" -lt 92 ] || problems+=("磁盘已用 ${used}%")
left="$(( ( $(date -d "$(openssl x509 -in /etc/nginx/ssl/xiaosaiai.com.crt -noout -enddate | cut -d= -f2)" +%s) - $(date +%s) ) / 86400 ))"
[ "$left" -gt 14 ] || problems+=("证书还剩 ${left} 天到期，请联系毛老师换新证书")
systemctl is-active --quiet nginx || problems+=("nginx 未运行")

now=$(date +%s); prev="$(cat $state/status 2>/dev/null || echo ok)"; last_alert="$(cat $state/last_alert 2>/dev/null || echo 0)"
notify() {
  logger -t edu-ai-healthcheck -p "$1" "$2"
  if [ -n "${ALERT_WEBHOOK_URL:-}" ]; then
    body="$(python3 -c 'import json,sys; print(json.dumps({"msgtype":"text","text":{"content":sys.argv[1]}}, ensure_ascii=False))' "$2")"
    curl -s -m 10 -H 'Content-Type: application/json' -d "$body" "$ALERT_WEBHOOK_URL" >/dev/null || true
  fi; echo "$now" > $state/last_alert; }
if [ ${#problems[@]} -gt 0 ]; then
  msg="【赛先生网站告警】$(printf '%s; ' "${problems[@]}")"
  if [ "$prev" = ok ] || [ $((now-last_alert)) -ge 21600 ]; then notify user.crit "$msg"; fi
  echo fail > $state/status
else
  if [ "$prev" != ok ]; then notify user.notice "【赛先生网站】已恢复正常"; fi
  echo ok > $state/status
fi
exit 0
