"""Approval queue service — manage approval lifecycle."""

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from db.tables import Approval, Device, Finding, Recommendation

log = structlog.get_logger()


async def list_pending(db: AsyncSession) -> list[dict]:
    """List all pending approvals with full context."""
    result = await db.execute(
        select(Approval)
        .where(Approval.status == "pending")
        .order_by(Approval.created_at.desc())
    )
    approvals = result.scalars().all()
    return [await _enrich_approval(db, a) for a in approvals]


async def list_active(db: AsyncSession) -> list[dict]:
    """List pending + approved (executing) approvals with full context."""
    result = await db.execute(
        select(Approval)
        .where(Approval.status.in_(["pending", "approved"]))
        .order_by(Approval.created_at.desc())
    )
    approvals = result.scalars().all()
    return [await _enrich_approval(db, a) for a in approvals]


async def list_history(db: AsyncSession, limit: int = 50) -> list[dict]:
    """List non-pending approvals (approved, denied, executed, failed, expired)."""
    result = await db.execute(
        select(Approval)
        .where(Approval.status != "pending")
        .order_by(Approval.created_at.desc())
        .limit(limit)
    )
    approvals = result.scalars().all()
    return [await _enrich_approval(db, a) for a in approvals]


async def get_approval(db: AsyncSession, approval_id: str) -> Approval | None:
    result = await db.execute(select(Approval).where(Approval.id == approval_id))
    return result.scalar_one_or_none()


async def approve(
    db: AsyncSession,
    approval_id: str,
    approved_by: str | None = None,
    approved_via: str = "web",
    notes: str | None = None,
) -> Approval | None:
    approval = await get_approval(db, approval_id)
    if not approval or approval.status != "pending":
        return None

    approval.status = "approved"
    approval.approved_by = approved_by
    approval.approved_via = approved_via
    approval.approved_at = datetime.now(timezone.utc)
    approval.notes = notes
    await db.commit()
    await db.refresh(approval)

    log.info("approval_approved", id=approval_id, by=approved_by, via=approved_via)
    await _emit_approval_event(approval, action="approved")
    return approval


async def deny(
    db: AsyncSession,
    approval_id: str,
    approved_by: str | None = None,
    approved_via: str = "web",
    notes: str | None = None,
) -> Approval | None:
    approval = await get_approval(db, approval_id)
    if not approval or approval.status != "pending":
        return None

    approval.status = "denied"
    approval.approved_by = approved_by
    approval.approved_via = approved_via
    approval.approved_at = datetime.now(timezone.utc)
    approval.notes = notes

    # Resolve the linked finding (and any other findings in the same
    # incident) so the dashboard reflects the operator's decision.
    # A denied approval means "this isn't worth fixing" — the symptom
    # may still exist on the device, but the operator has accepted it
    # as the new state. Without this the finding lingers as an
    # 'active' anomaly on the Insights view forever.
    rec_q = await db.execute(
        select(Recommendation).where(Recommendation.id == approval.recommendation_id)
    )
    rec = rec_q.scalar_one_or_none()
    resolved_finding_ids: list[str] = []
    if rec:
        # Pull the root finding and its incident peers.
        root_q = await db.execute(select(Finding).where(Finding.id == rec.finding_id))
        root_f = root_q.scalar_one_or_none()
        target_findings: list[Finding] = []
        if root_f:
            if root_f.incident_id:
                inc_q = await db.execute(
                    select(Finding).where(Finding.incident_id == root_f.incident_id)
                )
                target_findings = list(inc_q.scalars().all())
            else:
                target_findings = [root_f]
        denial_reason = notes or f"Denied by {approved_by or 'operator'}"
        for f in target_findings:
            f.requires_remediation = False
            ev = dict(f.evidence or {})
            ev["resolved"] = True
            ev["resolved_via"] = "denied"
            ev["denial_reason"] = denial_reason
            f.evidence = ev
            resolved_finding_ids.append(f.id)

    await db.commit()
    await db.refresh(approval)

    log.info(
        "approval_denied",
        id=approval_id, by=approved_by, via=approved_via,
        resolved_findings=resolved_finding_ids,
    )
    await _emit_approval_event(approval, action="denied")
    return approval


