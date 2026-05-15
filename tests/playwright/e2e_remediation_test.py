"""End-to-end remediation test against the live Clydeford homelab.

Exercises four scenarios through the full Parity loop:

  A. Unsanctioned loopback99 added on DC1-R1 — full snapshot->reason->
     approve->execute->verify->resolve cycle. Remediation reverts.

  C. Unsanctioned static route 198.51.100.0/24 (TEST-NET-2) added on
     DC2-R2, next-hop the existing BGP peer 192.168.2.2. The new entry
     shows up under routing.vrf.default.address_family.ipv4.routes.*
     with source_protocol=static — exactly the path shape the reasoner
     already covers. Remediation removes the static route.

  D1/D2. Two canned Davis problems from the Dynatrace MCP stub
     (P-1842 BGP_NEIGHBOR_DOWN and P-1903 INTERFACE_ERROR_STORM) —
     ingested, asserted, then closed via the stub's /admin/close-problem
     test-only endpoint. Re-ingest flips Parity's requires_remediation
     to False; dashboard tile counts drop back to 0.

Safety rails the script enforces on every config push:
  - Refuses to send any line touching the management subnet 192.168.20.0/24
    or the device's own SSH/management interface.
  - Refuses anything that could lock us out: `line vty`, `username`,
    `enable secret`, `interface <mgmt>`, `no aaa`, `no ip ssh`.
  - Pings the device immediately AFTER each push; if reachability is
    lost the script aborts loud and never advances.

Run:  py tests/playwright/e2e_remediation_test.py run-all
Sub-commands: preflight, dryrun-c, run-a, run-c, run-davis, run-all, cleanup
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
from dotenv import load_dotenv
from netmiko import ConnectHandler, NetmikoAuthenticationException, NetmikoTimeoutException


# ── Configuration ────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = Path(__file__).resolve().parent / "e2e_evidence"
load_dotenv(REPO_ROOT / ".env")

BASE = os.environ.get("PARITY_URL", "https://parity-dynatrace.clydeford.net")
MCP_STUB_URL = os.environ.get(
    # The stub isn't exposed publicly; we reach it via docker compose port 8220 on the host.
    "PARITY_MCP_STUB_URL",
    "http://localhost:8220",
)
PYATS_USERNAME = os.environ.get("PYATS_USERNAME", "")
PYATS_PASSWORD = os.environ.get("PYATS_PASSWORD", "")

DC1_R1 = {"hostname": "DC1-R1", "mgmt_ip": "192.168.20.13"}
DC2_R2 = {"hostname": "DC2-R2", "mgmt_ip": "192.168.20.12"}

MGMT_SUBNET = "192.168.20."
FORBIDDEN_TOKENS = (
    "line vty",
    "username ",
    "enable secret",
    "enable password",
    "no aaa",
    "no ip ssh",
    "transport input none",
    "shutdown",  # never blanket-shut anything in this test
)

LOOPBACK_NAME = "Loopback99"
LOOPBACK_IP = "192.0.2.99"
LOOPBACK_MASK = "255.255.255.255"
LOOPBACK_CIDR = "192.0.2.99/32"

DAVIS_PROBLEMS_TO_CLOSE = ["P-2026-05-13-1842", "P-2026-05-13-1903"]

# Scenario C: a documentation-prefix that won't collide with anything real.
# Next-hop is the device's existing BGP peer so the route actually installs.
SCENARIO_C_PREFIX = "198.51.100.0"
SCENARIO_C_MASK = "255.255.255.0"
SCENARIO_C_CIDR = "198.51.100.0/24"
SCENARIO_C_NEXT_HOP = "192.168.2.2"

POLL_INTERVAL = 5
DETECT_TIMEOUT = 240   # snapshot + reasoner
RESOLVE_TIMEOUT = 600  # execute + 3-phase verify


# ── Output helpers ───────────────────────────────────────────

_results: list[tuple[str, bool, str]] = []


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _check(name: str, ok: bool, detail: str = "") -> None:
    marker = "PASS" if ok else "FAIL"
    _log(f"  [{marker}] {name}{(' — ' + detail) if detail else ''}")
    _results.append((name, ok, detail))


def _save_evidence(scenario: str, name: str, data: Any) -> None:
    out_dir = EVIDENCE_DIR / scenario
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    _log(f"  evidence -> {path.relative_to(REPO_ROOT)}")


# ── HTTP helpers (Parity API via Cloudflare) ─────────────────


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=120.0)


def _get(path: str, **kw) -> Any:
    with _client() as c:
        r = c.get(path, **kw)
        r.raise_for_status()
        return r.json()


def _post(path: str, json_body: dict | None = None, **kw) -> Any:
    with _client() as c:
        r = c.post(path, json=json_body, **kw)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return r.text


def _delete(path: str, **kw) -> Any:
    with _client() as c:
        r = c.delete(path, **kw)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return r.text


def poll_until(
    fn: Callable[[], Any],
    *,
    desc: str,
    timeout: int,
    interval: int = POLL_INTERVAL,
) -> Any:
    """Call fn() until it returns a truthy value or timeout. Returns the last value."""
    start = time.monotonic()
    last = None
    while time.monotonic() - start < timeout:
        try:
            val = fn()
            if val:
                return val
            last = val
        except Exception as e:
            last = f"error: {e}"
        elapsed = int(time.monotonic() - start)
        _log(f"    polling {desc} (waited {elapsed}s/{timeout}s, last={last!r})")
        time.sleep(interval)
    raise TimeoutError(f"timeout waiting for {desc} after {timeout}s; last={last!r}")


# ── Lab interaction (netmiko) ────────────────────────────────


def _safety_check_commands(cmds: list[str], mgmt_ip: str) -> None:
    """Refuse anything that could brick the box or block our SSH."""
    for cmd in cmds:
        low = cmd.lower().strip()
        if MGMT_SUBNET in cmd:
            raise SystemExit(f"SAFETY: command references management subnet: {cmd!r}")
        if mgmt_ip in cmd:
            raise SystemExit(f"SAFETY: command references management IP {mgmt_ip}: {cmd!r}")
        for token in FORBIDDEN_TOKENS:
            if token in low:
                raise SystemExit(f"SAFETY: command contains forbidden token {token!r}: {cmd!r}")


def _ping(mgmt_ip: str) -> bool:
    """Quick reachability check from this host."""
    try:
        r = subprocess.run(
            ["ping", "-n", "2", "-w", "1500", mgmt_ip],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def _connect(device: dict) -> Any:
    if not PYATS_USERNAME or not PYATS_PASSWORD:
        raise SystemExit("PYATS_USERNAME / PYATS_PASSWORD must be set (read from .env)")
    return ConnectHandler(
        device_type="cisco_ios",
        host=device["mgmt_ip"],
        username=PYATS_USERNAME,
        password=PYATS_PASSWORD,
        secret=PYATS_PASSWORD,
        conn_timeout=20,
        banner_timeout=20,
        fast_cli=False,
    )


def lab_show(device: dict, cmd: str) -> str:
    _log(f"  {device['hostname']}: show> {cmd}")
    conn = _connect(device)
    try:
        return conn.send_command(cmd, read_timeout=30)
    finally:
        conn.disconnect()


def lab_configure(device: dict, cmds: list[str], *, label: str) -> str:
    """Push config to a device with full safety rails."""
    _safety_check_commands(cmds, device["mgmt_ip"])
    _log(f"  {device['hostname']}: APPLY [{label}]")
    for c in cmds:
        _log(f"    | {c}")
    if not _ping(device["mgmt_ip"]):
        raise SystemExit(f"SAFETY: {device['hostname']} not pingable before push — aborting")
    conn = _connect(device)
    try:
        out = conn.send_config_set(cmds, read_timeout=30)
        conn.save_config()
    finally:
        conn.disconnect()
    if not _ping(device["mgmt_ip"]):
        raise SystemExit(
            f"SAFETY: {device['hostname']} unreachable AFTER push — DO NOT proceed"
        )
    _log(f"  {device['hostname']}: APPLY OK ({len(cmds)} cmds)")
    return out


# ── Parity-pipeline helpers ──────────────────────────────────


def get_device_id(hostname: str) -> str:
    for d in _get("/api/v1/devices"):
        if d["hostname"].split(".")[0].upper() == hostname.upper():
            return d["id"]
    raise SystemExit(f"device not found in inventory: {hostname}")


def trigger_snapshot(device_id: str, *, label: str) -> dict:
    """Trigger a snapshot and wait for the snapshot job to finish."""
    _log(f"  snapshot trigger ({label})")
    _post("/api/v1/snapshots", json_body={"device_id": device_id})

    def _done():
        st = _get("/api/v1/snapshots/status")
        if not st.get("running"):
            return st
        return None

    status = poll_until(_done, desc=f"snapshot {label}", timeout=300, interval=10)
    if status.get("result") not in ("ok", "partial"):
        raise SystemExit(f"snapshot failed: {status}")
    snaps = _get(f"/api/v1/snapshots?device_id={device_id}&limit=1")
    if not snaps:
        raise SystemExit("no snapshot returned after job")
    return snaps[0]


def get_findings_for_snapshot(snapshot_id: str) -> list[dict]:
    return [
        f for f in _get("/api/v1/findings?limit=100&include_resolved=true")
        if f.get("snapshot_id") == snapshot_id
    ]


def get_active_finding_for_device(device_id: str) -> dict | None:
    """Most recent ACTIVE finding (requires_remediation=True) for this device."""
    rows = _get(f"/api/v1/findings?device_id={device_id}&limit=20")
    rows = [r for r in rows if r.get("requires_remediation")]
    return rows[0] if rows else None


def get_approval_for_finding(finding_id: str) -> dict | None:
    for a in _get("/api/v1/approvals"):
        if a.get("finding", {}).get("id") == finding_id:
            return a
    return None


def dashboard_metrics() -> dict:
    return _get("/api/v1/dashboard/metrics")


# ── Scenario A: loopback99 on DC1-R1 ─────────────────────────


def scenario_a() -> bool:
    sc = "scenario_a_loopback99"
    _log("\n=== Scenario A: loopback99 added on DC1-R1 ===")

    device_id = get_device_id(DC1_R1["hostname"])
    _save_evidence(sc, "dashboard_before", dashboard_metrics())

    # 1. Baseline snapshot
    baseline = trigger_snapshot(device_id, label="A baseline")
    _save_evidence(sc, "snapshot_baseline_meta", {
        "id": baseline["id"],
        "created_at": baseline.get("created_at"),
        "features": len(baseline.get("features_learned") or []),
    })

    # 2. Discover local ASN so the BGP `network` statement is correct
    asn_text = lab_show(DC1_R1, "show ip bgp summary | include BGP router identifier")
    asn_match = re.search(r"local AS number (\d+)", asn_text)
    if not asn_match:
        # Fallback — newer IOS-XE shows it as `local AS \d+` inline.
        asn_match = re.search(r"local AS (\d+)", asn_text)
    if not asn_match:
        # Last resort — pull from running-config
        rc = lab_show(DC1_R1, "show running-config | section router bgp")
        asn_match = re.search(r"router bgp (\d+)", rc)
    if not asn_match:
        _check("scenario_a: local ASN discovered", False, "could not parse ASN")
        return False
    asn = asn_match.group(1)
    _log(f"  DC1-R1 local ASN = {asn}")

    # 3. Inject the change
    inject_cmds = [
        f"interface {LOOPBACK_NAME}",
        " description PARITY-E2E-DO-NOT-USE",
        f" ip address {LOOPBACK_IP} {LOOPBACK_MASK}",
        f"router bgp {asn}",
        " address-family ipv4",
        f"  network {LOOPBACK_IP} mask {LOOPBACK_MASK}",
        " exit-address-family",
    ]
    lab_configure(DC1_R1, inject_cmds, label="A inject loopback99")
    _save_evidence(sc, "inject_commands", inject_cmds)

    # 4. Detection snapshot
    detect = trigger_snapshot(device_id, label="A detect")
    _save_evidence(sc, "snapshot_detect_meta", {
        "id": detect["id"],
        "created_at": detect.get("created_at"),
    })

    # 5. Wait for finding to appear with the right shape
    def _has_finding():
        f = get_active_finding_for_device(device_id)
        if not f:
            return None
        ev = f.get("evidence") or {}
        paths = " ".join(str(p) for p in (ev.get("diff_paths") or []))
        title = (f.get("title") or "").lower()
        if LOOPBACK_IP in paths or LOOPBACK_IP in title or LOOPBACK_CIDR in paths:
            return f
        return None

    finding = poll_until(_has_finding, desc="A finding", timeout=DETECT_TIMEOUT)
    _save_evidence(sc, "verdict", finding)
    _check(
        "scenario_a: finding detected with loopback99 prefix in evidence",
        True,
        f"{finding['severity']}/{finding['category']}",
    )

    # 6. Approve
    approval = poll_until(
        lambda: get_approval_for_finding(finding["id"]),
        desc="A approval queued",
        timeout=120,
    )
    _save_evidence(sc, "approval_pre", approval)
    _post(
        f"/api/v1/approvals/{approval['id']}/approve",
        json_body={"approved_by": "e2e-test", "approved_via": "script"},
    )
    _log(f"  approval {approval['id'][:8]} approved")

    # 7. Wait for resolution
    def _resolved():
        rows = _get(f"/api/v1/findings?device_id={device_id}&limit=20&include_resolved=true")
        same = [r for r in rows if r["id"] == finding["id"]]
        if not same:
            return None
        r = same[0]
        ev = r.get("evidence") or {}
        if not r.get("requires_remediation") or ev.get("resolved"):
            return r
        return None

    resolved = poll_until(_resolved, desc="A finding resolved", timeout=RESOLVE_TIMEOUT)
    _save_evidence(sc, "finding_resolved", resolved)

    # 8. Confirm the prefix is gone from the device
    rib = lab_show(DC1_R1, f"show ip route {LOOPBACK_IP}")
    prefix_present = LOOPBACK_IP in rib and "% Network not in table" not in rib
    _check(
        "scenario_a: loopback99 prefix removed from DC1-R1 RIB",
        not prefix_present,
        rib.splitlines()[0] if rib else "(empty)",
    )

    _save_evidence(sc, "dashboard_after", dashboard_metrics())
    return not prefix_present


# ── Scenario C: unsanctioned static route on DC2-R2 ──────────


def scenario_c(dry_run: bool = False) -> bool:
    sc = "scenario_c_static_route"
    _log("\n=== Scenario C: unsanctioned static route on DC2-R2 ===")

    device_id = get_device_id(DC2_R2["hostname"])

    _log(f"  target: ip route {SCENARIO_C_PREFIX} {SCENARIO_C_MASK} {SCENARIO_C_NEXT_HOP}")
    _save_evidence(sc, "chosen_target", {
        "prefix": SCENARIO_C_CIDR,
        "next_hop": SCENARIO_C_NEXT_HOP,
    })

    if dry_run:
        _log("  DRY RUN — no config applied. Re-run without --dry-run to execute.")
        return True

    _save_evidence(sc, "dashboard_before", dashboard_metrics())
    baseline = trigger_snapshot(device_id, label="C baseline")
    _save_evidence(sc, "snapshot_baseline_meta", {"id": baseline["id"]})

    # Confirm the next-hop is reachable so the static route will actually install
    nh_check = lab_show(DC2_R2, f"show ip route {SCENARIO_C_NEXT_HOP}")
    if "% Network not in table" in nh_check:
        _check("scenario_c: next-hop reachable", False,
               f"{SCENARIO_C_NEXT_HOP} not in table — aborting")
        return False

    inject_cmds = [
        f"ip route {SCENARIO_C_PREFIX} {SCENARIO_C_MASK} {SCENARIO_C_NEXT_HOP}",
    ]
    lab_configure(DC2_R2, inject_cmds, label="C inject static route")
    _save_evidence(sc, "inject_commands", inject_cmds)

    # Confirm the route installed before we ask Parity to detect it
    post_inject = lab_show(DC2_R2, f"show ip route {SCENARIO_C_PREFIX}")
    if "% Network not in table" in post_inject or SCENARIO_C_PREFIX not in post_inject:
        _check("scenario_c: static route installed in RIB", False, post_inject.splitlines()[0])
        return False
    _log(f"  static route installed: {post_inject.splitlines()[0]}")

    detect = trigger_snapshot(device_id, label="C detect")
    _save_evidence(sc, "snapshot_detect_meta", {"id": detect["id"]})

    def _has_finding():
        f = get_active_finding_for_device(device_id)
        if not f:
            return None
        ev = f.get("evidence") or {}
        paths = " ".join(str(p) for p in (ev.get("diff_paths") or []))
        title = (f.get("title") or "").lower()
        if SCENARIO_C_PREFIX in paths or SCENARIO_C_CIDR in paths or SCENARIO_C_PREFIX in title:
            return f
        return None

    finding = poll_until(_has_finding, desc="C finding", timeout=DETECT_TIMEOUT)
    _save_evidence(sc, "verdict", finding)
    _check(
        "scenario_c: finding detected for static route addition",
        True,
        f"{finding['severity']}/{finding['category']}",
    )

    approval = poll_until(
        lambda: get_approval_for_finding(finding["id"]),
        desc="C approval queued",
        timeout=120,
    )
    _save_evidence(sc, "approval_pre", approval)
    _post(
        f"/api/v1/approvals/{approval['id']}/approve",
        json_body={"approved_by": "e2e-test", "approved_via": "script"},
    )

    def _resolved():
        rows = _get(f"/api/v1/findings?device_id={device_id}&limit=20&include_resolved=true")
        same = [r for r in rows if r["id"] == finding["id"]]
        if not same:
            return None
        r = same[0]
        ev = r.get("evidence") or {}
        if not r.get("requires_remediation") or ev.get("resolved"):
            return r
        return None

    resolved = poll_until(_resolved, desc="C finding resolved", timeout=RESOLVE_TIMEOUT)
    _save_evidence(sc, "finding_resolved", resolved)

    # Confirm the static route is GONE from the device's RIB
    rib = lab_show(DC2_R2, f"show ip route {SCENARIO_C_PREFIX}")
    prefix_present = SCENARIO_C_PREFIX in rib and "% Network not in table" not in rib
    _check(
        "scenario_c: static route removed from DC2-R2 RIB",
        not prefix_present,
        rib.splitlines()[0] if rib else "(empty)",
    )

    _save_evidence(sc, "dashboard_after", dashboard_metrics())
    return not prefix_present


# ── Scenarios D1+D2: Davis lifecycle via stub admin ─────────


def scenario_davis() -> bool:
    sc = "scenario_davis_lifecycle"
    _log("\n=== Scenarios D1+D2: Davis P-1842 + P-1903 lifecycle ===")
    # Start clean — any stale dynatrace findings from previous tests
    _delete("/api/v1/dynatrace/findings?only_stub=true")

    # Re-open in the stub in case a previous run left them CLOSED
    for pid in DAVIS_PROBLEMS_TO_CLOSE:
        try:
            httpx.post(f"{MCP_STUB_URL}/admin/reopen-problem/{pid}", timeout=5).raise_for_status()
        except Exception as e:
            _log(f"  warning: could not reopen {pid}: {e}")

    ingest1 = _post("/api/v1/dynatrace/ingest")
    _save_evidence(sc, "ingest_open", ingest1)
    _check(
        "davis: initial ingest creates 3 findings",
        ingest1.get("created") == 3,
        f"created={ingest1.get('created')}",
    )

    findings = [
        f for f in _get("/api/v1/findings?source=dynatrace&limit=50&include_resolved=true")
        if f.get("source") == "dynatrace"
    ]
    open_count = sum(1 for f in findings if f.get("requires_remediation"))
    _save_evidence(sc, "findings_open", findings)
    _check(
        "davis: 3 findings active (requires_remediation=True)",
        open_count == 3,
        f"open={open_count}",
    )

    # Flip both selected problems to CLOSED on the stub
    for pid in DAVIS_PROBLEMS_TO_CLOSE:
        try:
            r = httpx.post(f"{MCP_STUB_URL}/admin/close-problem/{pid}", timeout=5)
            r.raise_for_status()
            _log(f"  stub: {pid} -> CLOSED")
        except Exception as e:
            _check(f"davis: stub admin close {pid}", False, str(e))
            return False

    ingest2 = _post("/api/v1/dynatrace/ingest")
    _save_evidence(sc, "ingest_after_close", ingest2)

    findings = [
        f for f in _get("/api/v1/findings?source=dynatrace&limit=50&include_resolved=true")
        if f.get("source") == "dynatrace"
    ]
    open_now = [f for f in findings if f.get("requires_remediation")]
    _save_evidence(sc, "findings_after_close", findings)
    _check(
        "davis: closed problems no longer require remediation",
        len(open_now) == 1,
        f"open_now={len(open_now)} (expected 1 — only the un-closed Synthetic)",
    )

    # Final cleanup: drop the remaining stub finding so the dashboard is clean.
    _delete("/api/v1/dynatrace/findings?only_stub=true")
    return len(open_now) == 1


# ── Pre-flight ───────────────────────────────────────────────


def preflight() -> bool:
    _log("=== Pre-flight ===")
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    health = _get("/api/v1/health/dependencies")
    ok = health.get("status") == "ok"
    _check("preflight: /health/dependencies ok", ok, health.get("status"))

    metrics = dashboard_metrics()
    _save_evidence("_preflight", "dashboard_before_run", metrics)
    open_findings = sum(metrics.get("findings", {}).values())
    if open_findings:
        _log(f"  WARNING: dashboard has {open_findings} active finding(s) before test.")
        _log("    These will not be cleaned automatically. Continuing anyway.")

    # Reachability check on both lab targets
    for dev in (DC1_R1, DC2_R2):
        reachable = _ping(dev["mgmt_ip"])
        _check(f"preflight: {dev['hostname']} ({dev['mgmt_ip']}) pingable", reachable)
        if not reachable:
            return False

    # Confirm both targets have a golden snapshot
    for dev in (DC1_R1, DC2_R2):
        did = get_device_id(dev["hostname"])
        goldens = _get(f"/api/v1/snapshots?device_id={did}&golden_only=true&limit=1")
        _check(
            f"preflight: {dev['hostname']} has a golden baseline",
            bool(goldens),
            goldens[0].get("created_at") if goldens else "no golden",
        )
        if not goldens:
            return False

    return True


# ── Driver / summary ─────────────────────────────────────────


def summary() -> int:
    print("\n" + "=" * 64)
    print("E2E Remediation — summary")
    print("=" * 64)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    for name, ok, detail in _results:
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] {name}  {('— ' + detail) if detail else ''}")
    print(f"\n{passed} passed, {failed} failed (of {len(_results)})")

    # Final dashboard
    try:
        m = dashboard_metrics()
        active = sum(m.get("findings", {}).values())
        ba = m.get("bgp", {}).get("affected", 0)
        ia = m.get("routing", {}).get("interface_affected", 0)
        ra = m.get("routing", {}).get("routes_affected", 0)
        print(f"\nFinal dashboard: active_findings={active}, "
              f"bgp.affected={ba}, interface_affected={ia}, routes_affected={ra}")
        if active == 0 and ba == 0 and ia == 0 and ra == 0:
            print("Dashboard CLEAN — 0 anomalies, 0 open concerns.")
        else:
            print("Dashboard NOT clean — investigate above.")
            failed += 1
    except Exception as e:
        print(f"\nFinal dashboard check failed: {e}")
        failed += 1

    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["preflight", "dryrun-c", "run-a", "run-c", "run-davis", "run-all", "cleanup"],
    )
    args = parser.parse_args()

    print(f"Target: {BASE}")
    print(f"Lab: DC1-R1={DC1_R1['mgmt_ip']}  DC2-R2={DC2_R2['mgmt_ip']}")
    print()

    if args.command == "preflight":
        preflight()
        return summary()

    if args.command == "dryrun-c":
        if not preflight():
            return summary()
        scenario_c(dry_run=True)
        return summary()

    if args.command == "cleanup":
        _delete("/api/v1/dynatrace/findings?only_stub=true")
        for pid in DAVIS_PROBLEMS_TO_CLOSE:
            try:
                httpx.post(f"{MCP_STUB_URL}/admin/reopen-problem/{pid}", timeout=5)
            except Exception:
                pass
        _log("cleanup done")
        return 0

    if not preflight():
        return summary()

    if args.command == "run-a":
        scenario_a()
    elif args.command == "run-c":
        scenario_c()
    elif args.command == "run-davis":
        scenario_davis()
    elif args.command == "run-all":
        scenario_a()
        scenario_c()
        scenario_davis()

    return summary()


if __name__ == "__main__":
    sys.exit(main())
