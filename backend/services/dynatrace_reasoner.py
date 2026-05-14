"""Reason over a pyATS snapshot diff.

Two modes, transparent to the caller:

* **MCP mode** — when ``settings.dt_platform_token`` is set (real
  Dynatrace tenant configured), routes through ``DynatraceClient`` →
  the MCP server's ``chat_with_davis_copilot`` tool → real Davis AI.

* **Gemini mode** — default. Uses ``GeminiClient`` with a system prompt
  that mimics how Davis would analyse a network state diff. Returns the
  same structured verdict shape, so the persisted Finding looks the
  same either way.

The switch is automatic — when the user mints a Platform Token and adds
it to ``.env``, the next call to ``reason_over_diff`` uses Davis. No
code change required.

Output shape (matches the MCP stub's Davis Copilot tool):

    {
        "severity": "ERROR|WARNING|INFO",
        "category": "bgp-adjacency|interface-state|...",
        "title": "...",
        "summary": "...",
        "evidence": [...],
        "recommended_actions": [...],
        "confidence": 0.0–1.0,
        "reasoner": "davis|gemini",
        "model": "gemini-2.5-flash|davis-copilot",
    }
"""

from __future__ import annotations

import json
import re
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.tables import Device, Finding, Snapshot
from integrations.gemini import gemini_client
from services.activity import activity_bus
from services.snapshot_engine import get_snapshot_diff

log = structlog.get_logger()


_REASONER_SYSTEM_PROMPT = """You are emulating Dynatrace's Davis AI Copilot for a network-state diff.

You are given a JSON diff between two pyATS snapshots of the same network device. Your job is to interpret it the way Davis would: classify severity, identify the most likely category of fault, write a short engineer-grade summary, list the strongest evidence paths, and suggest the next investigation step.

Respond with ONLY valid JSON, no surrounding prose, in this exact shape:

{
  "severity": "ERROR" | "WARNING" | "INFO",
  "category": "bgp-adjacency" | "interface-state" | "ospf-adjacency" | "routing-instability" | "arp-change" | "state-change" | "no-change",
  "title": "<= 80 chars, no trailing period",
  "summary": "2-4 sentences, dense technical prose, no marketing fluff",
  "evidence": ["<diff path>", ...],   // 1-5 strongest paths
  "recommended_actions": ["<show / ping / traceroute CLI>", ...],   // 1-4 diagnostics
  "confidence": 0.0..1.0
}

Style rules:
- Be specific. "BGP adjacency dropped on Gi0/0" beats "network issue".
- Recommended actions must be safe diagnostic commands (show, ping, traceroute).
- If the diff is empty or only contains noise, return severity=INFO category=no-change.
- Never invent evidence paths — only use ones actually present in the diff.
"""


def _strip_code_fences(text: str) -> str:
    """Pull JSON out of a markdown fenced response if present."""
    if "```" not in text:
        return text.strip()
    m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()


async def _reason_via_gemini(device_hostname: str, diff: dict) -> dict:
    """Send the diff to Gemini Flash and parse the Davis-shaped verdict."""
    prompt = (
        f"Device: {device_hostname}\n\n"
        f"Snapshot diff:\n```json\n{json.dumps(diff, default=str)[:8000]}\n```\n\n"
        "Produce the verdict JSON described in the system prompt."
    )
    resp = await gemini_client.message(
        prompt=prompt,
        system=_REASONER_SYSTEM_PROMPT,
        model=settings.gemini_flash_model,
        max_tokens=2048,
        temperature=0.1,
    )

    text = _strip_code_fences(resp.text or "")
    try:
        verdict = json.loads(text)
    except json.JSONDecodeError:
        log.warning("davis_stand_in_unparseable", text=text[:300])
        verdict = {
            "severity": "INFO",
            "category": "state-change",
            "title": "Reasoner returned unparseable output",
            "summary": (
                "Gemini's response did not parse as JSON. Raw text: "
                + (text[:200] if text else "<empty>")
            ),
            "evidence": [],
            "recommended_actions": [],
            "confidence": 0.3,
        }

    verdict.setdefault("severity", "INFO")
    verdict.setdefault("category", "state-change")
    verdict.setdefault("evidence", [])
    verdict.setdefault("recommended_actions", [])
    verdict.setdefault("confidence", 0.5)
    verdict["reasoner"] = "gemini"
    verdict["model"] = resp.model
    verdict["_tokens"] = {
        "input": resp.input_tokens,
        "output": resp.output_tokens,
        "thoughts": resp.thoughts_tokens,
    }
    return verdict


async def _reason_via_davis_mcp(device_hostname: str, diff: dict) -> dict:
    """Route through the Dynatrace MCP to the real (or stubbed) Davis Copilot."""
    # Import lazily so the MCP client is only loaded when used.
    from integrations.dynatrace import dynatrace_client

    prompt = (
        f"Analyse this network-state diff for {device_hostname}. "
        "Identify severity, likely cause, evidence, and next investigation steps."
    )
    body = await dynatrace_client._call_tool(
        "chat_with_davis_copilot",
        {"prompt": prompt, "context": {"device": device_hostname, "diff": diff}},
    )
    if not isinstance(body, dict):
        body = {"summary": str(body)}
    body.setdefault("severity", "INFO")
    body.setdefault("category", "state-change")
    body.setdefault("evidence", [])
    body.setdefault("recommended_actions", [])
    body.setdefault("confidence", 0.7)
    body["reasoner"] = "davis"
    body["model"] = "davis-copilot"
    return body


