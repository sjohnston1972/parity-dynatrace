"""Health check endpoints."""

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.postgres import get_db
from integrations.gemini import gemini_client

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok", "service": "parity"}


@router.get("/health/dependencies")
async def health_dependencies(db: AsyncSession = Depends(get_db)):
    deps: dict[str, dict] = {}

    # PostgreSQL
    try:
        await db.execute(text("SELECT 1"))
        deps["postgres"] = {"status": "ok"}
    except Exception as e:
        deps["postgres"] = {"status": "error", "detail": str(e)}

    # ChromaDB
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"http://{settings.chromadb_host}:{settings.chromadb_port}/api/v1/heartbeat"
            )
            r.raise_for_status()
            deps["chromadb"] = {"status": "ok"}
    except Exception as e:
        deps["chromadb"] = {"status": "error", "detail": str(e)}

    # Gemini (Vertex AI) — single token through Flash. Confirms ADC,
    # project, and Vertex API enablement in one round-trip. We cap
    # max_output_tokens at 8 to keep this probe cheap; the actual
    # text doesn't matter, just that the call returns 200.
    try:
        resp = await gemini_client.message(
            prompt="ping",
            max_tokens=8,
            temperature=0.0,
            model=settings.gemini_lite_model,
        )
        deps["gemini"] = {
            "status": "ok",
            "model": resp.model,
            "tokens": resp.input_tokens + resp.output_tokens + resp.thoughts_tokens,
        }
    except Exception as e:
        deps["gemini"] = {"status": "error", "detail": str(e)[:200]}

    # Grafana
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"{settings.grafana_url}/api/health",
                headers={"Authorization": f"Bearer {settings.grafana_api_key}"},
            )
            r.raise_for_status()
            deps["grafana"] = {"status": "ok"}
    except Exception as e:
        deps["grafana"] = {"status": "error", "detail": str(e)}

    overall = "ok" if all(d["status"] == "ok" for d in deps.values()) else "degraded"
    return {"status": overall, "dependencies": deps}
