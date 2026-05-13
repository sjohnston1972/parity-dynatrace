"""Cross-device finding correlation.

Groups findings created by per-device pipelines into INCIDENTS — sets of
findings that describe the same underlying network event observed from
multiple vantage points.

Why: when a transit interface goes down, the per-device pipeline (which
runs in isolation) flags it on N devices: the interface owner sees
'interface down' + 'BGP peer down', the BGP peer sees 'BGP session down',
downstream sites see 'route withdrawn'. Without correlation, that's N
independent findings, N Jira tickets, N Slack pings, N approvals — all
for ONE incident.

This module groups them via shared entities (IPs, prefixes, interface
names, MACs) and picks a root-cause finding per group. The snapshot
route then creates ONE approval/Jira per incident, not per finding.
"""

import json
import re
import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.tables import Approval, Device, Finding, Recommendation

log = structlog.get_logger()


# Network entity extraction patterns
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b")
_INTF = re.compile(
    r"\b(?:GigabitEthernet|TenGigabitEthernet|FastEthernet|Ethernet|Loopback|"
    r"Tunnel|Port-channel|Vlan|Serial)\d+(?:/\d+)*(?:\.\d+)?\b"
)
_MAC = re.compile(r"\b(?:[0-9a-f]{4}\.){2}[0-9a-f]{4}\b", re.IGNORECASE)


@dataclass
class IncidentGroup:
    incident_id: str
    findings: list[Finding]
    root_cause: Finding
    shared_entities: set[str]
    title: str  # synthesized incident title
    summary: str  # synthesized incident description


def _extract_entities(f: Finding) -> set[str]:
    """Pull network entities out of a finding's text + evidence.

    These entities become the join keys for grouping cross-device findings.
    We extract:
      - IPv4 host addresses (always normalised — strip /mask suffix)
      - IPv4 prefixes (kept with /mask — different prefixes shouldn't merge)
      - Interface names (lowercased)
      - MAC addresses (lowercased)

    192.168.1.2 and 192.168.1.2/24 must match — they reference the same
    host on the same link, just with different syntactic representations.
    """
    text_parts = [f.title or "", f.description or "", f.affected_entity or ""]
    if f.evidence:
        try:
            text_parts.append(json.dumps(f.evidence, default=str))
        except Exception:
            pass
    text = " ".join(text_parts)

    entities: set[str] = set()
    for raw in _IPV4.findall(text):
        if "/" in raw:
            host, mask = raw.split("/", 1)
            entities.add(host)            # host form for cross-device join
            try:
                if int(mask) < 32:
                    entities.add(raw)     # also keep prefix form
            except ValueError:
                entities.add(raw)
        else:
            entities.add(raw)
    entities.update(m.lower() for m in _INTF.findall(text))
    entities.update(m.lower() for m in _MAC.findall(text))

    # Filter out entities that are too generic to be useful join keys.
    noise = {
        "0.0.0.0", "255.255.255.255", "127.0.0.1", "224.0.0.5", "224.0.0.6",
        "224.0.0.10", "224.0.0.13", "::", "::1",
    }
    entities -= noise
    return entities


def _device_key(f: Finding, entities: set[str]) -> str:
    """A finding from device A and a finding from device B share an
    incident if their entities overlap. But two findings on the SAME
    device with different IPs shouldn't merge — keep that distinction.
    """
    return f.device_id


def _root_cause_priority(f: Finding) -> tuple:
    """Lower tuple = higher priority for root cause selection.

    Root-cause hierarchy:
      1. Interface failure / link down (the physical event)
      2. Critical BGP/OSPF session down (control plane next)
      3. Other critical findings
      4. High routing changes (downstream effect)
      5. Everything else
    """
    title = (f.title or "").lower()
    desc = (f.description or "").lower()
    cat = (f.category or "").lower()
    sev = (f.severity or "").lower()

    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}.get(sev, 5)

    is_interface_down = (
        cat == "interface" and (
            "down" in title or "failure" in title or "link" in title or "shut" in title
        )
    )
    is_session_down = (
        ("bgp" in title or "ospf" in title or "session" in title) and
        ("down" in title or "lost" in title or "dropped" in title or "idle" in title or "fail" in title)
    )
    is_route_withdrawn = (
        "route" in title and ("withdraw" in title or "removed" in title or "lost" in title)
    )

    if is_interface_down:
        bucket = 0
    elif is_session_down:
        bucket = 1
    elif sev == "critical":
        bucket = 2
    elif is_route_withdrawn:
        bucket = 4
    else:
        bucket = 3

    return (bucket, severity_rank, -(f.confidence or 0.0))


