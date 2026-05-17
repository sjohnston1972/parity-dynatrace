#!/usr/bin/env bash
# Dynatrace ActiveGate container entrypoint.
#
# Required env vars:
#   DT_TENANT_URL   — e.g. https://kea15603.live.dynatrace.com
#   DT_PAAS_TOKEN   — PAAS token with InstallerDownload scope
#                     (mint in tenant UI > Settings > Access tokens,
#                      or via the OAuth flow in scripts/deploy_activegate.py).
#
# Optional:
#   DT_AG_GROUP     — server-side group label (default: "parity")
#   DT_AG_NETWORK_ZONE — network zone (default: "default")
#   DT_SKIP_INSTALL — set to "1" to skip the installer step (used when
#                     an image is built with the installer baked in)
set -euo pipefail

AG_HOME=/opt/dynatrace/gateway
AG_DIR_MARKER="$AG_HOME/gateway"
INSTALL_DIR=/tmp/dt-install

if [[ -z "${DT_TENANT_URL:-}" ]] || [[ -z "${DT_PAAS_TOKEN:-}" ]]; then
    echo "[entrypoint] FATAL: DT_TENANT_URL and DT_PAAS_TOKEN must be set."
    echo "[entrypoint]   DT_TENANT_URL example: https://kea15603.live.dynatrace.com"
    echo "[entrypoint]   DT_PAAS_TOKEN: mint a PAAS token in tenant UI"
    echo "[entrypoint]     (Settings > Access tokens > Generate, scope:"
    echo "[entrypoint]     'PaaS integration - Installer download')."
    exit 1
fi

if [[ ! -d "$AG_DIR_MARKER" ]] && [[ "${DT_SKIP_INSTALL:-0}" != "1" ]]; then
    echo "[entrypoint] ActiveGate not present at $AG_DIR_MARKER — fetching installer."
    mkdir -p "$INSTALL_DIR"
    INSTALLER="$INSTALL_DIR/dt-gateway-installer.sh"
    URL="${DT_TENANT_URL%/}/api/v1/deployment/installer/gateway/unix/latest?arch=x86&flavor=default"
    echo "[entrypoint] GET $URL"
    curl -fsSL \
        --header "Authorization: Api-Token ${DT_PAAS_TOKEN}" \
        --output "$INSTALLER" \
        "$URL"
    chmod +x "$INSTALLER"
    echo "[entrypoint] Running installer (silent mode)..."
    # --set-network-zone and --set-server-group only apply on fresh install.
    GROUP="${DT_AG_GROUP:-parity}"
    ZONE="${DT_AG_NETWORK_ZONE:-default}"
    "$INSTALLER" \
        --set-network-zone="$ZONE" \
        --set-server-group="$GROUP" \
        --set-tenant="${DT_TENANT_URL%/}" \
        --set-tenant-token="$DT_PAAS_TOKEN" \
        || {
            echo "[entrypoint] installer exited non-zero (some warnings are OK)"
        }
fi

# Resolve the AG launch binary.
AG_BIN="$AG_HOME/gateway/bin/dynatracegateway"
if [[ ! -x "$AG_BIN" ]]; then
    echo "[entrypoint] FATAL: gateway binary not found at $AG_BIN"
    echo "[entrypoint] Contents of $AG_HOME:"
    ls -la "$AG_HOME" 2>/dev/null || true
    exit 1
fi

echo "[entrypoint] Starting ActiveGate: $AG_BIN"
exec "$AG_BIN"
