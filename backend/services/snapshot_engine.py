"""pyATS snapshot engine — connect to devices, learn features, store results."""

import asyncio
import time
from datetime import datetime, timezone

import structlog
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.tables import Device, Snapshot
from services.activity import activity_bus
from services.testbed_generator import generate_testbed

log = structlog.get_logger()

# Features to learn per device type.
# spanning_tree only makes sense on switches — routers don't participate.
ROUTER_FEATURES = [
    "interface",
    "ospf",
    "bgp",
    "arp",
    "routing",
    "platform",
    "hsrp",
    "vrf",
]

SWITCH_FEATURES = [
    "interface",
    "ospf",
    "bgp",
    "arp",
    "vlan",
    "spanning_tree",
    "routing",
    "platform",
    "hsrp",
    "vrf",
]

# Fallback for unknown device types — same as router (no spanning_tree).
DEFAULT_FEATURES = ROUTER_FEATURES


def _features_for_device(device) -> list[str]:
    """Return the feature list appropriate for a device's type."""
    dtype = (device.device_type or "").lower()
    if dtype == "switch":
        return SWITCH_FEATURES
    return ROUTER_FEATURES


async def take_snapshot(
    db: AsyncSession,
    device_id: str | None = None,
    features: list[str] | None = None,
    triggered_by: str = "manual",
    on_progress=None,
) -> list[Snapshot]:
    """Take a pyATS snapshot of one or all devices.

    Runs synchronously on device connections (pyATS is blocking) but
    stores results via async SQLAlchemy.  Each device is handled
    independently so a single failure doesn't abort the run.
    """
    # Resolve target devices
    if device_id:
        result = await db.execute(select(Device).where(Device.id == device_id))
        devices = list(result.scalars().all())
    else:
        result = await db.execute(select(Device).order_by(Device.hostname))
        devices = list(result.scalars().all())

    if not devices:
        log.warning("snapshot_no_devices")
        return []

    testbed_dict = generate_testbed(devices)
    snapshots: list[Snapshot] = []

    # Import pyATS lazily — it's heavy and only needed here
    try:
        from genie.testbed import load as load_testbed
    except ImportError:
        log.error("pyats_not_installed")
        raise RuntimeError(
            "pyATS/Genie is not installed. Install with: pip install pyats[full]"
        )

    testbed = load_testbed(testbed_dict)

    # Build list of (device, tb_device) pairs, skipping missing testbed entries
    device_pairs = []
    for device in devices:
        tb_device = testbed.devices.get(device.hostname)
        if not tb_device:
            log.error("testbed_device_missing", hostname=device.hostname)
            continue
        device_pairs.append((device, tb_device))

    # Snapshot all devices in parallel (capped at 20 concurrent threads)
    sem = asyncio.Semaphore(20)
    done_count = 0
    lock = asyncio.Lock()

    async def _snap_one(device, tb_device):
        nonlocal done_count
        dev_features = features or _features_for_device(device)
        act_id = activity_bus.start(
            pipeline_run=f"snapshot:{triggered_by}",
            node="snapshot",
            model="pyats",
            device=device.hostname,
            detail=f"Connecting to {device.hostname} — learning {len(dev_features)} features",
        )
        async with sem:
            result = await asyncio.to_thread(
                _collect_device_snapshot, tb_device, device.hostname, dev_features
            )

        has_error = "error" in result["data"] and not result["features"]
        if has_error:
            activity_bus.fail(act_id, f"Snapshot failed for {device.hostname}: {result['data'].get('error', 'unknown')}")
        else:
            activity_bus.complete(
                act_id,
                detail=f"Snapshot of {device.hostname} complete — {len(result['features'])} features in {result['duration']}s",
            )

        snapshot = Snapshot(
            device_id=device.id,
            snapshot_data=result["data"],
            features_learned=result["features"],
            triggered_by=triggered_by,
            duration_seconds=result["duration"],
        )
        async with lock:
            db.add(snapshot)
            snapshots.append(snapshot)
            done_count += 1
            log.info(
                "snapshot_complete",
                hostname=device.hostname,
                features=len(result["features"]),
                duration=result["duration"],
            )
            if on_progress:
                await on_progress(done_count, len(device_pairs), device.hostname)

    await asyncio.gather(*[_snap_one(d, tb) for d, tb in device_pairs])

    await db.commit()
    # Refresh to get server-generated fields
    for s in snapshots:
        await db.refresh(s)

    log.info("snapshot_run_complete", total_devices=len(snapshots))
    return snapshots


