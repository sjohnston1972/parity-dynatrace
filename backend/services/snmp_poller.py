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

# BGP4-MIB.bgpPeerTable - indexed by peer IP (last 4 OID octets).
# Confirmed reachable on every lab device with the readonly community.
# State enum: 1=idle, 2=connect, 3=active, 4=opensent, 5=openconfirm, 6=established.
BGP_PEER_OIDS = {
    "parity.snmp.bgp.peerState":         "1.3.6.1.2.1.15.3.1.2",
    "parity.snmp.bgp.peerAdminStatus":   "1.3.6.1.2.1.15.3.1.3",
    "parity.snmp.bgp.peerRemoteAs":      "1.3.6.1.2.1.15.3.1.9",
    "parity.snmp.bgp.peerFsmEstablishedTime": "1.3.6.1.2.1.15.3.1.13",
    "parity.snmp.bgp.peerInUpdates":     "1.3.6.1.2.1.15.3.1.16",
    "parity.snmp.bgp.peerOutUpdates":    "1.3.6.1.2.1.15.3.1.17",
}
BGP_PEER_TABLE_PREFIX = "1.3.6.1.2.1.15.3.1"


# ── Auth ─────────────────────────────────────────────────────
#
# Dynatrace SaaS metric ingest at /api/v2/metrics/ingest has a
# quirk: it accepts an OAuth Bearer with scope storage:metrics:write
# but the Bearer also needs an IAM permission binding for actual
# ingest, which the OAuth client doesn't get out of the box. A
# CLASSIC API token (Api-Token auth) with the legacy MetricsIngest
# scope works straight away.
#
# We bootstrap on first use: ask the OAuth client to mint a classic
# Api-Token (via environment-api:api-tokens:write), cache it in the
# .env file as PARITY_SNMP_METRICS_TOKEN so reruns don't re-mint.
# After that the OAuth client isn't needed for the ingest path.


_OAUTH_BEARER_CACHE: dict[str, Any] = {}
_METRIC_TOKEN_CACHE: dict[str, str] = {}


async def _oauth_bearer(scope: str) -> str | None:
    """Mint or reuse a short-lived OAuth Bearer with the requested scope."""
    cid = os.environ.get("DT_OAUTH_CLIENT_ID")
    sec = os.environ.get("DT_OAUTH_CLIENT_SECRET")
    if not (cid and sec):
        return None
    cache_key = f"bearer::{scope}"
    cached = _OAUTH_BEARER_CACHE.get(cache_key)
    exp = _OAUTH_BEARER_CACHE.get(f"exp::{scope}", 0)
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
        log.warning("snmp_oauth_fetch_failed", scope=scope, error=str(e))
        return None
    if r.status_code != 200:
        log.warning(
            "snmp_oauth_fetch_status",
            scope=scope, status=r.status_code, body=r.text[:200],
        )
        return None
    body = r.json()
    tok = body.get("access_token")
    _OAUTH_BEARER_CACHE[cache_key] = tok or ""
    _OAUTH_BEARER_CACHE[f"exp::{scope}"] = time.time() + int(body.get("expires_in", 300))
    return tok


