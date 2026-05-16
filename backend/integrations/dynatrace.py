"""Dynatrace integration — MCP read path + direct REST write path.

Two distinct surfaces live here:

* ``DynatraceClient`` — talks to a Dynatrace MCP server (the in-stack
  stub today, the real ``@dynatrace-oss/dynatrace-mcp-server`` later)
  over the streamable-HTTP transport. Used by ingestion routes that
  pull canned/real Davis problems into Parity findings.

* ``DynatraceWriter`` — talks directly to the live Dynatrace tenant's
  Generic Events API (and Grail/DQL for read-back). Used to push every
  Parity finding/resolution out as a CUSTOM_DEPLOYMENT event so the
  Davis side gets a complete audit trail of what the network agent
  did. Authenticates with the platform token in
  ``settings.dt_platform_token`` (env: DT_PLATFORM_TOKEN) and reaches
  the ``<tenant>.live.dynatrace.com`` host derived from
  ``settings.dt_environment`` (env: DT_ENVIRONMENT, which is the
  ``apps.dynatrace.com`` URL).

The writer is a best-effort fire-and-forget — every call is wrapped
to swallow exceptions and log, because a Dynatrace outage must never
block the network remediation pipeline.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
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


# ── Direct REST writer ────────────────────────────────────────


def _derive_live_url(environment_url: str) -> str:
    """Convert apps.dynatrace.com URL → live.dynatrace.com URL.

    The platform front-end (DQL, UI, OAuth) lives on the apps domain.
    Classic ingest endpoints (events, logs, metrics) live on the live
    domain. The two share a tenant ID; we just swap the subdomain.
    """
    if not environment_url:
        return ""
    return environment_url.rstrip("/").replace(".apps.dynatrace.com", ".live.dynatrace.com")


class DynatraceWriter:
    """Push Parity findings/resolutions out to Dynatrace as Davis events.

    The token only needs ``environment-api:events:write``, which is the
    narrowest write scope on the platform. We use CUSTOM_DEPLOYMENT
    events because they do not require an entitySelector (network
    devices aren't OneAgent-monitored hosts in this tenant), so events
    flow as environment-scoped Davis events that show up in DQL via
    ``fetch events | filter source == "parity"``.
    """

    EVENT_TYPE = "CUSTOM_DEPLOYMENT"

    def __init__(
        self,
        environment_url: str | None = None,
        token: str | None = None,
        timeout: float = 6.0,
    ):
        self.apps_url = (environment_url or settings.dt_environment or "").rstrip("/")
        self.live_url = _derive_live_url(self.apps_url)
        self.token = token or settings.dt_platform_token
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.live_url and self.token)

    async def _post_event(self, payload: dict) -> dict | None:
        if not self.configured:
            return None
        url = f"{self.live_url}/api/v2/events/ingest"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json",
                    },
                )
            if r.status_code >= 400:
                log.warning(
                    "dynatrace_event_rejected",
                    status=r.status_code, body=r.text[:200],
                    title=payload.get("title"),
                )
                return None
            return r.json()
        except Exception as e:
            log.warning("dynatrace_event_send_failed", error=str(e),
                        title=payload.get("title"))
            return None

    def _finding_payload(self, finding: Any, *, action: str,
                         device_hostname: str | None = None) -> dict:
        """Build the events-ingest payload for a finding lifecycle moment.

        Custom properties become DQL-queryable attributes on the event
        (e.g. parity.finding.id, parity.severity). Keep keys lower-case
        and dot-delimited per the Dynatrace convention.
        """
        evidence = getattr(finding, "evidence", None) or {}
        corr = evidence.get("correlation_key") if isinstance(evidence, dict) else None
        hostname = device_hostname or getattr(finding, "affected_entity", None) or "unknown"

        title_prefix = {
            "created": "Parity finding raised",
            "resolved": "Parity finding resolved",
        }.get(action, "Parity finding event")

        title = f"{title_prefix}: {getattr(finding, 'title', '')}"[:255]

        properties: dict[str, str] = {
            "source": "parity",
            "parity.action": action,
            "parity.finding.id": str(getattr(finding, "id", "")),
            "parity.severity": str(getattr(finding, "severity", "") or ""),
            "parity.category": str(getattr(finding, "category", "") or ""),
            "parity.confidence": str(getattr(finding, "confidence", "") or ""),
            "parity.device": str(hostname),
            "parity.title": str(getattr(finding, "title", "") or "")[:255],
        }
        if corr:
            properties["parity.correlation_key"] = str(corr)
        incident_id = getattr(finding, "incident_id", None)
        if incident_id:
            properties["parity.incident.id"] = str(incident_id)

        return {
            "eventType": self.EVENT_TYPE,
            "title": title,
            "properties": properties,
            # Custom deployment events default to a 15-minute open window;
            # we want them to close immediately so the timeline shows
            # discrete moments rather than overlapping bands.
            "timeout": 1,
        }

    async def emit_finding_created(self, finding: Any,
                                   device_hostname: str | None = None) -> None:
        if not self.configured:
            return
        payload = self._finding_payload(
            finding, action="created", device_hostname=device_hostname
        )
        result = await self._post_event(payload)
        if result and result.get("eventIngestResults"):
            log.info("dynatrace_event_emitted",
                     action="created",
                     finding_id=getattr(finding, "id", None),
                     correlation_id=result["eventIngestResults"][0].get("correlationId"))

    async def emit_finding_resolved(self, finding: Any,
                                    device_hostname: str | None = None,
                                    phase: str | None = None) -> None:
        if not self.configured:
            return
        payload = self._finding_payload(
            finding, action="resolved", device_hostname=device_hostname
        )
        if phase:
            payload["properties"]["parity.resolved.phase"] = phase
        result = await self._post_event(payload)
        if result and result.get("eventIngestResults"):
            log.info("dynatrace_event_emitted",
                     action="resolved",
                     finding_id=getattr(finding, "id", None),
                     correlation_id=result["eventIngestResults"][0].get("correlationId"))

    # ── Read-back via Grail/DQL ──────────────────────────────

    async def query_parity_events(self, lookback: str = "-1h",
                                  limit: int = 50) -> list[dict]:
        """DQL: fetch recent Parity-emitted events from Grail.

        Used by the live-demo path that proves the round-trip — fire
        a finding, then read it back via DQL within seconds.
        """
        if not (self.apps_url and self.token):
            return []
        q = (
            f"fetch events, from:{lookback} "
            f"| filter source == \"parity\" "
            f"| sort timestamp desc | limit {limit}"
        )
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                start = await client.post(
                    f"{self.apps_url}/platform/storage/query/v1/query:execute",
                    json={"query": q},
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json",
                    },
                )
                start.raise_for_status()
                token = start.json().get("requestToken")
                if not token:
                    return []
                # Poll up to 5 times for the result (Grail is usually fast).
                for _ in range(5):
                    await asyncio.sleep(1)
                    poll = await client.get(
                        f"{self.apps_url}/platform/storage/query/v1/query:poll",
                        params={"request-token": token},
                        headers={"Authorization": f"Bearer {self.token}"},
                    )
                    if poll.status_code >= 400:
                        return []
                    body = poll.json()
                    if body.get("state") == "SUCCEEDED":
                        return body.get("result", {}).get("records", [])
        except Exception as e:
            log.warning("dynatrace_dql_failed", error=str(e))
        return []


dynatrace_writer = DynatraceWriter()
