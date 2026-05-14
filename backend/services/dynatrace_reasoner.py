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
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.tables import Approval, Device, Finding, Recommendation, Snapshot
from integrations.gemini import gemini_client
from services.activity import activity_bus
from services.snapshot_engine import get_snapshot_diff

log = structlog.get_logger()


# How long after the first finding to treat a same-key observation as
# part of the same incident. After this window, a fresh occurrence is
# considered a new incident even if the prefix matches.
CORRELATION_WINDOW = timedelta(minutes=30)


def _compute_correlation_key(verdict: dict) -> str | None:
    """Stable signature for incident grouping.

    The root device that originated a propagating change typically gets
    classified differently from downstream devices (e.g. the source sees
    "config-drift" because a new interface appeared with a suspicious
    description, while the BGP peers see "routing-change" because a new
    prefix landed in their RIB). To merge them into a single incident
    we key on the *prefix* itself — category-agnostic.

    BGP/OSPF adjacency events without a prefix signature are NOT
    correlated cross-device here — they're typically per-device root
    causes that warrant their own incident.
    """
    cat = verdict.get("category") or ""
    if cat not in ("routing-change", "config-drift", "bgp-adjacency"):
        return None
    evidence_blob = " ".join(verdict.get("evidence") or []) + " " + (verdict.get("summary") or "")
    m = re.search(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}", evidence_blob)
    if m:
        return f"prefix:{m.group(0)}"
    return None


_REASONER_SYSTEM_PROMPT = """You are emulating Dynatrace's Davis AI Copilot for a network-state diff.

You are given TWO diffs of the same pyATS snapshot:

  * ``rolling_diff`` — vs the immediately previous snapshot. Catches what
    changed in the last collection interval.
  * ``golden_diff`` — vs the device's *blessed baseline* snapshot. Shows
    *every* drift from the sanctioned state, even if accumulated over
    many intervals.

Use both. The rolling_diff tells you "what just happened"; the
golden_diff tells you "what's wrong now". If the rolling_diff is empty
but the golden_diff shows the loopback is still present, the device is
NOT clean even though nothing changed in the last interval. Conversely,
if the rolling_diff shows the loopback going AWAY and golden_diff is
empty, the device has returned to baseline — verdict severity should
drop to INFO and category to no-change.

Your job is to interpret these the way Davis would: classify severity,
identify the most likely category of fault, write a short engineer-
grade summary, list the strongest evidence paths, draft *remediation*
commands (the change to apply to fix or revert the anomaly) and a
paired rollback, and end with a confidence score.

Respond with ONLY valid JSON, no surrounding prose, in this exact shape:

{
  "severity": "ERROR" | "WARNING" | "INFO",
  "category": "bgp-adjacency" | "interface-state" | "ospf-adjacency" | "routing-change" | "arp-change" | "config-drift" | "state-change" | "no-change",
  "title": "<= 80 chars, no trailing period",
  "summary": "2-4 sentences, dense technical prose, no marketing fluff",
  "evidence": ["<diff path>", ...],
  "diagnostic_actions": ["<show / ping / traceroute CLI>", ...],
  "remediation_commands": ["<config-mode CLI to revert the anomaly>", ...],
  "rollback_commands": ["<config-mode CLI to undo the remediation if it breaks something>", ...],
  "risk_level": "low" | "medium" | "high",
  "confidence": 0.0..1.0
}

Classification rules (these matter — read them):
- A NEW interface appearing in ARP / BGP / routing tables IS a notable structural change. Classify as WARNING category=routing-change (or config-drift if it looks intentional but unsanctioned). It is the exact kind of subtle drift that thresholded monitoring misses — that's why Parity exists.
- A new BGP prefix entering the table (path.total_entries going up, prefixes.total_entries going up, new neighbor entries) is also routing-change WARNING — not noise, not "no-change".
- Reserve no-change for diffs that are entirely empty or contain only filtered counters.
- A real BGP/OSPF adjacency state transition (Established→Idle, Full→Down) is ERROR severity.
- An interface oper_status change is ERROR severity.

Evidence-capture rules (critical for cross-device correlation):
- When the diff contains a path matching ``routing.vrf.<vrf>.address_family.<af>.routes.<CIDR>`` with status=added or removed, that path MUST be the FIRST item in the evidence array. This is the canonical prefix identifier; Parity's correlation engine extracts the CIDR from evidence to group findings on the same underlying change across devices. Omitting it splits one incident into many.
- If multiple new routes appear, include each route path in evidence before any aggregate counter paths.
- Counter paths like ``bgp.instance.X.neighbor.Y.address_family.Z.prefixes.total_entries`` are corroborating context, not the primary signal. Include them AFTER the route paths.
- For a finding about a NEW interface (e.g. interface.Loopback99), include the interface path first AND any routing.routes path for the new connected prefix.
- Never invent evidence paths — only use ones actually present in the diff.

Remediation rules:
- remediation_commands MUST be a flat list of CLI lines wrapped in mode-transition tokens. The list ALWAYS starts with "configure terminal", ends with "end", and contains the actual config edits in between. The executor splits these into exec/config groups and feeds the config block to pyATS configure() — without the framing, IOS-XE rejects everything as "Invalid input".
- Example for reverting a loopback advertisement:
    ["configure terminal", "no interface Loopback99", "end"]
- rollback_commands MUST be the reverse, same framing — what to apply to put the device back into the post-anomaly state if the remediation breaks something. For the loopback example:
    ["configure terminal", "interface Loopback99", "description PARITY-TEST", "ip address 192.0.2.99 255.255.255.255", "no shutdown", "end"]
- diagnostic_actions stay as plain show/ping/traceroute strings (no framing).
- For a state-change of unknown root cause, leave remediation_commands AND rollback_commands empty and let the human reason; never invent random commands.

Style rules:
- Be specific. "BGP table grew by 1 prefix — new Loopback99 advertisement" beats "network change observed".
- Never invent evidence paths — only use ones actually present in the diff.
"""


