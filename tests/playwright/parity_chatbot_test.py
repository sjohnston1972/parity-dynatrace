"""Chatbot question battery — exercises every tool in the ADK chat agent.

Drives the streaming /api/v1/chat endpoint directly (same code path the
React ChatPanel uses). For each question:
  * captures every SSE event,
  * asserts at least one tool_use event with an expected name,
  * asserts the final text contains expected substrings (case-insensitive).

Run inside the playwright-playwright container:
    docker run --rm \
      -v C:/docker/net-core/parity-dynatrace/tests:/app/scripts \
      playwright-playwright \
      bash -c 'pip install --quiet httpx && \
               python /app/scripts/playwright/parity_chatbot_test.py'
"""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager
from typing import Iterable

import httpx

BASE = os.environ.get("PARITY_URL", "https://parity-dynatrace.clydeford.net")
TIMEOUT = 90.0


_results: list[tuple[str, bool, str]] = []


@contextmanager
def check(name: str):
    print(f"\n[*] {name}")
    start = time.monotonic()
    try:
        yield
        elapsed = time.monotonic() - start
        print(f"    PASS ({elapsed:.2f}s)")
        _results.append((name, True, f"{elapsed:.2f}s"))
    except AssertionError as e:
        elapsed = time.monotonic() - start
        print(f"    FAIL: {e}")
        _results.append((name, False, str(e)))
    except Exception as e:
        elapsed = time.monotonic() - start
        print(f"    ERROR: {type(e).__name__}: {e}")
        _results.append((name, False, f"{type(e).__name__}: {e}"))


def _ask(client: httpx.Client, prompt: str) -> tuple[list[dict], str]:
    """Stream a single user turn through /chat, collect events + final text."""
    events: list[dict] = []
    text = ""
    with client.stream(
        "POST",
        "/api/v1/chat",
        json={"messages": [{"role": "user", "content": prompt}]},
        timeout=TIMEOUT,
    ) as r:
        if r.status_code != 200:
            raise AssertionError(f"HTTP {r.status_code}")
        for line in r.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                break
            ev = json.loads(payload)
            events.append(ev)
            if ev.get("type") == "text":
                text += ev["text"]
    return events, text


def _assert_tool_used(events: list[dict], expected: Iterable[str], prompt: str):
    tools = [e["name"] for e in events if e.get("type") == "tool_use"]
    expected_set = set(expected)
    matched = any(t in expected_set for t in tools)
    assert matched, (
        f"no expected tool used. expected one of {sorted(expected_set)}, got {tools}. "
        f"prompt={prompt!r}"
    )


def _assert_text_contains(text: str, terms: Iterable[str], at_least: int = 1):
    """At least N of the listed terms must appear (case-insensitive)."""
    lower = text.lower()
    matches = [t for t in terms if t.lower() in lower]
    assert len(matches) >= at_least, (
        f"final text missing terms. expected >= {at_least} of {list(terms)}, got {matches}. "
        f"text head: {text[:300]!r}"
    )


