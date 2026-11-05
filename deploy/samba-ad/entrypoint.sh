#!/bin/sh
# INF-004 · первый запуск: создать домен и тестовые данные; далее — просто запустить samba.
set -eu

: "${SAMBA_REALM:=TEST.ESTIMATOR.LOCAL}"
: "${SAMBA_DOMAIN:=ESTTEST}"
: "${SAMBA_ADMIN_PASSWORD:?нужен SAMBA_ADMIN_PASSWORD}"
: "${SAMBA_TEST_PASSWORD:?нужен SAMBA_TEST_PASSWORD}"
: "${SAMBA_CERT_DIR:=/certs}"

TLS_DIR=/var/lib/samba/private/tls-dev

# Samba требует, чтобы ключ TLS принадлежал root и имел права 0600 (CVE-2013-4476), а общий
# каталог dev-сертификатов доступен другим контейнерам. Поэтому копируем при каждом старте.
install -d -m 0700 "$TLS_DIR"
install -m 0600 -o root -g root "$SAMBA_CERT_DIR/samba-ad.key" "$TLS_DIR/key.pem"
install -m 0644 -o root -g root "$SAMBA_CERT_DIR/samba-ad.crt" "$TLS_DIR/cert.pem"
install -m 0644 -o root -g root "$SAMBA_CERT_DIR/ca.crt" "$TLS_DIR/ca.pem"

base_dn=$(echo "$SAMBA_REALM" | tr 'A-Z' 'a-z' | sed 's/^/DC=/; s/\./,DC=/g')

if [ ! -f /var/lib/samba/private/sam.ldb ]; then
  echo "samba-ad: создаю домен $SAMBA_REALM"
  rm -f /etc/samba/smb.conf
  # xattr_tdb: NT ACL хранятся в tdb, а не в security.* xattr — не нужен CAP_SYS_ADMIN
  samba-tool domain provision \
    --realm="$SAMBA_REALM" --domain="$SAMBA_DOMAIN" --server-role=dc \
    --dns-backend=SAMBA_INTERNAL --adminpass="$SAMBA_ADMIN_PASSWORD" \
    --host-name=dc1 \
    --option="vfs objects = dfs_samba4 acl_xattr xattr_tdb" \
    --option="tls enabled = yes" \
    --option="tls keyfile = $TLS_DIR/key.pem" \
    --option="tls certfile = $TLS_DIR/cert.pem" \
    --option="tls cafile = $TLS_DIR/ca.pem" \
    --option="ldap server require strong auth = yes" \
    --option="dns forwarder = 127.0.0.11"
  echo "$base_dn" > /var/lib/samba/base_dn
  # smb.conf хранится в томе вместе с базой, иначе пересоздание контейнера его теряет
  cp /etc/samba/smb.conf /var/lib/samba/smb.conf
  BASE_DN="$base_dn" /usr/local/bin/seed.sh
  echo "samba-ad: тестовые данные загружены"
fi

cp /var/lib/samba/smb.conf /etc/samba/smb.conf
exec samba --foreground --no-process-group --debug-stdout