async def _metrics_ingest_token() -> str | None:
    """Return a classic API token good for /api/v2/metrics/ingest.

    Resolution order:
      1. PARITY_SNMP_METRICS_TOKEN env var (cached from a prior run).
      2. Process-cache (this run already minted one).
      3. Mint a fresh one via the OAuth client + cache in .env.
    """
    cached_env = os.environ.get("PARITY_SNMP_METRICS_TOKEN")
    if cached_env:
        return cached_env
    if "token" in _METRIC_TOKEN_CACHE:
        return _METRIC_TOKEN_CACHE["token"]

    bearer = await _oauth_bearer("environment-api:api-tokens:write")
    if not bearer:
        log.warning("snmp_metrics_token_no_bearer")
        return None
    apps = (os.environ.get("DT_ENVIRONMENT") or "").rstrip("/")
    live = apps.replace(".apps.dynatrace.com", ".live.dynatrace.com")
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{live}/api/v2/apiTokens",
                headers={
                    "Authorization": f"Bearer {bearer}",
                    "Content-Type": "application/json",
                },
                json={
                    "name": "parity-snmp-metric-ingest",
                    "scopes": ["metrics.ingest"],
                },
            )
    except Exception as e:
        log.warning("snmp_metrics_token_mint_failed", error=str(e))
        return None
    if r.status_code not in (200, 201):
        log.warning(
            "snmp_metrics_token_mint_status",
            status=r.status_code, body=r.text[:200],
        )
        return None
    tok = r.json().get("token")
    if not tok:
        return None
    _METRIC_TOKEN_CACHE["token"] = tok
    # Persist to .env so process restarts reuse it (avoid token churn).
    try:
        from dotenv import set_key
        env_path = "/app/.env" if os.path.exists("/app/.env") else ".env"
        set_key(env_path, "PARITY_SNMP_METRICS_TOKEN", tok)
    except Exception as e:
        log.debug("snmp_metrics_token_persist_failed", error=str(e))
    log.info("snmp_metrics_token_minted", prefix=tok[:14])
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


# ── Transition detection (Davis problem trigger) ─────────────

# Per-device snapshot of the last cycle's BGP + interface state.
# Keyed by device hostname. Populated on every poll; transitions
# only emit when prior state exists for the object (so the very
# first cycle is silent — no flood of "alerts" at boot).
_PRIOR_STATE: dict[str, dict[str, dict]] = {}

# IF-MIB convention: 1=up, 2=down. A "fault" is admin=1 AND oper=2.
# BGP4-MIB.bgpPeerState: 1=idle 2=connect 3=active 4=opensent 5=openconfirm 6=established.

# Don't re-fire a Davis problem if a transition keeps oscillating
# faster than this. Per-key debounce keyed by transition_key.
_LAST_FIRED: dict[str, float] = {}
_DEBOUNCE_S = 90


def _intf_is_fault(state: dict[str, int]) -> bool:
    return state.get("admin") == 1 and state.get("oper") == 2


def _bgp_is_down(state: int | None) -> bool:
    # Anything other than Established(6) is "not Established" — but
    # Idle(1) due to admin shutdown should still alert because the
    # operator may not have intended it (config drift).
    return state is not None and state != 6


