"""Slack interactivity endpoint — approve/deny buttons from the outbound
approval card posted by integrations/slack.py.

Authentication note: this route authenticates via Slack's request
signature (verify_slack_signature), NOT api.deps.require_auth (the
shared API-token dependency used by approvals.router / execution.router
etc). It must stay exempt from that dependency — see the
include_router() call in main.py.
"""

import asyncio
import json

import structlog
from fastapi import APIRouter, HTTPException, Request

from config import settings
from db.postgres import async_session
from integrations.slack import verify_slack_signature
from services import approval_service

log = structlog.get_logger()

router = APIRouter(prefix="/slack", tags=["slack"])

_APPROVE_ACTION_IDS = {"approve_action", "approve"}
_DENY_ACTION_IDS = {"deny_action", "deny"}


@router.post("/interactivity")
async def slack_interactivity(request: Request):
    """Receive a Slack Block Kit button click (approve/deny).

    Verifies the request signature over the *raw* body before parsing
    anything, then responds immediately (Slack requires a response
    within 3 seconds) and does the actual approve/deny + downstream
    side effects in a background task.
    """
    raw_body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp")
    signature = request.headers.get("X-Slack-Signature")

    if not verify_slack_signature(
        settings.slack_signing_secret, timestamp, raw_body, signature
    ):
        log.warning("slack_interactivity_signature_rejected")
        raise HTTPException(status_code=401, detail="invalid Slack signature")

    form = await request.form()
    payload_raw = form.get("payload")
    if not payload_raw:
        raise HTTPException(status_code=400, detail="missing payload")

    try:
        payload = json.loads(payload_raw)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="malformed payload")

    actions = payload.get("actions") or []
    if not actions:
        return {"ok": True}

    action = actions[0]
    action_id = action.get("action_id")
    approval_id = action.get("value")
    user = payload.get("user") or {}
    slack_user = user.get("username") or user.get("id") or "slack-user"

    if not approval_id or (action_id not in _APPROVE_ACTION_IDS and action_id not in _DENY_ACTION_IDS):
        log.warning("slack_interactivity_unrecognized_action", action_id=action_id)
        return {"ok": True}

    # Stay well under Slack's 3s budget — the real work happens after
    # we've already responded.
    asyncio.create_task(_process_action(action_id, approval_id, slack_user))
    return {"ok": True}


async def _process_action(action_id: str, approval_id: str, slack_user: str) -> None:
    """Approve/deny the approval and run the same downstream side
    effects the web /approvals routes run (Jira transition, Slack
    status update, auto-execute on approve). Never raises — logs and
    swallows so the background task can't crash silently in a way
    that's invisible.
    """
    async with async_session() as db:
        try:
            if action_id in _APPROVE_ACTION_IDS:
                approval = await approval_service.approve(
                    db, approval_id, approved_by=slack_user, approved_via="slack",
                )
                action_name = "approved"
            else:
                approval = await approval_service.deny(
                    db, approval_id, approved_by=slack_user, approved_via="slack",
                )
                action_name = "denied"

            if not approval:
                log.warning(
                    "slack_interactivity_approval_not_found",
                    approval_id=approval_id,
                    action_id=action_id,
                )
                return

            if approval.jira_issue_key:
                from integrations.jira import jira_client

                await jira_client.transition_issue(
                    approval.jira_issue_key,
                    status=action_name,
                    comment=f"{action_name.capitalize()} by {slack_user} via slack",
                )

            from integrations.slack import slack_client

            await slack_client.notify_approval_update(approval, action_name)

            if action_name == "approved":
                asyncio.create_task(_execute_background(approval_id))

            log.info(
                "slack_interactivity_processed",
                approval_id=approval_id,
                action=action_name,
                by=slack_user,
            )
        except Exception as exc:
            log.error(
                "slack_interactivity_processing_failed",
                error=str(exc),
                approval_id=approval_id,
                action_id=action_id,
            )


async def _execute_background(approval_id: str) -> None:
    """Mirrors api/routes/approvals.py's _execute_background — runs the
    approved remediation. Kept local (rather than imported) so this
    file has no dependency on the web routes module."""
    async with async_session() as db:
        try:
            from services.execution_engine import execute_approved

            result = await execute_approved(db, approval_id)
            if result.get("error"):
                log.error(
                    "auto_execution_failed", approval_id=approval_id, error=result["error"]
                )
            else:
                log.info("auto_execution_complete", approval_id=approval_id)
        except Exception as e:
            log.error("auto_execution_error", approval_id=approval_id, error=str(e))
