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
    await db.commit()
    await db.refresh(approval)

    log.info("approval_denied", id=approval_id, by=approved_by, via=approved_via)
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
    return len(stale)


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
