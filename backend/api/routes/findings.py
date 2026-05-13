"""Finding query and management endpoints."""

import asyncio

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db, async_session
from db.tables import Approval, Device, Finding, Recommendation, Snapshot
from models.finding import FindingRead

router = APIRouter(prefix="/findings", tags=["findings"])
log = structlog.get_logger()


@router.get("", response_model=list[FindingRead])
async def list_findings(
    severity: str | None = None,
    category: str | None = None,
    device_id: str | None = None,
    include_resolved: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List findings.

    By default, only returns *active* findings:
      * pyats-source: snapshot_id matches the device's latest successful
        snapshot (the symptom is still present in the current state).
      * dynatrace-source: always active until ingest marks them resolved
        by Dynatrace's own lifecycle (status -> CLOSED). They have no
        snapshot_id, so the snapshot-match check doesn't apply.

    Pass ?include_resolved=true to see everything regardless of source.
    """
    q = select(Finding).order_by(Finding.created_at.desc())
    if severity:
        q = q.where(Finding.severity == severity)
    if category:
        q = q.where(Finding.category == category)
    if device_id:
        q = q.where(Finding.device_id == device_id)

    if not include_resolved:
        latest_per_device = (
            select(Snapshot.device_id, func.max(Snapshot.created_at).label("max_ts"))
            .where(func.array_length(Snapshot.features_learned, 1) > 0)
            .group_by(Snapshot.device_id)
            .subquery()
        )
        latest_snap_q = await db.execute(
            select(Snapshot.id, Snapshot.device_id)
            .join(
                latest_per_device,
                (Snapshot.device_id == latest_per_device.c.device_id)
                & (Snapshot.created_at == latest_per_device.c.max_ts),
            )
        )
        latest_ids = {row[1]: row[0] for row in latest_snap_q.all()}
        result = await db.execute(q)
        all_rows = list(result.scalars().all())
        active = [
            f
            for f in all_rows
            if f.source == "dynatrace"
            or latest_ids.get(f.device_id) == f.snapshot_id
        ]
        return active[offset:offset + limit]

    q = q.limit(limit).offset(offset)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{finding_id}")
async def get_finding(finding_id: str, db: AsyncSession = Depends(get_db)):
    """Return finding with device context, recommendations, and approval status."""
    result = await db.execute(select(Finding).where(Finding.id == finding_id))
    finding = result.scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    # Load device
    dev_result = await db.execute(select(Device).where(Device.id == finding.device_id))
    device = dev_result.scalar_one_or_none()

    # Load recommendations + approvals for this finding
    rec_result = await db.execute(
        select(Recommendation).where(Recommendation.finding_id == finding_id)
    )
    recs = rec_result.scalars().all()

    rec_data = []
    for rec in recs:
        appr_result = await db.execute(
            select(Approval).where(Approval.recommendation_id == rec.id)
        )
        approval = appr_result.scalar_one_or_none()
        rec_data.append({
            "id": rec.id,
            "action_description": rec.action_description,
            "commands": rec.commands,
            "rollback_commands": rec.rollback_commands,
            "risk_level": rec.risk_level,
            "reasoning": rec.reasoning,
            "agent_model": rec.agent_model,
            "approval": {
                "id": approval.id,
                "status": approval.status,
                "jira_issue_key": approval.jira_issue_key,
                "jira_issue_url": approval.jira_issue_url,
            } if approval else None,
        })

    # If this finding belongs to a multi-finding incident, load the linked findings
    linked_findings: list[dict] = []
    if finding.incident_id:
        linked_result = await db.execute(
            select(Finding, Device)
            .join(Device, Finding.device_id == Device.id)
            .where(Finding.incident_id == finding.incident_id)
            .where(Finding.id != finding.id)
            .order_by(Finding.is_root_cause.desc(), Finding.severity)
        )
        for lf, ldev in linked_result.all():
            linked_findings.append({
                "id": lf.id,
                "title": lf.title,
                "severity": lf.severity,
                "category": lf.category,
                "is_root_cause": lf.is_root_cause,
                "device_hostname": ldev.hostname.split(".")[0] if ldev else None,
            })

    return {
        "id": finding.id,
        "snapshot_id": finding.snapshot_id,
        "device_id": finding.device_id,
        "category": finding.category,
        "severity": finding.severity,
        "confidence": finding.confidence,
        "title": finding.title,
        "description": finding.description,
        "affected_entity": finding.affected_entity,
        "evidence": finding.evidence,
        "requires_remediation": finding.requires_remediation,
        "agent_model": finding.agent_model,
        "tokens_used": finding.tokens_used,
        "incident_id": finding.incident_id,
        "is_root_cause": finding.is_root_cause,
        "correlation_reason": finding.correlation_reason,
        "linked_findings": linked_findings,
        "created_at": finding.created_at,
        "device": {
            "id": device.id,
            "hostname": device.hostname,
            "management_ip": device.management_ip,
            "platform": device.platform,
            "device_type": device.device_type,
        } if device else None,
        "recommendations": rec_data,
    }


@router.post("/incidents/recorrelate")
async def recorrelate_incidents(db: AsyncSession = Depends(get_db)):
    """Force-rerun the correlation engine across ALL current findings.

    Useful for: (a) recovering after a partial pipeline run where the
    correlation step crashed, (b) re-grouping after manually editing or
    dismissing findings, (c) one-off testing.
    """
    from services.correlation import (
        apply_correlation,
        create_incident_approvals,
        generate_incident_remediations,
    )

    # Get the snapshot_ids of all currently-active findings
    sids_result = await db.execute(select(Finding.snapshot_id).distinct())
    snapshot_ids = [row[0] for row in sids_result.all()]
    if not snapshot_ids:
        return {"incidents": 0, "approvals_created": 0}

    incidents = await apply_correlation(db, snapshot_ids)
    recs_created = await generate_incident_remediations(db, incidents)
    approvals_created = await create_incident_approvals(db, incidents)
    await db.commit()

    return {
        "incidents": len(incidents),
        "multi_finding_incidents": sum(1 for i in incidents if len(i.findings) > 1),
        "recommendations_created": recs_created,
        "approvals_created": approvals_created,
    }


@router.get("/incidents/list")
async def list_incidents(db: AsyncSession = Depends(get_db)):
    """Group all CURRENTLY-ACTIVE findings by incident_id.

    A finding is considered active if its snapshot_id is the most recent
    snapshot for its device. The pipeline keeps a finding's snapshot_id
    pointing to the latest snapshot every time the symptom is re-detected
    (via the dedup carry-forward in graph.py). So a finding whose snap_id
    is older than its device's latest snapshot represents a symptom that
    was NOT re-detected — i.e. the issue resolved itself or was fixed.
    Those are filtered out of the active incidents view.

    Returns one entry per incident with the root cause finding and a
    list of linked findings. Solo findings (no correlation) are returned
    as 1-finding incidents.
    """
    # Per-device latest snapshot id → for filtering stale findings
    latest_per_device = (
        select(Snapshot.device_id, func.max(Snapshot.created_at).label("max_ts"))
        .where(func.array_length(Snapshot.features_learned, 1) > 0)
        .group_by(Snapshot.device_id)
        .subquery()
    )
    latest_snap_q = await db.execute(
        select(Snapshot.id, Snapshot.device_id, Snapshot.created_at)
        .join(
            latest_per_device,
            (Snapshot.device_id == latest_per_device.c.device_id)
            & (Snapshot.created_at == latest_per_device.c.max_ts),
        )
    )
    latest_snap_id_per_device: dict[str, str] = {
        row[1]: row[0] for row in latest_snap_q.all()
    }

    result = await db.execute(
        select(Finding).order_by(Finding.created_at.desc())
    )
    all_findings = list(result.scalars().all())
    findings = [
        f for f in all_findings
        if latest_snap_id_per_device.get(f.device_id) == f.snapshot_id
    ]
    if not findings:
        return []

    # Group by incident_id; null incident_id = solo finding
    groups: dict[str, list[Finding]] = {}
    for f in findings:
        key = f.incident_id or f"solo:{f.id}"
        groups.setdefault(key, []).append(f)

    # Resolve device hostnames in one query
    dev_ids = list({f.device_id for f in findings})
    dev_result = await db.execute(select(Device).where(Device.id.in_(dev_ids)))
    dev_map = {d.id: d.hostname for d in dev_result.scalars().all()}

    # Pre-fetch the root-cause recommendation summaries in one query so we
    # can surface the AI's actual reasoning on the incident card. Without
    # this the operator has to drill into the modal to see *why* the AI
    # thinks this is broken — the most valuable data is one click away.
    root_finding_ids = []
    for fs in groups.values():
        root = next((f for f in fs if f.is_root_cause), None)
        if root is None:
            sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
            root = sorted(fs, key=lambda f: (sev_rank.get(f.severity, 5), -(f.confidence or 0)))[0]
        root_finding_ids.append(root.id)

    rec_map: dict[str, Recommendation] = {}
    appr_map: dict[str, Approval] = {}
    if root_finding_ids:
        rec_result = await db.execute(
            select(Recommendation).where(Recommendation.finding_id.in_(root_finding_ids))
        )
        for r in rec_result.scalars().all():
            rec_map[r.finding_id] = r
        if rec_map:
            appr_q = await db.execute(
                select(Approval).where(Approval.recommendation_id.in_([r.id for r in rec_map.values()]))
            )
            for a in appr_q.scalars().all():
                appr_map[a.recommendation_id] = a

    incidents = []
    for key, fs in groups.items():
        root = next((f for f in fs if f.is_root_cause), None)
        if root is None:
            sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
            root = sorted(fs, key=lambda f: (sev_rank.get(f.severity, 5), -(f.confidence or 0)))[0]

        affected = sorted({dev_map.get(f.device_id, "?").split(".")[0] for f in fs})
        rec = rec_map.get(root.id)
        appr = appr_map.get(rec.id) if rec else None

        recommendation_summary = None
        if rec:
            recommendation_summary = {
                "id": rec.id,
                "action": rec.action_description,
                "reasoning": rec.reasoning,
                "risk_level": rec.risk_level,
                "commands": rec.commands,
                "model": rec.agent_model,
                "approval": {
                    "id": appr.id,
                    "status": appr.status,
                    "jira_key": appr.jira_issue_key,
                    "jira_url": appr.jira_issue_url,
                } if appr else None,
            }

        incidents.append({
            "incident_id": key if not key.startswith("solo:") else None,
            "is_correlated": len(fs) > 1,
            "finding_count": len(fs),
            "affected_device_count": len(affected),
            "affected_devices": affected,
            "max_severity": min(fs, key=lambda f: {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}.get(f.severity, 5)).severity,
            "root_cause": {
                "id": root.id,
                "title": root.title,
                "severity": root.severity,
                "category": root.category,
                "device_hostname": dev_map.get(root.device_id, "?").split(".")[0],
                "agent_model": root.agent_model,
                "description": root.description,
                "created_at": root.created_at,
            },
            "recommendation": recommendation_summary,
            "linked_findings": [
                {
                    "id": f.id,
                    "title": f.title,
                    "severity": f.severity,
                    "category": f.category,
                    "device_hostname": dev_map.get(f.device_id, "?").split(".")[0],
                } for f in fs if f.id != root.id
            ],
            "created_at": max(f.created_at for f in fs),
        })

    # Order by severity then time
    sev_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    incidents.sort(key=lambda i: (sev_rank.get(i["max_severity"], 5), -i["created_at"].timestamp()))
    return incidents


@router.delete("/{finding_id}")
async def dismiss_finding(finding_id: str, db: AsyncSession = Depends(get_db)):
    """Dismiss (delete) a finding and its linked recommendations/approvals."""
    result = await db.execute(select(Finding).where(Finding.id == finding_id))
    finding = result.scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    # Delete linked approvals → recommendations → finding
    rec_result = await db.execute(
        select(Recommendation).where(Recommendation.finding_id == finding_id)
    )
    for rec in rec_result.scalars().all():
        appr_result = await db.execute(
            select(Approval).where(Approval.recommendation_id == rec.id)
        )
        for appr in appr_result.scalars().all():
            await db.delete(appr)
        await db.delete(rec)

    await db.delete(finding)
    await db.commit()

    # Remove from vector store
    from db.vector import delete_finding as vector_delete
    vector_delete(finding_id)

    log.info("finding_dismissed", finding_id=finding_id, title=finding.title)
    return {"status": "dismissed", "id": finding_id}


@router.post("/{finding_id}/escalate")
async def escalate_finding(finding_id: str, db: AsyncSession = Depends(get_db)):
    """Re-analyse this finding's snapshot with Opus (Tier 3) escalation."""
    result = await db.execute(select(Finding).where(Finding.id == finding_id))
    finding = result.scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    # Load snapshot and device
    snap_result = await db.execute(
        select(Snapshot).where(Snapshot.id == finding.snapshot_id)
    )
    snapshot = snap_result.scalar_one_or_none()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    dev_result = await db.execute(
        select(Device).where(Device.id == finding.device_id)
    )
    device = dev_result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Launch escalation in background
    asyncio.create_task(_escalate_background(
        snapshot_id=snapshot.id,
        device_id=device.id,
        device_hostname=device.hostname,
        device_platform=device.platform,
        raw_snapshot=snapshot.snapshot_data,
    ))

    return {
        "status": "escalating",
        "finding_id": finding_id,
        "device": device.hostname,
        "message": "Re-analysing with Opus. New findings will appear shortly.",
    }


async def _escalate_background(
    snapshot_id: str,
    device_id: str,
    device_hostname: str,
    device_platform: str,
    raw_snapshot: dict,
):
    """Run the full pipeline with forced Opus escalation."""
    async with async_session() as db:
        try:
            from agents.graph import run_pipeline

            await run_pipeline(
                db=db,
                snapshot_id=snapshot_id,
                device_id=device_id,
                device_hostname=device_hostname,
                device_platform=device_platform,
                raw_snapshot=raw_snapshot,
                force_escalation=True,
            )

            log.info("escalation_complete", hostname=device_hostname)
        except Exception as e:
            log.error("escalation_failed", hostname=device_hostname, error=str(e))
