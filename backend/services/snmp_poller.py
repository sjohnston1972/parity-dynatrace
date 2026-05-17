"""SNMPv2c poller that pushes Cisco/IF-MIB counters to Dynatrace.

Replacement for the AG-hosted SNMP Generic extension v2 path
(blocked because Dynatrace's AG installer requires systemd, which
standard Docker containers don't provide). Same metric shape and
naming convention so the existing themed dashboards and the
extension YAML in ``extensions/parity-snmp-cisco/`` are both
re-usable when an AG ever gets stood up on a real Linux host.

Polling cadence: 60s per device.
Devices: pulled from the Parity inventory (``Device.management_ip``).
Auth: Dynatrace ``/api/v2/metrics/ingest`` via the OAuth client
(needs scope ``environment-api:metrics:write`` — already granted).

Each metric line carries dimensions:
  device.label   - short hostname (e.g. S4-R1)
  device.ip      - management IP (192.168.x.x)
  site           - SITE1/2/3/4/DC1/DC2 from Device.tags
  source         - "dt-snmp" (matches the extension manifest tag so
                   dashboards filter the same regardless of source)
  dt.entity.custom_device - the Dynatrace CUSTOM_DEVICE id we
                            registered earlier (parity-<hostname>),
                            so metrics roll up onto the entity.
  ifIndex / ifDescr - on interface metrics only.

Best-effort throughout: a single device unreachable or a single
metric ingest failure must not stop the poll loop or break the
backend startup.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx
import structlog

log = structlog.get_logger()


# ── Config (env-driven so the user can flip on/off without code) ──

POLL_INTERVAL_S = int(os.environ.get("PARITY_SNMP_POLL_INTERVAL_S", "60"))
SNMP_COMMUNITY = os.environ.get("PARITY_SNMP_COMMUNITY", "readonly")
SNMP_TIMEOUT_S = int(os.environ.get("PARITY_SNMP_TIMEOUT_S", "5"))
SNMP_RETRIES = int(os.environ.get("PARITY_SNMP_RETRIES", "1"))

# Same OIDs the Telegraf cisco input + the SNMP extension YAML use.
SCALAR_OIDS = {
    "parity.snmp.sysUptime":              "1.3.6.1.2.1.1.3.0",
    "parity.snmp.cisco.cpu_5min":         "1.3.6.1.4.1.9.2.1.58.0",
    "parity.snmp.cisco.mem_used_bytes":   "1.3.6.1.4.1.9.9.48.1.1.1.5.1",
    "parity.snmp.cisco.mem_free_bytes":   "1.3.6.1.4.1.9.9.48.1.1.1.6.1",
}

# IF-MIB / ifXTable columns. The walker pivots on ifIndex; each row
# becomes one line per metric tagged with ifIndex + ifDescr.
INTERFACE_TABLE_OIDS = {
    "parity.snmp.if.adminStatus": "1.3.6.1.2.1.2.2.1.7",
    "parity.snmp.if.operStatus":  "1.3.6.1.2.1.2.2.1.8",
    "parity.snmp.if.inOctets":    "1.3.6.1.2.1.31.1.1.1.6",   # ifHCInOctets
    "parity.snmp.if.outOctets":   "1.3.6.1.2.1.31.1.1.1.10",  # ifHCOutOctets
    "parity.snmp.if.inErrors":    "1.3.6.1.2.1.2.2.1.14",
    "parity.snmp.if.outErrors":   "1.3.6.1.2.1.2.2.1.20",
    "parity.snmp.if.inDiscards":  "1.3.6.1.2.1.2.2.1.13",
    "parity.snmp.if.outDiscards": "1.3.6.1.2.1.2.2.1.19",
    "parity.snmp.if.speed":       "1.3.6.1.2.1.2.2.1.5",
}
IF_DESCR_OID = "1.3.6.1.2.1.2.2.1.2"


# ── OAuth Bearer cache (env-driven) ──────────────────────────


_OAUTH_BEARER_CACHE: dict[str, Any] = {}


async def _oauth_bearer() -> str | None:
    """Mint or reuse a short-lived OAuth Bearer with metrics:write."""
    cid = os.environ.get("DT_OAUTH_CLIENT_ID")
    sec = os.environ.get("DT_OAUTH_CLIENT_SECRET")
    if not (cid and sec):
        return None
    cached = _OAUTH_BEARER_CACHE.get("token")
    exp = _OAUTH_BEARER_CACHE.get("expires_at", 0)
    if cached and time.time() < (exp - 60):
        return str(cached)
    sso = os.environ.get(
        "DT_OAUTH_TOKEN_URL", "https://sso.dynatrace.com/sso/oauth2/token"
    )
    urn = (
        os.environ.get("DT_OAUTH_URN")
        or os.environ.get("DT_OAUTH_RESOURCE")
        or f"urn:dtenvironment:{_env_id()}"
    )
    scope = os.environ.get(
        "PARITY_SNMP_OAUTH_SCOPE",
        "environment-api:metrics:write",
    )
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                sso,
                data={
                    "grant_type": "client_credentials",
                    "client_id": cid,
                    "client_secret": sec,
                    "scope": scope,
                    "resource": urn,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except Exception as e:
        log.warning("snmp_oauth_fetch_failed", error=str(e))
        return None
    if r.status_code != 200:
        log.warning(
            "snmp_oauth_fetch_status",
            status=r.status_code, body=r.text[:200],
        )
        return None
    body = r.json()
    tok = body.get("access_token")
    _OAUTH_BEARER_CACHE["token"] = tok or ""
    _OAUTH_BEARER_CACHE["expires_at"] = time.time() + int(body.get("expires_in", 300))
    return tok


def _env_id() -> str:
    apps = (os.environ.get("DT_ENVIRONMENT") or "").rstrip("/")
    return apps.split("//")[-1].split(".")[0]


# ── Device discovery ─────────────────────────────────────────


async def _discover_devices() -> list[dict[str, str]]:
    """Pull (hostname, ip, site) for every routable device from the DB."""
    try:
        from sqlalchemy import select
        from db.postgres import async_session
        from db.tables import Device
        async with async_session() as s:
            rows = (await s.execute(select(Device))).scalars().all()
    except Exception as e:
        log.warning("snmp_discover_devices_failed", error=str(e))
        return []
    out: list[dict[str, str]] = []
    for d in rows:
        ip = d.management_ip
        if not ip:
            continue
        host = (d.hostname or "").split(".")[0]
        if not host:
            continue
        out.append({
            "hostname": host,
            "ip": ip,
            "site": (d.tags or {}).get("site", "unknown") if d.tags else "unknown",
            "platform": d.platform or "unknown",
        })
    return out


# ── SNMP poll one device ─────────────────────────────────────


async def _poll_one_device(dev: dict[str, str]) -> list[str]:
    """Walk scalar + interface OIDs, return a list of metric lines."""
    try:
        from pysnmp.hlapi.v3arch.asyncio import (
            CommunityData, ContextData, ObjectIdentity, ObjectType,
            SnmpEngine, UdpTransportTarget, get_cmd, next_cmd,
        )
    except Exception:
        # Older pysnmp packaging fallback
        from pysnmp.hlapi.asyncio import (  # type: ignore
            CommunityData, ContextData, ObjectIdentity, ObjectType,
            SnmpEngine, UdpTransportTarget, get_cmd, next_cmd,
        )

    lines: list[str] = []
    ip = dev["ip"]
    base_dims = (
        f'device.label="{dev["hostname"]}",'
        f'device.ip="{ip}",'
        f'site="{dev["site"]}",'
        f'source="dt-snmp",'
        f'dt.entity.custom_device="parity-{dev["hostname"]}"'
    )
    engine = SnmpEngine()
    community = CommunityData(SNMP_COMMUNITY, mpModel=1)  # mpModel=1 => v2c
    target = await UdpTransportTarget.create(
        (ip, 161), timeout=SNMP_TIMEOUT_S, retries=SNMP_RETRIES,
    )
    ctx = ContextData()

    # Scalars
    for name, oid in SCALAR_OIDS.items():
        try:
            err_ind, err_status, _err_idx, var_binds = await get_cmd(
                engine, community, target, ctx, ObjectType(ObjectIdentity(oid)),
            )
            if err_ind or err_status:
                continue
            for _, val in var_binds:
                try:
                    v = int(val)
                except Exception:
                    continue
                lines.append(f"{name},{base_dims} {v}")
        except Exception as e:
            log.debug("snmp_scalar_failed", device=dev["hostname"], oid=oid, error=str(e))

    # Interface table — first walk ifDescr to map ifIndex -> ifDescr
    if_descr: dict[int, str] = {}
    try:
        async for err_ind, err_status, _err_idx, var_binds in next_cmd(
            engine, community, target, ctx,
            ObjectType(ObjectIdentity(IF_DESCR_OID)), lexicographicMode=False,
        ):
            if err_ind or err_status:
                break
            for oid_obj, val in var_binds:
                idx = int(oid_obj.prettyPrint().rsplit(".", 1)[-1])
                if_descr[idx] = str(val).strip()
    except Exception as e:
        log.debug("snmp_ifdescr_walk_failed", device=dev["hostname"], error=str(e))

    # Per-column walk for each interface metric
    for metric, oid in INTERFACE_TABLE_OIDS.items():
        try:
            async for err_ind, err_status, _err_idx, var_binds in next_cmd(
                engine, community, target, ctx,
                ObjectType(ObjectIdentity(oid)), lexicographicMode=False,
            ):
                if err_ind or err_status:
                    break
                for oid_obj, val in var_binds:
                    idx = int(oid_obj.prettyPrint().rsplit(".", 1)[-1])
                    desc = if_descr.get(idx, f"ifIndex.{idx}")
                    # Skip mgmt-only interfaces if they happen to carry mgmt IPs (very unlikely)
                    try:
                        v = int(val)
                    except Exception:
                        continue
                    safe_desc = desc.replace('"', "").replace(",", "")[:80]
                    lines.append(
                        f'{metric},{base_dims},ifIndex="{idx}",'
                        f'ifDescr="{safe_desc}" {v}'
                    )
        except Exception as e:
            log.debug(
                "snmp_iftable_walk_failed",
                device=dev["hostname"], oid=oid, error=str(e),
            )

    return lines


# ── Push line-protocol to Dynatrace ──────────────────────────


async def _push(lines: list[str]) -> tuple[int, int]:
    """POST a chunk of line-protocol metrics. Returns (sent, rejected)."""
    if not lines:
        return 0, 0
    bearer = await _oauth_bearer()
    if not bearer:
        return 0, len(lines)
    apps = (os.environ.get("DT_ENVIRONMENT") or "").rstrip("/")
    live = apps.replace(".apps.dynatrace.com", ".live.dynatrace.com")
    if not live:
        return 0, len(lines)
    # Dynatrace metrics ingest accepts batches up to ~1000 lines / 1MB.
    sent_total = 0
    rejected_total = 0
    CHUNK = 500
    async with httpx.AsyncClient(timeout=30) as c:
        for i in range(0, len(lines), CHUNK):
            chunk = "\n".join(lines[i:i + CHUNK])
            try:
                r = await c.post(
                    f"{live}/api/v2/metrics/ingest",
                    headers={
                        "Authorization": f"Bearer {bearer}",
                        "Content-Type": "text/plain",
                    },
                    content=chunk,
                )
            except Exception as e:
                log.warning("snmp_push_failed", error=str(e))
                rejected_total += len(lines[i:i + CHUNK])
                continue
            if r.status_code in (200, 202, 204):
                sent_total += len(lines[i:i + CHUNK])
            else:
                rejected_total += len(lines[i:i + CHUNK])
                log.warning(
                    "snmp_push_rejected",
                    status=r.status_code, body=r.text[:200],
                )
    return sent_total, rejected_total


# ── Forever loop ─────────────────────────────────────────────


_RUN = False


async def run_forever() -> None:
    """Poll every device every POLL_INTERVAL_S, push metrics to Dynatrace."""
    global _RUN
    if _RUN:
        log.info("snmp_poller_already_running")
        return
    if os.environ.get("PARITY_SNMP_DISABLED", "").lower() in ("1", "true", "yes"):
        log.info("snmp_poller_disabled_via_env")
        return
    _RUN = True
    log.info("snmp_poller_start", interval_s=POLL_INTERVAL_S, community=SNMP_COMMUNITY)
    try:
        while _RUN:
            t0 = time.monotonic()
            devices = await _discover_devices()
            if not devices:
                log.info("snmp_poller_no_devices")
            else:
                results = await asyncio.gather(
                    *(_poll_one_device(d) for d in devices),
                    return_exceptions=True,
                )
                all_lines: list[str] = []
                ok_devices = 0
                for dev, res in zip(devices, results):
                    if isinstance(res, Exception):
                        log.debug(
                            "snmp_poll_device_failed",
                            device=dev["hostname"], error=str(res),
                        )
                        continue
                    if res:
                        ok_devices += 1
                        all_lines.extend(res)
                sent, rejected = await _push(all_lines)
                log.info(
                    "snmp_poller_tick",
                    devices_polled=len(devices), devices_ok=ok_devices,
                    metric_lines=len(all_lines), sent=sent, rejected=rejected,
                    elapsed_s=round(time.monotonic() - t0, 1),
                )
            # Sleep the remainder of the interval
            slept = time.monotonic() - t0
            if slept < POLL_INTERVAL_S:
                await asyncio.sleep(POLL_INTERVAL_S - slept)
    except Exception as e:
        log.exception("snmp_poller_crashed", error=str(e))
    finally:
        _RUN = False


def stop() -> None:
    global _RUN
    _RUN = False
