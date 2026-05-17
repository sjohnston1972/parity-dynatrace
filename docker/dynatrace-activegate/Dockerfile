# Dynatrace ActiveGate, containerised.
#
# The official Dynatrace deployment model is "install on a dedicated
# Linux host", but the same installer script runs cleanly inside an
# Ubuntu container with two caveats:
#
#   1. The installer is hosted on the tenant — we fetch it at build
#      time with the PAAS token (NOT the platform token). This means
#      the build can't be done without DT_TENANT_URL + DT_PAAS_TOKEN
#      build-args (or via the bootstrap entrypoint at run time, the
#      pattern this image uses).
#   2. ActiveGate listens on UDP/161 (SNMP) — when using the SNMP
#      Generic extension v2 the AG is the SNMP client, so we open
#      9999 (AG management) + map UDP 161 outbound only.
#
# Lifecycle: container fetches the installer on first start (if not
# already installed), runs it, then exec's the AG main process. On
# restart the installed AG is reused.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl gpg sudo procps net-tools libcap2-bin \
        iputils-ping less \
    && rm -rf /var/lib/apt/lists/*

# Healthcheck endpoint on the AG: /rest/health on the AG's HTTPS port.
HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=120s \
    CMD curl -fsk https://localhost:9999/rest/health || exit 1

# AG installs to /opt/dynatrace/gateway/ by default. Persist it on
# a docker volume so reinstalls + cert state survive container
# replacement.
VOLUME ["/var/lib/dynatrace/gateway"]

EXPOSE 9999/tcp

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
