"""Chat endpoint — Parity chat assistant on Google ADK.

Streaming SSE protocol matches the kopis-era client expectations so
the React UI works without changes:

    data: {"type": "tool_use",    "name": ..., "input": {...}}
    data: {"type": "tool_result", "name": ..., "preview": "..."}
    data: {"type": "text",        "text": "..."}
    data: [DONE]

ADK's Runner emits events for each turn — function calls, function
responses, and final text. We translate those into the wire shapes
above so the existing ChatPanel.jsx component understands them.
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import structlog
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

from agents.chat_agent import build_chat_agent

router = APIRouter(prefix="/chat", tags=["chat"])
log = structlog.get_logger()


# In-memory session store is fine for the assistant — each chat thread
# is short-lived and we don't need history to survive backend restarts.
# DatabaseSessionService stays untouched (see feedback memory: ADK tool
# confirmation doesn't support it, so we'd hit edge cases if we tried).
_session_service = InMemorySessionService()


class ChatRequest(BaseModel):
    messages: list[dict]
    model: str | None = None  # Reserved for future tier override


def _truncate(s: str, n: int = 240) -> str:
    if not s:
        return ""
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _user_text(messages: list[dict]) -> str:
    """Concatenate the *latest* user-turn content into a single string.

    The frontend sends the entire conversation history each request, but
    ADK's Runner already maintains conversation state in the session,
    so we only feed it the newest user message. We treat the last
    user-role message as the input. If the client sends multiple user
    turns at once we join them.
    """
    last_user_parts: list[str] = []
    for m in reversed(messages):
        role = m.get("role")
        content = m.get("content")
        if role != "user":
            if last_user_parts:
                break
            continue
        if isinstance(content, str):
            last_user_parts.insert(0, content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    last_user_parts.insert(0, block.get("text", ""))
    return "\n".join(p for p in last_user_parts if p)


@router.post("")
async def chat(req: ChatRequest):
    """Run the user's latest turn through the ADK chat agent."""
    agent = build_chat_agent()
    runner = Runner(
        agent=agent,
        app_name="parity-chat",
        session_service=_session_service,
    )

    user_id = "anonymous"
    session_id = f"sess-{uuid4().hex[:12]}"
    await _session_service.create_session(
        app_name="parity-chat",
        user_id=user_id,
        session_id=session_id,
    )

    user_msg = _user_text(req.messages) or "Hello."
    content = types.Content(role="user", parts=[types.Part(text=user_msg)])

    async def generate():
        queue: asyncio.Queue = asyncio.Queue()

        async def producer():
            try:
                async for event in runner.run_async(
                    user_id=user_id,
                    session_id=session_id,
                    new_message=content,
                ):
                    # ── Tool calls (function_call parts on the model turn) ──
                    fcalls = event.get_function_calls() if hasattr(event, "get_function_calls") else []
                    for fc in fcalls or []:
                        await queue.put({
                            "type": "tool_use",
                            "name": fc.name,
                            "input": dict(fc.args or {}),
                        })

                    # ── Tool responses (function_response parts on the user turn) ──
                    fresps = event.get_function_responses() if hasattr(event, "get_function_responses") else []
                    for fr in fresps or []:
                        preview_src = fr.response
                        if isinstance(preview_src, dict):
                            preview_src = preview_src.get("result", preview_src)
                        await queue.put({
                            "type": "tool_result",
                            "name": fr.name,
                            "preview": _truncate(str(preview_src)),
                        })

                    # ── Final text reply ──
                    if event.is_final_response() and event.content and event.content.parts:
                        text = "".join(
                            (p.text or "") for p in event.content.parts if hasattr(p, "text")
                        )
                        if text:
                            await queue.put({"type": "text", "text": text})
            except Exception as e:
                log.exception("chat_agent_failed")
                await queue.put({"type": "text", "text": f"\n\n[chat error: {e}]"})
            finally:
                await queue.put(None)

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
