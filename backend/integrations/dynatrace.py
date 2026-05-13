"""Dynatrace integration.

Parity talks to Dynatrace through its MCP server (``@dynatrace-oss/dynatrace-mcp-server``)
rather than the REST API directly. Tools the agent layer consumes:

  * ``list_problems`` — Davis-detected problems (the source of findings)
  * ``find_entity_by_name`` — entity resolution for enrichment
  * ``execute_dql`` — Grail queries (topology, synthetic monitors, etc.)
  * ``execute_davis_analyzer`` — Davis AI analyzers when deeper reasoning is needed

Rewire 3 implements this module. Until then it's a placeholder so the
ingestion route and verification step can import cleanly.
"""

from __future__ import annotations


class DynatraceClient:
    """Wraps MCP tool calls behind a Python-friendly API.

    During Rewire 3 the agent layer will receive an ``McpToolset`` directly
    (so the LLM can pick which tool to call). This client exists for the
    *non-agent* code paths — ingestion polling, the verify step, ad-hoc
    queries from FastAPI routes — where calling MCP tools by name is cleaner
    than going through an agent.
    """

    def __init__(self, mcp_url: str):
        self.mcp_url = mcp_url

    async def list_problems(self) -> list[dict]:
        """Return open Davis problems. See real schema at:
        https://docs.dynatrace.com/docs/dynatrace-intelligence/dynatrace-mcp
        """
        raise NotImplementedError("Wired in Rewire 3.")