def correlate_findings(findings: list[Finding]) -> list[IncidentGroup]:
    """Group a list of Finding ORM objects into incidents.

    Groups findings whose extracted entities overlap (union-find).
    Single-finding groups are still returned as 1-finding incidents —
    every finding belongs to an incident, even if it's solo.
    """
    if not findings:
        return []

    # Step 1: extract entities per finding
    entities: dict[str, set[str]] = {f.id: _extract_entities(f) for f in findings}

    # Step 2: union-find over shared entities
    parent: dict[str, str] = {f.id: f.id for f in findings}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Build entity → finding ids index for O(N + edges) grouping rather than O(N^2).
    entity_to_findings: dict[str, list[str]] = {}
    for f in findings:
        for e in entities[f.id]:
            entity_to_findings.setdefault(e, []).append(f.id)

    for ids in entity_to_findings.values():
        if len(ids) < 2:
            continue
        first = ids[0]
        for other in ids[1:]:
            union(first, other)

    # Step 3: collect groups
    groups: dict[str, list[Finding]] = {}
    for f in findings:
        groups.setdefault(find(f.id), []).append(f)

    # Step 4: build IncidentGroup objects with stable incident_ids and root cause
    incidents: list[IncidentGroup] = []
    for group_findings in groups.values():
        group_findings.sort(key=_root_cause_priority)
        root = group_findings[0]
        shared = set()
        for f in group_findings:
            shared |= entities[f.id]

        incident_id = str(uuid.uuid4())
        title, summary = _summarise_incident(group_findings, root, shared)
        incidents.append(IncidentGroup(
            incident_id=incident_id,
            findings=group_findings,
            root_cause=root,
            shared_entities=shared,
            title=title,
            summary=summary,
        ))

    return incidents


def _summarise_incident(findings: list[Finding], root: Finding, shared: set[str]) -> tuple[str, str]:
    """Build a compact incident title + summary from grouped findings."""
    if len(findings) == 1:
        return (root.title or "Incident", "")

    # Multi-finding incident — synthesize a title that names the root and the spread
    device_count = len({f.device_id for f in findings})
    severities = sorted({f.severity for f in findings})
    root_title = root.title or "Incident"
    title = f"{root_title} (correlated across {device_count} device{'s' if device_count > 1 else ''})"

    lines = [
        f"Root cause: {root_title}",
        f"This incident produced {len(findings)} findings across {device_count} devices.",
        f"Severities observed: {', '.join(severities)}.",
    ]
    if shared:
        # Show up to 5 entities so the operator sees what links them
        sample = sorted(shared)[:5]
        more = f" (and {len(shared)-5} more)" if len(shared) > 5 else ""
        lines.append(f"Shared entities: {', '.join(sample)}{more}.")
    lines.append("Other findings in this incident were caused by, or are downstream effects of, the root cause above.")
    return (title, "\n".join(lines))


async def _load_topology_neighbors(db: AsyncSession) -> dict[str, set[str]]:
    """Build device_id → set of neighbor device_ids from the topology service.

    Findings on directly-connected devices (via BGP peering or shared L2
    segment) are likely the same incident even when their text doesn't
    explicitly share an entity. This map is the topology overlay.
    """
    try:
        from services.topology import build_topology
        topo = await build_topology(db)
    except Exception as exc:
        log.warning("topology_load_failed_for_correlation", error=str(exc))
        return {}

    neighbors: dict[str, set[str]] = {}
    for edge in topo.get("bgp_edges", []):
        a, b = edge.get("from"), edge.get("to")
        if a and b:
            neighbors.setdefault(a, set()).add(b)
            neighbors.setdefault(b, set()).add(a)
    for seg in topo.get("l2_segments", []):
        members = [m.get("device_id") for m in seg.get("members", []) if m.get("device_id")]
        for i, m1 in enumerate(members):
            for m2 in members[i + 1:]:
                neighbors.setdefault(m1, set()).add(m2)
                neighbors.setdefault(m2, set()).add(m1)
    return neighbors


# Causally-related category pairs. A finding in the FIRST category on the
# same device usually causes findings in the SECOND. We use this to merge
# obvious "interface broke → BGP died on the same box" incidents.
_CAUSAL_PAIRS: list[tuple[str, str]] = [
    ("interface", "routing"),       # interface down → BGP/OSPF/route lost
    ("interface", "performance"),   # interface errors → throughput drop
    ("routing", "routing"),         # one routing finding causes another
]


def _categories_causally_linked(a: str, b: str) -> bool:
    a, b = (a or "").lower(), (b or "").lower()
    return any({a, b} == {x, y} or a == b for x, y in _CAUSAL_PAIRS)


