# Parity — Functional Test Plan

End-to-end validation of the day-2 NetOps loop against the **live homelab** at 192.168.20.0/24. The unit / API plan in [TEST_PLAN.md](TEST_PLAN.md) covers individual endpoints; this plan covers the *workflow* — change → detect → reason → approve → act → verify → resolve — with real device interaction.

**Lab credentials:** `steven` / `Extr748a`. Management interfaces (the SSH-source IP) are out of bounds — touching them disconnects pyATS mid-test.

## Scope

| Phase | Validates | Engine component |
|---|---|---|
| 0. Reset | Clean baseline, no stale findings/snapshots | DB |
| 1. Baseline snapshot | pyATS reaches every reachable device | snapshot_engine |
| 2. Subtle change | A change that traditional thresholds won't catch (no link flap, no neighbour reset) | manual via SSH |
| 3. Detect (A) | pyATS captures the diff on the source AND every device it propagates to | snapshot_engine + get_snapshot_diff |
| 4. Reason (B) | Reasoner classifies each diff; correlation engine recognises they share a root cause → ONE incident, not N | dynatrace_reasoner + correlation |
| 5. Ticket (C) | One Jira ticket per incident, with forensic comments tagged with the engine that wrote them | integrations/jira |
| 6. Insight (D) | Recommendation has *remediation* commands (not just show commands) and a paired rollback | reasoner-2 (Gemini Pro) |
| 7. Act (E) | Approval flow → pyATS pushes the commands → Jira gets workflow comments at every stage | approval_service + execution_engine |
| 8. Verify (F) | Post-fix snapshot + diff + reason → finding marked *resolved*, dashboard tile counts return to baseline, no anomaly "stickiness" | reasoner + finding lifecycle |
| 9. Chatbot | Twelve tools answer 20+ representative questions correctly via the UI chat panel | ADK chat agent |

## Subtle change protocol

A change should:
- Not flap any interface (no `shutdown` / `no shutdown`).
- Not touch the device's management IP.
- Propagate across the routing fabric (BGP / OSPF redistribution).
- Be invisible to a counter-threshold alert (no error rate spike, no neighbour state transition).

**Default change:** add a loopback with a /32 IP that doesn't collide with anything; ensure `redistribute connected` is in scope for whichever IGP/EGP carries the LAN. The new /32 then appears in every BGP/OSPF peer's RIB — a propagating, structural change with no symptom on any link.

```
configure terminal
 interface Loopback99
  description PARITY-TEST-DO-NOT-USE
  ip address 192.0.2.99 255.255.255.255
 router bgp <AS>
  address-family ipv4
   network 192.0.2.99 mask 255.255.255.255
 end
write memory
```

(Or, depending on the device's current redistribution policy, the loopback alone may be enough.)

## Pass criteria per phase

### Phase 3 — Detection (Test A)
- ≥ 2 devices have a new snapshot in the last 5 minutes.
- `get_snapshot_diff` for those snapshots returns a non-empty `changes` dict with at least one path containing the new prefix (`192.0.2.99` or its variant).
- The diff is captured even though no interface, no BGP/OSPF neighbour state, and no counter has changed materially.

### Phase 4 — Reasoning + correlation (Test B)
- Per-device: each affected snapshot produces exactly one Finding (no duplicates).
- Cross-device: a single Incident groups every Finding that shares the same evidence prefix.
- Dashboard "Anomalies" tile shows **1** (incident), not N (per-device findings) — that's the noise-suppression test.
- If `apply_correlation` is missing or broken, **build it** before re-running this phase.

### Phase 5 — Jira (Test C)
- One Jira issue created in the configured project.
- Initial comment from `parity-detect-engine` with the diff evidence.
- The issue stays referenced (not closed) until verification confirms the fix.

### Phase 6 — Insight quality (Test D)
- Recommendation `commands[]` contains config-mode commands that, when applied, would revert the change.
- `rollback_commands[]` contains commands that re-apply the original change (so we can undo if the fix breaks something).
- `risk_level` is set; reasoning explains *why* the proposed commands fix the symptom.
- If the reasoner emits only `recommended_actions` (diagnostic shows), **build a Gemini-Pro remediation drafter** before re-running.

### Phase 7 — Approval + execute (Test E)
- Playwright drives the Approvals page: pending approval appears for the new incident; clicking *Approve* triggers execution.
- Backend logs `execution_started`, `execution_complete`, with the actual commands pushed.
- Jira gets a comment from `parity-executor` listing every command sent and the device response.
- A second Jira comment from `parity-verifier` after the verification snapshot.

### Phase 8 — Resolution (Test F)
- A new snapshot of the affected device(s) runs automatically after execution.
- The new diff no longer contains the offending prefix.
- The reasoner produces verdict `category=no-change` (or equivalent).
- The Finding row's `requires_remediation` flips to `False`; the Incident is closed.
- Dashboard "Anomalies" tile drops by the correlated count — back to baseline.
- Jira issue receives a *Resolved* comment from `parity-verifier`; transition to Done if the integration supports it.

### Phase 9 — Chatbot battery
At least 20 questions, covering every tool. The chat panel must answer correctly (right tool call + a coherent response) for **all** of them.

Representative questions (will be expanded into the test script):
1. "List every device."
2. "What's the platform of DC1-R1?"
3. "Show me the latest snapshot for S1-R1."
4. "List all active findings."
5. "Are there any critical issues right now?"
6. "Pick the most recent incident and tell me what it's about."
7. "Find detail on finding `<short-id>`."
8. "List approvals waiting on a human."
9. "Show me the last 5 things that executed."
10. "What does the topology look like?"
11. "Give me the dashboard headline numbers."
12. "Have we seen a BGP issue like this before?" (semantic search)
13. "Trigger a snapshot of S1-R1 right now."
14. "Run `show ip bgp summary` on DC1-R1."
15. "What's the difference between an incident and a finding?"
16. "Why isn't this finding requiring remediation?"
17. "Walk me through the approval flow."
18. "Can you change device config?" (must say no)
19. "What just changed on S1-R1?" (analyze-snapshot via tool, once wired)
20. "If I approve this, what will happen?"

Each driven through the Playwright chat panel; assertion is on (a) at least one `tool_use` event of the *right* tool name and (b) a final text answer that contains expected substrings.

## Engine attribution in Jira comments

Every Jira comment includes a structured header so a human reading the timeline knows which engine wrote each entry:

```
[engine: parity-detect-engine | 2026-05-14T07:12:08Z | snapshot=abc1234]
<comment body>
```

Engines and what they log:
- `parity-detect-engine` — pyATS snapshot diff observed, prefix appeared
- `parity-reason-engine` — Davis (or Gemini-as-Davis) verdict + recommendation drafted
- `parity-approval-engine` — operator approved / denied (records who, via which channel)
- `parity-executor` — pyATS executed which commands, what each device returned
- `parity-verifier` — post-fix snapshot diff, reasoner verdict, *Resolved*

## Iteration protocol

1. Run the plan top to bottom.
2. The first run will fail at phases 4–8 because correlation, remediation drafting, resolution-detection, and forensic Jira logging are not yet wired.
3. For each failure: stop, build/fix the responsible piece, write a regression unit test, re-run from the failing phase.
4. Repeat until phases 0–9 are green AND the Playwright suite passes 100%.
5. Final run produces a clean, end-to-end audit trail: snapshot timestamps, finding ids, the single incident id, the Jira issue key, the approval id, the execution id, and the resolved-at timestamp — all from the dashboard tiles back to 0.
