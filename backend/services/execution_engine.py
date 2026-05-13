"""Execution engine — send approved remediation commands to devices.

Only executes commands from APPROVED recommendations. Captures output,
updates approval status, and triggers a verification snapshot.
"""

import asyncio
import time

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.tables import Approval, Device, Finding, Recommendation, Snapshot
from services import approval_service
from services.activity import activity_bus

log = structlog.get_logger()


async def execute_approved(db: AsyncSession, approval_id: str) -> dict:
    """Execute the commands for an approved recommendation.

    Returns execution result dict with command outputs.
    """
    approval = await approval_service.get_approval(db, approval_id)
    if not approval or approval.status != "approved":
        return {"error": "Approval not found or not in approved state"}

    # Load recommendation
    rec_result = await db.execute(
        select(Recommendation).where(Recommendation.id == approval.recommendation_id)
    )
    rec = rec_result.scalar_one_or_none()
    if not rec:
        return {"error": "Recommendation not found"}

    # Load finding -> device
    finding_result = await db.execute(
        select(Finding).where(Finding.id == rec.finding_id)
    )
    finding = finding_result.scalar_one_or_none()
    if not finding:
        # Finding was dismissed/deleted between approval and execution.
        # Don't run commands for a problem the operator already cleared.
        await approval_service.mark_executed(
            db, approval_id,
            {"error": "Finding no longer exists (dismissed)", "skipped": True, "outputs": []},
            success=False,
        )
        return {"error": "Finding was dismissed before execution; skipping"}

    device_result = await db.execute(
        select(Device).where(Device.id == finding.device_id)
    )
    device = device_result.scalar_one_or_none()
    if not device:
        return {"error": "Device not found"}

    # Pre-flight sanity check: take a fresh single-device snapshot and
    # verify the finding's symptom still applies. Avoids running stale
    # config changes on devices that have already self-recovered or had
    # their issue manually fixed in the time between approval and execute.
    try:
        from services.snapshot_engine import take_snapshot
        fresh = await take_snapshot(db, device_id=device.id, triggered_by="pre-exec-check")
        still_present = _symptom_still_present(finding, fresh[0].snapshot_data if fresh else {})
        if not still_present:
            log.info("execution_skipped_symptom_resolved",
                     approval_id=approval_id, finding_id=finding.id, hostname=device.hostname)
            await approval_service.mark_executed(
                db, approval_id,
                {
                    "skipped": True,
                    "reason": "Pre-flight check: symptom no longer present on device",
                    "hostname": device.hostname,
                    "outputs": [],
                    "success": True,
                },
                success=True,
            )
            return {"skipped": True, "reason": "Symptom resolved before execution"}
    except Exception as exc:
        # If pre-flight fails, log but don't block — the operator approved,
        # and a flaky pre-flight shouldn't be a hard gate.
        log.warning("pre_exec_check_failed", error=str(exc), approval_id=approval_id)

    # Extract commands
    commands = rec.commands
    if not commands:
        return {"error": "No commands to execute"}

    # Flatten if commands are dicts (from JSON)
    if isinstance(commands[0], dict):
        commands = [c.get("command", str(c)) for c in commands]

    log.info(
        "execution_start",
        approval_id=approval_id,
        hostname=device.hostname,
        command_count=len(commands),
    )

    act_id = activity_bus.start(
        pipeline_run=f"exec:{approval_id}",
        node="execution",
        model="pyats",
        device=device.hostname,
        detail=f"Executing {len(commands)} commands on {device.hostname}",
    )

    # Execute via pyATS/Netmiko (blocking — run in thread)
    import asyncio
    result = await asyncio.to_thread(_send_commands_sync, device, commands)

    # Update approval record
    success = not result.get("error")
    duration = result.get("duration_seconds", 0)
    if success:
        activity_bus.complete(act_id, detail=f"Executed {len(commands)} commands on {device.hostname} in {duration}s")
    else:
        activity_bus.fail(act_id, f"Execution failed on {device.hostname}: {result.get('error', 'unknown')}")

    await approval_service.mark_executed(db, approval_id, result, success=success)

    # Update Jira ticket
    if approval.jira_issue_key:
        from integrations.jira import jira_client

        status = "executed" if success else "failed"
        duration = result.get("duration_seconds", 0)
        cmd_count = len(result.get("outputs", []))
        ok_count = sum(1 for o in result.get("outputs", []) if o.get("success"))

        comment_parts = [
            f"h3. Execution {'Succeeded' if success else 'FAILED'}",
            f"*Device:* {device.hostname}",
            f"*Duration:* {duration}s",
            f"*Commands:* {ok_count}/{cmd_count} succeeded",
        ]
        if rec.agent_model:
            comment_parts.append(f"*Remediation Model:* {rec.agent_model}")
        if rec.reasoning:
            comment_parts.append(f"\n*AI Reasoning:*\n{rec.reasoning}")
        comment_parts.append(
            f"\n*Command Outputs:*\n{{code}}\n{_format_outputs(result)}\n{{code}}"
        )
        if rec.rollback_commands:
            rb_list = rec.rollback_commands
            if isinstance(rb_list[0], str):
                rb_text = "\n".join(f"  {c}" for c in rb_list)
            else:
                rb_text = str(rb_list)
            comment_parts.append(
                f"\n*Rollback Commands (if needed):*\n{{code}}\n{rb_text}\n{{code}}"
            )

        comment = "\n".join(comment_parts)
        await jira_client.transition_issue(approval.jira_issue_key, status, comment)

    # Notify Slack
    from integrations.slack import slack_client

    await slack_client.notify_approval_update(
        approval, "executed" if success else "failed"
    )

    # Three-phase verification:
    #   1. Immediately re-snapshot the FIXED device — confirms the fix
    #      took on the device we actually touched.
    #   2. Wait CONVERGENCE_DELAY (BGP/routing needs time to propagate)
    #      then snapshot every OTHER device that had a finding in the
    #      incident. Without this delay, the verification snapshot can
    #      outrun BGP and capture a still-broken downstream state — the
    #      finding stays "active" even though the network has recovered.
    #   3. If any findings on incident devices are still flagged active,
    #      sleep again and re-snapshot ONLY those devices. One retry
    #      catches the slow-convergers (S4-S1, the far end of the fabric).
    CONVERGENCE_DELAY = 30  # seconds — typical BGP keepalive + reconvergence
    RETRY_DELAY = 30        # seconds — for stragglers after the first pass
    if success:
        verify_device_ids: set[str] = {device.id}
        if finding.incident_id:
            inc_result = await db.execute(
                select(Finding.device_id).where(Finding.incident_id == finding.incident_id)
            )
            verify_device_ids.update(row[0] for row in inc_result.all())

        verify_devices_q = await db.execute(
            select(Device).where(Device.id.in_(verify_device_ids))
        )
        all_verify = list(verify_devices_q.scalars().all())
        fixed_device = next((d for d in all_verify if d.id == device.id), None)
        downstream = [d for d in all_verify if d.id != device.id]

        snap_act_id = activity_bus.start(
            pipeline_run=f"verify:{approval_id}",
            node="verification",
            model="pyats",
            device=device.hostname,
            detail=f"3-phase verify of {len(all_verify)} device(s) — fixed device first, then downstream after {CONVERGENCE_DELAY}s wait",
        )
        try:
            from agents.graph import run_pipeline
            from services.snapshot_engine import get_snapshot_diff, take_snapshot

            async def _verify_one(vdev: Device, phase: str) -> None:
                log.info("verification_snapshot_start", hostname=vdev.hostname, phase=phase)
                new_snaps = await take_snapshot(
                    db, device_id=vdev.id, triggered_by=f"post-execution-{phase}"
                )
                for snap in new_snaps:
                    try:
                        diff_result = await get_snapshot_diff(db, snap.id)
                        snapshot_diff = diff_result.get("changes", {})
                        await run_pipeline(
                            db=db,
                            snapshot_id=snap.id,
                            device_id=vdev.id,
                            device_hostname=vdev.hostname,
                            device_platform=vdev.platform,
                            raw_snapshot=snap.snapshot_data,
                            snapshot_diff=snapshot_diff,
                            create_approvals=False,
                            defer_remediation=True,
                        )
                    except Exception as pipe_err:
                        log.error(
                            "verification_pipeline_failed",
                            hostname=vdev.hostname, error=str(pipe_err),
                        )

            # Phase 1: re-snapshot the fixed device immediately
            if fixed_device:
                await _verify_one(fixed_device, phase="fixed-device")

            # Phase 2: let routing/BGP converge, then sample downstream
            if downstream:
                log.info("verification_convergence_wait", seconds=CONVERGENCE_DELAY)
                await asyncio.sleep(CONVERGENCE_DELAY)
                for vdev in downstream:
                    await _verify_one(vdev, phase="downstream")

            # Phase 3: any incident finding still pinned to the latest
            # snapshot is a real residual symptom. Retry once after
            # another short wait — almost always resolves slow-convergers.
            from sqlalchemy import select as sa_select
            if finding.incident_id:
                # Build per-device latest snapshot_id map
                latest_sq = (
                    sa_select(Snapshot.device_id, func.max(Snapshot.created_at).label("max_ts"))
                    .where(func.array_length(Snapshot.features_learned, 1) > 0)
                    .group_by(Snapshot.device_id)
                    .subquery()
                )
                latest_q = await db.execute(
                    sa_select(Snapshot.id, Snapshot.device_id)
                    .join(
                        latest_sq,
                        (Snapshot.device_id == latest_sq.c.device_id)
                        & (Snapshot.created_at == latest_sq.c.max_ts),
                    )
                )
                latest_per_dev = {row[1]: row[0] for row in latest_q.all()}

                still_q = await db.execute(
                    sa_select(Finding.device_id)
                    .where(Finding.incident_id == finding.incident_id)
                )
                stragglers = []
                for row in still_q.all():
                    dev_id = row[0]
                    # We only need to retry devices whose latest snapshot
                    # *also* has an active finding for this incident
                    f_check = await db.execute(
                        sa_select(Finding)
                        .where(Finding.incident_id == finding.incident_id)
                        .where(Finding.device_id == dev_id)
                    )
                    for f in f_check.scalars().all():
                        if latest_per_dev.get(dev_id) == f.snapshot_id:
                            stragglers.append(dev_id)
                            break

                straggler_devs_q = await db.execute(
                    sa_select(Device).where(Device.id.in_(set(stragglers)))
                )
                straggler_devs = list(straggler_devs_q.scalars().all())
                # Don't re-verify the device we just remediated — it's
                # been sampled twice already.
                straggler_devs = [d for d in straggler_devs if d.id != device.id]

                if straggler_devs:
                    log.info(
                        "verification_retry_wait",
                        stragglers=[d.hostname for d in straggler_devs],
                        seconds=RETRY_DELAY,
                    )
                    await asyncio.sleep(RETRY_DELAY)
                    for vdev in straggler_devs:
                        await _verify_one(vdev, phase="retry")

            activity_bus.complete(
                snap_act_id,
                detail=f"Verified {len(all_verify)} device(s) over 3 phases",
            )
        except Exception as e:
            log.warning("verification_snapshot_failed", error=str(e))
            activity_bus.fail(snap_act_id, f"Verification snapshot failed: {e}")

    return result


