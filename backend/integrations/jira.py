"""Jira API client — create and manage service request tickets for approvals."""

import base64

import httpx
import structlog

from config import settings

log = structlog.get_logger()


class JiraClient:
    def __init__(self) -> None:
        self.base_url = settings.jira_url.rstrip("/")
        self.project_key = settings.jira_project_key
        self._enabled = bool(
            settings.jira_url and settings.jira_api_token and settings.jira_user_email
        )

    @property
    def _headers(self) -> dict:
        token = base64.b64encode(
            f"{settings.jira_user_email}:{settings.jira_api_token}".encode()
        ).decode()
        return {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def create_service_request(
        self,
        title: str,
        description: str,
        severity: str,
        device_hostname: str,
        approval_id: str,
        commands: list | None = None,
        risk_level: str = "medium",
        reasoning: str | None = None,
        rollback_commands: list | None = None,
        analysis_model: str | None = None,
        remediation_model: str | None = None,
    ) -> dict | None:
        """Create a Jira issue for a remediation recommendation.

        Returns {"key": "KSR-123", "url": "https://..."} or None if Jira is not configured.
        """
        if not self._enabled:
            log.debug("jira_skip", reason="not configured")
            return None

        # Map severity to Jira priority
        priority_map = {
            "critical": "Highest",
            "high": "High",
            "medium": "Medium",
            "low": "Low",
            "info": "Lowest",
        }
        priority = priority_map.get(severity, "Medium")

        # Build description
        command_text = ""
        if commands:
            cmd_list = "\n".join(f"  {c}" for c in commands) if isinstance(commands[0], str) else str(commands)
            command_text = f"\n\n*Commands to execute:*\n{{code}}\n{cmd_list}\n{{code}}"

        reasoning_text = ""
        if reasoning:
            reasoning_text = f"\n\n*AI Reasoning:*\n{reasoning}"

        rollback_text = ""
        if rollback_commands:
            rb_list = "\n".join(f"  {c}" for c in rollback_commands) if isinstance(rollback_commands[0], str) else str(rollback_commands)
            rollback_text = f"\n\n*Rollback Commands:*\n{{code}}\n{rb_list}\n{{code}}"

        model_text = ""
        models = []
        if analysis_model:
            models.append(f"Analysis: {analysis_model}")
        if remediation_model:
            models.append(f"Remediation: {remediation_model}")
        if models:
            model_text = f"\n*AI Models:* {', '.join(models)}"

        full_description = (
            f"{description}\n\n"
            f"*Device:* {device_hostname}\n"
            f"*Risk Level:* {risk_level}\n"
            f"*Parity Approval ID:* {approval_id}"
            f"{model_text}"
            f"{reasoning_text}"
            f"{command_text}"
            f"{rollback_text}"
        )

        payload = {
            "fields": {
                "project": {"key": self.project_key},
                "summary": f"[Parity] {title}",
                "description": full_description,
                "issuetype": {"name": "Task"},
                "priority": {"name": priority},
                "labels": ["parity", f"severity-{severity}", f"device-{device_hostname}"],
            }
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{self.base_url}/rest/api/2/issue",
                    headers=self._headers,
                    json=payload,
                )
                r.raise_for_status()
                data = r.json()
                key = data["key"]
                url = f"{self.base_url}/browse/{key}"
                log.info("jira_issue_created", key=key, approval_id=approval_id)
                return {"key": key, "url": url}
        except Exception as e:
            log.error("jira_create_failed", error=str(e), approval_id=approval_id)
            return None

    async def transition_issue(
        self, issue_key: str, status: str, comment: str | None = None
    ) -> bool:
        """Update a Jira issue when an approval status changes.

        Adds a comment and attempts to transition the issue.
        """
        if not self._enabled:
            return False

        # Add comment first
        if comment:
            await self._add_comment(issue_key, comment)

        # Try to find and execute a matching transition
        transitions = await self._get_transitions(issue_key)
        if not transitions:
            return False

        # Map our status names to common Jira transition names
        transition_map = {
            "approved": ["approve", "approved", "in progress", "start progress"],
            "denied": ["deny", "denied", "reject", "rejected", "won't do", "done"],
            "executed": ["done", "resolved", "complete", "closed"],
            "failed": ["done", "resolved", "failed"],
            "expired": ["done", "expired", "won't do", "closed"],
        }

        target_names = transition_map.get(status, [])
        matched = None
        for t in transitions:
            if t["name"].lower() in target_names:
                matched = t
                break

        if matched:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    r = await client.post(
                        f"{self.base_url}/rest/api/2/issue/{issue_key}/transitions",
                        headers=self._headers,
                        json={"transition": {"id": matched["id"]}},
                    )
                    r.raise_for_status()
                    log.info("jira_transitioned", key=issue_key, to=matched["name"])
                    return True
            except Exception as e:
                log.warning("jira_transition_failed", key=issue_key, error=str(e))

        return False

    async def _add_comment(self, issue_key: str, body: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                await client.post(
                    f"{self.base_url}/rest/api/2/issue/{issue_key}/comment",
                    headers=self._headers,
                    json={"body": body},
                )
        except Exception as e:
            log.warning("jira_comment_failed", key=issue_key, error=str(e))

    async def _get_transitions(self, issue_key: str) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"{self.base_url}/rest/api/2/issue/{issue_key}/transitions",
                    headers=self._headers,
                )
                r.raise_for_status()
                return r.json().get("transitions", [])
        except Exception as e:
            log.warning("jira_transitions_fetch_failed", key=issue_key, error=str(e))
            return []


jira_client = JiraClient()