def _merge_same_device_incidents(incidents: list[IncidentGroup]) -> list[IncidentGroup]:
    """Merge incidents whose findings share a device AND have causally-
    related categories. Catches the case where 'interface admin-down' and
    'BGP neighbor in Idle' on the SAME device are obviously the same event,
    even when no IP/interface name overlaps in the text.
    """
    if len(incidents) < 2:
        return incidents

    parent = {inc.incident_id: inc.incident_id for inc in incidents}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, inc_a in enumerate(incidents):
        a_devs = {f.device_id for f in inc_a.findings}
        a_cats = {(f.category or "").lower() for f in inc_a.findings}
        for inc_b in incidents[i + 1:]:
            b_devs = {f.device_id for f in inc_b.findings}
            shared_devs = a_devs & b_devs
            if not shared_devs:
                continue
            b_cats = {(f.category or "").lower() for f in inc_b.findings}
            # If any pair of categories across the two incidents is
            # causally linked, merge them.
            linked = any(_categories_causally_linked(ca, cb) for ca in a_cats for cb in b_cats)
            if linked:
                union(inc_a.incident_id, inc_b.incident_id)

    return _rebuild_groups_from_unionfind(incidents, parent, find,
                                          merge_note="Merged: findings on the same device with causally-related categories.")


def _rebuild_groups_from_unionfind(
    incidents: list[IncidentGroup],
    parent: dict[str, str],
    find,
    merge_note: str,
) -> list[IncidentGroup]:
    merged: dict[str, list[IncidentGroup]] = {}
    for inc in incidents:
        merged.setdefault(find(inc.incident_id), []).append(inc)

    final: list[IncidentGroup] = []
    for group in merged.values():
        if len(group) == 1:
            final.append(group[0])
            continue
        all_findings = [f for g in group for f in g.findings]
        all_findings.sort(key=_root_cause_priority)
        root = all_findings[0]
        shared = set()
        for g in group:
            shared |= g.shared_entities
        merged_id = group[0].incident_id
        title, summary = _summarise_incident(all_findings, root, shared)
        summary += f"\n{merge_note}"
        final.append(IncidentGroup(
            incident_id=merged_id,
            findings=all_findings,
            root_cause=root,
            shared_entities=shared,
            title=title,
            summary=summary,
        ))
    return final


def _correlate_with_topology(
    findings: list[Finding],
    neighbors: dict[str, set[str]],
) -> list[IncidentGroup]:
    """Same as correlate_findings, but also merges incidents whose root
    findings sit on directly-connected devices AND share the same primary
    category (interface/routing). This catches the case where two ends of a
    broken link describe the issue without naming each other.
    """
    incidents = correlate_findings(findings)
    # Pass A: same-device causal merge — runs first because it's the
    # cleanest signal (interface and BGP failure on same box ARE the same
    # incident, no ambiguity).
    incidents = _merge_same_device_incidents(incidents)
    if not neighbors or len(incidents) < 2:
        return incidents

    # Re-run union-find at the incident level using topology neighbour edges.
    parent = {inc.incident_id: inc.incident_id for inc in incidents}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, inc_a in enumerate(incidents):
        a_devs = {f.device_id for f in inc_a.findings}
        a_cats = {(f.category or "").lower() for f in inc_a.findings}
        for inc_b in incidents[i + 1:]:
            b_devs = {f.device_id for f in inc_b.findings}
            b_cats = {(f.category or "").lower() for f in inc_b.findings}
            shared_family = bool(a_cats & b_cats)
            if not shared_family:
                continue
            connected = any(d2 in neighbors.get(d1, set()) for d1 in a_devs for d2 in b_devs)
            if connected:
                union(inc_a.incident_id, inc_b.incident_id)

    return _rebuild_groups_from_unionfind(incidents, parent, find,
                                          merge_note="Topology-aware merge: these findings sit on directly-connected devices.")


