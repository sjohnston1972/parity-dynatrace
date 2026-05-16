"""Idempotent provisioner for the Parity ⇄ Dynatrace surfaces.

Creates (or updates if `externalId` already exists):

  * A platform dashboard named "Parity · Network Remediation Activity"
    with DQL-driven tiles for the lifecycle of every finding Parity
    emits — events over time, lifecycle breakdown, top devices and
    categories, latest-events table.

  * A Davis Workflow that watches for `source==parity` events of
    severity high/critical and posts a Davis problem so the events
    surface in the Problems view, not just the Events stream.

  * (Best-effort) registers each Parity-managed router as a
    CUSTOM_DEVICE on the tenant so future events can attach to a
    Dynatrace entity. Skipped automatically if the token lacks
    `environment-api:entities:write`.

Idempotent: re-running updates in place via `externalId` lookup so we
never accumulate duplicates.

Run:  py scripts/dynatrace_setup.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

APPS = (os.environ.get("DT_ENVIRONMENT") or "").rstrip("/")
LIVE = APPS.replace(".apps.dynatrace.com", ".live.dynatrace.com")
TOKEN = os.environ.get("DT_PLATFORM_TOKEN") or ""

DASHBOARD_EXTERNAL_ID = "parity-dynatrace-dashboard-v1"
WORKFLOW_TITLE = "parity · open Davis problem on high-severity finding"

ROUTERS = [
    {"id": "parity-DC1-R1", "name": "DC1-R1.clydeford.net", "mgmt": "192.168.20.13"},
    {"id": "parity-DC2-R2", "name": "DC2-R2.clydeford.net", "mgmt": "192.168.20.12"},
    {"id": "parity-S1-R1",  "name": "S1-R1.clydeford.net",  "mgmt": "192.168.20.33"},
    {"id": "parity-S2-R1",  "name": "S2-R1.clydeford.net",  "mgmt": "192.168.20.22"},
]


# ── Helpers ──────────────────────────────────────────────────


def _hdr() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _log(msg: str) -> None:
    print(msg, flush=True)


def _abort_if_unconfigured():
    if not APPS or not TOKEN:
        raise SystemExit(
            "DT_ENVIRONMENT and DT_PLATFORM_TOKEN must be set in .env"
        )


# ── Dashboard ────────────────────────────────────────────────


def _dashboard_content() -> dict[str, Any]:
    """Build the Parity dashboard layout — DQL tiles only.

    Schema: Dynatrace platform dashboard document v15. Tiles indexed by
    string keys; layouts reference the same keys with x/y/w/h on a
    24-wide grid.
    """
    return {
        "version": 15,
        "variables": [],
        "tiles": {
            # Markdown title strip
            "0": {
                "type": "markdown",
                "content": (
                    "# Parity · Network Remediation Activity\n\n"
                    "Live view of findings raised, resolved, and correlated by "
                    "[Parity](https://parity-dynatrace.clydeford.net) — "
                    "an autonomous day-2 NetOps loop. Every event below was "
                    "emitted by Parity into this tenant via the Generic Events "
                    "API; this dashboard reads them straight back from Grail."
                ),
            },
            # KPI: findings raised (24h)
            "1": {
                "type": "data",
                "title": "Findings raised · 24 h",
                "query": (
                    'fetch events, from:-24h | filter source == "parity" '
                    '| filter parity.action == "created" | summarize n = count()'
                ),
                "visualization": "singleValue",
                "visualizationSettings": {
                    "singleValue": {"label": "raised", "showLabel": True}
                },
            },
            # KPI: findings resolved (24h)
            "2": {
                "type": "data",
                "title": "Findings resolved · 24 h",
                "query": (
                    'fetch events, from:-24h | filter source == "parity" '
                    '| filter parity.action == "resolved" | summarize n = count()'
                ),
                "visualization": "singleValue",
                "visualizationSettings": {
                    "singleValue": {"label": "resolved", "showLabel": True}
                },
            },
            # KPI: distinct devices touched (24h)
            "3": {
                "type": "data",
                "title": "Distinct devices · 24 h",
                "query": (
                    'fetch events, from:-24h | filter source == "parity" '
                    '| summarize n = countDistinctExact(parity.device)'
                ),
                "visualization": "singleValue",
                "visualizationSettings": {
                    "singleValue": {"label": "devices", "showLabel": True}
                },
            },
            # Time series: lifecycle over time
            "4": {
                "type": "data",
                "title": "Lifecycle over time",
                "query": (
                    'fetch events, from:-24h | filter source == "parity" '
                    '| makeTimeseries n = count(), by: { parity.action }, '
                    'interval: 5m'
                ),
                "visualization": "lineChart",
            },
            # Bar: severity distribution
            "5": {
                "type": "data",
                "title": "Severity distribution",
                "query": (
                    'fetch events, from:-24h | filter source == "parity" '
                    '| summarize n = count(), by: { parity.severity } '
                    '| sort n desc'
                ),
                "visualization": "honeycomb",
            },
            # Bar: category distribution
            "6": {
                "type": "data",
                "title": "Drift categories",
                "query": (
                    'fetch events, from:-24h | filter source == "parity" '
                    '| filter isNotNull(parity.category) '
                    '| summarize n = count(), by: { parity.category } '
                    '| sort n desc'
                ),
                "visualization": "pieChart",
            },
            # Bar: top devices
            "7": {
                "type": "data",
                "title": "Top devices",
                "query": (
                    'fetch events, from:-24h | filter source == "parity" '
                    '| summarize n = count(), by: { parity.device } '
                    '| sort n desc | limit 10'
                ),
                "visualization": "barChart",
            },
            # Table: latest events
            "8": {
                "type": "data",
                "title": "Latest 25 events",
                "query": (
                    'fetch events, from:-24h | filter source == "parity" '
                    '| sort timestamp desc | limit 25 '
                    '| fields timestamp, parity.action, parity.severity, '
                    'parity.category, parity.device, parity.title'
                ),
                "visualization": "table",
            },
        },
        "layouts": {
            "0": {"x": 0,  "y": 0,  "w": 24, "h": 2},   # header
            "1": {"x": 0,  "y": 2,  "w": 8,  "h": 3},   # raised
            "2": {"x": 8,  "y": 2,  "w": 8,  "h": 3},   # resolved
            "3": {"x": 16, "y": 2,  "w": 8,  "h": 3},   # devices
            "4": {"x": 0,  "y": 5,  "w": 24, "h": 6},   # timeseries
            "5": {"x": 0,  "y": 11, "w": 8,  "h": 6},   # severity
            "6": {"x": 8,  "y": 11, "w": 8,  "h": 6},   # category
            "7": {"x": 16, "y": 11, "w": 8,  "h": 6},   # devices
            "8": {"x": 0,  "y": 17, "w": 24, "h": 7},   # latest events
        },
    }


def find_existing_doc(external_id: str) -> dict | None:
    """Documents API filters by externalId — used for idempotent upsert."""
    r = httpx.get(
        f"{APPS}/platform/document/v1/documents",
        headers=_hdr(),
        params={"filter": f"externalId=='{external_id}'", "pageSize": 5},
        timeout=15,
    )
    if r.status_code != 200:
        return None
    docs = r.json().get("documents") or []
    return docs[0] if docs else None


def upsert_dashboard() -> str:
    """Create or update the Parity dashboard, return its URL."""
    content = _dashboard_content()
    content_blob = json.dumps(content)
    existing = find_existing_doc(DASHBOARD_EXTERNAL_ID)

    if existing:
        doc_id = existing["id"]
        _log(f"  found existing dashboard id={doc_id} — updating")
        r = httpx.patch(
            f"{APPS}/platform/document/v1/documents/{doc_id}",
            headers=_hdr(),
            params={"optimistic-locking-version": str(existing.get("version", 1))},
            files={
                "name": (None, "Parity · Network Remediation Activity"),
                "content": ("content.json", content_blob, "application/json"),
            },
            timeout=20,
        )
        if r.status_code >= 400:
            _log(f"  FAIL update failed {r.status_code}: {r.text[:300]}")
            return ""
    else:
        _log("  no existing dashboard — creating")
        r = httpx.post(
            f"{APPS}/platform/document/v1/documents",
            headers=_hdr(),
            files={
                "name": (None, "Parity · Network Remediation Activity"),
                "type": (None, "dashboard"),
                "externalId": (None, DASHBOARD_EXTERNAL_ID),
                "content": ("content.json", content_blob, "application/json"),
            },
            timeout=20,
        )
        if r.status_code >= 400:
            _log(f"  FAIL create failed {r.status_code}: {r.text[:300]}")
            return ""
        doc_id = r.json()["id"]

    url = f"{APPS}/ui/apps/dynatrace.dashboards/dashboard/{doc_id}"
    _log(f"  OK dashboard ready: {url}")
    return url


# ── Workflow ─────────────────────────────────────────────────


def _workflow_definition() -> dict[str, Any]:
    """Davis Workflow: watch Parity events, post a Davis problem.

    Trigger: any event with source==parity AND severity in (high,critical).
    Action: a JavaScript task that hits the events.ingest API again with
    a different eventType so the event also appears as a problem-shaped
    entry in the Davis Problems list.
    """
    js = (
        "import { execution } from '@dynatrace-sdk/automation-utils';\n"
        "import { eventsClient } from '@dynatrace-sdk/client-classic-environment-v2';\n"
        "\n"
        "export default async ({ execution_id, event }) => {\n"
        "  const e = event() || {};\n"
        "  const title = e['event.name'] || 'Parity finding';\n"
        "  const device = e['parity.device'] || 'unknown';\n"
        "  const severity = e['parity.severity'] || 'high';\n"
        "  const finding = e['parity.finding.id'] || '';\n"
        "  try {\n"
        "    await eventsClient.createEvent({\n"
        "      body: {\n"
        "        eventType: 'AVAILABILITY_EVENT',\n"
        "        title: `Parity: ${title}`,\n"
        "        properties: {\n"
        "          'parity.relays.from_workflow': execution_id,\n"
        "          'parity.device': device,\n"
        "          'parity.severity': severity,\n"
        "          'parity.finding.id': finding,\n"
        "        }\n"
        "      }\n"
        "    });\n"
        "    return { status: 'relayed', finding };\n"
        "  } catch (err) {\n"
        "    return { status: 'error', error: String(err) };\n"
        "  }\n"
        "};\n"
    )
    return {
        "title": WORKFLOW_TITLE,
        "description": "When Parity raises a high-severity finding, relay it as a Davis availability event so it appears in the Problems list.",
        "isPrivate": False,
        "trigger": {
            "eventTrigger": {
                "isActive": True,
                "triggerConfiguration": {
                    "type": "event",
                    "value": {
                        "query": (
                            'event.type=="CUSTOM_DEPLOYMENT" AND '
                            'source=="parity" AND '
                            'parity.action=="created" AND '
                            '(parity.severity=="high" OR parity.severity=="critical")'
                        ),
                        "eventType": "events",
                    },
                },
            }
        },
        "tasks": {
            "relay": {
                "name": "relay",
                "action": "dynatrace.automations:run-javascript",
                "input": {"script": js},
                "position": {"x": 0, "y": 1},
            }
        },
    }


def find_existing_workflow() -> str | None:
    r = httpx.get(
        f"{APPS}/platform/automation/v1/workflows",
        headers=_hdr(),
        timeout=15,
    )
    if r.status_code != 200:
        return None
    for wf in r.json().get("results", []):
        if wf.get("title") == WORKFLOW_TITLE:
            return wf.get("id")
    return None


def upsert_workflow() -> str:
    defn = _workflow_definition()
    existing = find_existing_workflow()
    if existing:
        _log(f"  found existing workflow id={existing} — updating")
        r = httpx.put(
            f"{APPS}/platform/automation/v1/workflows/{existing}",
            headers=_hdr(),
            json=defn,
            timeout=20,
        )
        if r.status_code >= 400:
            _log(f"  FAIL update failed {r.status_code}: {r.text[:300]}")
            return ""
        wf_id = existing
    else:
        _log("  no existing workflow — creating")
        r = httpx.post(
            f"{APPS}/platform/automation/v1/workflows",
            headers=_hdr(),
            json=defn,
            timeout=20,
        )
        if r.status_code >= 400:
            _log(f"  FAIL create failed {r.status_code}: {r.text[:300]}")
            return ""
        wf_id = r.json().get("id")

    url = f"{APPS}/ui/apps/dynatrace.automations/workflows/{wf_id}"
    _log(f"  OK workflow ready: {url}")
    return url


# ── Custom Devices (best-effort — needs entities:write) ─────


def register_custom_devices() -> tuple[int, int]:
    """Register each Parity-managed router as a CUSTOM_DEVICE.

    Skips silently if the token lacks the scope (returns 0,0).
    """
    ok = skipped = 0
    for r in ROUTERS:
        resp = httpx.post(
            f"{LIVE}/api/v2/entities/custom",
            headers={**_hdr(), "Content-Type": "application/json"},
            json={
                "customDeviceId": r["id"],
                "displayName": r["name"],
                "type": "NETWORK_DEVICE",
                "ipAddresses": [r["mgmt"]],
                "properties": {
                    "managed_by": "parity",
                    "platform": "iosxe",
                    "mgmt_ip": r["mgmt"],
                },
            },
            timeout=10,
        )
        if resp.status_code == 403:
            skipped = len(ROUTERS)
            _log("  skipping all custom-device creates — token lacks entities:write")
            break
        if resp.status_code in (200, 201):
            ok += 1
            _log(f"  OK {r['name']}")
        else:
            _log(f"  FAIL {r['name']} {resp.status_code}: {resp.text[:120]}")
    return ok, skipped


# ── Main ─────────────────────────────────────────────────────


def main() -> int:
    _abort_if_unconfigured()
    print(f"Provisioning Parity surfaces on {APPS}")
    print()

    print("[1/3] Dashboard")
    dashboard_url = upsert_dashboard()
    print()

    print("[2/3] Davis Workflow")
    workflow_url = upsert_workflow()
    print()

    print("[3/3] Custom Devices (best-effort)")
    ok, skipped = register_custom_devices()
    print()

    print("=" * 60)
    print("Summary")
    print("=" * 60)
    if dashboard_url:
        print(f"Dashboard:  {dashboard_url}")
    if workflow_url:
        print(f"Workflow:   {workflow_url}")
    print(f"Devices:    {ok} created / {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