async def mark_executed(
    db: AsyncSession,
    approval_id: str,
    result: dict,
    success: bool = True,
) -> Approval | None:
    approval = await get_approval(db, approval_id)
    if not approval:
        return None

    approval.status = "executed" if success else "failed"
    approval.executed_at = datetime.now(timezone.utc)
    approval.execution_result = result
    await db.commit()
    await db.refresh(approval)
    await _emit_approval_event(
        approval,
        action="executed" if success else "execution_failed",
        success=success,
    )
    return approval


async def expire_stale(db: AsyncSession) -> int:
    """Expire approvals that have been pending longer than the TTL."""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.approval_expiry_hours)
    result = await db.execute(
        select(Approval)
        .where(Approval.status == "pending")
        .where(Approval.created_at < cutoff)
    )
    stale = result.scalars().all()
    for a in stale:
        a.status = "expired"
    await db.commit()
    log.info("approvals_expired", count=len(stale))
    for a in stale:
        await _emit_approval_event(a, action="expired")
    return len(stale)


async def _emit_approval_event(
    approval: Approval,
    action: str,
    success: bool | None = None,
) -> None:
    """Fire a parity-self event for an approval lifecycle moment.

    Best-effort: any failure is swallowed so the lifecycle DB commit
    still wins. Properties chosen so the Dynatrace dashboard's
    Approvals tile can pivot by status, severity, and elapsed time.
    """
    try:
        from integrations.dynatrace import dynatrace_writer
        elapsed = None
        if approval.approved_at and approval.created_at:
            elapsed = (
                approval.approved_at - approval.created_at
            ).total_seconds()
        kwargs: dict[str, object] = {
            "action": action,
            "approval_id": approval.id,
            "status": approval.status,
        }
        if approval.approved_via:
            kwargs["approved_via"] = approval.approved_via
        if approval.approved_by:
            kwargs["approved_by"] = approval.approved_by
        if elapsed is not None:
            kwargs["time_to_decision_s"] = round(elapsed, 1)
        if success is not None:
            kwargs["success"] = bool(success)
        await dynatrace_writer.emit_self_metric("approval", **kwargs)
    except Exception as e:
        log.debug("emit_approval_event_failed", error=str(e))


async def _enrich_approval(db: AsyncSession, approval: Approval) -> dict:
    """Add recommendation, finding, and device context to an approval."""
    rec_result = await db.execute(
        select(Recommendation).where(Recommendation.id == approval.recommendation_id)
    )
    rec = rec_result.scalar_one_or_none()

    finding = None
    device = None
    if rec:
        finding_result = await db.execute(
            select(Finding).where(Finding.id == rec.finding_id)
        )
        finding = finding_result.scalar_one_or_none()
        if finding:
            device_result = await db.execute(
                select(Device).where(Device.id == finding.device_id)
            )
            device = device_result.scalar_one_or_none()

    return {
        "id": approval.id,
        "recommendation_id": approval.recommendation_id,
        "status": approval.status,
        "approved_by": approval.approved_by,
        "approved_via": approval.approved_via,
        "approved_at": approval.approved_at,
        "executed_at": approval.executed_at,
        "execution_result": approval.execution_result,
        "notes": approval.notes,
        "jira_key": approval.jira_issue_key,
        "jira_url": approval.jira_issue_url,
        "created_at": approval.created_at,
        "finding": {
            "id": finding.id,
            "title": finding.title,
            "severity": finding.severity,
            "affected_entity": finding.affected_entity,
            "agent_model": finding.agent_model,
            # Surface davis_assessment so the Approvals UI can badge
            # the card with a Davis Copilot chip when applicable.
            "davis_assessment": (finding.evidence or {}).get("davis_assessment")
                if isinstance(finding.evidence, dict) else None,
        } if finding else None,
        "recommendation": {
            "id": rec.id,
            "action": rec.action_description,
            "action_description": rec.action_description,
            "commands": rec.commands,
            "rollback_commands": rec.rollback_commands,
            "risk_level": rec.risk_level,
            "reasoning": rec.reasoning,
            "agent_model": rec.agent_model,
        } if rec else None,
        "device": {
            "id": device.id,
            "hostname": device.hostname,
        } if device else None,
    }