async def apply_correlation(
    db: AsyncSession,
    snapshot_ids: list[str],
) -> list[IncidentGroup]:
    """Load all findings for the given snapshot_ids, correlate, and persist.

    Sets ``incident_id``, ``is_root_cause`` and ``correlation_reason`` on
    each finding. Returns the IncidentGroups for downstream callers
    (approval/Jira creation).

    Two-pass correlation:
      1. Entity overlap (shared IPs/interfaces/MACs) — catches most cascades
      2. Topology overlay (BGP edges + L2 segments) — catches cases where
         two ends of a broken link don't textually share an entity
    """
    if not snapshot_ids:
        return []

    result = await db.execute(
        select(Finding).where(Finding.snapshot_id.in_(snapshot_ids))
    )
    findings = list(result.scalars().all())
    if not findings:
        return []

    neighbors = await _load_topology_neighbors(db)
    incidents = _correlate_with_topology(findings, neighbors)

    # History-aware: when a finding's incident_id was already set by a prior
    # snapshot run (e.g. it was deduped from an earlier finding which had
    # been correlated then), prefer that stable incident_id over a freshly
    # generated one. Keeps long-running incidents identifiable across runs
    # so the operator sees "still incident #abc, ongoing" not "new incident
    # #def every hour".
    for inc in incidents:
        prior_ids = {f.incident_id for f in inc.findings if f.incident_id}
        if prior_ids:
            # Take the most-frequent prior id; ties resolved arbitrarily
            from collections import Counter
            prior_id = Counter(
                f.incident_id for f in inc.findings if f.incident_id
            ).most_common(1)[0][0]
            inc.incident_id = prior_id

    for inc in incidents:
        for f in inc.findings:
            f.incident_id = inc.incident_id
            f.is_root_cause = (f.id == inc.root_cause.id)
            if len(inc.findings) > 1:
                if f.is_root_cause:
                    f.correlation_reason = (
                        f"Root cause of incident with {len(inc.findings)} findings "
                        f"across {len({x.device_id for x in inc.findings})} devices."
                    )
                else:
                    f.correlation_reason = (
                        f"Linked to root cause: '{inc.root_cause.title}' "
                        f"on the same incident."
                    )

    await db.flush()

    log.info(
        "correlation_complete",
        snapshots=len(snapshot_ids),
        findings=len(findings),
        incidents=len(incidents),
        multi_finding_incidents=sum(1 for i in incidents if len(i.findings) > 1),
    )

    return incidents


async def generate_incident_remediations(
    db: AsyncSession,
    incidents: list[IncidentGroup],
) -> int:
    """For each incident whose root cause needs remediation, run Sonnet ONCE
    to generate a Recommendation. Skips incidents whose root finding has
    ``requires_remediation == False``. Returns the number of recommendations
    created.

    The Sonnet prompt receives the root cause finding plus a brief summary
    of any linked findings — this gives the model the cross-device context
    it needs to suggest a fix that addresses the whole incident, not just
    one device's symptom.
    """
    if not incidents:
        return 0

    import json

    from agents.nodes.remediation import SYSTEM_PROMPT
    from config import settings
    from db.tables import Device
    from integrations.anthropic import anthropic_client

    # Resolve device hostnames in one query
    device_ids = list({f.device_id for inc in incidents for f in inc.findings})
    dev_result = await db.execute(select(Device).where(Device.id.in_(device_ids)))
    dev_map: dict[str, str] = {d.id: d.hostname for d in dev_result.scalars().all()}

    created = 0
    for inc in incidents:
        root = inc.root_cause
        if not root.requires_remediation:
            continue

        # Skip only if there's an OPEN approval (pending or approved). An
        # already-executed/denied/expired approval from a prior occurrence
        # of the same finding (carried forward by ChromaDB dedup) is a
        # closed loop — the issue has come back, generate fresh advice.
        open_q = await db.execute(
            select(Approval)
            .join(Recommendation, Approval.recommendation_id == Recommendation.id)
            .where(Recommendation.finding_id == root.id)
            .where(Approval.status.in_(["pending", "approved"]))
        )
        if open_q.scalars().first() is not None:
            continue

        root_host = dev_map.get(root.device_id, "unknown")
        root_payload = {
            "id": root.id,
            "category": root.category,
            "severity": root.severity,
            "confidence": root.confidence,
            "title": root.title,
            "description": root.description,
            "affected_entity": root.affected_entity,
            "evidence": root.evidence,
            "requires_remediation": root.requires_remediation,
        }
        linked = []
        for f in inc.findings:
            if f.id == root.id:
                continue
            linked.append({
                "title": f.title,
                "severity": f.severity,
                "device": dev_map.get(f.device_id, "?").split(".")[0],
                "affected_entity": f.affected_entity,
            })

        prompt = (
            f"Device: {root_host} (root cause)\n\n"
            f"## Root-Cause Finding (this is what needs remediation)\n"
            f"```json\n{json.dumps(root_payload, default=str, indent=2)}\n```\n\n"
        )
        if linked:
            prompt += (
                f"## Linked Downstream Findings (for context — do NOT generate "
                f"separate fixes for these; they should resolve when the root "
                f"cause is fixed)\n"
                f"```json\n{json.dumps(linked, default=str, indent=2)}\n```\n\n"
            )
        prompt += (
            "Generate ONE remediation recommendation that addresses the root "
            "cause. The fix should be applied on the device named above."
        )

        try:
            result = await anthropic_client.message(
                prompt=prompt,
                system=SYSTEM_PROMPT,
                model=settings.sonnet_model,
                max_tokens=8192,
                temperature=0.2,
            )
        except Exception as e:
            log.error(
                "incident_remediation_failed",
                incident_id=inc.incident_id,
                root_finding=root.id,
                error=str(e),
            )
            continue

        recs = result.get("recommendations", [])
        model = result.get("_model", settings.sonnet_model)
        if not recs:
            continue
        # The model may return one recommendation; take the first.
        r = recs[0]
        rec = Recommendation(
            finding_id=root.id,
            action_description=r.get("action", ""),
            commands=r.get("commands", []),
            rollback_commands=r.get("rollback_commands", []),
            risk_level=r.get("risk_level", "medium"),
            reasoning=r.get("reasoning", ""),
            agent_model=model,
            tokens_used=None,
        )
        db.add(rec)
        created += 1

    await db.flush()
    log.info(
        "incident_remediations_generated",
        incidents=len(incidents),
        recommendations=created,
    )
    return created


