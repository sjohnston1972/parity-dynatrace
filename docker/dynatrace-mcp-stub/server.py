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
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("parity-dt-mcp-stub")

mcp = FastMCP(
    name="parity-dynatrace-stub",
    instructions=(
        "Dynatrace MCP server stub for the Parity hackathon project. "
        "Same tool surface as @dynatrace-oss/dynatrace-mcp-server but "
        "returns canned data so downstream agents can be built without "
        "a live Dynatrace tenant."
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