_MODE_BOUNDARIES = {
    "configure terminal", "config terminal", "config t", "conf t",
    "end", "exit",
}


def _symptom_still_present(finding: Finding, snapshot_data: dict) -> bool:
    """Verify the finding's symptom still exists in the fresh snapshot.

    Only checks the most common, high-confidence symptom types. For symptom
    types we can't reliably re-check (e.g. abstract policy issues), we
    return True (i.e. assume it's still relevant — don't block).
    """
    if not snapshot_data or not isinstance(snapshot_data, dict):
        return True

    title = (finding.title or "").lower()
    affected = (finding.affected_entity or "").lower()

    # Interface admin-down / oper-down — confirm the named interface is
    # still actually down. If admin re-enabled, no need to re-enable again.
    if finding.category == "interface" or "interface" in title:
        intf_name = None
        for token in (finding.affected_entity or "").split():
            if any(token.lower().startswith(p) for p in (
                "ethernet", "gigabitethernet", "tengigabitethernet",
                "fastethernet", "loopback", "tunnel", "vlan", "port-channel",
            )):
                intf_name = token
                break
        if intf_name:
            intf = snapshot_data.get("interface", {}).get(intf_name)
            if isinstance(intf, dict):
                # Symptom = down/admin-down. Resolved if oper_status=up AND enabled=true.
                if intf.get("oper_status") == "up" and intf.get("enabled") is True:
                    return False
        return True

    # BGP neighbour in non-Established state — verify it's still not
    # Established. If it's recovered, no need to fix.
    if finding.category == "routing" and "bgp" in title and "neighbor" in title:
        peer_ip = None
        for token in affected.split():
            if token.count(".") == 3:
                peer_ip = token
                break
        if peer_ip:
            bgp = snapshot_data.get("bgp", {})
            for inst in (bgp.get("instance", {}) if isinstance(bgp, dict) else {}).values():
                if not isinstance(inst, dict):
                    continue
                for vrf in inst.get("vrf", {}).values():
                    if not isinstance(vrf, dict):
                        continue
                    nbr = vrf.get("neighbor", {}).get(peer_ip)
                    if isinstance(nbr, dict) and nbr.get("session_state") == "Established":
                        return False
        return True

    return True  # Default: don't block


