"""Dynatrace ingestion endpoints.

POST /api/v1/dynatrace/ingest pulls the current open Davis problems
from the configured MCP server and persists each as a Finding row
(source=dynatrace). Idempotent on external_id (the Dynatrace
problemId) so repeated calls don't create duplicate findings — they
update the existing row instead.
"""

from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db
from db.tables import Device, Finding
from integrations.dynatrace import dynatrace_client, dynatrace_writer, severity_for
from config import settings as parity_settings

router = APIRouter(prefix="/dynatrace", tags=["dynatrace"])
log = structlog.get_logger()


def _affected_entity_name(problem: dict) -> str:
    """Pick a single primary entity to display in the finding row.

    Prefers the root-cause entity; falls back to the first affected
    entity; finally returns "unknown".
    """
    rc = problem.get("rootCauseEntity")
    if isinstance(rc, dict) and rc.get("name"):
        return rc["name"]
    for e in problem.get("affectedEntities") or []:
        if isinstance(e, dict) and e.get("name"):
            return e["name"]
    return "unknown"


def _description(problem: dict) -> str:
    """Build a short markdown-ish description from problem evidence."""
    lines = [problem.get("title") or problem.get("displayName") or "(no title)"]
    details = (problem.get("evidenceDetails") or {}).get("details") or []
    if details:
        lines.append("")
        lines.append("Evidence:")
        for d in details[:5]:
            label = d.get("displayName", "(evidence)")
            kind = d.get("evidenceType", "")
            lines.append(f"- [{kind}] {label}")
    return "\n".join(lines)


async def _resolve_device_id(db: AsyncSession, entity_name: str) -> str | None:
    """Try to match a Dynatrace entity name (e.g. S1-R1.clydeford.net) to a Device."""
    if not entity_name or entity_name == "unknown":
        return None
    exact = await db.execute(select(Device).where(Device.hostname == entity_name))
    dev = exact.scalar_one_or_none()
    if dev:
        return dev.id
    short = entity_name.split(".")[0].lower()
    all_devs = await db.execute(select(Device))
    for d in all_devs.scalars().all():
        if d.hostname.split(".")[0].lower() == short:
            return d.id
    return None


@router.post("/ingest")
async def ingest_problems(db: AsyncSession = Depends(get_db)):
    """Pull open Davis problems from Dynatrace MCP, persist as Findings.

    Returns counts of created/updated/skipped rows. Safe to re-run.
    """
    try:
        problems = await dynatrace_client.list_problems()
    except Exception as e:
        log.exception("dynatrace_list_problems_failed")
        raise HTTPException(status_code=502, detail=f"Dynatrace MCP unreachable: {e}") from e

    created = 0
    updated = 0
    skipped = 0

    for problem in problems:
        pid = problem.get("problemId")
        if not pid:
            skipped += 1
            continue

        entity_name = _affected_entity_name(problem)
        device_id = await _resolve_device_id(db, entity_name)

        # Upsert by external_id
        result = await db.execute(
            select(Finding).where(
                (Finding.source == "dynatrace") & (Finding.external_id == pid)
            )
        )
        existing = result.scalar_one_or_none()

        fields = dict(
            source="dynatrace",
            external_id=pid,
            device_id=device_id,
            snapshot_id=None,
            category="dynatrace-problem",
            severity=severity_for(problem.get("severityLevel")),
            confidence=1.0,
            title=problem.get("title") or problem.get("displayName") or "Dynatrace problem",
            description=_description(problem),
            affected_entity=entity_name,
            evidence=problem,
            requires_remediation=problem.get("status") == "OPEN",
        )

        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            updated += 1
        else:
            db.add(Finding(**fields))
            created += 1

    await db.commit()

    return {
        "total_problems": len(problems),
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }


@router.get("/problems")
async def list_open_problems():
    """Pass-through: open Davis problems straight from the MCP (no DB write)."""
    try:
        problems = await dynatrace_client.list_problems()
    except Exception as e:
        log.exception("dynatrace_list_problems_failed")
        raise HTTPException(status_code=502, detail=f"Dynatrace MCP unreachable: {e}") from e
    return {"problems": problems, "totalCount": len(problems)}