def _strip_code_fences(text: str) -> str:
    """Pull JSON out of a markdown fenced response if present."""
    if "```" not in text:
        return text.strip()
    m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Opening fence with no closing — Gemini hit MAX_TOKENS mid-response.
    # Strip the leading fence so the partial JSON has a chance to parse.
    lines = text.strip().split("\n")
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _safe_parse_json(text: str) -> dict | None:
    """Parse JSON, tolerating MAX_TOKENS-truncated responses.

    Attempts to recover by closing dangling braces/brackets/quotes when the
    reasoner's reply ran out of token budget mid-object.
    """
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Recovery: trim trailing comma/whitespace and close open structures.
    work = text.rstrip().rstrip(",")
    # If we're inside an unterminated string, close it.
    if work.count('"') % 2 == 1:
        work += '"'
    open_braces = work.count("{") - work.count("}")
    open_brackets = work.count("[") - work.count("]")
    if open_braces > 0 or open_brackets > 0:
        work += "]" * max(0, open_brackets) + "}" * max(0, open_braces)
    try:
        return json.loads(work)
    except json.JSONDecodeError:
        return None


async def _reason_via_gemini(
    device_hostname: str,
    rolling_diff: dict,
    golden_diff: dict | None = None,
) -> dict:
    """Send both diffs to Gemini Flash and parse the Davis-shaped verdict."""
    parts = [
        f"Device: {device_hostname}\n",
        "rolling_diff (vs immediately previous snapshot):",
        f"```json\n{json.dumps(rolling_diff, default=str)[:6000]}\n```",
    ]
    if golden_diff is not None:
        parts.append("golden_diff (vs blessed baseline snapshot):")
        parts.append(f"```json\n{json.dumps(golden_diff, default=str)[:6000]}\n```")
    parts.append("Produce the verdict JSON described in the system prompt.")
    prompt = "\n\n".join(parts)
    resp = await gemini_client.message(
        prompt=prompt,
        system=_REASONER_SYSTEM_PROMPT,
        model=settings.gemini_flash_model,
        max_tokens=6144,  # Gemini 2.5 burns lots of thinking tokens — give the visible reply enough room.
        temperature=0.1,
    )

    text = _strip_code_fences(resp.text or "")
    verdict = _safe_parse_json(text)
    if verdict is None:
        log.warning("reasoner_unparseable", text=text[:300])
        verdict = {
            "severity": "INFO",
            "category": "state-change",
            "title": "Reasoner returned unparseable output",
            "summary": (
                "Gemini's response did not parse as JSON. Raw text: "
                + (text[:200] if text else "<empty>")
            ),
            "evidence": [],
            "diagnostic_actions": [],
            "remediation_commands": [],
            "rollback_commands": [],
            "risk_level": "low",
            "confidence": 0.3,
        }

    verdict.setdefault("severity", "INFO")
    verdict.setdefault("category", "state-change")
    verdict.setdefault("evidence", [])
    verdict.setdefault("diagnostic_actions", verdict.pop("recommended_actions", []))
    verdict.setdefault("remediation_commands", [])
    verdict.setdefault("rollback_commands", [])
    verdict.setdefault("risk_level", "medium")
    verdict.setdefault("confidence", 0.5)
    verdict["reasoner"] = "gemini"
    verdict["model"] = resp.model
    verdict["_tokens"] = {
        "input": resp.input_tokens,
        "output": resp.output_tokens,
        "thoughts": resp.thoughts_tokens,
    }
    return verdict


