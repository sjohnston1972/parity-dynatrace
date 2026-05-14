"""Parity Dynatrace MCP stub server.

Returns canned Davis-style problems so the rest of Parity (ADK agents,
ingestion routes, UI) can be built and demoed before we connect a real
Dynatrace tenant. The tool surface and JSON shapes mirror the real
@dynatrace-oss/dynatrace-mcp-server so swapping the URL in .env once
you have a tenant is the only change required.

Exposes the streamable-HTTP transport on /mcp at port 8000. Plus a
plain /health endpoint for the Docker healthcheck so we don't have to
speak MCP from a shell probe.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("parity-dt-mcp-stub")

# FastMCP defaults DNS-rebinding protection ON, which validates the
# request Host header against an allowlist (only 127.0.0.1/localhost
# by default). In a Docker network requests arrive with Host:
# "parity-dt-mcp:8000" — those get a 421 Misdirected Request. Allow
# the container's hostname so the backend can call us.
mcp = FastMCP(
    name="parity-dynatrace-stub",
    instructions=(
        "Dynatrace MCP server stub for the Parity hackathon project. "
        "Same tool surface as @dynatrace-oss/dynatrace-mcp-server but "
        "returns canned data so downstream agents can be built without "
        "a live Dynatrace tenant."
    ),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _ago_iso(minutes: int) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(minutes=minutes)).isoformat()


# ── Canned Davis-style problems ──────────────────────────────
# Shapes mirror the real Dynatrace Problem entity. Three problems
# representing the kind of incidents Parity is designed to spot:
#   1. BGP peer down — critical, single device.
#   2. Interface error storm — high, single device.
#   3. Synthetic monitor failing — medium, cross-device.

_PROBLEMS = [
    {
        "problemId": "P-2026-05-13-1842",
        "displayId": "P-1842",
        "title": "BGP neighbor down on S1-R1",
        "displayName": "BGP_NEIGHBOR_DOWN",
        "severityLevel": "ERROR",
        "status": "OPEN",
        "impactLevel": "INFRASTRUCTURE",
        "startTime": _ago_iso(18),
        "endTime": None,
        "affectedEntities": [
            {
                "entityId": {
                    "id": "HOST-S1R1-CLYDEFORD",
                    "type": "HOST",
                },
                "name": "S1-R1.clydeford.net",
            }
        ],
        "rootCauseEntity": {
            "entityId": {"id": "HOST-S1R1-CLYDEFORD", "type": "HOST"},
            "name": "S1-R1.clydeford.net",
        },
        "evidenceDetails": {
            "totalEvidenceCount": 3,
            "details": [
                {
                    "evidenceType": "EVENT",
                    "displayName": "BGP session to 10.0.0.2 transitioned to Idle",
                    "startTime": _ago_iso(18),
                },
                {
                    "evidenceType": "METRIC",
                    "displayName": "bgp.peers.up dropped from 2 to 1",
                    "startTime": _ago_iso(17),
                },
                {
                    "evidenceType": "EVENT",
                    "displayName": "Adjacency lost to neighbor 10.0.0.2 (AS 65020)",
                    "startTime": _ago_iso(17),
                },
            ],
        },
        "managementZones": [{"id": "1", "name": "Production"}],
    },
    {
        "problemId": "P-2026-05-13-1903",
        "displayId": "P-1903",
        "title": "Input errors burst on S2-R1 GigabitEthernet0/1",
        "displayName": "INTERFACE_ERROR_STORM",
        "severityLevel": "ERROR",
        "status": "OPEN",
        "impactLevel": "SERVICE",
        "startTime": _ago_iso(9),
        "endTime": None,
        "affectedEntities": [
            {
                "entityId": {
                    "id": "HOST-S2R1-CLYDEFORD",
                    "type": "HOST",
                },
                "name": "S2-R1.clydeford.net",
            }
        ],
        "rootCauseEntity": {
            "entityId": {"id": "HOST-S2R1-CLYDEFORD", "type": "HOST"},
            "name": "S2-R1.clydeford.net",
        },
        "evidenceDetails": {
            "totalEvidenceCount": 2,
            "details": [
                {
                    "evidenceType": "METRIC",
                    "displayName": "interface.input_errors > 1200 errors/min on Gi0/1",
                    "startTime": _ago_iso(9),
                },
                {
                    "evidenceType": "METRIC",
                    "displayName": "interface.crc_errors rising on Gi0/1",
                    "startTime": _ago_iso(8),
                },
            ],
        },
        "managementZones": [{"id": "1", "name": "Production"}],
    },
    {
        "problemId": "P-2026-05-13-1855",
        "displayId": "P-1855",
        "title": "Synthetic monitor failing — login.clydeford.net",
        "displayName": "SYNTHETIC_MONITOR_FAILURE",
        "severityLevel": "WARNING",
        "status": "OPEN",
        "impactLevel": "APPLICATION",
        "startTime": _ago_iso(31),
        "endTime": None,
        "affectedEntities": [
            {
                "entityId": {
                    "id": "SYNTHETIC_TEST-LOGIN-CLYDEFORD",
                    "type": "SYNTHETIC_TEST",
                },
                "name": "login.clydeford.net",
            },
            {
                "entityId": {
                    "id": "HOST-SJFW01-CLYDEFORD",
                    "type": "HOST",
                },
                "name": "SJFW01.clydeford.net",
            },
        ],
        "rootCauseEntity": None,
        "evidenceDetails": {
            "totalEvidenceCount": 2,
            "details": [
                {
                    "evidenceType": "EVENT",
                    "displayName": "HTTP 504 from /auth at three monitoring locations",
                    "startTime": _ago_iso(31),
                },
                {
                    "evidenceType": "METRIC",
                    "displayName": "Response time > 30s for 6 consecutive checks",
                    "startTime": _ago_iso(28),
                },
            ],
        },
        "managementZones": [{"id": "2", "name": "Edge"}],
    },
]


@mcp.tool()
def list_problems() -> dict:
    """List currently open Davis problems.

    Returns the same envelope shape as the real Dynatrace MCP's
    list_problems tool: ``{"problems": [...], "totalCount": N}``.
    """
    log.info("list_problems called -> %d problems", len(_PROBLEMS))
    return {"problems": _PROBLEMS, "totalCount": len(_PROBLEMS)}


@mcp.tool()
def find_entity_by_name(name: str) -> dict:
    """Resolve an entity by name (case-insensitive substring match)."""
    name_lc = (name or "").lower()
    matches: list[dict] = []
    for p in _PROBLEMS:
        for e in p["affectedEntities"]:
            if name_lc in e["name"].lower():
                matches.append(e)
    log.info("find_entity_by_name(%r) -> %d matches", name, len(matches))
    return {"entities": matches}


@mcp.tool()
def execute_dql(query: str) -> dict:
    """Stubbed DQL executor — returns an empty result set with the query echoed.

    Real Dynatrace MCP would run this against Grail. For the stub we
    just record the query so demos can show the *intent* to query
    without us needing a real tenant.
    """
    log.info("execute_dql called: %s", query[:120])
    return {"query": query, "records": [], "metadata": {"stubbed": True}}


# ── Davis Copilot stub ───────────────────────────────────────
# The real chat_with_davis_copilot tool sends a free-form prompt
# (plus optional structured context) to Dynatrace's Davis AI and
# returns its analysis. For the stub we pattern-match on the diff
# context the caller supplies so the demo gets realistic-looking
# reasoning even without a live tenant.


def _classify_diff(diff: dict) -> dict:
    """Walk a pyATS diff and produce a Davis-style verdict.

    Looks for fingerprints of common network anomalies — BGP adjacency
    transitions, interface oper-state changes, route-count crashes,
    OSPF neighbour churn — and returns a structured reasoning block.
    Falls back to a generic 'state change observed' verdict when no
    fingerprint matches.
    """
    changes = diff.get("changes") if isinstance(diff, dict) else None
    if not isinstance(changes, dict) or not changes:
        return {
            "severity": "INFO",
            "category": "no-change",
            "title": "No structural change observed",
            "summary": (
                "Davis examined the snapshot diff and found no significant "
                "state transitions on this device. Counters and timers were "
                "filtered as noise."
            ),
            "evidence": [],
            "recommended_actions": [],
            "confidence": 0.95,
        }

    paths = list(changes.keys())
    paths_joined = " ".join(paths).lower()

    # BGP adjacency loss
    if "bgp" in paths_joined and any(
        marker in paths_joined for marker in ("idle", "active", "session", "neighbor")
    ):
        affected = [p for p in paths if "bgp" in p.lower()][:5]
        return {
            "severity": "ERROR",
            "category": "bgp-adjacency",
            "title": "BGP adjacency transition detected",
            "summary": (
                "One or more BGP sessions on this device transitioned out of "
                "Established state between the two snapshots. Likely loss of "
                "reachability to the remote AS, peer-side configuration drift, "
                "or a routing policy change. Investigate transport reachability, "
                "BGP timers, and recent config changes."
            ),
            "evidence": affected,
            "recommended_actions": [
                "show ip bgp summary",
                "show bgp neighbors <peer> | include BGP state",
                "ping <peer-bgp-source-ip>",
            ],
            "confidence": 0.92,
        }

    # Interface oper-state change
    if any(("interface" in p.lower() and "oper_status" in p.lower()) for p in paths):
        affected = [p for p in paths if "oper_status" in p.lower()][:5]
        return {
            "severity": "ERROR",
            "category": "interface-state",
            "title": "Interface oper-state changed",
            "summary": (
                "At least one interface flipped operational state since the last "
                "snapshot. Look for physical-layer issues (link, transceiver, "
                "cable), administrative-state changes, or upstream STP/LACP "
                "convergence."
            ),
            "evidence": affected,
            "recommended_actions": [
                "show interfaces <intf> status",
                "show interfaces <intf> counters errors",
                "show logging | include <intf>",
            ],
            "confidence": 0.9,
        }

    # OSPF neighbour churn
    if "ospf" in paths_joined and ("neighbor" in paths_joined or "state" in paths_joined):
        affected = [p for p in paths if "ospf" in p.lower()][:5]
        return {
            "severity": "WARNING",
            "category": "ospf-adjacency",
            "title": "OSPF adjacency change",
            "summary": (
                "OSPF neighbour state moved away from FULL/2WAY on at least one "
                "adjacency. Possible causes: MTU mismatch, hello-interval drift, "
                "area/auth misconfiguration, or upstream link instability."
            ),
            "evidence": affected,
            "recommended_actions": [
                "show ip ospf neighbor",
                "show ip ospf interface brief",
                "debug ip ospf events  (use with care)",
            ],
            "confidence": 0.85,
        }

    # Route-table change
    if "routing" in paths_joined or "route" in paths_joined:
        affected = [p for p in paths if "rout" in p.lower()][:5]
        return {
            "severity": "WARNING",
            "category": "routing-instability",
            "title": "Routing table change",
            "summary": (
                "Routing table contents shifted between snapshots — added, "
                "removed, or changed prefixes. Could reflect a legitimate "
                "topology change, but a sudden drop in route count usually "
                "indicates a peer flap, redistribution glitch, or filter "
                "misconfiguration."
            ),
            "evidence": affected,
            "recommended_actions": [
                "show ip route summary",
                "show ip route | include <prefix>",
                "show ip bgp neighbors <peer> received-routes",
            ],
            "confidence": 0.8,
        }

    # ARP plane wobble — often a downstream effect of interface/routing change
    if "arp" in paths_joined:
        affected = [p for p in paths if "arp" in p.lower()][:5]
        return {
            "severity": "INFO",
            "category": "arp-change",
            "title": "ARP table change",
            "summary": (
                "ARP entries changed since the last snapshot. Usually a "
                "downstream symptom of an interface or VLAN change rather "
                "than a root cause."
            ),
            "evidence": affected,
            "recommended_actions": [
                "show ip arp",
                "show interfaces description",
            ],
            "confidence": 0.7,
        }

    # Catch-all
    return {
        "severity": "INFO",
        "category": "state-change",
        "title": f"{len(paths)} state change(s) observed",
        "summary": (
            "Davis detected structural changes in the device state but no "
            "specific fingerprint matched. Inspect the listed paths for "
            "operational impact."
        ),
        "evidence": paths[:8],
        "recommended_actions": [
            "Review the listed paths in the diff",
            "Compare against the previous successful snapshot",
        ],
        "confidence": 0.6,
    }


@mcp.tool()
def chat_with_davis_copilot(prompt: str, context: dict | None = None) -> dict:
    """Send a prompt + optional context to Davis Copilot for AI analysis.

    The real Davis Copilot accepts a free-form prompt with optional
    structured context (a JSON payload of evidence, e.g. a network state
    diff). It returns Davis's interpretation — severity, likely cause,
    suggested investigation steps.

    The stub pattern-matches against ``context["diff"]`` (a pyATS diff
    object) so callers get a realistic verdict shape without a live
    Dynatrace tenant. Schema matches what the production endpoint
    returns: ``{title, severity, summary, evidence, recommended_actions,
    confidence}``.
    """
    diff = (context or {}).get("diff") if isinstance(context, dict) else None
    log.info(
        "chat_with_davis_copilot(prompt=%r, has_diff=%s)",
        (prompt or "")[:80],
        diff is not None,
    )
    verdict = _classify_diff(diff or {})
    verdict["prompt_echo"] = (prompt or "")[:200]
    return verdict


# ── Health route on a sibling Starlette app ──────────────────


async def health(_request):
    return JSONResponse({"status": "ok", "service": "parity-dt-mcp-stub"})


# FastMCP's streamable_http_app() returns a Starlette app rooted at /mcp.
# We graft a plain /health endpoint alongside it for Docker probes.
streamable = mcp.streamable_http_app()
app = Starlette(
    routes=[
        Route("/health", health),
        Mount("/", app=streamable),
    ],
    lifespan=streamable.router.lifespan_context,
)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    log.info("starting parity-dt-mcp-stub on :%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