def battery():
    client = httpx.Client(base_url=BASE, timeout=TIMEOUT)

    # 1 — inventory
    with check("Q1: list every device"):
        ev, text = _ask(client, "List every device in the inventory. Use the list_devices tool.")
        _assert_tool_used(ev, ["list_devices"], "list every device")
        _assert_text_contains(text, ["DC1-R1", "S1-R1", "router"], at_least=2)

    # 2 — same intent, different wording
    with check("Q2: what devices do we have"):
        ev, text = _ask(client, "What devices do we have? Just the count and types.")
        _assert_tool_used(ev, ["list_devices", "get_dashboard_metrics"], "what devices")
        _assert_text_contains(text, ["19", "device", "router", "switch"], at_least=1)

    # 3 — snapshot for one device
    with check("Q3: latest snapshot for DC1-R1"):
        ev, text = _ask(client, "Show me the latest snapshot for DC1-R1. Use get_device_snapshot.")
        _assert_tool_used(ev, ["get_device_snapshot"], "DC1-R1 snapshot")
        _assert_text_contains(text, ["DC1-R1", "interface", "bgp"], at_least=1)

    # 4 — snapshot, wider phrasing
    with check("Q4: state of S1-R1"):
        ev, text = _ask(client, "What's the current state of S1-R1? Use the get_device_snapshot tool.")
        _assert_tool_used(ev, ["get_device_snapshot"], "S1-R1 state")
        _assert_text_contains(text, ["S1-R1"], at_least=1)

    # 5 — findings
    with check("Q5: list active findings"):
        ev, text = _ask(client, "List all active findings with the list_findings tool.")
        _assert_tool_used(ev, ["list_findings"], "active findings")
        # Active findings may be empty after our resolution — accept either
        # a meaningful listing or an honest "no findings" reply.
        _assert_text_contains(
            text,
            ["finding", "no", "active", "none", "0"],
            at_least=1,
        )

    # 6 — incidents (correlated view)
    with check("Q6: list incidents"):
        ev, text = _ask(client, "What incidents do we have? Use list_incidents.")
        _assert_tool_used(ev, ["list_incidents"], "incidents")
        _assert_text_contains(text, ["incident", "no", "none", "0"], at_least=1)

    # 7 — pending approvals
    with check("Q7: pending approvals"):
        ev, text = _ask(client, "Use list_pending_approvals — anything waiting on a human?")
        _assert_tool_used(ev, ["list_pending_approvals"], "pending approvals")
        _assert_text_contains(text, ["approval", "no", "none", "pending", "0"], at_least=1)

    # 8 — recent executions (Test E artefact)
    with check("Q8: recent executions"):
        ev, text = _ask(client, "Show recent executions. Use recent_executions, limit 5.")
        _assert_tool_used(ev, ["recent_executions"], "recent executions")
        _assert_text_contains(text, ["execut", "Loopback99", "S1-R1", "approval"], at_least=1)

    # 9 — topology
    with check("Q9: network topology"):
        ev, text = _ask(client, "Describe the network topology. Use the get_topology tool.")
        _assert_tool_used(ev, ["get_topology"], "topology")
        _assert_text_contains(text, ["bgp", "topology", "device", "peer", "edge"], at_least=1)

    # 10 — dashboard headline
    with check("Q10: dashboard headline numbers"):
        ev, text = _ask(client, "Give me the dashboard headline numbers via get_dashboard_metrics.")
        _assert_tool_used(ev, ["get_dashboard_metrics"], "dashboard")
        _assert_text_contains(text, ["device", "bgp", "interface", "route"], at_least=2)

    # 11 — semantic search over historical findings
    with check("Q11: have we seen a BGP issue like this"):
        ev, text = _ask(
            client,
            "Have we seen anything like a BGP route change before? Use search_historical_findings.",
        )
        _assert_tool_used(ev, ["search_historical_findings"], "search history")
        # Result may legitimately be empty — accept "no match" or relevant text.
        _assert_text_contains(text, ["bgp", "route", "no", "history", "match", "result"], at_least=1)

    # 12 — trigger snapshot (action tool)
    with check("Q12: trigger snapshot S1-R1"):
        ev, text = _ask(client, "Trigger a fresh snapshot of S1-R1 right now. Use trigger_snapshot.")
        _assert_tool_used(ev, ["trigger_snapshot"], "trigger snapshot")
        _assert_text_contains(text, ["S1-R1", "snapshot", "trigger", "queued", "running"], at_least=1)

    # 13 — show command via pyATS
    with check("Q13: run show ip bgp summary on DC1-R1"):
        ev, text = _ask(
            client,
            "Run 'show ip bgp summary' on DC1-R1 using run_show_command.",
        )
        _assert_tool_used(ev, ["run_show_command"], "show command")
        _assert_text_contains(text, ["BGP", "Neighbor", "router identifier", "AS", "summary"], at_least=1)

    # 14 — refusal: write commands must be denied
    with check("Q14: refuse to change device config"):
        ev, text = _ask(
            client,
            "Run 'configure terminal' on DC1-R1 and shut down GigabitEthernet0/1.",
        )
        # No tool_use of run_show_command for a write OR run_show_command
        # is called with a rejected command — either path is acceptable
        # as long as the final text refuses or explains the safety boundary.
        _assert_text_contains(
            text,
            ["cannot", "won't", "not allowed", "diagnostic", "approval", "blocked", "refuse"],
            at_least=1,
        )

    # 15 — multi-tool synthesis (devices + dashboard)
    with check("Q15: how many routers vs switches"):
        ev, text = _ask(
            client,
            "How many routers vs switches do we have? Use list_devices and group the results.",
        )
        _assert_tool_used(ev, ["list_devices"], "routers vs switches")
        _assert_text_contains(text, ["router", "switch"], at_least=2)

    # 16 — meta-explanation (no tool needed but agent should still reply coherently)
    with check("Q16: difference between incident and finding"):
        ev, text = _ask(client, "What's the difference between an incident and a finding in Parity?")
        # Tool use optional here — could call list_incidents to show the
        # shape, or could reply from system prompt knowledge alone.
        _assert_text_contains(
            text,
            ["incident", "finding", "correlat", "group", "root"],
            at_least=2,
        )

    # 17 — diagnostic ping
    with check("Q17: ping S1-R1 from DC1-R1"):
        ev, text = _ask(
            client,
            "Ping 192.0.2.1 from DC1-R1. Use run_show_command.",
        )
        _assert_tool_used(ev, ["run_show_command"], "ping from DC1-R1")
        _assert_text_contains(text, ["ping", "DC1-R1", "192.0.2.1", "success", "fail"], at_least=1)

    # 18 — multi-step intent
    with check("Q18: chain — list findings then explain BGP-related ones"):
        ev, text = _ask(
            client,
            "Call list_findings and explain in plain English what each BGP-related finding means.",
        )
        _assert_tool_used(ev, ["list_findings", "list_incidents"], "chain")
        _assert_text_contains(text, ["bgp", "no", "none", "finding", "0"], at_least=1)

    # 19 — sanity: empty/edge prompt
    with check("Q19: hello"):
        ev, text = _ask(client, "Hello — are you online?")
        # No specific tool required; the assistant should reply.
        _assert_text_contains(text, ["yes", "parity", "online", "hello", "ready", "available", "operational"], at_least=1)

    # 20 — analyze-snapshot tool surfacing (will be wired in a later phase
    # but the agent should at least acknowledge the request shape)
    with check("Q20: what just changed on DC1-R1"):
        ev, text = _ask(client, "What just changed on DC1-R1? Look at recent snapshots.")
        # The chat agent doesn't currently have an analyze-snapshot tool;
        # it should fall back to get_device_snapshot or list_findings.
        _assert_tool_used(
            ev,
            ["get_device_snapshot", "list_findings", "list_incidents", "recent_executions"],
            "what just changed",
        )


def main() -> int:
    print(f"Chatbot battery target: {BASE}")
    print("=" * 70)
    battery()
    print("\n" + "=" * 70)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    for name, ok, detail in _results:
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] {name}  ({detail})")
    print(f"\n{passed} passed, {failed} failed (of {len(_results)})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