async def _reason_via_davis_mcp(
    device_hostname: str,
    rolling_diff: dict,
    golden_diff: dict | None = None,
) -> dict:
    """Route through the Dynatrace MCP to the real (or stubbed) Davis Copilot."""
    # Import lazily so the MCP client is only loaded when used.
    from integrations.dynatrace import dynatrace_client

    prompt = (
        f"Analyse this network-state diff for {device_hostname}. "
        "Identify severity, likely cause, evidence, and next investigation steps."
    )
    body = await dynatrace_client._call_tool(
        "chat_with_davis_copilot",
        {
            "prompt": prompt,
            "context": {
                "device": device_hostname,
                "diff": rolling_diff,
                "golden_diff": golden_diff,
            },
        },
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

    # ── Diff (deterministic, Python) — both modes ─────────────────
    diff_event = activity_bus.start(pipeline_run, "diff", "pyats", hostname,
                                    "Computing snapshot diff (rolling + golden)")
    rolling_diff = await get_snapshot_diff(db, snapshot_id, mode="rolling")
    golden_diff = await get_snapshot_diff(db, snapshot_id, mode="golden")
    rolling_changes = rolling_diff.get("changes") or {}
    golden_changes = golden_diff.get("changes") or {}
    rolling_change_count = (
        len([k for k in rolling_changes.keys() if k != "note"])
        if isinstance(rolling_changes, dict)
        else 0
    )
    golden_change_count = (
        len([k for k in golden_changes.keys() if k != "note"])
        if isinstance(golden_changes, dict)
        else 0
    )
    # Keep change_count name for downstream evidence payload; favour
    # golden because it's the load-bearing signal for "is this broken".
    change_count = golden_change_count if golden_change_count else rolling_change_count
    activity_bus.complete(
        diff_event,
        tokens=0,
        detail=f"Diff — rolling: {rolling_change_count} change(s); "
               f"golden: {golden_change_count} change(s)",
    )

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
            verdict = await _reason_via_davis_mcp(hostname, rolling_diff, golden_diff)
        else:
            verdict = await _reason_via_gemini(hostname, rolling_diff, golden_diff)
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

    # ── Correlation lookup ───────────────────────────────────────
    # If another device produced a finding with the same correlation
    # key within the window, this observation joins THAT incident.
    correlation_key = _compute_correlation_key(verdict)

    # Token-presence override: counting diff entries isn't enough.
    # The noise filter doesn't catch every BGP/OSPF/ARP counter that
    # cycles over hours, so golden_diff can be technically non-empty
    # even when nothing structural has drifted. Authoritative check:
    # is the symptom token (e.g. "192.0.2.99/32") actually present in
    # the current snapshot's data? If not, the device IS clean
    # regardless of how many counters wandered.
    if correlation_key and correlation_key.startswith("prefix:"):
        symptom_token = correlation_key.split(":", 1)[1]
        snap_text = json.dumps(snapshot.snapshot_data) if snapshot.snapshot_data else ""
        if symptom_token and symptom_token not in snap_text:
            log.info(
                "verdict_overridden_token_absent",
                device=hostname,
                original_category=verdict.get("category"),
                token=symptom_token,
                rolling_count=rolling_change_count,
                golden_count=golden_change_count,
            )
            verdict["category"] = "no-change"
            verdict["severity"] = "INFO"
            verdict["title"] = "Device matches blessed baseline"
            verdict["summary"] = (
                f"Reasoner observed diff activity (rolling: {rolling_change_count}, "
                f"golden: {golden_change_count}) but the symptom token "
                f"{symptom_token!r} is no longer present in the device's state. "
                "Treating as a return to baseline."
            )
            verdict["remediation_commands"] = []
            verdict["rollback_commands"] = []
            verdict["evidence"] = []
            correlation_key = None  # don't correlate clean states

    # Even without a correlation key: if golden_diff is empty AND the
    # rolling-diff shows only noise the model interpreted, fall back to
    # no-change. (Kept the empty-count override as a safety net for
    # adjacency-flap-style verdicts that don't carry a prefix token.)
    if golden_change_count == 0 and verdict.get("category") not in ("no-change",):
        log.info(
            "verdict_overridden_by_golden",
            device=hostname,
            original_category=verdict.get("category"),
            rolling_count=rolling_change_count,
        )
        verdict["category"] = "no-change"
        verdict["severity"] = "INFO"
        verdict["title"] = "Device matches blessed baseline"
        verdict["summary"] = (
            "rolling_diff showed " + str(rolling_change_count) + " change(s), but "
            "golden_diff is empty — the device is in its sanctioned baseline state."
        )
        verdict["remediation_commands"] = []
        verdict["rollback_commands"] = []
        verdict["evidence"] = []
        correlation_key = None

    primary_finding: Finding | None = None
    if correlation_key:
        existing_q = await db.execute(
            select(Finding)
            .where(Finding.external_id == f"corr:{correlation_key}")
            .where(Finding.created_at > datetime.now(timezone.utc) - CORRELATION_WINDOW)
            .order_by(Finding.created_at.asc())
            .limit(1)
        )
        primary_finding = existing_q.scalar_one_or_none()

    # ── Persist as a Finding (+ Recommendation + Approval when actionable) ─
    finding_id: str | None = None
    recommendation_id: str | None = None
    approval_id: str | None = None
    incident_id: str | None = None
    correlated_to: str | None = None

    if persist_finding and verdict.get("category") != "no-change":
        diagnostic_actions = verdict.get("diagnostic_actions") or verdict.get("recommended_actions") or []
        remediation_commands = verdict.get("remediation_commands") or []
        rollback_commands = verdict.get("rollback_commands") or []
        risk_level = str(verdict.get("risk_level") or "medium").lower()

        # A finding requires_remediation when we have actual config-mode
        # commands to apply — not when we only have show-only diagnostics.
        actionable = bool(remediation_commands)

        external_id_value = (
            f"corr:{correlation_key}" if correlation_key else f"snap:{snapshot_id}"
        )

        finding = Finding(
            source=f"pyats-{verdict['reasoner']}",
            external_id=external_id_value,
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
                "diagnostic_actions": diagnostic_actions,
                "remediation_commands": remediation_commands,
                "rollback_commands": rollback_commands,
                "risk_level": risk_level,
                "raw_diff_change_count": change_count,
                "rolling_change_count": rolling_change_count,
                "golden_change_count": golden_change_count,
                "reasoner": verdict["reasoner"],
                "model": verdict["model"],
                "correlation_key": correlation_key,
            },
            requires_remediation=actionable
                or verdict.get("severity") in ("ERROR", "CRITICAL"),
            agent_model=verdict["model"],
            incident_id=(primary_finding.incident_id or primary_finding.id) if primary_finding else None,
            is_root_cause=primary_finding is None,
        )
        db.add(finding)
        await db.flush()
        finding_id = finding.id
        # First-of-its-kind: make finding.id its own incident anchor.
        if primary_finding is None:
            finding.incident_id = finding.id
            await db.flush()
        incident_id = finding.incident_id
        correlated_to = primary_finding.id if primary_finding else None

        # When this is a correlated observation (not the root cause),
        # don't create a duplicate Recommendation/Approval/Jira — instead
        # append a comment to the primary's Jira issue noting that the
        # same change has been observed on another device. This is the
        # noise-suppression behaviour the test plan calls for.
        if actionable and primary_finding is not None:
            try:
                primary_appr_q = await db.execute(
                    select(Approval)
                    .join(Recommendation, Approval.recommendation_id == Recommendation.id)
                    .where(Recommendation.finding_id == primary_finding.id)
                )
                primary_appr = primary_appr_q.scalars().first()
                if primary_appr and primary_appr.jira_issue_key:
                    from integrations.jira import jira_client
                    await jira_client._add_comment(
                        primary_appr.jira_issue_key,
                        _engine_comment(
                            "parity-detect-engine",
                            (
                                f"Same change observed on additional device {hostname}.\n"
                                f"snapshot={snapshot_id}\n"
                                f"correlation_key={correlation_key}\n"
                                f"diff change count: {change_count}.\n"
                                "Not raising a new ticket; this is part of incident "
                                f"{primary_finding.incident_id or primary_finding.id}."
                            ),
                            snapshot_id=snapshot_id,
                            device=hostname,
                        ),
                    )
            except Exception as e:
                log.warning("correlation_jira_comment_failed", error=str(e))

        # Auto-draft a Recommendation when this is the *primary* finding
        # of a new incident (or an uncorrelated singleton) and the
        # reasoner produced config-mode commands.
        if actionable and primary_finding is None:
            rec = Recommendation(
                finding_id=finding.id,
                action_description=verdict.get("title") or "Revert observed change",
                commands=remediation_commands,
                rollback_commands=rollback_commands,
                risk_level=risk_level if risk_level in ("low", "medium", "high") else "medium",
                reasoning=verdict.get("summary") or "",
                agent_model=verdict["model"],
                tokens_used=tokens or None,
            )
            db.add(rec)
            await db.flush()
            recommendation_id = rec.id

            # Open an Approval queue entry so the operator sees it in the UI.
            appr = Approval(
                recommendation_id=rec.id,
                status="pending",
                approved_by=None,
                approved_via=None,
            )
            db.add(appr)
            await db.flush()
            approval_id = appr.id

            # Best-effort: create a Jira ticket + first forensic comment.
            # Failure here doesn't block the workflow — the approval is
            # already queued in Parity; Jira sync can retry.
            try:
                from integrations.jira import jira_client
                jira_issue = await jira_client.create_service_request(
                    title=str(verdict.get("title") or "Parity recommendation")[:200],
                    description=(verdict.get("summary") or "")[:2000],
                    severity=finding.severity,
                    device_hostname=hostname,
                    approval_id=appr.id,
                    commands=remediation_commands,
                    risk_level=risk_level if risk_level in ("low", "medium", "high") else "medium",
                    rollback_commands=rollback_commands,
                    reasoning=verdict.get("summary") or "",
                    analysis_model=verdict["model"],
                    remediation_model=verdict["model"],
                )
                if jira_issue and jira_issue.get("key"):
                    appr.jira_issue_key = jira_issue["key"]
                    appr.jira_issue_url = jira_issue.get("url") or ""
                    await jira_client._add_comment(
                        jira_issue["key"],
                        _engine_comment(
                            "parity-detect-engine",
                            f"pyATS diff produced {change_count} change(s); "
                            f"reasoner classified as {verdict.get('category')} "
                            f"({verdict.get('severity')}). Evidence top: "
                            + ", ".join((verdict.get('evidence') or [])[:3]),
                            snapshot_id=snapshot_id,
                        ),
                    )
            except Exception as jira_err:
                log.warning("jira_create_failed", error=str(jira_err))

        await db.commit()

    # ── Out-of-band resolution sweep ─────────────────────────────
    # If an operator fixed something via the console/Ansible/elsewhere
    # without going through Parity's approval flow, there's no verifier
    # call to mark the prior finding resolved. After a *persisting*
    # reasoner pass, sweep any other still-active findings for this
    # device — if their correlation symptom is no longer present in the
    # current snapshot, mark them resolved with a clear breadcrumb.
    #
    # Skipped when persist_finding=False because that's the verifier's
    # signal — it has its own resolution logic (_resolve_incident_if_clear)
    # that knows whether resolution came from an approval flow vs out-of-
    # band. Running both produces conflicting "via" labels on the same row.
    if device and persist_finding:
        try:
            sweep_resolved = await _sweep_out_of_band_resolutions(
                db,
                device_id=device.id,
                hostname=hostname,
                fresh_snapshot=snapshot,
                except_finding_id=finding_id,
            )
        except Exception as sweep_err:
            log.warning("oob_sweep_failed", error=str(sweep_err))
            sweep_resolved = []
    else:
        sweep_resolved = []

    return {
        "snapshot_id": snapshot_id,
        "device": hostname,
        "diff_change_count": change_count,
        "verdict": verdict,
        "finding_id": finding_id,
        "recommendation_id": recommendation_id,
        "approval_id": approval_id,
        "incident_id": incident_id,
        "correlated_to": correlated_to,
        "correlation_key": correlation_key,
        "out_of_band_resolved": sweep_resolved,
        "reasoner": verdict["reasoner"],
        "model": verdict["model"],
    }


