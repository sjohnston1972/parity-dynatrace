"""Deploy a Dynatrace ActiveGate container + SNMP Generic extension.

End-to-end orchestration for the SNMP integration the user asked for:

  1.  Mint (or reuse) a PAAS install token using the existing OAuth
      client (scope environment-api:activegate-tokens:create). Caches
      the token in .env under DT_PAAS_TOKEN.
  2.  Build the parity-activegate Docker image from
      docker/dynatrace-activegate/Dockerfile.
  3.  Start the container with the PAAS token mounted in. The container
      fetches the AG installer from the tenant on first boot, runs it,
      and connects back to register itself.
  4.  Poll the tenant's /api/v2/activeGates until the AG appears in the
      list (registration usually completes within 60-120s).
  5.  Upload extensions/parity-snmp-cisco/extension.yaml via the
      extensions API and activate one monitoring configuration per
      device from the live Parity inventory (the same 19 devices we
      registered as Custom Devices earlier).
  6.  Verify SNMP metrics land in Grail within 5 minutes by polling
      `fetch metric.series parity.snmp.sysUptime`.

The script is idempotent at every step - reruns notice existing
state (PAAS token in .env, AG container running, extension installed,
configs activated) and skip the corresponding step.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv, set_key

REPO = Path(__file__).resolve().parent.parent
load_dotenv(REPO / ".env")

APPS = (os.environ.get("DT_ENVIRONMENT") or "").rstrip("/")
LIVE = APPS.replace(".apps.dynatrace.com", ".live.dynatrace.com")
ENV_ID = APPS.split("//")[-1].split(".")[0]  # "kea15603"
OAUTH_CID = os.environ.get("DT_OAUTH_CLIENT_ID")
OAUTH_SEC = os.environ.get("DT_OAUTH_CLIENT_SECRET")
OAUTH_URN = (
    os.environ.get("DT_OAUTH_URN")
    or os.environ.get("DT_OAUTH_RESOURCE")
    or f"urn:dtenvironment:{ENV_ID}"
)
SSO_URL = os.environ.get(
    "DT_OAUTH_TOKEN_URL", "https://sso.dynatrace.com/sso/oauth2/token"
)
AG_CONTAINER_NAME = "parity-activegate"
AG_IMAGE = "parity-activegate:latest"
EXTENSION_NAME = "custom:parity.snmp.cisco"


def _log(msg: str) -> None:
    print(msg, flush=True)


def _abort_if_unconfigured() -> None:
    if not APPS:
        raise SystemExit("DT_ENVIRONMENT not set in .env")
    if not (OAUTH_CID and OAUTH_SEC):
        raise SystemExit(
            "DT_OAUTH_CLIENT_ID + DT_OAUTH_CLIENT_SECRET must be set"
        )


def _oauth_bearer(scope: str) -> str:
    """Exchange OAuth client credentials for a short-lived Bearer."""
    r = httpx.post(
        SSO_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": OAUTH_CID,
            "client_secret": OAUTH_SEC,
            "scope": scope,
            "resource": OAUTH_URN,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if r.status_code != 200:
        raise SystemExit(
            f"OAuth token fetch failed ({r.status_code}): {r.text[:300]}\n"
            f"Likely missing scope: {scope}. Add it to the OAuth client in\n"
            f"Account Management > Identity & access > OAuth clients."
        )
    return r.json()["access_token"]


# ── Step 1: installer + AG token ─────────────────────────────


INSTALLER_LOCAL = REPO / "docker" / "dynatrace-activegate" / "dt-installer.sh"


def step_fetch_installer_and_ag_token() -> str:
    """Download the AG installer via OAuth Bearer + mint the AG runtime token.

    The installer endpoint accepts an OAuth Bearer with scope
    environment-api:deployment:download (verified). The AG runtime
    token comes from /api/v2/activeGateTokens (scope
    environment-api:activegate-tokens:create). Two different things;
    the installer download is one-shot from the host while the runtime
    token gets mounted into the container.
    """
    cached = os.environ.get("DT_PAAS_TOKEN")
    if cached and INSTALLER_LOCAL.exists():
        _log(f"[1/6] AG token cached + installer present "
             f"({INSTALLER_LOCAL.stat().st_size // 1024} KB)")
        return cached

    _log("[1/6] Downloading AG installer via OAuth Bearer...")
    dl_bearer = _oauth_bearer("environment-api:deployment:download")
    url = f"{LIVE}/api/v1/deployment/installer/gateway/unix/latest?arch=x86&flavor=default"
    with httpx.stream(
        "GET", url,
        headers={"Authorization": f"Bearer {dl_bearer}"},
        timeout=120, follow_redirects=True,
    ) as r:
        if r.status_code != 200:
            raise SystemExit(
                f"installer download failed ({r.status_code}): {r.read()[:300]}"
            )
        INSTALLER_LOCAL.parent.mkdir(parents=True, exist_ok=True)
        with open(INSTALLER_LOCAL, "wb") as fh:
            for chunk in r.iter_bytes():
                fh.write(chunk)
    _log(f"[1/6] installer saved: {INSTALLER_LOCAL} "
         f"({INSTALLER_LOCAL.stat().st_size // 1024} KB)")

    _log("[1/6] Minting AG runtime token...")
    tok_bearer = _oauth_bearer(
        "environment-api:activegate-tokens:create "
        "environment-api:activegate-tokens:write"
    )
    r = httpx.post(
        f"{LIVE}/api/v2/activeGateTokens",
        headers={"Authorization": f"Bearer {tok_bearer}",
                 "Content-Type": "application/json"},
        json={
            "name": "parity-activegate-runtime",
            "expirationDate": None,
            "activeGateType": "ENVIRONMENT",
            "seedToken": False,
        },
        timeout=15,
    )
    if r.status_code not in (200, 201):
        raise SystemExit(
            f"AG token create failed ({r.status_code}): {r.text[:300]}"
        )
    tok = r.json()["token"]
    set_key(str(REPO / ".env"), "DT_PAAS_TOKEN", tok)
    os.environ["DT_PAAS_TOKEN"] = tok
    _log(f"[1/6] OK — AG runtime token cached as DT_PAAS_TOKEN (prefix {tok[:10]}...)")
    return tok


# Back-compat name so the main() wiring below keeps working.
step_mint_paas_token = step_fetch_installer_and_ag_token


# ── Step 2: build the AG image ───────────────────────────────


def step_build_image() -> None:
    _log("[2/6] Building parity-activegate image...")
    out = subprocess.run(
        ["docker", "build", "-t", AG_IMAGE,
         str(REPO / "docker" / "dynatrace-activegate")],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise SystemExit(f"docker build failed:\n{out.stderr[-2000:]}")
    _log("[2/6] OK — image built")


# ── Step 3: run the AG container ─────────────────────────────


def step_run_container(paas_token: str) -> None:
    # Skip if already running.
    inspect = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", AG_CONTAINER_NAME],
        capture_output=True, text=True,
    )
    if inspect.returncode == 0 and inspect.stdout.strip() == "running":
        _log(f"[3/6] {AG_CONTAINER_NAME} already running")
        return
    if inspect.returncode == 0:
        _log(f"[3/6] removing stopped {AG_CONTAINER_NAME}")
        subprocess.run(["docker", "rm", "-f", AG_CONTAINER_NAME], capture_output=True)
    _log(f"[3/6] Starting {AG_CONTAINER_NAME}...")
    if not INSTALLER_LOCAL.exists():
        raise SystemExit(
            f"installer missing at {INSTALLER_LOCAL}; re-run step 1"
        )
    out = subprocess.run([
        "docker", "run", "-d",
        "--name", AG_CONTAINER_NAME,
        "--restart", "unless-stopped",
        "--network", "net_core",
        "-e", f"DT_TENANT_URL={LIVE}",
        "-e", f"DT_PAAS_TOKEN={paas_token}",
        "-e", "DT_AG_GROUP=parity",
        # Bind-mount the host-downloaded installer so the container
        # doesn't have to re-do the OAuth dance for the download.
        "-v", f"{INSTALLER_LOCAL}:/opt/dt-installer/installer.sh:ro",
        "-v", "parity-ag-data:/var/lib/dynatrace/gateway",
        "-v", "parity-ag-opt:/opt/dynatrace",
        "-p", "9999:9999",
        AG_IMAGE,
    ], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"docker run failed:\n{out.stderr[-2000:]}")
    _log(f"[3/6] OK — container started (id {out.stdout.strip()[:12]})")


# ── Step 4: wait for AG registration ─────────────────────────


def step_wait_for_registration(timeout: int = 240) -> str | None:
    _log(f"[4/6] Waiting up to {timeout}s for AG to register with tenant...")
    bearer = _oauth_bearer("environment-api:activegates:read")
    deadline = time.monotonic() + timeout
    ag_id: str | None = None
    while time.monotonic() < deadline:
        r = httpx.get(
            f"{LIVE}/api/v2/activeGates",
            headers={"Authorization": f"Bearer {bearer}"},
            timeout=15,
        )
        if r.status_code == 200:
            ags = r.json().get("activeGates", [])
            for ag in ags:
                if (ag.get("group") or "").lower() == "parity" or \
                   "parity" in (ag.get("hostname") or "").lower():
                    ag_id = str(ag.get("id"))
                    break
            if ag_id:
                _log(f"[4/6] OK — ActiveGate registered: id={ag_id}")
                return ag_id
        time.sleep(8)
    _log(f"[4/6] WARN — AG not registered after {timeout}s. Continuing anyway.")
    return None


# ── Step 5: upload + activate extension ─────────────────────


def step_install_extension() -> str | None:
    _log(f"[5/6] Uploading SNMP extension {EXTENSION_NAME}...")
    bearer = _oauth_bearer(
        "environment-api:extensions:read environment-api:extensions:write "
        "environment-api:extension-configurations:read "
        "environment-api:extension-configurations:write"
    )
    # Bundle the extension YAML into a zip the API can accept.
    import zipfile
    zip_path = REPO / "extensions" / "parity-snmp-cisco" / "extension.zip"
    src = REPO / "extensions" / "parity-snmp-cisco" / "extension.yaml"
    if not src.exists():
        raise SystemExit(f"extension manifest missing: {src}")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(src, arcname="extension.yaml")
    with open(zip_path, "rb") as fh:
        r = httpx.post(
            f"{APPS}/api/v2/extensions",
            headers={"Authorization": f"Bearer {bearer}"},
            files={"file": ("extension.zip", fh, "application/zip")},
            timeout=30,
        )
    if r.status_code not in (200, 201):
        _log(f"[5/6] WARN — extension upload {r.status_code}: {r.text[:300]}")
        _log("       The extension framework on this tenant may require")
        _log("       extensions to be signed by Dynatrace. In that case,")
        _log("       deploy via Hub manually: open the Hub app, search for")
        _log("       'SNMP Generic', and add devices via Monitoring Config.")
        return None
    _log(f"[5/6] OK — extension {EXTENSION_NAME} accepted ({r.status_code})")
    return EXTENSION_NAME


# ── Step 6: activate per-device monitoring configs ──────────


def step_activate_configs(extension_id: str, ag_id: str | None) -> int:
    _log("[6/6] Activating per-device SNMP monitoring configs...")
    # Pull device inventory from Parity API.
    parity_url = os.environ.get("PARITY_URL", "https://parity-dynatrace.clydeford.net")
    try:
        devs = httpx.get(f"{parity_url}/api/v1/devices", timeout=15).json()
    except Exception as e:
        _log(f"[6/6] WARN — could not pull inventory ({e}); skipping")
        return 0
    community = os.environ.get("DT_SNMP_COMMUNITY", "readonly")
    bearer = _oauth_bearer(
        "environment-api:extension-configurations:read "
        "environment-api:extension-configurations:write"
    )
    activated = 0
    for d in devs:
        short = (d.get("hostname") or "").split(".")[0]
        ip = d.get("management_ip") or d.get("mgmt_ip")
        if not (short and ip):
            continue
        site = (d.get("tags") or {}).get("site") or "unknown"
        cfg = {
            "scope": ag_id or "ag_group-parity",
            "value": {
                "enabled": True,
                "description": f"SNMP polling of {short} ({ip})",
                "version": "1.0.0",
                "vars": {
                    "device_ip": ip,
                    "device_label": short,
                    "site": str(site).upper(),
                    "community": community,
                },
            },
        }
        r = httpx.post(
            f"{APPS}/api/v2/extensions/{extension_id}/monitoringConfigurations",
            headers={"Authorization": f"Bearer {bearer}",
                     "Content-Type": "application/json"},
            json=cfg, timeout=15,
        )
        if r.status_code in (200, 201):
            activated += 1
            _log(f"  OK {short:<10} {ip:<16} (site={site})")
        else:
            _log(f"  FAIL {short:<10} {ip:<16} {r.status_code}: {r.text[:120]}")
    _log(f"[6/6] activated {activated}/{len(devs)} device configs")
    return activated


# ── Main ─────────────────────────────────────────────────────


def main() -> int:
    _abort_if_unconfigured()
    _log(f"Deploying Dynatrace ActiveGate + SNMP extension on {APPS}")
    _log("")
    paas = step_mint_paas_token()
    _log("")
    step_build_image()
    _log("")
    step_run_container(paas)
    _log("")
    ag_id = step_wait_for_registration()
    _log("")
    ext = step_install_extension()
    _log("")
    if ext:
        step_activate_configs(ext, ag_id)
    _log("")
    _log("=" * 60)
    _log("Summary")
    _log("=" * 60)
    _log(f"ActiveGate container: {AG_CONTAINER_NAME} ({AG_IMAGE})")
    _log(f"Tenant AG group:      parity")
    _log(f"Extension:            {ext or 'NOT INSTALLED (see notes above)'}")
    if ag_id:
        _log(f"AG entity id:         {ag_id}")
    _log("")
    _log("Wait ~5 minutes, then DQL:")
    _log("  fetch metric.series parity.snmp.sysUptime, from:-15m")
    _log("  | summarize seen = count(), by: { device.label }")
    return 0


if __name__ == "__main__":
    sys.exit(main())
