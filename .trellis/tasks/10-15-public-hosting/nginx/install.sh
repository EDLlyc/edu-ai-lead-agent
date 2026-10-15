#!/usr/bin/env bash
# Install nginx on the production host and publish the console (ops) and the exhibit (pgc).
# Run as root. Usage: install.sh <staging dir>
# Staging dir holds: ngrender/{edu-admin.conf,edu-exhibit.conf,snippets/*}, dist-admin/, exhibit/,
# xiaosaiai.com.crt, xiaosaiai.com.key. The key is installed 600 root and the staged copy shredded.
# Touches no container. Nothing here is secret except the key, which is never printed.
set -Eeuo pipefail
test "$(id -u)" = 0
s="${1:?staging dir}"
test -s "$s/xiaosaiai.com.crt" && test -s "$s/xiaosaiai.com.key"
# the key must match the certificate (compare public key digests)
a="$(openssl x509 -in "$s/xiaosaiai.com.crt" -noout -pubkey | sha256sum | cut -c1-16)"
b="$(openssl pkey -in "$s/xiaosaiai.com.key" -pubout | sha256sum | cut -c1-16)"
test "$a" = "$b"
openssl x509 -in "$s/xiaosaiai.com.crt" -noout -subject -enddate
ss -ltn '( sport = :80 or sport = :443 )' | tail -n +2 | wc -l | grep -qx 0   # ports free
ss -ltn 'sport = :8000' | grep -q 127.0.0.1 || ss -ltn 'sport = :8000' | grep -q 8000   # API reachable

if ! command -v nginx >/dev/null; then
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends nginx >/dev/null
fi
systemctl stop nginx 2>/dev/null || true
rm -f /etc/nginx/sites-enabled/default

install -d -m 755 /etc/nginx/ssl /var/www/certbot
install -m 644 -o root -g root "$s/xiaosaiai.com.crt" /etc/nginx/ssl/xiaosaiai.com.crt
install -m 600 -o root -g root "$s/xiaosaiai.com.key" /etc/nginx/ssl/xiaosaiai.com.key
shred -u "$s/xiaosaiai.com.key" || rm -f "$s/xiaosaiai.com.key"

install -m 644 "$s"/ngrender/snippets/*.conf /etc/nginx/snippets/
install -m 644 "$s/ngrender/edu-admin.conf" /etc/nginx/conf.d/edu-admin.conf
install -m 644 "$s/ngrender/edu-exhibit.conf" /etc/nginx/conf.d/edu-exhibit.conf

rm -rf /var/www/edu-ai-admin /var/www/edu-ai-exhibit
install -d -m 755 /var/www/edu-ai-admin /var/www/edu-ai-exhibit
cp -a "$s/dist-admin/." /var/www/edu-ai-admin/
cp -a "$s/exhibit/." /var/www/edu-ai-exhibit/
chown -R root:root /var/www/edu-ai-admin /var/www/edu-ai-exhibit
find /var/www/edu-ai-admin /var/www/edu-ai-exhibit -type d -exec chmod 755 {} +
find /var/www/edu-ai-admin /var/www/edu-ai-exhibit -type f -exec chmod 644 {} +

install -d -m 755 /var/www/edu-ai-static
install -m 644 "$s"/static/* /var/www/edu-ai-static/ 2>/dev/null || true
nginx -t
systemctl enable --now nginx
sleep 1
systemctl is-active nginx
ss -ltn '( sport = :80 or sport = :443 )'
rm -rf "$s"
echo nginx_published
