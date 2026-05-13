"""Chat endpoint — agentic conversation with Claude about this network.

Claude has access to a tool registry (services/chat_tools.py) of read-only
network queries plus a snapshot trigger and a safe show-command runner.
Each user message kicks off an agentic loop:
  1. Send messages + tools to Claude
  2. If response has tool_use blocks, execute each tool
  3. Append tool_results to messages, loop back to step 1
  4. When Claude returns end_turn, stream the final text back to the UI

The protocol back to the frontend is SSE with three event shapes:
  data: {"type": "tool_use",    "name": ..., "input": {...}}
  data: {"type": "tool_result", "name": ..., "preview": "..."}
  data: {"type": "text",        "text": "..."}
  data: [DONE]

A short system prompt sets the agent's role and orientation. The big
context dumps the old chat used to inject (full inventory, every
snapshot summary, all findings) are gone — Claude fetches what it
needs via tools, which keeps a "hello" cheap and lets a real
diagnostic question pull only the relevant data.
"""

from __future__ import annotations

import json

import httpx
import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.postgres import get_db
from db.tables import Device
from services.chat_tools import TOOLS, execute_tool

router = APIRouter(prefix="/chat", tags=["chat"])
log = structlog.get_logger()

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


class ChatRequest(BaseModel):
    messages: list[dict]
    model: str | None = None


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


def _truncate(s: str, n: int = 240) -> str:
    """Compact preview shown to the UI for each tool result."""
    if not s:
        return ""
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


async def _anthropic_call(payload: dict) -> dict:
    """One non-streaming Anthropic call. Used for tool-use turns."""
    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(ANTHROPIC_API_URL, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()


async def _anthropic_stream(payload: dict, sse_emit):
    """Final streaming Anthropic call — pushes text deltas to the SSE channel."""
    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", ANTHROPIC_API_URL, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        await sse_emit({"type": "text", "text": delta["text"]})


def _normalise_messages(raw: list[dict]) -> list[dict]:
    """Anthropic's Messages API rejects any extra keys beyond {role, content}.
    The chat UI carries UI-only fields (e.g. toolCalls) on its message
    objects; clients may also send other metadata. Strip everything that
    isn't part of the wire schema before the loop forwards them.
    """
    cleaned = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant"):
            continue
        if content is None:
            continue
        cleaned.append({"role": role, "content": content})
    return cleaned


@router.post("")
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)):
    model = req.model or settings.haiku_model
    messages = _normalise_messages(req.messages)

    # We don't pre-inject device data anymore — Claude calls list_devices
    # if it needs the inventory. That keeps trivial chats cheap.
    system = SSE_TERMINATOR = None
    system = SYSTEM_PROMPT

    async def generate():
        # Inline async queue so we can fan out events from the tool loop
        # AND from the final streaming call into one SSE response.
        import asyncio
        queue: asyncio.Queue = asyncio.Queue()

        async def emit(event: dict):
            await queue.put(event)

        async def producer():
            try:
                # ── Agentic loop ─────────────────────────────────────
                # Cap iterations to avoid runaway loops if Claude keeps
                # calling tools without converging. 8 is generous —
                # most real questions need 1–3 tool calls.
                for _ in range(8):
                    payload = {
                        "model": model,
                        "max_tokens": 4096,
                        "temperature": 0.3,
                        "system": system,
                        "tools": TOOLS,
                        "messages": messages,
                    }
                    result = await _anthropic_call(payload)
                    stop_reason = result.get("stop_reason")
                    content_blocks = result.get("content", [])

                    if stop_reason == "tool_use":
                        # Append the assistant turn (with the tool_use blocks) to history
                        messages.append({"role": "assistant", "content": content_blocks})

                        # Execute each tool_use block, build the tool_result reply
                        tool_results = []
                        for block in content_blocks:
                            if block.get("type") != "tool_use":
                                continue
                            name = block.get("name", "")
                            args = block.get("input", {}) or {}
                            tool_id = block.get("id", "")
                            await emit({"type": "tool_use", "name": name, "input": args})

                            output = await execute_tool(db, name, args)
                            await emit({
                                "type": "tool_result",
                                "name": name,
                                "preview": _truncate(output),
                            })
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": output,
                            })

                        messages.append({"role": "user", "content": tool_results})
                        continue  # loop back for the next turn

                    # ── No more tool calls — final answer ─────────────
                    # Re-issue as streaming so the user sees text as it's
                    # generated. The non-streaming call we just made is
                    # discarded (its content is already in `content_blocks`
                    # but we want token-by-token feel for the operator).
                    # OPTIMISATION: skip the re-call if there's no text
                    # content — sometimes the model returns just a tool
                    # rejection or an empty content block.
                    has_text = any(b.get("type") == "text" and b.get("text") for b in content_blocks)
                    if not has_text:
                        await emit({"type": "text", "text": "(no response)"})
                        break

                    # Stream the final answer fresh
                    stream_payload = {
                        "model": model,
                        "max_tokens": 4096,
                        "temperature": 0.3,
                        "system": system,
                        "tools": TOOLS,
                        "messages": messages,
                        "stream": True,
                    }
                    await _anthropic_stream(stream_payload, emit)
                    break
                else:
                    await emit({"type": "text", "text": "(tool loop hit cap — stopping)"})
            except httpx.HTTPStatusError as e:
                await emit({"type": "text", "text": f"\n\n[chat error: {e.response.status_code} {e.response.text[:200]}]"})
            except Exception as e:
                log.exception("chat_loop_failed")
                await emit({"type": "text", "text": f"\n\n[chat error: {e}]"})
            finally:
                await queue.put(None)  # sentinel

        producer_task = asyncio.create_task(producer())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            if not producer_task.done():
                producer_task.cancel()

    return StreamingResponse(generate(), media_type="text/event-stream")
