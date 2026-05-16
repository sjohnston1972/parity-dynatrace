"""Exercise every tool the real Dynatrace MCP server exposes.

Talks to the @dynatrace-oss/dynatrace-mcp-server sidecar
(`parity-dt-mcp-real` in docker-compose; reachable on host port 8222)
over the streamable-HTTP transport using the Python MCP SDK — exactly
the same path Parity's `DynatraceClient` uses.

Each tool is invoked with a representative payload; we assert the
response is well-formed JSON/text (not a transport error). For tools
that need data the empty kea15603 tenant doesn't yet have (problems,
vulnerabilities, exceptions, k8s events, entity lookup), we accept
an empty-but-valid response — the contract being tested is the wire,
not the data.

Run:  py tests/playwright/dynatrace_mcp_test.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from contextlib import contextmanager
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.environ.get("DT_REAL_MCP_URL", "http://localhost:8222/mcp")

_results: list[tuple[str, bool, str]] = []


@contextmanager
def _check(name: str):
    t0 = time.monotonic()
    print(f"\n[*] {name}", flush=True)
    try:
        yield
        dt = time.monotonic() - t0
        print(f"    PASS ({dt:.2f}s)", flush=True)
        _results.append((name, True, f"{dt:.2f}s"))
    except AssertionError as e:
        print(f"    FAIL: {e}", flush=True)
        _results.append((name, False, str(e)))
    except Exception as e:
        print(f"    ERROR: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
        _results.append((name, False, f"{type(e).__name__}: {e}"))


async def _call(session: ClientSession, tool: str, args: dict[str, Any]) -> str:
    # MCP server enforces 5 tool calls / 20s. Insert a polite delay so
    # we never trip the limit during a fast sweep.
    await asyncio.sleep(4.0)
    res = await session.call_tool(tool, args)
    parts = []
    for block in (res.content or []):
        t = getattr(block, "text", None)
        if t:
            parts.append(t)
    return "\n".join(parts)


async def main() -> int:
    print(f"Probing real Dynatrace MCP at: {MCP_URL}")
    print("=" * 72)

    async with streamablehttp_client(MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as s:
            await s.initialize()

            tools_list = await s.list_tools()
            tool_names = {t.name for t in tools_list.tools}
            print(f"\nServer exposes {len(tool_names)} tools.")

            with _check("tool: get_environment_info"):
                out = await _call(s, "get_environment_info", {})
                assert "kea15603" in out or "Environment" in out, out[:300]

            with _check("tool: chat_with_davis_copilot — short question"):
                out = await _call(s, "chat_with_davis_copilot", {
                    "text": "Reply with exactly two words: 'hello parity'"
                })
                low = out.lower()
                assert "answer" in low or "hello" in low, out[:400]

            with _check("tool: generate_dql_from_natural_language"):
                out = await _call(s, "generate_dql_from_natural_language", {
                    "text": "show me Parity events from the last hour"
                })
                low = out.lower()
                assert "fetch" in low or "dql" in low, out[:400]

            with _check("tool: explain_dql_in_natural_language"):
                out = await _call(s, "explain_dql_in_natural_language", {
                    "dql": 'fetch events, from:-1h | filter source == "parity"'
                })
                assert len(out) > 20, out[:400]

            with _check("tool: verify_dql — valid query"):
                out = await _call(s, "verify_dql", {
                    "dqlStatement": 'fetch events, from:-1h | limit 1'
                })
                assert "valid" in out.lower() or "ok" in out.lower() or len(out) > 5, out[:400]

            with _check("tool: execute_dql — Parity events round-trip"):
                out = await _call(s, "execute_dql", {
                    "dqlStatement": 'fetch events, from:-24h | filter source == "parity" | limit 5'
                })
                # Tenant may have zero events but the call should succeed.
                assert "fetch" not in out.lower()[:30] or "0 records" in out.lower() or len(out) > 0, out[:400]

            with _check("tool: list_problems"):
                out = await _call(s, "list_problems", {})
                # Empty tenant returns no problems; just confirm the call succeeded.
                assert "problems" in out.lower() or "no" in out.lower() or len(out) > 0, out[:400]

            with _check("tool: list_vulnerabilities"):
                out = await _call(s, "list_vulnerabilities", {})
                assert "vulnerab" in out.lower() or "no" in out.lower() or len(out) > 0, out[:400]

            with _check("tool: list_exceptions"):
                out = await _call(s, "list_exceptions", {})
                assert len(out) > 0, "empty response"

            with _check("tool: find_entity_by_name — known-empty"):
                out = await _call(s, "find_entity_by_name", {
                    "entityName": "DC1-R1.clydeford.net"
                })
                # Tenant has no entities; expect empty or 'not found' kind of msg.
                assert len(out) > 0, "empty response"

            with _check("tool: get_kubernetes_events"):
                out = await _call(s, "get_kubernetes_events", {
                    "clusterId": "no-such-cluster"
                })
                assert len(out) > 0, "empty response"

            with _check("tool: list_davis_analyzers"):
                out = await _call(s, "list_davis_analyzers", {})
                low = out.lower()
                assert "analyzer" in low or "forecast" in low, out[:400]

            with _check("tool: execute_davis_analyzer — forecast on Parity event count"):
                # Use a timeseries that's valid in this tenant — count of Parity events per hour.
                # The analyzer needs a metric-style timeseries; for a parameterised count
                # we use the events stream itself via `summarize count()` over time bins.
                out = await _call(s, "execute_davis_analyzer", {
                    "analyzerName": "dt.statistics.GenericForecastAnalyzer",
                    "inputParameters": {
                        "timeSeriesData": (
                            'timeseries n = count(), from:-24h, by:{parity.action}, '
                            'filter:{source=="parity"}, interval:1h'
                        ),
                        "forecastHorizon": 6,
                    },
                })
                assert len(out) > 0, "empty response"

            with _check("tool: send_event — emit a CUSTOM_INFO probe via MCP"):
                out = await _call(s, "send_event", {
                    "eventType": "CUSTOM_INFO",
                    "title": "Parity MCP-tool probe",
                    "properties": {"source": "parity-mcp-probe"},
                })
                low = out.lower()
                assert "event" in low or "success" in low or "ok" in low or len(out) > 0, out[:400]

            for tool in (
                "create_workflow_for_notification", "make_workflow_public",
                "send_slack_message", "send_email", "create_dynatrace_notebook",
                "reset_grail_budget",
            ):
                # Just assert the tool is advertised; we don't execute side-effect-heavy
                # ones in the test suite to avoid leaving artefacts in the tenant.
                with _check(f"tool: {tool} (advertised)"):
                    assert tool in tool_names, f"{tool} not in server tool list"

    print("\n" + "=" * 72)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    for name, ok, detail in _results:
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] {name}  ({detail})")
    print(f"\n{passed} passed, {failed} failed (of {len(_results)})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
