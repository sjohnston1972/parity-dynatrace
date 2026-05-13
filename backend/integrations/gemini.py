"""Gemini client (Vertex AI).

A thin async wrapper around ``google-genai`` for one-shot LLM calls.
Authentication is Application Default Credentials (ADC) — no API key.
Project and location come from ``backend.config.settings``.

Most agent-flavoured Gemini work lives inside ADK agents (Rewire 2),
which call Gemini through the same SDK directly. This client exists
for the *non-agent* code paths — health probes, FastAPI route helpers,
ad-hoc evaluation scripts — where spinning up an agent for one call
would be heavy.

Returns a ``GeminiResponse`` dataclass with the response text and
token-usage breakdown, so callers can log spend per request.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from google import genai
from google.genai import types

from config import settings

log = structlog.get_logger()


@dataclass
class GeminiResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    thoughts_tokens: int  # Gemini 2.5 "thinking" tokens (billed)
    finish_reason: str | None


# Module-level singleton so we don't reopen the SDK client per call.
# The SDK reads ADC + project/location once at construction.
_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(
            vertexai=settings.google_genai_use_vertexai,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
        )
    return _client


class GeminiClient:
    """Thin async wrapper around the google-genai SDK.

    Example::

        from integrations.gemini import GeminiClient
        gemini = GeminiClient()
        resp = await gemini.message("Summarise OSPF in one sentence.")
        print(resp.text, resp.input_tokens, resp.output_tokens)
    """

    async def message(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> GeminiResponse:
        """Send a single-turn prompt to a Gemini model.

        Args:
            prompt: User message.
            system: Optional system instruction.
            model: Model id (defaults to ``settings.gemini_flash_model``).
                Use ``settings.gemini_pro_model`` for harder reasoning.
            max_tokens: Cap on visible output tokens. Gemini 2.5 also
                spends "thoughts" tokens before reply, so leave headroom
                (>= 256 for non-trivial prompts).
            temperature: Sampling temperature, 0.0 - 1.0.
        """
        model_id = model or settings.gemini_flash_model
        contents = [
            types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
        ]
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens,
            temperature=temperature,
        )

        client = _get_client()
        resp = await client.aio.models.generate_content(
            model=model_id,
            contents=contents,
            config=config,
        )

        usage = resp.usage_metadata
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        thoughts_tokens = getattr(usage, "thoughts_token_count", 0) or 0

        finish_reason = None
        if resp.candidates:
            fr = resp.candidates[0].finish_reason
            finish_reason = str(fr) if fr is not None else None

        text = resp.text or ""

        log.debug(
            "gemini_call",
            model=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thoughts_tokens=thoughts_tokens,
            finish_reason=finish_reason,
        )

        return GeminiResponse(
            text=text,
            model=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thoughts_tokens=thoughts_tokens,
            finish_reason=finish_reason,
        )


# Module-level default instance — import this where you only need
# .message() and don't want to construct the class every time.
gemini_client = GeminiClient()