async def _sweep_out_of_band_resolutions(
    db: AsyncSession,
    *,
    device_id: str,
    hostname: str,
    fresh_snapshot: Snapshot,
    except_finding_id: str | None,
) -> list[str]:
    """Mark active findings for this device as resolved when their
    correlation token is no longer present in the device's current state.

    Triggered by any reasoner pass — handles operator-initiated fixes,
    spontaneous BGP reconvergence, anything that resolves the underlying
    signal without going through Parity's approval flow.

    Returns the list of finding ids flipped to resolved.
    """
    snap_text = json.dumps(fresh_snapshot.snapshot_data) if fresh_snapshot.snapshot_data else ""
    if not snap_text:
        return []

    candidates_q = await db.execute(
        select(Finding)
        .where(Finding.device_id == device_id)
        .where(Finding.requires_remediation == True)  # noqa: E712
    )
    resolved_ids: list[str] = []
    for f in candidates_q.scalars().all():
        if f.id == except_finding_id:
            continue
        # We need a correlation key to test against the snapshot — without
        # one we can't say with confidence whether the symptom is gone.
        ev = f.evidence if isinstance(f.evidence, dict) else None
        key = (ev or {}).get("correlation_key") if ev else None
        if not key or not key.startswith("prefix:"):
            continue
        token = key.split(":", 1)[1]
        if token in snap_text:
            continue  # symptom still present
        # Symptom gone — mark resolved with a forensic marker.
        f.requires_remediation = False
        new_ev = dict(ev or {})
        new_ev["resolved"] = True
        new_ev["resolved_via"] = "out-of-band"
        new_ev["resolved_at_snapshot"] = fresh_snapshot.id
        f.evidence = new_ev
        resolved_ids.append(f.id)
        log.info(
            "oob_resolution",
            finding_id=f.id, device=hostname, token=token,
            snapshot=fresh_snapshot.id,
        )

    if resolved_ids:
        await db.commit()
        # If any of these belonged to a Jira-linked approval, log a
        # forensic verifier comment so the ticket reflects the operator
        # closing the symptom out-of-band.
        try:
            from integrations.jira import jira_client
            jira_q = await db.execute(
                select(Approval)
                .join(Recommendation, Approval.recommendation_id == Recommendation.id)
                .where(Recommendation.finding_id.in_(resolved_ids))
            )
            for appr in jira_q.scalars().all():
                if not appr.jira_issue_key:
                    continue
                from datetime import datetime, timezone
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                await jira_client._add_comment(
                    appr.jira_issue_key,
                    (
                        f"[engine: parity-oob-sweeper | {ts} | device={hostname}]\n"
                        f"Out-of-band resolution detected: a fresh snapshot of "
                        f"{hostname} no longer carries the symptom this incident "
                        "was raised against. The operator likely remediated this "
                        "outside the Parity approval flow. Finding(s) marked "
                        "resolved without execution; consider reviewing your "
                        "change-control process if this was unexpected."
                    ),
                )
        except Exception as e:
            log.warning("oob_sweep_jira_comment_failed", error=str(e))

    return resolved_ids


def _engine_comment(engine: str, body: str, **kv) -> str:
    """Format a Jira comment with a structured engine header so the
    timeline reads like a forensic audit trail."""
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    kv_str = " ".join(f"{k}={v}" for k, v in kv.items())
    header = f"[engine: {engine} | {ts}" + (f" | {kv_str}" if kv_str else "") + "]"
    return f"{header}\n{body}"
