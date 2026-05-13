"""LLM smoke endpoints — quick proof that Gemini is reachable.

Useful during development and for the Rewire-1 demo gate: hit
``GET /api/v1/llm/ping`` and see the model echo back. Returns the
response text and token-usage breakdown so you can confirm both
that auth is wired AND that the *-2.5 model is the one answering.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from config import settings
from integrations.gemini import gemini_client

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/ping")
async def ping(
    model: str | None = Query(None, description="Gemini model id; defaults to flash."),
):
    """Round-trip a tiny prompt through Gemini and return text + tokens."""
    try:
        resp = await gemini_client.message(
            prompt="Reply with exactly the text PARITY-OK and nothing else.",
            max_tokens=256,
            temperature=0.0,
            model=model or settings.gemini_flash_model,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini call failed: {e}") from e

    return {
        "ok": resp.text.strip() == "PARITY-OK",
        "model": resp.model,
        "text": resp.text,
        "tokens": {
            "input": resp.input_tokens,
            "output": resp.output_tokens,
            "thoughts": resp.thoughts_tokens,
            "total": resp.input_tokens + resp.output_tokens + resp.thoughts_tokens,
        },
        "finish_reason": resp.finish_reason,
    }
