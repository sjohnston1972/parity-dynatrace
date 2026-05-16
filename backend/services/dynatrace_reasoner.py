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
- A BGP/routing PREFIX BEING REMOVED is just as significant as one being added. If you see `routing.vrf.<vrf>.address_family.<af>.routes.<CIDR>` with status=removed, the device has lost reachability to that prefix — classify WARNING category=routing-change (or config-drift if a prefix-list / route-map / neighbor was added on this device). Counters (`prefixes.total_entries` going DOWN) corroborate. NEVER classify a route-removal diff as no-change.
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
- COMPLETE REMOVAL: when an unsanctioned interface or prefix is being removed, you MUST remove EVERY config line that references the resource. Removing just the interface and leaving a `network <prefix>` statement under `router bgp` orphans config. Likewise, removing an interface that participates in a `redistribute connected` route-map or in OSPF/EIGRP networks requires the matching clean-up. Check the diff for ALL paths that mention the resource and emit `no <line>` for each. A clean revert leaves no traces.
- Example for reverting a loopback advertisement (BOTH the interface AND the BGP network statement that advertised it must be removed):
    ["configure terminal",
     "no interface Loopback99",
     "router bgp <local-asn>",
     " address-family ipv4",
     "  no network <prefix> mask <mask>",
     " exit-address-family",
     "end"]
- rollback_commands MUST be the reverse, same framing — what to apply to put the device back into the post-anomaly state if the remediation breaks something. For the loopback example, re-create the interface AND the BGP network advertisement:
    ["configure terminal",
     "interface Loopback99",
     " description PARITY-TEST",
     " ip address 192.0.2.99 255.255.255.255",
     " no shutdown",
     "router bgp <local-asn>",
     " address-family ipv4",
     "  network 192.0.2.99 mask 255.255.255.255",
     " exit-address-family",
     "end"]
- Local ASN and exact prefixes come from the diff itself — never guess. If the diff shows `bgp.instance.<asn>...` use that asn; if it shows `routing.vrf.<vrf>.address_family.ipv4.routes.<CIDR>` use that CIDR.
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
    """Pick the primary reasoner — always Gemini today.

    Davis Copilot returns conversational free-form text that doesn't
    fit our structured verdict schema, so it can't be the primary
    reasoner. It is, however, called in parallel as a second opinion
    via `_call_davis_for_second_opinion()` whenever the real MCP
    sidecar is reachable; the response is attached to the finding as
    evidence so the operator can read both views.
    """
    return "gemini"


def _is_real_davis_mcp_configured() -> bool:
    """True when the real-MCP sidecar URL is set (separate from stub URL)."""
    return bool(settings.dt_platform_token) and bool(settings.dt_real_mcp_url)


# Phrases Davis Copilot returns when it rejects an ungrounded prompt.
# Detecting any of these triggers the simpler-prompt retry below.
_DAVIS_REJECTION_MARKERS = (
    "valid question",
    "rephrase",
    "additional context",
    "more information",
    "doesn't seem",
    "does not seem",
)


def _extract_davis_answer(body: object) -> str:
    """Pull the **Answer:** block out of a Davis Copilot MCP response."""
    text = (
        (body.get("text") if isinstance(body, dict) else None)
        or str(body)
    )
    m = re.search(r"\*\*Answer:\*\*\s*(.+?)(?:\n\n\*\*|\Z)", text, re.S)
    return (m.group(1).strip() if m else text.strip())[:600]


def _looks_like_davis_rejection(answer: str) -> bool:
    low = (answer or "").lower()
    return any(marker in low for marker in _DAVIS_REJECTION_MARKERS)