async def create_incident_approvals(
    db: AsyncSession,
    incidents: list[IncidentGroup],
) -> int:
    """For each incident, create ONE pending approval + Jira ticket from the
    root-cause finding's recommendation. Skips incidents whose root cause
    has no recommendation (low-severity findings without remediation).

    Returns the number of approvals created.
    """
    if not incidents:
        return 0

    from integrations.jira import jira_client
    from integrations.slack import slack_client

    # Resolve device hostnames in one query
    device_ids = list({inc.root_cause.device_id for inc in incidents})
    dev_result = await db.execute(select(Device).where(Device.id.in_(device_ids)))
    dev_map: dict[str, str] = {d.id: d.hostname for d in dev_result.scalars().all()}

    created = 0
    for inc in incidents:
        root = inc.root_cause
        # Find the recommendation for the root finding. Multiple may exist
        # in edge cases (re-runs / recurring incidents); take the most recent.
        rec_result = await db.execute(
            select(Recommendation)
            .where(Recommendation.finding_id == root.id)
            .order_by(Recommendation.created_at.desc())
        )
        rec = rec_result.scalars().first()
        if rec is None:
            continue  # root finding doesn't need remediation — no approval needed

        # Skip only if there's an OPEN approval (pending or approved) for
        # THIS specific recommendation. An old executed/denied approval on
        # an earlier recommendation for the same finding is a closed loop;
        # the new recommendation deserves a fresh approval.
        existing_open = await db.execute(
            select(Approval)
            .where(Approval.recommendation_id == rec.id)
            .where(Approval.status.in_(["pending", "approved"]))
        )
        if existing_open.scalars().first() is not None:
            continue

        host = dev_map.get(root.device_id, "unknown")
        approval = Approval(recommendation_id=rec.id, status="pending")

        # One Jira ticket per incident — title prepends the cascade context
        affected_hosts = sorted({dev_map.get(f.device_id, "?") for f in inc.findings})
        title = root.title
        if len(inc.findings) > 1:
            title = f"[INCIDENT] {root.title} (+{len(inc.findings)-1} linked findings)"

        description = rec.reasoning or ""
        if len(inc.findings) > 1:
            description = (
                f"{description}\n\n--- Correlated incident ---\n"
                f"This incident produced {len(inc.findings)} findings across "
                f"{len(affected_hosts)} devices: {', '.join(h.split('.')[0] for h in affected_hosts)}.\n"
                f"{inc.summary}"
            )

        jira_result = await jira_client.create_service_request(
            title=title,
            description=description,
            severity=root.severity,
            device_hostname=host,
            approval_id=approval.id,
            commands=rec.commands,
            risk_level=rec.risk_level,
            reasoning=description,
            rollback_commands=rec.rollback_commands,
            analysis_model=root.agent_model,
            remediation_model=rec.agent_model,
        )
        if jira_result:
            approval.jira_issue_key = jira_result["key"]
            approval.jira_issue_url = jira_result["url"]

        db.add(approval)
        created += 1

        await slack_client.notify_new_approval(
            approval_id=approval.id,
            finding_title=title,
            severity=root.severity,
            device_hostname=host,
            action_description=rec.action_description,
            risk_level=rec.risk_level,
            commands=rec.commands,
            jira_url=jira_result["url"] if jira_result else None,
        )

    await db.flush()
    log.info("incident_approvals_created", incidents=len(incidents), approvals=created)
    return created