@router.delete("/findings")
async def clear_dynatrace_findings(
    only_stub: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Admin: clear findings ingested from Dynatrace.

    By default removes only the stub-server seed problems (external_id
    starting with 'P-' — the canned Davis-style IDs). Set
    ``only_stub=false`` to remove every ``source=dynatrace`` row.

    The test suite calls this after the idempotency check so it doesn't
    leave residue on the live dashboard. Safe to re-run — re-ingesting
    is just one POST to /dynatrace/ingest.
    """
    from db.tables import Approval, Finding, Recommendation
    from sqlalchemy import delete as sa_delete

    q = sa_delete(Finding).where(Finding.source == "dynatrace")
    if only_stub:
        q = q.where(Finding.external_id.like("P-%"))
    res = await db.execute(q)
    await db.commit()
    return {"deleted": res.rowcount, "only_stub": only_stub}


@router.post("/analyze-snapshot/{snapshot_id}")
async def analyze_snapshot(
    snapshot_id: str,
    persist: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Reason over a snapshot's diff and (optionally) persist a Finding.

    Today the reasoning is done by Gemini Flash with a system prompt that
    emulates Davis Copilot's analysis style. When a Dynatrace Platform
    Token is configured (DT_PLATFORM_TOKEN in .env), the same call routes
    via the MCP server to the real Davis Copilot endpoint — no client
    change required.

    Activity events fire on the pipeline activity bus so the AI Pipeline
    graphic shows the flow in real time.
    """
    from services.dynatrace_reasoner import reason_over_snapshot
    try:
        return await reason_over_snapshot(db, snapshot_id, persist_finding=persist)
    except Exception as e:
        log.exception("analyze_snapshot_failed", snapshot_id=snapshot_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


# ── Live integration status + read-back via DQL ───────────────


@router.get("/status")
async def dynatrace_status():
    """Comprehensive Dynatrace integration status for dashboard tiles.

    Returns: tenant identifier, the apps & live URLs in use, masked
    token prefix, whether the writer is configured, and a live event
    count from the tenant (last hour, source=parity) so the UI can
    show the integration as actively flowing data rather than just
    'configured'.
    """
    apps_url = (parity_settings.dt_environment or "").rstrip("/")
    token = parity_settings.dt_platform_token or ""
    tenant = apps_url.split("//", 1)[-1].split(".", 1)[0] if apps_url else ""
    live_url = apps_url.replace(".apps.dynatrace.com", ".live.dynatrace.com")

    status: dict = {
        "configured": bool(apps_url and token),
        "tenant": tenant,
        "apps_url": apps_url,
        "live_url": live_url,
        "token_prefix": (token[:8] + "…") if token else "",
        "stub_mcp_url": parity_settings.dt_mcp_url,
    }

    # Hard-coded links to the Parity artefacts we provision via
    # scripts/dynatrace_setup.py — externalIds are stable per tenant.
    if apps_url:
        status["dashboard_url"] = (
            f"{apps_url}/ui/apps/dynatrace.dashboards/dashboard/"
            f"parity-dynatrace-dashboard-v1"
        )
        status["notebook_url"] = (
            f"{apps_url}/ui/apps/dynatrace.notebooks/notebook/"
            f"parity-dynatrace-notebook-v1"
        )
    else:
        status["dashboard_url"] = ""
        status["notebook_url"] = ""

    if not status["configured"]:
        status["events_last_hour"] = 0
        status["capabilities"] = {}
        return status

    # Capability map — which write paths the token can actually use.
    # Cached after first probe; surfaced so the UI can show greyed-out
    # tiles for missing scopes.
    try:
        status["capabilities"] = await dynatrace_writer.probe_capabilities()
    except Exception as e:
        log.warning("dt_capability_probe_failed", error=str(e))
        status["capabilities"] = {}

    # Count Parity events the writer has emitted in the last hour.
    try:
        records = await dynatrace_writer.query_parity_events(
            lookback="-1h", limit=500
        )
        status["events_last_hour"] = len(records)
        # Break the count down by action so the UI can show created vs resolved.
        created = sum(1 for r in records if r.get("parity.action") == "created")
        resolved = sum(1 for r in records if r.get("parity.action") == "resolved")
        status["events_breakdown"] = {"created": created, "resolved": resolved}
        if records:
            status["last_event_at"] = str(records[0].get("timestamp", ""))
            status["last_event_title"] = records[0].get("event.name", "")
    except Exception as e:
        log.warning("dynatrace_status_query_failed", error=str(e))
        status["events_last_hour"] = None
        status["error"] = str(e)[:200]
    return status


@router.get("/events")
async def dynatrace_events(lookback: str = "-1h", limit: int = 50):
    """Recent Parity-emitted events read straight from Dynatrace Grail.

    Each record is a row from `events` filtered to source=='parity'.
    Caller renders these as a timeline in the UI; round-trip proof
    that the events Parity fires are actually landing in Davis.
    """
    if not dynatrace_writer.configured:
        return {"records": [], "lookback": lookback, "configured": False}
    records = await dynatrace_writer.query_parity_events(
        lookback=lookback, limit=limit
    )
    # Project a stable subset of fields so the UI doesn't break when
    # Davis adds new columns to the events stream.
    projected = []
    for r in records:
        projected.append({
            "timestamp": r.get("timestamp"),
            "title": r.get("event.name"),
            "action": r.get("parity.action"),
            "severity": r.get("parity.severity"),
            "category": r.get("parity.category"),
            "device": r.get("parity.device"),
            "finding_id": r.get("parity.finding.id"),
            "incident_id": r.get("parity.incident.id"),
            "correlation_key": r.get("parity.correlation_key"),
            "event_id": r.get("event.id"),
            "correlation_id": r.get("dt.event.correlation_id"),
            "phase": r.get("parity.resolved.phase"),
        })
    return {
        "records": projected,
        "count": len(projected),
        "lookback": lookback,
        "configured": True,
        "tenant_url": (parity_settings.dt_environment or "").rstrip("/"),
    }


@router.get("/davis-problems")
async def dynatrace_davis_problems(lookback: str = "-24h", limit: int = 50):
    """Davis problems read straight from Grail (`fetch dt.davis.problems`).

    Empty on a freshly-provisioned tenant; populates as soon as a
    OneAgent reports a problem. Provided so the UI can prove the
    read path is live.
    """
    if not dynatrace_writer.configured:
        return {"records": [], "configured": False, "lookback": lookback}
    try:
        async with __import__("httpx").AsyncClient(timeout=6) as client:
            r = await client.post(
                f"{parity_settings.dt_environment.rstrip('/')}/platform/storage/query/v1/query:execute",
                json={"query": f"fetch dt.davis.problems, from:{lookback} | sort event.start desc | limit {limit}"},
                headers={
                    "Authorization": f"Bearer {parity_settings.dt_platform_token}",
                    "Content-Type": "application/json",
                },
            )
            r.raise_for_status()
            token = r.json().get("requestToken")
            if not token:
                return {"records": [], "configured": True, "lookback": lookback}
            import asyncio
            for _ in range(5):
                await asyncio.sleep(1)
                poll = await client.get(
                    f"{parity_settings.dt_environment.rstrip('/')}/platform/storage/query/v1/query:poll",
                    params={"request-token": token},
                    headers={"Authorization": f"Bearer {parity_settings.dt_platform_token}"},
                )
                if poll.status_code >= 400:
                    return {"records": [], "configured": True, "error": poll.text[:200]}
                body = poll.json()
                if body.get("state") == "SUCCEEDED":
                    return {
                        "records": body.get("result", {}).get("records", []),
                        "configured": True,
                        "lookback": lookback,
                    }
    except Exception as e:
        log.warning("davis_problems_query_failed", error=str(e))
        return {"records": [], "configured": True, "error": str(e)[:200]}
    return {"records": [], "configured": True, "lookback": lookback}
