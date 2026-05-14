"""ADK-backed chat assistant.

The twelve network-operations tools are wrapped here as plain async
Python functions so the ADK ``LlmAgent`` can introspect each signature
into a Gemini function declaration without us hand-translating JSON
schemas.

Each wrapper opens its own AsyncSession via ``async_session()`` — ADK
tools are not given the FastAPI request DB session, so we re-open one
per call. Wrapped handlers in ``services.chat_tools`` already expect
``(db, args)`` and produce a string, which is exactly what an ADK tool
should return for the model to read.
"""

from __future__ import annotations

import structlog
from google.adk.agents import LlmAgent

from config import settings
from db.postgres import async_session
from services import chat_tools

log = structlog.get_logger()


CHAT_SYSTEM_PROMPT = """You are Parity, an AI network operations assistant for a homelab network running in GNS3.

You're an experienced network engineer with deep knowledge of Cisco IOS-XE, IOS-v, NX-OS, BGP, OSPF, spanning-tree, VLANs, and enterprise routing. The operator you're talking to is also a network engineer — be direct and technically dense, skip the basics.

## How you work

You have **tools** for reading the network's current state — device inventory, snapshots, findings, incidents, topology, approvals, execution history, semantic search over historical findings. You also have a snapshot trigger and a safe show-command runner.

**Use tools instead of guessing.** If the user asks about a specific device, call `get_device_snapshot`. If they ask about active issues, call `list_incidents` (preferred) or `list_findings`. If they ask "have we seen this before?", call `search_historical_findings`. If you need real-time state (the snapshot might be stale), use `run_show_command` with a `show` command.

Prefer `list_incidents` over `list_findings` for the operator-facing summary — incidents are the de-duplicated, correlated, root-cause-picked view. Findings are the raw underlying observations.

## What you cannot do

You cannot approve, deny, or execute remediations. You cannot modify device config. Those operations require explicit human action through the Approval flow with full audit trail. If the operator asks you to "fix" something, walk them through what's needed and point at the pending approval (or suggest they trigger a snapshot if the issue isn't yet detected).

`run_show_command` only accepts diagnostic commands (show / ping / traceroute) — anything else is rejected at the tool boundary.

## Style

- Be concise. Code blocks for CLI. No marketing fluff.
- When you reference a device, finding, or incident, use its short hostname or 8-char id so the operator can find it in the UI.
- If a tool returns no results, say so — don't fabricate a plausible-looking answer.
- Multi-step diagnostics: chain tool calls. Don't ask the operator for permission to call read-only tools."""


# ── Tool wrappers ────────────────────────────────────────────
# Each takes well-typed parameters (ADK introspects to build the Gemini
# function declaration) and delegates to the existing chat_tools handler.


async def list_devices() -> str:
    """List every device in inventory with hostname, management IP, platform (iosxe/fortinet/etc.), and type (router/switch/firewall). Use when you need to know what devices exist."""
    async with async_session() as db:
        return await chat_tools.t_list_devices(db, {})


async def get_device_snapshot(hostname: str) -> str:
    """Get the latest pyATS snapshot summary for one device — interfaces with state and IPs, BGP/OSPF neighbours and session states, routes per VRF, platform info.

    Args:
        hostname: Device hostname, full or short (e.g. 'S1-R1' or 'S1-R1.clydeford.net').
    """
    async with async_session() as db:
        return await chat_tools.t_get_device_snapshot(db, {"hostname": hostname})


async def list_findings(
    severity: str | None = None,
    category: str | None = None,
    device_hostname: str | None = None,
    limit: int = 20,
) -> str:
    """List active findings (open issues detected by the AI pipeline). Filter by severity (critical/high/medium/low/info), category (interface/routing/security/performance), or device.

    Args:
        severity: One of critical, high, medium, low, info.
        category: One of interface, routing, security, performance.
        device_hostname: Limit to findings for a single device.
        limit: Cap on returned findings (default 20).
    """
    args: dict = {}
    if severity is not None:
        args["severity"] = severity
    if category is not None:
        args["category"] = category
    if device_hostname is not None:
        args["device_hostname"] = device_hostname
    if limit is not None:
        args["limit"] = limit
    async with async_session() as db:
        return await chat_tools.t_list_findings(db, args)