async def _call_davis_for_second_opinion(
    device_hostname: str,
    rolling_diff: dict,
    gemini_verdict: dict,
) -> str | None:
    """Ask the real Davis Copilot (via the MCP sidecar) to validate Gemini's verdict.

    Returns the Davis Copilot reply as a short string ready to be
    embedded in a Finding's evidence as `davis_assessment`. Returns
    None if the real MCP isn't configured or the call fails — the
    primary Gemini reasoning is never blocked by this.

    Davis Copilot is grounded in the tenant's monitored data; an
    ungrounded hypothetical sometimes comes back as "I'm sorry, but
    this doesn't seem to be a valid question." We therefore:

    1. Pass the diff as ``context`` so Davis has something concrete
       to reason about (the real Dynatrace MCP accepts a context
       object).
    2. If the answer still looks like a rejection, retry once with a
       simpler risk-grading prompt that doesn't mention Gemini.
    """
    if not _is_real_davis_mcp_configured():
        return None
    try:
        from integrations.dynatrace import DynatraceClient
        client = DynatraceClient(mcp_url=settings.dt_real_mcp_url)
        # Truncate the diff so we stay under whatever token limit the
        # bundled Davis chat enforces.
        diff_summary = json.dumps(rolling_diff, default=str)[:3000]
        gemini_summary = (
            f"category={gemini_verdict.get('category')} "
            f"severity={gemini_verdict.get('severity')} "
            f"title={(gemini_verdict.get('title') or '')[:120]}"
        )
        prompt = (
            f"A network device drift was detected on {device_hostname}. "
            f"Our primary AI reasoner (Gemini) concluded: {gemini_summary}. "
            "In ONE short paragraph (max 60 words), do you agree this is a "
            "configuration drift worth alerting on? Reply with one of "
            "AGREE / DISAGREE / UNCERTAIN and a one-sentence rationale. "
            "Do not list URLs."
        )
        body = await client._call_tool(
            "chat_with_davis_copilot",
            {
                "text": prompt,
                "context": {
                    "device": device_hostname,
                    "diff_summary": diff_summary,
                    "gemini_summary": gemini_summary,
                },
            },
        )
        answer = _extract_davis_answer(body)

        if _looks_like_davis_rejection(answer):
            log.info(
                "davis_second_opinion_retry",
                device=device_hostname,
                first_attempt_snippet=answer[:160],
            )
            fallback_prompt = (
                f"A network configuration change was detected on "
                f"{device_hostname} ({gemini_verdict.get('category') or 'state-change'}). "
                "Briefly assess the operational risk in ONE sentence. "
                "Reply starting with one of LOW / MEDIUM / HIGH."
            )
            body = await client._call_tool(
                "chat_with_davis_copilot",
                {
                    "text": fallback_prompt,
                    "context": {
                        "device": device_hostname,
                        "change_category": gemini_verdict.get("category"),
                        "change_title": (gemini_verdict.get("title") or "")[:200],
                    },
                },
            )
            answer = _extract_davis_answer(body)

        return answer
    except Exception as e:
        log.warning("davis_second_opinion_failed", error=str(e))
        return None


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
    # ── Evidence post-process: force prefix paths to be present ──
    # Gemini sometimes summarises a BGP-table change via the counter
    # paths (path.total_entries, prefixes.total_entries) and omits the
    # specific routing.vrf.X.address_family.Y.routes.<CIDR> path even
    # when it's in the diff. The correlation engine extracts the CIDR
    # from evidence, so omission splits one incident into many.
    #
    # Only prepend route paths whose diff status is 'added' or 'removed'
    # — those are propagation events, structurally distinct from
    # pre-existing routes whose attributes 'changed'. Including the
    # latter would cause correlation collisions (a device's own LAN
    # prefix would out-rank the propagating change).
    _route_path_pattern = re.compile(
        r"routing\.vrf\.[^.]+\.address_family\.[^.]+\.routes\.[\d./:a-fA-F]+"
    )

    def _structural_route_paths(changes: dict) -> list[str]:
        if not isinstance(changes, dict):
            return []
        out: list[str] = []
        for k, v in changes.items():
            if not _route_path_pattern.match(k):
                continue
            status = v.get("status") if isinstance(v, dict) else None
            if status in ("added", "removed"):
                out.append(k)
        return out

    route_paths_in_diff = (
        _structural_route_paths(rolling_changes)
        + _structural_route_paths(golden_changes)
    )
    if route_paths_in_diff:
        existing_ev = verdict.get("evidence") or []
        if not isinstance(existing_ev, list):
            existing_ev = [existing_ev]
        seen = set(existing_ev)
        for p in route_paths_in_diff:
            if p not in seen:
                existing_ev.insert(0, p)
                seen.add(p)
        verdict["evidence"] = existing_ev[:20]
        log.info(
            "evidence_post_fixed",
            device=hostname,
            route_paths_added=route_paths_in_diff[:5],
        )

    # Deterministic post-process — category + remediation completeness.
    #
    # Gemini's category call is non-deterministic at the boundary between
    # routing-change and config-drift: a device that ADDED an interface
    # locally is the ORIGIN of a route propagation, not an observer, but
    # the model sometimes labels it routing-change because the BGP table
    # also moved. Promote-to-root then misses it. Fix: scan the rolling
    # diff for `interface.<Name>` paths with status=added; the presence
    # of one on this device is conclusive evidence of config-drift here.
    _interface_added_pattern = re.compile(r"^interface\.[A-Za-z][\w\-/.]*$")
    locally_added_interfaces: list[str] = []
    # Scan BOTH diffs — an interface added several intervals ago no
    # longer shows up in rolling_diff (both sides already have it) but
    # is still present-vs-baseline in golden_diff.
    for changes in (rolling_changes, golden_changes):
        for k, v in (changes or {}).items():
            if _interface_added_pattern.match(k) and isinstance(v, dict):
                if v.get("status") == "added":
                    name = k.split(".", 1)[1]
                    if name not in locally_added_interfaces:
                        locally_added_interfaces.append(name)
    if locally_added_interfaces and verdict.get("category") not in (
        "config-drift", "no-change"
    ):
        log.info(
            "category_overridden_to_config_drift",
            device=hostname,
            original_category=verdict.get("category"),
            interfaces_added=locally_added_interfaces,
        )
        verdict["category"] = "config-drift"

    # Route-removal override: a structural route disappearing from the
    # routing table is never operational noise. Gemini sometimes calls
    # this no-change when the counter changes dominate the diff and the
    # singular `removed` entry gets lost in the rolling diff. Force the
    # category off no-change when at least one route path has
    # status=removed in either diff.
    removed_route_paths: list[str] = []
    for changes in (rolling_changes, golden_changes):
        for p in _structural_route_paths(changes):
            if (changes.get(p) or {}).get("status") == "removed":
                if p not in removed_route_paths:
                    removed_route_paths.append(p)
    if removed_route_paths and verdict.get("category") == "no-change":
        # If we ALSO see a locally added prefix-list or route-map config
        # this is config-drift; otherwise it's a routing-change.
        log.info(
            "category_overridden_route_removed",
            device=hostname,
            original_category="no-change",
            removed=removed_route_paths[:3],
        )
        verdict["category"] = "routing-change"
        if not verdict.get("severity") or verdict.get("severity") == "INFO":
            verdict["severity"] = "WARNING"
        if not verdict.get("title") or "baseline" in str(verdict.get("title", "")).lower():
            verdict["title"] = (
                f"BGP route(s) removed: {', '.join(p.rsplit('.', 1)[-1] for p in removed_route_paths[:2])}"
            )[:200]

    # Gemini's remediation also sometimes omits the matching BGP
    # `network` statement when a loopback-plus-advertisement pair is
    # being removed (pyATS doesn't surface `network` lines as their own
    # diff path so the model has no signal to act on). Inject the
    # cleanup deterministically when both the locally-added interface
    # AND a route-add for the same prefix are visible in the diff, and
    # the device's snapshot tells us the local ASN.
    if locally_added_interfaces:
        # Same dual-scan rationale — the route may only show as 'added'
        # in golden_diff after the first round.
        added_prefixes: list[str] = []
        for changes in (rolling_changes, golden_changes):
            for p in _structural_route_paths(changes):
                m = re.search(r"routes\.([\d./:a-fA-F]+)$", p)
                if m and (changes.get(p) or {}).get("status") == "added":
                    cidr = m.group(1)
                    if cidr not in added_prefixes:
                        added_prefixes.append(cidr)
        # pyATS stores BGP under instance.default (a fixed instance name);
        # the actual local ASN lives at instance.default.bgp_id. Fall
        # back to scanning instance keys in case a future pyATS version
        # keys by ASN directly.
        local_asn = None
        try:
            bgp_inst = (snapshot.snapshot_data or {}).get("bgp", {}).get("instance", {})
            default_inst = bgp_inst.get("default") or {}
            if default_inst.get("bgp_id"):
                local_asn = str(default_inst["bgp_id"])
            if not local_asn:
                for asn in bgp_inst.keys():
                    if asn and asn != "default":
                        local_asn = str(asn)
                        break
        except Exception:
            local_asn = None
        rcmds = verdict.get("remediation_commands") or []
        rbcmds = verdict.get("rollback_commands") or []

        # Gemini sometimes copies our example wholesale and leaves
        # `<LOCAL_ASN>` (or `<prefix>`/`<mask>`) as a literal placeholder.
        # Substitute the real values before the executor sees them —
        # otherwise pyATS `configure()` chokes on the angle brackets.
        _asn_pattern = re.compile(
            r"<\s*(LOCAL_ASN|local-asn|local_asn|ASN|asn|local-as)\s*>",
            re.IGNORECASE,
        )
        # Build prefix-and-mask substitutions from the diff-derived list.
        # The first added prefix is the canonical one for the example.
        first_prefix = added_prefixes[0] if added_prefixes else None
        first_net = first_mask = None
        if first_prefix and "/" in first_prefix:
            try:
                fn, fp = first_prefix.split("/", 1)
                fp_int = int(fp)
                fm_int = (0xFFFFFFFF << (32 - fp_int)) & 0xFFFFFFFF
                first_net = fn
                first_mask = ".".join(
                    str((fm_int >> (8 * (3 - i))) & 0xFF) for i in range(4)
                )
            except ValueError:
                pass

        def _sub_placeholders(lst):
            if not isinstance(lst, list):
                return lst
            out = []
            for c in lst:
                s = str(c)
                if local_asn:
                    s = _asn_pattern.sub(local_asn, s)
                if first_net:
                    s = re.sub(
                        r"<\s*(prefix|network|net)\s*>", first_net, s, flags=re.IGNORECASE
                    )
                if first_mask:
                    s = re.sub(r"<\s*mask\s*>", first_mask, s, flags=re.IGNORECASE)
                out.append(s)
            return out

        new_rcmds = _sub_placeholders(rcmds)
        new_rbcmds = _sub_placeholders(rbcmds)
        if new_rcmds != rcmds or new_rbcmds != rbcmds:
            log.info(
                "remediation_placeholders_substituted",
                device=hostname,
                asn=local_asn,
                prefix=first_prefix,
            )
            verdict["remediation_commands"] = new_rcmds
            verdict["rollback_commands"] = new_rbcmds
            rcmds, rbcmds = new_rcmds, new_rbcmds

        # Zero-state synthesis: Gemini occasionally returns rich evidence
        # but an EMPTY remediation_commands list — usually when the model
        # is confident in the diagnosis but hedges on the fix. For the
        # canonical drift shape (locally-added interface + matching new
        # prefix + known local ASN) the correct remediation is mechanical
        # and the executor can run it safely. Build it from scratch so a
        # finding doesn't get stranded as detection-only when the
        # downstream pipeline has everything it needs to act.
        if (
            not rcmds
            and added_prefixes
            and local_asn
            and locally_added_interfaces
        ):
            log.info(
                "remediation_synthesized_from_zero",
                device=hostname, asn=local_asn,
                interfaces=list(locally_added_interfaces),
                prefixes=added_prefixes,
            )
            rcmds_new: list[str] = ["configure terminal"]
            # Strip BGP `network` statements first so the interface
            # removal doesn't dangle an advertisement behind.
            rcmds_new.append(f"router bgp {local_asn}")
            rcmds_new.append(" address-family ipv4")
            for cidr in added_prefixes:
                if "/" in cidr:
                    net, plen = cidr.split("/", 1)
                    try:
                        pi = int(plen)
                        mi = (0xFFFFFFFF << (32 - pi)) & 0xFFFFFFFF
                        mask = ".".join(
                            str((mi >> (8 * (3 - i))) & 0xFF) for i in range(4)
                        )
                        rcmds_new.append(f"  no network {net} mask {mask}")
                    except ValueError:
                        rcmds_new.append(f"  no network {net}")
                else:
                    rcmds_new.append(f"  no network {cidr}")
            rcmds_new.append(" exit-address-family")
            for iface in locally_added_interfaces:
                rcmds_new.append(f"no interface {iface}")
            rcmds_new.append("end")
            verdict["remediation_commands"] = rcmds_new
            rcmds = rcmds_new

            # Mirror rollback — re-create the interfaces (without an IP
            # since we don't know it from the diff path alone; the
            # original config still in pyATS history covers re-creation
            # if needed) and re-add the BGP advertisements.
            rb_new: list[str] = ["configure terminal"]
            for iface in locally_added_interfaces:
                rb_new.append(f"interface {iface}")
                rb_new.append(" description PARITY-ROLLBACK")
                if first_net and first_mask:
                    rb_new.append(f" ip address {first_net} {first_mask}")
                rb_new.append(" no shutdown")
            rb_new.append(f"router bgp {local_asn}")
            rb_new.append(" address-family ipv4")
            for cidr in added_prefixes:
                if "/" in cidr:
                    net, plen = cidr.split("/", 1)
                    try:
                        pi = int(plen)
                        mi = (0xFFFFFFFF << (32 - pi)) & 0xFFFFFFFF
                        mask = ".".join(
                            str((mi >> (8 * (3 - i))) & 0xFF) for i in range(4)
                        )
                        rb_new.append(f"  network {net} mask {mask}")
                    except ValueError:
                        rb_new.append(f"  network {net}")
            rb_new.append(" exit-address-family")
            rb_new.append("end")
            verdict["rollback_commands"] = rb_new
            rbcmds = rb_new

        if (
            added_prefixes
            and local_asn
            and isinstance(rcmds, list)
            and any("no interface" in str(c).lower() for c in rcmds)
            and not any("no network" in str(c).lower() for c in rcmds)
        ):
            log.info(
                "remediation_augmented_bgp_network",
                device=hostname,
                asn=local_asn,
                prefixes=added_prefixes,
            )
            # Insert BGP-side cleanup before the trailing "end" token.
            insert_at = len(rcmds)
            for i in range(len(rcmds) - 1, -1, -1):
                if str(rcmds[i]).strip().lower() == "end":
                    insert_at = i
                    break
            bgp_block = [f"router bgp {local_asn}", " address-family ipv4"]
            for cidr in added_prefixes:
                if "/" in cidr:
                    net, plen = cidr.split("/", 1)
                    try:
                        plen_int = int(plen)
                        mask_int = (0xFFFFFFFF << (32 - plen_int)) & 0xFFFFFFFF
                        mask = ".".join(
                            str((mask_int >> (8 * (3 - i))) & 0xFF) for i in range(4)
                        )
                        bgp_block.append(f"  no network {net} mask {mask}")
                    except ValueError:
                        bgp_block.append(f"  no network {net}")
                else:
                    bgp_block.append(f"  no network {cidr}")
            bgp_block.append(" exit-address-family")
            verdict["remediation_commands"] = rcmds[:insert_at] + bgp_block + rcmds[insert_at:]

            # Mirror to rollback: re-add the network statements.
            if isinstance(rbcmds, list) and not any(
                "network" in str(c).lower() and "no network" not in str(c).lower()
                for c in rbcmds
            ):
                insert_at_rb = len(rbcmds)
                for i in range(len(rbcmds) - 1, -1, -1):
                    if str(rbcmds[i]).strip().lower() == "end":
                        insert_at_rb = i
                        break
                rb_bgp_block = [f"router bgp {local_asn}", " address-family ipv4"]
                for cidr in added_prefixes:
                    if "/" in cidr:
                        net, plen = cidr.split("/", 1)
                        try:
                            plen_int = int(plen)
                            mask_int = (0xFFFFFFFF << (32 - plen_int)) & 0xFFFFFFFF
                            mask = ".".join(
                                str((mask_int >> (8 * (3 - i))) & 0xFF)
                                for i in range(4)
                            )
                            rb_bgp_block.append(f"  network {net} mask {mask}")
                        except ValueError:
                            rb_bgp_block.append(f"  network {net}")
                    else:
                        rb_bgp_block.append(f"  network {cidr}")
                rb_bgp_block.append(" exit-address-family")
                verdict["rollback_commands"] = (
                    rbcmds[:insert_at_rb] + rb_bgp_block + rbcmds[insert_at_rb:]
                )

    correlation_key = _compute_correlation_key(verdict)

    # Token-presence override: counting diff entries isn't enough.
    # The noise filter doesn't catch every BGP/OSPF/ARP counter that
    # cycles over hours, so golden_diff can be technically non-empty
    # even when nothing structural has drifted. Authoritative check:
    # is the symptom token (e.g. "192.0.2.99/32") actually present in
    # the current snapshot's data? If not, the device IS clean
    # regardless of how many counters wandered.
    #
    # BUT — this only applies when the symptom is an ADDITION. For
    # route-removals, the symptom IS its absence: the prefix should be
    # there but isn't. Detect by checking whether the diff shows the
    # symptom as removed in either rolling or golden — if so, skip the
    # token-absent override (the absence is the load-bearing signal).
    symptom_is_removal = False
    if correlation_key and correlation_key.startswith("prefix:"):
        symptom_token = correlation_key.split(":", 1)[1]
        for changes in (rolling_changes, golden_changes):
            for p in _structural_route_paths(changes):
                if symptom_token and symptom_token in p:
                    if (changes.get(p) or {}).get("status") == "removed":
                        symptom_is_removal = True
                        break
            if symptom_is_removal:
                break
    if correlation_key and correlation_key.startswith("prefix:") and not symptom_is_removal:
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
        # Find the CURRENT ROOT of this correlation. We want the finding
        # that is currently is_root_cause=true (which may have been
        # promoted from an earlier observer), not just the oldest row.
        # If no root yet, fall back to the oldest row so we still join
        # the same incident.
        #
        # CRITICAL: skip resolved findings. A finding marked
        # evidence.resolved=true (denied OOB-fixed, etc.) is historical;
        # joining new live findings to it would block the
        # recommendation/approval path. New findings need a fresh root.
        not_resolved = (
            (Finding.evidence["resolved"].astext != "true")
            | Finding.evidence["resolved"].is_(None)
        )
        root_q = await db.execute(
            select(Finding)
            .where(Finding.external_id == f"corr:{correlation_key}")
            .where(Finding.created_at > datetime.now(timezone.utc) - CORRELATION_WINDOW)
            .where(Finding.is_root_cause == True)  # noqa: E712
            .where(not_resolved)
            .order_by(Finding.created_at.asc())
            .limit(1)
        )
        primary_finding = root_q.scalar_one_or_none()
        if primary_finding is None:
            existing_q = await db.execute(
                select(Finding)
                .where(Finding.external_id == f"corr:{correlation_key}")
                .where(Finding.created_at > datetime.now(timezone.utc) - CORRELATION_WINDOW)
                .where(not_resolved)
                .order_by(Finding.created_at.asc())
                .limit(1)
            )
            primary_finding = existing_q.scalar_one_or_none()

    # Root-cause preference, in order:
    #   1. config-drift beats anything else (an actual config change
    #      somewhere is more authoritative than a downstream observer).
    #   2. Actionable (remediation_commands present) beats non-actionable
    #      — only findings with commands can drive the approval flow, so
    #      a finding WITHOUT commands cannot remain root if a peer with
    #      commands shows up.
    # In both cases we keep the new finding in the SAME incident as the
    # existing primary (incident_id inherited); we just transfer the
    # root role.
    promote_to_root = False
    if primary_finding is not None:
        new_category = verdict.get("category")
        new_actionable = bool(verdict.get("remediation_commands"))
        primary_actionable = bool(
            (primary_finding.evidence or {}).get("remediation_commands")
        )
        primary_category = primary_finding.category

        promote_reason: str | None = None
        if new_category == "config-drift" and primary_category != "config-drift":
            promote_reason = "config-drift-supersedes-observer"
        elif new_actionable and not primary_actionable:
            promote_reason = "actionable-supersedes-observer"

        if promote_reason:
            log.info(
                "promoting_root_cause",
                from_finding=primary_finding.id,
                from_category=primary_category,
                to_device=hostname,
                to_category=new_category,
                incident=primary_finding.incident_id,
                reason=promote_reason,
            )
            primary_finding.is_root_cause = False
            await db.flush()
            promote_to_root = True

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
                # Second opinion from real Davis Copilot, gathered in
                # parallel via the official Dynatrace MCP server. None
                # when the real MCP sidecar isn't reachable. Never blocks.
                "davis_assessment": await _call_davis_for_second_opinion(
                    hostname, rolling_diff, verdict
                ),
            },
            requires_remediation=actionable
                or verdict.get("severity") in ("ERROR", "CRITICAL"),
            agent_model=verdict["model"],
            incident_id=(primary_finding.incident_id or primary_finding.id) if primary_finding else None,
            is_root_cause=(primary_finding is None) or promote_to_root,
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

        # Push to Dynatrace as a CUSTOM_DEPLOYMENT event. Best-effort —
        # the writer no-ops when DT_ENVIRONMENT / DT_PLATFORM_TOKEN are
        # unset, and silently logs on any HTTP failure rather than
        # blocking the reasoner pipeline.
        try:
            from integrations.dynatrace import dynatrace_writer
            await dynatrace_writer.emit_finding_created(
                finding, device_hostname=hostname,
            )
        except Exception as dt_err:
            log.warning("dynatrace_emit_skipped", error=str(dt_err))

        # When this is a correlated observation (not the root cause),
        # don't create a duplicate Recommendation/Approval/Jira — instead
        # append a comment to the primary's Jira issue noting that the
        # same change has been observed on another device. This is the
        # noise-suppression behaviour the test plan calls for.
        # Exception: if we just promoted this finding to root (config-
        # drift superseding a routing-change primary), we DO want to
        # create the Recommendation/Approval/Jira here.
        if actionable and primary_finding is not None and not promote_to_root:
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
        # of a new incident (or an uncorrelated singleton OR we just
        # promoted this finding to root) and the reasoner produced
        # config-mode commands.
        if actionable and (primary_finding is None or promote_to_root):
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
