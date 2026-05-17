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
    # The deploy_activegate.py script downloads the installer on the
    # host (using an OAuth Bearer with environment-api:deployment:download)
    # and bind-mounts it into the container at /opt/dt-installer/installer.sh.
    # This avoids re-doing the auth dance inside the container.
    INSTALLER="/opt/dt-installer/installer.sh"
    if [[ ! -x "$INSTALLER" ]] && [[ -f "$INSTALLER" ]]; then
        chmod +x "$INSTALLER"
    fi
    if [[ ! -f "$INSTALLER" ]]; then
        echo "[entrypoint] FATAL: installer not bind-mounted at $INSTALLER"
        echo "[entrypoint]   Re-run scripts/deploy_activegate.py from the host;"
        echo "[entrypoint]   it downloads the installer + minfs an AG token + runs"
        echo "[entrypoint]   the container with -v <host>/installer.sh:$INSTALLER:ro."
        exit 1
    fi
    echo "[entrypoint] Running pre-downloaded installer (silent mode)..."
    GROUP="${DT_AG_GROUP:-parity}"
    ZONE="${DT_AG_NETWORK_ZONE:-default}"
    # Derive the bare tenant id from the URL (e.g. "kea15603" from
    # https://kea15603.live.dynatrace.com). The installer's TENANT
    # arg wants the id, not the full URL; SERVER wants the URL.
    TENANT_ID="$(echo "$DT_TENANT_URL" | sed -E 's@https?://([^.]+).*@\1@')"
    # Installer accepts both `--set-*` flags AND positional KEY=value
    # args. TENANT + TENANT_TOKEN MUST be the positional form.
    "$INSTALLER" \
        --set-network-zone="$ZONE" \
        --set-group="$GROUP" \
        SERVER="${DT_TENANT_URL%/}" \
        TENANT="$TENANT_ID" \
        TENANT_TOKEN="$DT_PAAS_TOKEN" \
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
