"""Gemini client (Vertex AI).

Implements the same interface the kopis project used for its Anthropic
client so the LangGraph nodes (and, after Rewire 2, the ADK agents) can
call ``.message(...)`` without caring which model family is behind it.

Rewire 1 fills in the body. Until then this raises so anyone wiring an
agent to it before Gemini is configured fails loudly rather than silently.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GeminiResponse:
    """Mirrors what the previous Anthropic wrapper returned."""

    text: str
    input_tokens: int
    output_tokens: int
    model: str


class GeminiClient:
    """Thin wrapper around Vertex AI Gemini.

    The constructor takes nothing because credentials come from Application
    Default Credentials (set up once on the host with
    ``gcloud auth application-default login``). Region and project are read
    from environment variables in ``backend.config``.
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
            model: Model id (defaults to GEMINI_FLASH_MODEL from config).
            max_tokens: Output token cap.
            temperature: Sampling temperature.

        Returns:
            A ``GeminiResponse`` carrying the text and token usage.
        """
        raise NotImplementedError(
            "GeminiClient.message is wired in Rewire 1. See README phase notes."
        )