async def _detect_and_emit_transitions(
    dev: dict[str, str],
    *,
    intf_state_now: dict[str, dict[str, int]],
    bgp_state_now: dict[str, int],
    peer_as: dict[str, str],
    if_descr: dict[str, str],
) -> None:
    """Compare current SNMP state to prior cycle, emit Davis-relayable
    events on edges only. Quietly no-ops on the first cycle for each
    device (when no prior state exists)."""
    from integrations.dynatrace import dynatrace_writer

    host = dev["hostname"]
    site = dev.get("site", "unknown")
    prior = _PRIOR_STATE.get(host)
    new_prior = {
        "intf": {k: dict(v) for k, v in intf_state_now.items()},
        "bgp":  dict(bgp_state_now),
    }

    # First-ever cycle for this device — establish baseline silently.
    if not prior:
        _PRIOR_STATE[host] = new_prior
        return

    now = time.monotonic()
    emits: list = []

    # Interface fault edges.
    for idx, st_now in intf_state_now.items():
        st_prev = (prior.get("intf") or {}).get(idx)
        if st_prev is None:
            continue  # newly-discovered interface — wait one more cycle
        descr = if_descr.get(idx, f"ifIndex.{idx}")
        key = f"{host}/intf/{idx}"
        if _intf_is_fault(st_now) and not _intf_is_fault(st_prev):
            if now - _LAST_FIRED.get(key, 0) < _DEBOUNCE_S:
                continue
            _LAST_FIRED[key] = now
            emits.append(dynatrace_writer.emit_snmp_anomaly(
                category="intf-fault",
                action="created",
                hostname=host, site=site, severity="high",
                title=f"{host} · interface {descr} is admin-up but oper-down",
                description=(
                    f"SNMP detected an admin-up + operationally-down "
                    f"interface on {host} ({descr}). Most common causes: "
                    f"physical link issue, peer side admin-shut, or "
                    f"protocol-down condition."
                ),
                transition_key=key,
                if_index=idx, if_descr=descr,
            ))
        elif _intf_is_fault(st_prev) and not _intf_is_fault(st_now):
            emits.append(dynatrace_writer.emit_snmp_anomaly(
                category="intf-fault",
                action="resolved",
                hostname=host, site=site, severity="high",
                title=f"{host} · interface {descr} recovered (oper-up)",
                description=f"Interface {descr} on {host} is back up.",
                transition_key=key,
                if_index=idx, if_descr=descr,
            ))

    # BGP peer state edges.
    for peer_ip, state_now in bgp_state_now.items():
        state_prev = (prior.get("bgp") or {}).get(peer_ip)
        if state_prev is None:
            continue
        key = f"{host}/bgp/{peer_ip}"
        as_tag = peer_as.get(peer_ip, "?")
        if _bgp_is_down(state_now) and not _bgp_is_down(state_prev):
            if now - _LAST_FIRED.get(key, 0) < _DEBOUNCE_S:
                continue
            _LAST_FIRED[key] = now
            emits.append(dynatrace_writer.emit_snmp_anomaly(
                category="bgp-down",
                action="created",
                hostname=host, site=site, severity="high",
                title=f"{host} · BGP peer {peer_ip} (AS {as_tag}) not Established (state={state_now})",
                description=(
                    f"BGP4-MIB.bgpPeerState on {host} reports peer "
                    f"{peer_ip} (AS {as_tag}) is no longer Established "
                    f"— current FSM state code {state_now}."
                ),
                transition_key=key,
                peer_ip=peer_ip, peer_as=as_tag, peer_state=state_now,
            ))
        elif _bgp_is_down(state_prev) and not _bgp_is_down(state_now):
            emits.append(dynatrace_writer.emit_snmp_anomaly(
                category="bgp-down",
                action="resolved",
                hostname=host, site=site, severity="high",
                title=f"{host} · BGP peer {peer_ip} (AS {as_tag}) Established again",
                description=f"BGP session to {peer_ip} (AS {as_tag}) recovered.",
                transition_key=key,
                peer_ip=peer_ip, peer_as=as_tag, peer_state=state_now,
            ))

    _PRIOR_STATE[host] = new_prior
    if emits:
        await asyncio.gather(*emits, return_exceptions=True)


# ── SNMP poll one device ─────────────────────────────────────


