"""Chat endpoint — Parity chat assistant on Google ADK.

Streams Server-Sent Events to the React UI in this shape:

    data: {"type": "tool_use",    "name": ..., "input": {...}}
    data: {"type": "tool_result", "name": ..., "preview": "..."}
    data: {"type": "text",        "text": "..."}
    data: [DONE]

ADK's Runner emits events for each turn — function calls, function
responses, and final text. We translate those into the wire shapes
above so the ChatPanel.jsx component renders them.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from uuid import uuid4

import structlog
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

from agents.chat_agent import build_chat_agent
from config import settings as parity_settings
from services.dynatrace_reasoner import (
    _extract_davis_answer,
    _looks_like_davis_rejection,
)

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
    # Frontend-collected snapshot of what the operator is looking at
    # RIGHT NOW (route, page title, list of visible entity refs).
    # Lets the assistant resolve "this incident" / "these devices"
    # without the user having to paste IDs. See ChatPanel.jsx for the
    # collection logic and the per-page parityPageContext globals.
    page_context: dict | None = None
    # Stable session id per chat panel mount. Without this every turn
    # got a fresh InMemorySessionService session and the agent lost
    # ALL memory of prior tool calls / responses between turns - which
    # is why follow-ups like "thats not cdp neighbours" came back with
    # "what output are you referring to?". The frontend now sends a
    # uuid generated on first chat-open; backend reuses the session.
    session_id: str | None = None
    # Opt-in toggle from the ChatPanel "Bring Davis in" button. When
    # False (default), Davis stays quiet — Gemini answers solo. When
    # True, every turn fans out to Davis Copilot in parallel and the
    # answer arrives as a `davis_text` SSE event. Default OFF because
    # Davis adds ~3s latency and is most useful when the operator is
    # specifically asking about live tenant state.
    davis_enabled: bool = False


def _truncate(s: str, n: int = 240) -> str:
    if not s:
        return ""
    s = s.replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# Detect when the operator is talking to ONE of the assistants by
# name. Matches "Hi Davis, ...", "Gemini, do you agree?",
# "@davis what about...", "hey gemini". The name must be followed
# by a word boundary AND a comma / colon / question mark / space-
# then-question word so casual mentions like "Davis is great" or
# "Gemini is faster" don't get treated as direct address.
_ADDRESSEE_RE = re.compile(
    r"^\s*(?:hi|hey|hello|ok|so|@)?\s*"
    r"(davis|gemini)"
    r"(?:[\s,:!.?]|$)",
    re.IGNORECASE,
)


def _detect_addressee(msg: str) -> str | None:
    """Return 'davis', 'gemini', or None when the message isn't
    obviously addressed to one of them. Only checks the first ~30
    chars so a long message mentioning both names mid-paragraph
    still gets the both-respond default."""
    head = (msg or "")[:40]
    m = _ADDRESSEE_RE.match(head)
    return m.group(1).lower() if m else None


# ── Davis "chimes in" group-chat helper ──
#
# Every chat turn fans out to BOTH Gemini (primary, via ADK Runner)
# and Davis Copilot (secondary, via the real Dynatrace MCP sidecar).
# Davis's answer is grounded in the tenant's monitored entities, so
# it routinely declines free-text questions ("not a valid question").
# We try a couple of progressively-simpler prompt shapes (same trick
# as `_call_davis_for_second_opinion`) and silently skip the bubble
# when all attempts get rejected — better to leave Davis quiet than
# to render a rejection banner that looks like a bug.

_DAVIS_DISABLED = os.environ.get(
    "PARITY_DAVIS_CHAT_DISABLED", ""
).lower() in ("1", "true", "yes")


def _davis_configured() -> bool:
    return (
        not _DAVIS_DISABLED
        and bool(parity_settings.dt_platform_token)
        and bool(parity_settings.dt_real_mcp_url)
    )


async def _ask_davis(user_msg: str, page_ctx: dict | None) -> str | None:
    """Ask Davis Copilot the same question the user asked Gemini.

    Returns the Davis answer string, or None when:
      - the real-MCP sidecar isn't configured, or
      - all retry prompts came back as rejections, or
      - the network call raised.

    Davis Copilot can ground its answers in everything live in the
    tenant — Davis Problems, custom events (incl. SNMP transitions
    Parity emits as AVAILABILITY_EVENTs against each CUSTOM_DEVICE),
    Grail logs/events, monitored entities. The first prompt frames
    the question as "what do you see in this tenant?" so Davis
    reaches for that data instead of replying with generic docs.
    """
    if not _davis_configured():
        return None
    from integrations.dynatrace import DynatraceClient
    client = DynatraceClient(mcp_url=parity_settings.dt_real_mcp_url)

    ctx_hint = ""
    if page_ctx:
        route = page_ctx.get("route") or ""
        title = page_ctx.get("title") or ""
        if route or title:
            ctx_hint = f" The operator is on the Parity '{title or route}' page."

    # Tell Davis up front it has access to everything in the tenant —
    # otherwise it tends to fall back to generic Dynatrace docs. The
    # CUSTOM_DEVICE entities are the 19 lab routers/switches that
    # Parity registered via the entities API; SNMP transitions and
    # finding lifecycles show up as events with source=="parity".
    tenant_preamble = (
        "You are Davis Copilot, embedded in the Parity NetOps "
        "assistant alongside Google Gemini. You have full access to "
        "the live Dynatrace tenant (kea15603): Davis Problems, all "
        "events (incl. CUSTOM_DEPLOYMENT/AVAILABILITY_EVENT entries "
        "with source==\"parity\" and parity.snmp.transition==\"true\" "
        "from the SNMP poller), Grail logs, metrics, and the 19 "
        "CUSTOM_DEVICE entities representing the lab network "
        "(S1-R1..S4-S2 + DC1-R1 + DC2-R2, all suffixed "
        "'.clydeford.net'). Prefer reaching into that data over "
        "answering from documentation. If you query Grail, summarise "
        "the answer in 2-4 sentences rather than dumping rows."
        f"{ctx_hint}"
    )

    prompts = [
        # First try: framed prompt with tenant preamble.
        f"{tenant_preamble}\n\nOperator question: {user_msg.strip()[:1500]}",
        # Fallback: bare question with a 'use tenant data' nudge.
        (
            "Using only the data you have for this Dynatrace tenant "
            "(kea15603) — Davis Problems, events, logs, the 19 "
            "CUSTOM_DEVICE entities — briefly answer in 1-3 sentences: "
            f"{user_msg.strip()[:600]}"
        ),
    ]
    last_answer = ""
    for prompt_text in prompts:
        try:
            body = await client._call_tool(
                "chat_with_davis_copilot",
                {"text": prompt_text},
            )
        except Exception as e:
            log.warning("davis_chat_call_failed", error=str(e))
            return None
        answer = _extract_davis_answer(body)
        if answer and not _looks_like_davis_rejection(answer):
            return answer
        last_answer = answer
    # Both prompts rejected — stay quiet rather than emit a rejection.
    log.info(
        "davis_chat_declined",
        snippet=(last_answer or "")[:120],
    )
    return None


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
    # Reuse the frontend-supplied session id so multi-turn context
    # actually carries between requests. Fall back to a fresh uuid
    # only if the client didn't send one (legacy callers).
    session_id = req.session_id or f"sess-{uuid4().hex[:12]}"
    existing = await _session_service.get_session(
        app_name="parity-chat",
        user_id=user_id,
        session_id=session_id,
    )
    if existing is None:
        await _session_service.create_session(
            app_name="parity-chat",
            user_id=user_id,
            session_id=session_id,
        )

    user_msg = _user_text(req.messages) or "Hello."

    # Prepend a Page-Context preamble so the assistant can resolve
    # references like "this incident" without the user pasting IDs.
    # Kept short - just route + title + up to 12 visible item refs.
    # The page_context shape is intentionally loose so each page can
    # decide what's worth exposing.
    ctx = req.page_context or {}
    preamble_parts: list[str] = []
    if ctx.get("route"):
        preamble_parts.append(f"Page route: {ctx['route']}")
    if ctx.get("title"):
        preamble_parts.append(f"Page title: {ctx['title']}")
    vis = ctx.get("visible") or []
    if isinstance(vis, list) and vis:
        preamble_parts.append("Currently visible on this page:")
        for item in vis[:12]:
            if not isinstance(item, dict):
                continue
            t = str(item.get("type") or "item")
            iid = str(item.get("id") or "")
            label = str(item.get("title") or item.get("label") or "")[:120]
            preamble_parts.append(f"  - {t} {iid[:8]}: {label}")
    if preamble_parts:
        preamble = (
            "[Page context — what the operator is currently looking at; "
            "use this to resolve 'this'/'these' references and pick the "
            "right entity IDs for tool calls]\n"
            + "\n".join(preamble_parts)
            + "\n\n[User message:]\n"
        )
        user_msg = preamble + user_msg
    content = types.Content(role="user", parts=[types.Part(text=user_msg)])

    # Plain user text (without the page-context preamble) is what
    # we hand to Davis — it doesn't need the operator-page hint
    # embedded in the prompt body since we fold that into the
    # follow-up wrapper inside _ask_davis instead.
    raw_user_msg = _user_text(req.messages) or "Hello."

    # Group-chat addressing: "Hi Davis..." / "Gemini, ..." routes
    # the turn to just one model. None = both behave per davis_enabled.
    addressee = _detect_addressee(raw_user_msg)
    gemini_active = addressee in (None, "gemini")
    davis_active = (
        addressee == "davis"
        or (addressee is None and req.davis_enabled)
    )

    async def generate():
        queue: asyncio.Queue = asyncio.Queue()

        # When the user addressed Davis directly, tell the frontend
        # to remove the pre-created assistant (Gemini) placeholder
        # bubble — Gemini stays silent this turn.
        if not gemini_active:
            await queue.put({"type": "skip_assistant"})

        # Fire Davis in parallel with Gemini so the second voice in
        # the group chat doesn't gate Gemini's reply. Davis usually
        # answers in 2-5s; Gemini Flash in <1s for short questions.
        # Opt-in via toggle OR explicit "Hi Davis..." addressing.
        davis_task: asyncio.Task | None = None
        if davis_active and _davis_configured():
            davis_task = asyncio.create_task(_ask_davis(raw_user_msg, ctx))

        async def producer():
            try:
                if not gemini_active:
                    # User addressed Davis only — don't run the ADK
                    # agent at all. Davis task already kicked off
                    # above; the finally-block will drain it.
                    return
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
                # Wait for Davis to chime in (or decline silently).
                # Cap so a stuck MCP call can't hold the stream open.
                if davis_task is not None:
                    try:
                        davis_answer = await asyncio.wait_for(
                            davis_task, timeout=20
                        )
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        davis_answer = None
                    except Exception as e:
                        log.warning("davis_chat_task_failed", error=str(e))
                        davis_answer = None
                    if davis_answer:
                        await queue.put({
                            "type": "davis_text",
                            "text": davis_answer,
                            "label": "Davis Copilot",
                        })
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
