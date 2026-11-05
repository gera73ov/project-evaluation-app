# syntax=docker/dockerfile:1
# INF-004 · тестовый контроллер домена Samba AD DC для профиля test (SPEC 17.1, Q-50).
# Только для dev и test: эмулирует корпоративный AD (LDAPS 636, StartTLS 389, вложенные
# группы, отключённые учётки). Официального образа Samba нет, поэтому собираем из Debian.
ARG DEBIAN_IMAGE=debian:trixie-slim@sha256:f6b08b09a05725f9431502d3b5714f5c4576e82c1a84fa1debe0c24a7e0c3ec4
FROM ${DEBIAN_IMAGE}
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -o APT::Update::Error-Mode=any \
 && apt-get install -y --no-install-recommends \
      samba samba-ad-dc samba-ad-provision samba-dsdb-modules samba-vfs-modules \
      winbind ldb-tools ca-certificates \
 && apt-get -y upgrade \
 && rm -rf /var/lib/apt/lists/* \
 && rm -f /etc/samba/smb.conf
COPY deploy/samba-ad/entrypoint.sh deploy/samba-ad/seed.sh /usr/local/bin/
RUN chmod 0755 /usr/local/bin/entrypoint.sh /usr/local/bin/seed.sh
# samba-ad-dc обслуживает LDAP/Kerberos/DNS и сам понижает привилегии рабочих процессов
EXPOSE 389 636
HEALTHCHECK --interval=10s --timeout=5s --start-period=90s --retries=12 \
  CMD samba-tool domain info 127.0.0.1 >/dev/null 2>&1 || exit 1
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