async def _poll_one_device(dev: dict[str, str]) -> list[str]:
    """Walk scalar + interface OIDs, return a list of metric lines.

    Uses the legacy pysnmp-lextudio 6.x asyncio API (camelCase
    getCmd/nextCmd, UdpTransportTarget constructor). The newer
    v3arch.asyncio module shape exists in 7.x but isn't in 6.1.4.
    """
    from pysnmp.hlapi.asyncio import (
        CommunityData, ContextData, ObjectIdentity, ObjectType,
        SnmpEngine, UdpTransportTarget, getCmd, nextCmd,
    )

    lines: list[str] = []
    ip = dev["ip"]
    # Dynatrace metric dimension keys must match [a-z][a-z0-9_-]*; dots
    # in key names are rejected with "invalid dimension key". Use
    # underscores and keep the host-friendly mapping in the README.
    # (dt.entity.custom_device linkage isn't reliable via line-protocol
    # ingest without an ActiveGate-side relabel - we tag via device_label
    # instead and let the dashboards correlate.)
    base_dims = (
        f'device_label="{dev["hostname"]}",'
        f'device_ip="{ip}",'
        f'site="{dev["site"]}",'
        f'source="dt-snmp"'
    )
    engine = SnmpEngine()
    community = CommunityData(SNMP_COMMUNITY, mpModel=1)  # mpModel=1 => v2c
    target = UdpTransportTarget(
        (ip, 161), timeout=SNMP_TIMEOUT_S, retries=SNMP_RETRIES,
    )
    ctx = ContextData()

    # Scalars
    for name, oid in SCALAR_OIDS.items():
        try:
            err_ind, err_status, _err_idx, var_binds = await getCmd(
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

    # Interface table — walk by repeatedly calling nextCmd until the
    # OID prefix changes.
    #
    # Quirk: pysnmp's ObjectIdentity.prettyPrint() returns MIB names
    # (e.g. "SNMPv2-SMI::mib-2.2.2.1.2.1") not numeric, so we cannot
    # do string startswith on the dotted form. Use the underlying
    # ObjectName tuple comparison instead.
    start_prefix_cache: dict[str, tuple[int, ...]] = {}

    def _prefix_tuple(dotted: str) -> tuple[int, ...]:
        if dotted not in start_prefix_cache:
            start_prefix_cache[dotted] = tuple(int(x) for x in dotted.split("."))
        return start_prefix_cache[dotted]

    async def _walk(start_oid: str):
        """Return list of (ifIndex, value) under start_oid."""
        results: list[tuple[int, Any]] = []
        prefix = _prefix_tuple(start_oid)
        prefix_len = len(prefix)
        var_iter = ObjectType(ObjectIdentity(start_oid))
        # Safety: cap at 1000 iters to avoid infinite loops on
        # MIB-resolution edge cases.
        for _ in range(1000):
            err_ind, err_status, _err_idx, var_binds = await nextCmd(
                engine, community, target, ctx, var_iter,
                lexicographicMode=False,
            )
            if err_ind or err_status or not var_binds:
                break
            stop = False
            for vb in var_binds:
                if isinstance(vb, list):
                    if not vb:
                        stop = True
                        break
                    oid_obj, val = vb[0]
                else:
                    oid_obj, val = vb
                # Pull the numeric OID tuple via getOid().asTuple() —
                # MIB-pretty-print form is unreliable for prefix checks.
                try:
                    oid_tup = tuple(oid_obj.getOid().asTuple())  # type: ignore[attr-defined]
                except Exception:
                    # Fallback: parse the dotted form
                    oid_tup = tuple(
                        int(x) for x in str(oid_obj).split(".") if x.isdigit()
                    )
                if oid_tup[:prefix_len] != prefix:
                    stop = True
                    break
                # ifIndex is the last sub-id in IF-MIB.
                idx = oid_tup[-1]
                results.append((idx, val))
                var_iter = ObjectType(oid_obj)
            if stop:
                break
        return results

    if_descr: dict[int, str] = {}
    try:
        for idx, val in await _walk(IF_DESCR_OID):
            if_descr[idx] = str(val).strip()
    except Exception as e:
        log.debug("snmp_ifdescr_walk_failed", device=dev["hostname"], error=str(e))

    # Per-interface (admin, oper) snapshot for transition detection.
    intf_state_now: dict[str, dict[str, int]] = {}
    for metric, oid in INTERFACE_TABLE_OIDS.items():
        try:
            for idx, val in await _walk(oid):
                desc = if_descr.get(idx, f"ifIndex.{idx}")
                try:
                    v = int(val)
                except Exception:
                    continue
                safe_desc = desc.replace('"', "").replace(",", "")[:80]
                lines.append(
                    f'{metric},{base_dims},if_index="{idx}",'
                    f'if_descr="{safe_desc}" {v}'
                )
                if metric == "parity.snmp.if.adminStatus":
                    intf_state_now.setdefault(idx, {})["admin"] = v
                elif metric == "parity.snmp.if.operStatus":
                    intf_state_now.setdefault(idx, {})["oper"] = v
        except Exception as e:
            log.debug(
                "snmp_iftable_walk_failed",
                device=dev["hostname"], oid=oid, error=str(e),
            )

    # BGP4-MIB.bgpPeerTable walk. Different shape from IF-MIB: the
    # table is indexed by the 4-octet peer IP, so the OID suffix after
    # the metric prefix is e.g. ".192.168.1.2". Custom walker pulls
    # the last 4 sub-ids as the peer-IP dimension.
    async def _walk_bgp(start_oid: str):
        """Return list of (peer_ip_str, value)."""
        results: list[tuple[str, Any]] = []
        prefix = _prefix_tuple(start_oid)
        prefix_len = len(prefix)
        var_iter = ObjectType(ObjectIdentity(start_oid))
        for _ in range(200):
            err_ind, err_status, _err_idx, var_binds = await nextCmd(
                engine, community, target, ctx, var_iter,
                lexicographicMode=False,
            )
            if err_ind or err_status or not var_binds:
                break
            stop = False
            for vb in var_binds:
                if isinstance(vb, list):
                    if not vb:
                        stop = True
                        break
                    oid_obj, val = vb[0]
                else:
                    oid_obj, val = vb
                try:
                    oid_tup = tuple(oid_obj.getOid().asTuple())
                except Exception:
                    continue
                if oid_tup[:prefix_len] != prefix:
                    stop = True
                    break
                # Peer IP is the last 4 sub-ids.
                if len(oid_tup) < prefix_len + 4:
                    continue
                peer_ip = ".".join(str(x) for x in oid_tup[-4:])
                results.append((peer_ip, val))
                var_iter = ObjectType(oid_obj)
            if stop:
                break
        return results

    # First walk peerRemoteAs so we can tag every other metric with the
    # AS number too.
    peer_as: dict[str, str] = {}
    try:
        for peer_ip, val in await _walk_bgp(BGP_PEER_OIDS["parity.snmp.bgp.peerRemoteAs"]):
            try:
                peer_as[peer_ip] = str(int(val))
            except Exception:
                continue
    except Exception as e:
        log.debug("snmp_bgp_remoteas_walk_failed", device=dev["hostname"], error=str(e))

    bgp_state_now: dict[str, int] = {}
    for metric, oid in BGP_PEER_OIDS.items():
        try:
            for peer_ip, val in await _walk_bgp(oid):
                try:
                    v = int(val)
                except Exception:
                    continue
                as_tag = peer_as.get(peer_ip, "")
                extra = f',peer_as="{as_tag}"' if as_tag else ""
                lines.append(
                    f'{metric},{base_dims},peer_ip="{peer_ip}"{extra} {v}'
                )
                if metric == "parity.snmp.bgp.peerState":
                    bgp_state_now[peer_ip] = v
        except Exception as e:
            log.debug(
                "snmp_bgp_walk_failed",
                device=dev["hostname"], oid=oid, error=str(e),
            )

    # ── Edge-trigger anomaly events ──
    # Compare current state to last cycle's snapshot for this device.
    # Emit a Davis-relayable event ONLY on transitions, never on every
    # cycle, never on the first cycle (when prior is empty). The
    # davis-relay workflow turns these into Davis Problems.
    await _detect_and_emit_transitions(
        dev, intf_state_now=intf_state_now, bgp_state_now=bgp_state_now,
        peer_as=peer_as, if_descr=if_descr,
    )

    return lines


# ── Push line-protocol to Dynatrace ──────────────────────────


async def _push(lines: list[str]) -> tuple[int, int]:
    """POST a chunk of line-protocol metrics. Returns (sent, rejected)."""
    if not lines:
        return 0, 0
    token = await _metrics_ingest_token()
    if not token:
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
                        "Authorization": f"Api-Token {token}",
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