def _collect_device_snapshot(
    tb_device, hostname: str, features: list[str]
) -> dict:
    """Blocking function that connects to a device and learns features.

    Runs in a separate thread via asyncio.to_thread so it doesn't block
    the event loop.
    """
    start = time.time()
    learned_data: dict = {}
    learned_features: list[str] = []

    try:
        log.info("device_connecting", hostname=hostname)
        tb_device.connect(
            learn_hostname=True,
            log_stdout=False,
            connection_timeout=settings.pyats_connect_timeout,
        )
    except Exception as e:
        log.error("device_connect_failed", hostname=hostname, error=str(e))
        return {
            "data": {"error": f"Connection failed: {e}"},
            "features": [],
            "duration": round(time.time() - start, 2),
        }

    for feature in features:
        try:
            log.info("device_learning", hostname=hostname, feature=feature)
            output = tb_device.learn(feature)
            if hasattr(output, "info"):
                learned_data[feature] = output.info
            else:
                learned_data[feature] = str(output)
            learned_features.append(feature)
        except Exception as e:
            log.warning(
                "feature_learn_failed",
                hostname=hostname,
                feature=feature,
                error=str(e),
            )
            learned_data[feature] = {"error": str(e)}

    try:
        tb_device.disconnect()
    except Exception:
        pass

    return {
        "data": learned_data,
        "features": learned_features,
        "duration": round(time.time() - start, 2),
    }


async def get_snapshot(db: AsyncSession, snapshot_id: str) -> Snapshot | None:
    result = await db.execute(select(Snapshot).where(Snapshot.id == snapshot_id))
    return result.scalar_one_or_none()


async def list_snapshots(
    db: AsyncSession, device_id: str | None = None, limit: int = 50, offset: int = 0
) -> list[Snapshot]:
    q = select(Snapshot).order_by(Snapshot.created_at.desc()).limit(limit).offset(offset)
    if device_id:
        q = q.where(Snapshot.device_id == device_id)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_snapshot_diff(db: AsyncSession, snapshot_id: str) -> dict:
    """Compute diff between a snapshot and the previous snapshot for the same device.

    Uses a simple recursive dict comparison.  For richer diffs consider
    pyATS Diff when running inside the pyATS container.
    """
    snapshot = await get_snapshot(db, snapshot_id)
    if not snapshot:
        return {"error": "Snapshot not found"}

    # Find the previous snapshot for the same device
    result = await db.execute(
        select(Snapshot)
        .where(Snapshot.device_id == snapshot.device_id)
        .where(Snapshot.created_at < snapshot.created_at)
        .order_by(Snapshot.created_at.desc())
        .limit(1)
    )
    previous = result.scalar_one_or_none()

    if not previous:
        return {
            "snapshot_id": snapshot.id,
            "previous_snapshot_id": None,
            "changes": {"note": "No previous snapshot to compare against"},
        }

    raw_changes = _diff_dicts(previous.snapshot_data, snapshot.snapshot_data)
    changes = _filter_noise(raw_changes)
    return {
        "snapshot_id": snapshot.id,
        "previous_snapshot_id": previous.id,
        "changes": changes,
    }


# Diff path fragments that are operational noise — counters, timers, keepalives.
# These change on every snapshot and never indicate a real problem.
_NOISE_KEYWORDS = {
    # Counters
    "in_octets", "out_octets", "in_pkts", "out_pkts", "in_unicast_pkts",
    "out_unicast_pkts", "in_broadcast_pkts", "out_broadcast_pkts",
    "in_multicast_pkts", "out_multicast_pkts", "in_discards", "out_discards",
    "in_unknown_protos", "last_clear", "rate", "in_rate", "out_rate",
    "in_rate_pkts", "out_rate_pkts", "counters",
    # Timers & keepalives
    "keepalive", "dead_timer", "hello_timer", "last_input", "last_output",
    "uptime", "up_time", "last_restart", "last_update", "last_read",
    "last_write", "elapsed_time", "holdtime", "keepalive_interval",
    "msg_rcvd", "msg_sent", "tbl_ver", "up_down",
    # Timestamps and ages
    "timestamp", "age", "last_change", "last_transition",
    # OSPF/routing metric churn
    "spf_count", "spf_last", "retransmit_count", "lsa_count",
    "checksum_sum",
}


def _is_noise(path: str) -> bool:
    """Return True if a diff path is operational noise that should be filtered."""
    parts = path.lower().split(".")
    leaf = parts[-1] if parts else ""
    # Direct match on leaf key
    if leaf in _NOISE_KEYWORDS:
        return True
    # Any segment matches a noise keyword
    for part in parts:
        if part in _NOISE_KEYWORDS:
            return True
    return False


def _filter_noise(changes: dict) -> dict:
    """Remove operational noise from a diff so only real state changes remain."""
    return {k: v for k, v in changes.items() if not _is_noise(k)}


def _diff_dicts(old: dict, new: dict, path: str = "") -> dict:
    """Recursively diff two dicts, returning added/removed/changed keys."""
    changes: dict = {}

    all_keys = set(old.keys()) | set(new.keys())
    for key in sorted(all_keys):
        current_path = f"{path}.{key}" if path else key

        if key not in old:
            changes[current_path] = {"status": "added", "value": new[key]}
        elif key not in new:
            changes[current_path] = {"status": "removed", "value": old[key]}
        elif old[key] != new[key]:
            if isinstance(old[key], dict) and isinstance(new[key], dict):
                nested = _diff_dicts(old[key], new[key], current_path)
                changes.update(nested)
            else:
                changes[current_path] = {
                    "status": "changed",
                    "old": old[key],
                    "new": new[key],
                }

    return changes
