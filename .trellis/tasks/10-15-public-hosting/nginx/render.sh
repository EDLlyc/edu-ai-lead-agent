#!/usr/bin/env bash
# Render the two nginx server files for xiaosaiai.com into <outdir>. No secrets involved.
set -Eeuo pipefail
out="${1:?outdir}"; here="$(cd "$(dirname "$0")" && pwd)"; src="$here/../../../../deploy/admin-console"
ADMIN=ops.xiaosaiai.com; SHOW=pgc.xiaosaiai.com; CRT=/etc/nginx/ssl/xiaosaiai.com.crt; KEY=/etc/nginx/ssl/xiaosaiai.com.key
mkdir -p "$out/snippets"
sed -e "s#/etc/nginx/ssl/__DOMAIN__.crt#$CRT#" -e "s#/etc/nginx/ssl/__DOMAIN__.key#$KEY#" -e "s#__DOMAIN__#$ADMIN#g" "$src/edu-admin.conf.template" > "$out/edu-admin.conf"
sed -e "s#/etc/nginx/ssl/__SHOW_HOST__.crt#$CRT#" -e "s#/etc/nginx/ssl/__SHOW_HOST__.key#$KEY#" -e "s#__SHOW_HOST__#$SHOW#g" -e "s#__ADMIN_HOST__#$ADMIN#g" "$src/edu-exhibit.conf.template" > "$out/edu-exhibit.conf"
cp "$src/edu-admin-headers.conf" "$src/edu-exhibit-headers.conf" "$out/snippets/"
grep -nE '^[^#]*__[A-Z_]+__' "$out"/*.conf && { echo "unreplaced placeholder"; exit 1; } || true
echo rendered