def _resolve_reasoning_backend() -> str:
    """Pick the reasoner. Real Davis if a Platform Token is configured, else Gemini."""
    return "davis" if settings.dt_platform_token else "gemini"


_SEVERITY_TO_FINDING = {
    "ERROR": "critical",
    "CRITICAL": "critical",
    "WARNING": "high",
    "WARN": "high",
    "INFO": "medium",
}


async def reason_over_snapshot(
    db: AsyncSession,
    snapshot_id: str,
    *,
    persist_finding: bool = True,
) -> dict:
    """Top-level entry point — diff a snapshot, get a verdict, optionally persist a Finding.

    Returns the verdict dict + ``finding_id`` if persisted. Surfaces the
    flow as activity-bus events so the AI Pipeline graphic lights up in
    real time.
    """
    pipeline_run = f"reason-{uuid.uuid4().hex[:8]}"

    # ── Load snapshot + device ─────────────────────────────────────
    snap_res = await db.execute(select(Snapshot).where(Snapshot.id == snapshot_id))
    snapshot = snap_res.scalar_one_or_none()
    if not snapshot:
        return {"error": "snapshot_not_found", "snapshot_id": snapshot_id}

    dev_res = await db.execute(select(Device).where(Device.id == snapshot.device_id))
    device = dev_res.scalar_one_or_none()
    hostname = device.hostname if device else "unknown"

    # ── Diff (deterministic, Python) ──────────────────────────────
    diff_event = activity_bus.start(pipeline_run, "diff", "pyats", hostname,
                                    "Computing snapshot diff")
    diff = await get_snapshot_diff(db, snapshot_id)
    changes = diff.get("changes") or {}
    change_count = (
        len([k for k in changes.keys() if k != "note"]) if isinstance(changes, dict) else 0
    )
    activity_bus.complete(diff_event, tokens=0,
                          detail=f"Diff produced — {change_count} change(s)")

    # ── Reasoner (Gemini today, Davis when DT token configured) ──
    backend = _resolve_reasoning_backend()
    reasoner_model = (
        "davis-copilot" if backend == "davis" else settings.gemini_flash_model
    )
    reason_event = activity_bus.start(
        pipeline_run, "davis-reasoning", reasoner_model, hostname,
        ("Davis Copilot reasoning over diff"
         if backend == "davis" else "Gemini reasoning over diff (Davis stand-in)"),
    )
    try:
        if backend == "davis":
            verdict = await _reason_via_davis_mcp(hostname, diff)
        else:
            verdict = await _reason_via_gemini(hostname, diff)
    except Exception as e:
        activity_bus.fail(reason_event, error=f"reasoner failed: {e}")
        log.exception("reasoner_failed", snapshot_id=snapshot_id)
        return {"error": "reasoner_failed", "detail": str(e), "snapshot_id": snapshot_id}

    tokens = (verdict.get("_tokens") or {}).get("input", 0) + \
             (verdict.get("_tokens") or {}).get("output", 0)
    activity_bus.complete(
        reason_event,
        tokens=tokens,
        detail=f"{verdict.get('category', 'state-change')} — {verdict.get('severity', 'INFO')}",
    )

    # ── Persist as a Finding ──────────────────────────────────────
    finding_id: str | None = None
    if persist_finding and verdict.get("category") != "no-change":
        finding = Finding(
            source=f"pyats-{verdict['reasoner']}",
            external_id=f"snap:{snapshot_id}",
            snapshot_id=snapshot_id,
            device_id=device.id if device else None,
            category=verdict.get("category", "state-change"),
            severity=_SEVERITY_TO_FINDING.get(
                str(verdict.get("severity", "INFO")).upper(), "medium"
            ),
            confidence=float(verdict.get("confidence", 0.5)),
            title=str(verdict.get("title") or "Snapshot diff analysed")[:500],
            description=str(verdict.get("summary") or ""),
            affected_entity=hostname,
            evidence={
                "diff_paths": (verdict.get("evidence") or [])[:20],
                "recommended_actions": verdict.get("recommended_actions") or [],
                "raw_diff_change_count": change_count,
                "reasoner": verdict["reasoner"],
                "model": verdict["model"],
            },
            requires_remediation=verdict.get("severity") in ("ERROR", "CRITICAL"),
            agent_model=verdict["model"],
        )
        db.add(finding)
        await db.flush()
        finding_id = finding.id
        await db.commit()

    return {
        "snapshot_id": snapshot_id,
        "device": hostname,
        "diff_change_count": change_count,
        "verdict": verdict,
        "finding_id": finding_id,
        "reasoner": verdict["reasoner"],
        "model": verdict["model"],
    }