async def list_incidents() -> str:
    """List active incidents (correlated finding groups). Each incident is one network event observed across one or more devices, with a single root cause and recommendation. Usually more useful than list_findings."""
    async with async_session() as db:
        return await chat_tools.t_list_incidents(db, {})


async def get_finding(finding_id: str) -> str:
    """Get full detail for one finding — device context, evidence, AI reasoning, recommendation commands, approval status, linked findings in the same incident.

    Args:
        finding_id: The finding's id (full UUID or short 8-char prefix).
    """
    async with async_session() as db:
        return await chat_tools.t_get_finding(db, {"finding_id": finding_id})


async def list_pending_approvals() -> str:
    """List remediations awaiting human approval — proposed CLI commands, risk level, AI reasoning, Jira ticket key."""
    async with async_session() as db:
        return await chat_tools.t_list_pending_approvals(db, {})


async def recent_executions(limit: int = 20) -> str:
    """List recent execution history (approvals that were executed, failed, or denied).

    Args:
        limit: Cap on returned executions (default 20).
    """
    async with async_session() as db:
        return await chat_tools.t_recent_executions(db, {"limit": limit})


async def get_topology() -> str:
    """Get the discovered network topology — devices, BGP peering edges (with from/to interfaces and AS), L2 segments (shared subnets via ARP). Use to understand how devices connect."""
    async with async_session() as db:
        return await chat_tools.t_get_topology(db, {})


async def get_dashboard_metrics() -> str:
    """Get the headline dashboard counts — interfaces up/down, BGP sessions, routes, ARP, VLANs, active findings by severity."""
    async with async_session() as db:
        return await chat_tools.t_get_dashboard(db, {})


async def search_historical_findings(query: str, limit: int = 5) -> str:
    """Semantic search over historical findings (active or resolved) in the ChromaDB vector store. Use to answer 'have we seen this before?'.

    Args:
        query: Natural-language search query.
        limit: Cap on returned matches (default 5).
    """
    async with async_session() as db:
        return await chat_tools.t_search_history(db, {"query": query, "limit": limit})


async def trigger_snapshot(hostname: str | None = None) -> str:
    """Trigger a fresh pyATS snapshot of a device (or all devices if hostname omitted). Returns immediately; the pipeline runs in the background.

    Args:
        hostname: Optional device hostname; omit to snapshot every device.
    """
    args: dict = {}
    if hostname:
        args["hostname"] = hostname
    async with async_session() as db:
        return await chat_tools.t_trigger_snapshot(db, args)


async def run_show_command(hostname: str, command: str) -> str:
    """Run a diagnostic command on a device via pyATS. ONLY show, ping, or traceroute commands are accepted — config changes are blocked at the tool boundary.

    Args:
        hostname: Target device hostname.
        command: Must start with 'show', 'ping', or 'traceroute'.
    """
    async with async_session() as db:
        return await chat_tools.t_run_show_command(
            db, {"hostname": hostname, "command": command}
        )


CHAT_TOOLS = [
    list_devices,
    get_device_snapshot,
    list_findings,
    list_incidents,
    get_finding,
    list_pending_approvals,
    recent_executions,
    get_topology,
    get_dashboard_metrics,
    search_historical_findings,
    trigger_snapshot,
    run_show_command,
]


def build_chat_agent() -> LlmAgent:
    """Construct the Parity chat assistant LlmAgent.

    Re-constructed per request rather than module-level so each request
    gets a fresh agent state (ADK reuses model + tool bindings cheaply).
    """
    return LlmAgent(
        name="parity_chat",
        description="Network operations chat assistant for Parity.",
        model=settings.gemini_flash_model,
        instruction=CHAT_SYSTEM_PROMPT,
        tools=CHAT_TOOLS,
    )
