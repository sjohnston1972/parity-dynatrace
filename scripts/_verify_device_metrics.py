"""One-off verification probe for the new device_metrics_emitter.

Hits the local Dynatrace MCP (raw JSON-RPC) to count the
``parity.net.<feature>.*`` events emitted in the last ~5 minutes,
grouped by ``parity.self.category``.
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx

MCP_URL = os.environ.get("DT_REAL_MCP_URL", "http://localhost:8222/mcp")

DQL = (
    'fetch events, from:-5m '
    '| filter source=="parity-self" '
    '| filter startsWith(`parity.self.category`, "net-") '
    '| summarize n=count(), by:{`parity.self.category`}'
)


async def _mcp_call(tool: str, args: dict) -> str:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    }
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(
            MCP_URL,
            json=body,
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
    text = r.text
    if "data:" in text:
        lines = [l[5:].strip() for l in text.splitlines() if l.startswith("data:")]
        text = lines[-1] if lines else "{}"
    data = json.loads(text)
    if data.get("error"):
        raise RuntimeError(f"MCP error: {data['error']}")
    content = data.get("result", {}).get("content", [])
    parts = [c.get("text", "") for c in content if c.get("type") == "text"]
    return "\n".join(parts) if parts else json.dumps(data.get("result", {}))


async def main():
    print(f"MCP_URL = {MCP_URL}")
    print(f"DQL = {DQL}")
    out = await _mcp_call("execute_dql", {"dqlStatement": DQL})
    print("\n=== raw MCP output ===")
    print(out)


if __name__ == "__main__":
    asyncio.run(main())