def _classify_commands(commands: list[str]) -> tuple[list[str], list[str]]:
    """Split a flat command list into (exec_commands, config_commands).

    Strips mode-boundary tokens (configure terminal / end / exit). pyATS
    handles mode transitions itself via execute() vs configure().

    Heuristic: anything inside a 'configure terminal' ... 'end' block is
    config; anything outside is exec. Commands starting with 'show', 'ping',
    'traceroute', 'clear' are always exec even if appearing inside a block.
    """
    exec_cmds: list[str] = []
    cfg_cmds: list[str] = []
    in_config = False

    for raw in commands:
        cmd = raw.strip()
        low = cmd.lower()
        if low in _MODE_BOUNDARIES:
            if low.startswith("conf"):
                in_config = True
            elif low in {"end", "exit"} and in_config:
                in_config = False
            continue
        # Show/diagnostic commands are exec regardless of mode
        first = low.split()[0] if low else ""
        if first in {"show", "ping", "traceroute", "clear", "reload", "write"}:
            exec_cmds.append(cmd)
        elif in_config:
            cfg_cmds.append(cmd)
        else:
            exec_cmds.append(cmd)

    return exec_cmds, cfg_cmds


def _send_commands_sync(device, commands: list[str]) -> dict:
    """Connect to a device and send commands (blocking — run via asyncio.to_thread).

    Splits commands into exec vs config groups; uses tb_device.execute() for
    exec commands and tb_device.configure() for config commands. The latter
    handles 'configure terminal' / 'end' transitions internally — feeding it
    those tokens (or running config commands through execute()) puts the
    session into the wrong state and every subsequent command fails.
    """
    from services.testbed_generator import generate_testbed

    outputs: list[dict] = []
    start = time.time()

    exec_cmds, cfg_cmds = _classify_commands(commands)

    try:
        from genie.testbed import load as load_testbed

        testbed_dict = generate_testbed([device])
        testbed = load_testbed(testbed_dict)
        tb_device = testbed.devices.get(device.hostname)

        if not tb_device:
            return {"error": f"Device {device.hostname} not in testbed"}

        tb_device.connect(
            learn_hostname=True,
            log_stdout=False,
            connection_timeout=settings.pyats_connect_timeout,
        )

        # Run exec commands first (e.g. 'show' diagnostics), then config block.
        for cmd in exec_cmds:
            try:
                output = tb_device.execute(cmd, timeout=settings.pyats_command_timeout)
                outputs.append({"command": cmd, "output": output, "success": True})
            except Exception as e:
                outputs.append({"command": cmd, "output": str(e), "success": False})
                # Don't bail on a failed show — but DO bail before changing config
                if cmd.lower().split()[0] not in {"show", "ping", "traceroute"}:
                    break

        # Apply config commands as one transactional block — pyATS handles
        # 'configure terminal' / 'end' / commit semantics itself.
        if cfg_cmds and (not outputs or all(o["success"] for o in outputs)):
            try:
                output = tb_device.configure(cfg_cmds, timeout=settings.pyats_command_timeout)
                outputs.append({
                    "command": "configure { " + "; ".join(cfg_cmds) + " }",
                    "output": output if isinstance(output, str) else str(output),
                    "success": True,
                })
            except Exception as e:
                outputs.append({
                    "command": "configure { " + "; ".join(cfg_cmds) + " }",
                    "output": str(e),
                    "success": False,
                })

        try:
            tb_device.disconnect()
        except Exception:
            pass

    except ImportError:
        for cmd in commands:
            outputs.append(
                {"command": cmd, "output": "[DRY RUN] pyATS not installed", "success": True}
            )

    duration = round(time.time() - start, 2)
    all_success = bool(outputs) and all(o["success"] for o in outputs)

    return {
        "hostname": device.hostname,
        "outputs": outputs,
        "duration_seconds": duration,
        "success": all_success,
        **({"error": "One or more commands failed"} if not all_success else {}),
    }


def _format_outputs(result: dict) -> str:
    """Format execution outputs for display in Jira/Slack."""
    lines = []
    for o in result.get("outputs", []):
        status = "OK" if o.get("success") else "FAIL"
        lines.append(f"[{status}] {o.get('command', '?')}")
        if o.get("output"):
            lines.append(f"  {o['output'][:200]}")
    return "\n".join(lines) or "No output"
