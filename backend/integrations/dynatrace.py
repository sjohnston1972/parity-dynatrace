"""Dynatrace integration via MCP.

Talks to the Dynatrace MCP server (stub today, real @dynatrace-oss/
dynatrace-mcp-server later) over the streamable-HTTP transport. The
URL is configurable via ``settings.dt_mcp_url`` (env: DT_MCP_URL).

This client is the *non-agent* code path — used by ingestion routes
and verification logic that want to call MCP tools directly without
spinning up an ADK agent. ADK agents talk to the same MCP server via
``McpToolset`` in the agent definitions.
"""

from __future__ import annotations

import json

import structlog
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from config import settings

log = structlog.get_logger()


# Severity mapping: Dynatrace problem severity → Parity finding severity.
_SEVERITY = {
    "ERROR": "critical",
    "CRITICAL": "critical",
    "WARNING": "high",
    "WARN": "high",
    "INFO": "medium",
    "AVAILABILITY": "high",
    "PERFORMANCE": "high",
    "MONITORING_UNAVAILABLE": "medium",
}


def severity_for(level: str | None) -> str:
    return _SEVERITY.get((level or "").upper(), "medium")


class DynatraceClient:
    """Lightweight Dynatrace MCP wrapper for non-agent code paths."""

    def __init__(self, mcp_url: str | None = None):
        self.mcp_url = mcp_url or settings.dt_mcp_url

    async def _call_tool(self, name: str, arguments: dict | None = None) -> dict:
        """Open an MCP session, call a tool, parse the JSON result.

        Tools on FastMCP return Python dicts which the protocol delivers
        as a JSON-stringified content block. We parse that back to a dict
        so callers can work with structured data.
        """
        async with streamablehttp_client(self.mcp_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments or {})

        # FastMCP returns structuredContent when available, or content blocks.
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            return structured
        for block in result.content or []:
            text = getattr(block, "text", None)
            if text:
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"text": text}
        return {}

    async def list_problems(self) -> list[dict]:
        """Return open Davis problems."""
        body = await self._call_tool("list_problems")
        return body.get("problems", []) if isinstance(body, dict) else []

    async def find_entity_by_name(self, name: str) -> list[dict]:
        body = await self._call_tool("find_entity_by_name", {"name": name})
        return body.get("entities", []) if isinstance(body, dict) else []

    async def execute_dql(self, query: str) -> dict:
        return await self._call_tool("execute_dql", {"query": query})


dynatrace_client = DynatraceClient()
