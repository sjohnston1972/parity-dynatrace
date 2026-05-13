"""Chat endpoint — temporarily stubbed during the LLM swap.

The kopis chat assistant ran an Anthropic tool-use loop over twelve
tools (see ``backend/services/chat_tools.py``). Porting that loop to
Gemini's function-calling shape would be ~150 lines of throwaway code,
because Rewire 2 turns the assistant into a Google ADK ``LlmAgent``
whose tool-loop is handled by the framework natively.

So during Rewire 1 the route returns HTTP 503 with a structured body
the React UI can recognise and surface as a "rewiring in progress"
notice. ``SYSTEM_PROMPT`` and the tool import are kept so Rewire 2
can find their natural home unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.chat_tools import TOOLS  # noqa: F401 — kept for Rewire 2

router = APIRouter(prefix="/chat", tags=["chat"])


SYSTEM_PROMPT = """You are Parity, an AI network operations assistant for a homelab network running in GNS3.

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


class ChatRequest(BaseModel):
    messages: list[dict]
    model: str | None = None


_STUB_BODY = {
    "error": "chat_unavailable",
    "message": (
        "The chat assistant is being rebuilt on Google ADK. It returns in "
        "Rewire 2 with the same twelve tools and a streaming UI. For now, "
        "use /api/v1/llm/ping to confirm Gemini reachability, or hit the "
        "individual REST endpoints (devices, findings, incidents) directly."
    ),
    "rewire_phase": 2,
}


@router.post("")
async def chat_stub(req: ChatRequest):
    """Placeholder for the future ADK-backed chat assistant."""
    return JSONResponse(status_code=503, content=_STUB_BODY)
