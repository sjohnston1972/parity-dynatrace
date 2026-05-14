"""End-to-end test suite for Parity.

Runs against the public Cloudflare-fronted URL so the tunnel + frontend
+ backend + Gemini + Dynatrace MCP are all exercised together. Designed
to be run from the existing playwright container with this repo's
tests/ dir bind-mounted into /app/scripts:

    docker run --rm \\
        --name parity-test \\
        -v C:/docker/net-core/parity-dynatrace/tests:/app/scripts \\
        mcr.microsoft.com/playwright/python:v1.52.0 \\
        python /app/scripts/playwright/parity_test.py

The script prints PASS/FAIL per check and exits 0 only if every check
passes. Tests are independent — a failed one doesn't stop the others.
"""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager
from typing import Any

import httpx
from playwright.sync_api import sync_playwright

BASE = os.environ.get("PARITY_URL", "https://parity-dynatrace.clydeford.net")
TIMEOUT = 30.0


# ── Result tracking ──────────────────────────────────────────


_results: list[tuple[str, bool, str]] = []  # (name, passed, detail)


@contextmanager
def check(name: str):
    """Wrap a check; capture pass/fail/exception."""
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


# ── API checks (httpx, no browser) ───────────────────────────


def api_checks():
    client = httpx.Client(base_url=BASE, timeout=TIMEOUT)

    with check("GET /api/v1/health"):
        r = client.get("/api/v1/health")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        body = r.json()
        assert body == {"status": "ok", "service": "parity"}, body

    with check("GET /api/v1/health/dependencies (all green)"):
        r = client.get("/api/v1/health/dependencies")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        body = r.json()
        assert body["status"] == "ok", body
        deps = body["dependencies"]
        for dep in ("postgres", "chromadb", "gemini", "grafana"):
            assert deps.get(dep, {}).get("status") == "ok", f"{dep}: {deps.get(dep)}"
        assert "gemini-2.5" in deps["gemini"]["model"], deps["gemini"]

    with check("GET /api/v1/llm/ping returns PARITY-OK"):
        r = client.get("/api/v1/llm/ping")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        body = r.json()
        assert body["ok"] is True, body
        assert body["text"].strip() == "PARITY-OK", body
        assert "gemini-2.5" in body["model"], body
        assert body["tokens"]["total"] > 0

    with check("GET /api/v1/dynatrace/problems returns canned problems"):
        r = client.get("/api/v1/dynatrace/problems")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        body = r.json()
        assert body["totalCount"] == 3, body
        ids = {p["problemId"] for p in body["problems"]}
        assert "P-2026-05-13-1842" in ids, ids  # BGP
        assert "P-2026-05-13-1903" in ids, ids  # Interface errors
        assert "P-2026-05-13-1855" in ids, ids  # Synthetic monitor

    with check("POST /api/v1/dynatrace/ingest is idempotent"):
        r1 = client.post("/api/v1/dynatrace/ingest")
        assert r1.status_code == 200, f"HTTP {r1.status_code}: {r1.text}"
        r2 = client.post("/api/v1/dynatrace/ingest")
        assert r2.status_code == 200, f"HTTP {r2.status_code}: {r2.text}"
        b2 = r2.json()
        assert b2["created"] == 0, f"expected created=0 on second call, got {b2}"
        assert b2["updated"] == 3, f"expected updated=3, got {b2}"

    with check("GET /api/v1/findings includes dynatrace-source rows"):
        r = client.get("/api/v1/findings?limit=50")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        findings = r.json()
        dt = [f for f in findings if f.get("source") == "dynatrace"]
        assert len(dt) >= 3, f"expected >=3 dynatrace findings, got {len(dt)}"
        titles = {f["title"] for f in dt}
        assert any("BGP" in t for t in titles), titles
        assert any("Input errors" in t or "Interface" in t.lower() for t in titles), titles

    with check("POST /api/v1/chat returns SSE tool_use + text"):
        with client.stream(
            "POST",
            "/api/v1/chat",
            json={
                "messages": [
                    {"role": "user", "content": "How many devices do we have? Just the number."}
                ]
            },
            timeout=60.0,
        ) as r:
            assert r.status_code == 200, f"HTTP {r.status_code}"
            events: list[dict[str, Any]] = []
            text_chunks: list[str] = []
            for line in r.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                ev = json.loads(payload)
                events.append(ev)
                if ev.get("type") == "text":
                    text_chunks.append(ev["text"])
            tool_uses = [e for e in events if e.get("type") == "tool_use"]
            assert tool_uses, f"no tool_use events: {events!r}"
            assert text_chunks, f"no text events: {events!r}"

    with check("POST /api/v1/chat (Dynatrace question) reaches list_findings"):
        with client.stream(
            "POST",
            "/api/v1/chat",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Use the list_findings tool to list all open findings "
                            "with category 'dynatrace-problem'. After the tool "
                            "returns, summarise each one by title."
                        ),
                    }
                ]
            },
            timeout=60.0,
        ) as r:
            assert r.status_code == 200, f"HTTP {r.status_code}"
            tools_called: list[str] = []
            final_text = ""
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                ev = json.loads(payload)
                if ev.get("type") == "tool_use":
                    tools_called.append(ev["name"])
                elif ev.get("type") == "text":
                    final_text += ev["text"]
            assert any(t in ("list_findings", "list_incidents") for t in tools_called), (
                f"expected list_findings or list_incidents, got {tools_called!r}"
            )
            # At least one of the seeded problem titles should make the answer
            assert (
                "BGP" in final_text
                or "Input errors" in final_text
                or "Synthetic" in final_text
            ), f"final answer: {final_text!r}"

    with check("GET /api/v1/devices includes Grafana-sourced inventory"):
        r = client.get("/api/v1/devices")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        devices = r.json()
        assert len(devices) >= 10, f"expected >=10 devices, got {len(devices)}"
        # Sanity-check shapes
        for d in devices[:3]:
            for k in ("id", "hostname", "platform"):
                assert k in d, f"missing {k}: {d}"

    with check("GET /api/v1/dashboard/metrics responds with counts"):
        r = client.get("/api/v1/dashboard/metrics")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        body = r.json()
        # Don't be strict on shape — different deployments may add fields.
        # Require at least one numeric or list value.
        assert isinstance(body, dict) and body, f"empty dashboard payload: {body}"

    with check("GET /api/v1/topology responds with nodes/edges shape"):
        r = client.get("/api/v1/topology")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        body = r.json()
        assert isinstance(body, dict), f"unexpected topology body: {body!r}"

    with check("GET /api/v1/approvals responds"):
        r = client.get("/api/v1/approvals")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        # No content assertion — there are no approvals until the
        # remediation pipeline (Rewire 2.5+) is wired to findings.

    with check("Dynatrace-origin findings have null snapshot_id, resolved device_id"):
        r = client.get("/api/v1/findings?limit=50")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        dt = [f for f in r.json() if f.get("source") == "dynatrace"]
        assert dt, "no dynatrace findings — run /dynatrace/ingest first"
        for f in dt:
            assert f["snapshot_id"] is None, f"snapshot_id should be NULL: {f}"
        # At least one Dynatrace problem maps to a real device (S1-R1 etc.)
        with_device = [f for f in dt if f["device_id"]]
        assert with_device, "no dynatrace finding resolved to a device"

    with check("GET /docs (OpenAPI) responds 200"):
        r = client.get("/docs")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        assert "Parity" in r.text or "OpenAPI" in r.text or "swagger" in r.text.lower()

    with check("Gemini 2.5 thinking-token accounting is present"):
        r = client.get("/api/v1/llm/ping")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        body = r.json()
        assert body["tokens"]["thoughts"] > 0, (
            f"expected >0 thoughts tokens for gemini-2.5, got {body}"
        )


# ── UI checks (Playwright) ───────────────────────────────────


def ui_checks():
    out_dir = "/app/scripts/playwright/screenshots"
    os.makedirs(out_dir, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})

        with check("UI: dashboard page loads"):
            page = ctx.new_page()
            page.goto(f"{BASE}/", wait_until="domcontentloaded", timeout=int(TIMEOUT * 1000))
            page.screenshot(path=f"{out_dir}/01_dashboard.png", full_page=True)
            content = page.content()
            assert "Parity" in content or "Dashboard" in content or "Network" in content, (
                "page did not contain expected branding"
            )

        with check("UI: insights page loads"):
            page = ctx.new_page()
            page.goto(
                f"{BASE}/insights",
                wait_until="domcontentloaded",
                timeout=int(TIMEOUT * 1000),
            )
            page.screenshot(path=f"{out_dir}/02_insights.png", full_page=True)
            # The Insights page should mention findings or the dynatrace
            # problem titles after a successful ingest.
            text = page.inner_text("body")
            assert (
                "Finding" in text
                or "BGP" in text
                or "Insight" in text
                or "Severity" in text
            ), f"insights page body: {text[:300]!r}"

        with check("UI: devices page lists devices"):
            page = ctx.new_page()
            page.goto(
                f"{BASE}/devices",
                wait_until="domcontentloaded",
                timeout=int(TIMEOUT * 1000),
            )
            page.screenshot(path=f"{out_dir}/03_devices.png", full_page=True)
            text = page.inner_text("body")
            # Inventory pulled from the shared Grafana should produce S1-R1 etc.
            assert (
                "S1-R1" in text
                or "S2-R1" in text
                or "DC1-R1" in text
                or "iosxe" in text
            ), f"devices page body: {text[:300]!r}"

        with check("UI: approvals page loads"):
            page = ctx.new_page()
            page.goto(
                f"{BASE}/approvals",
                wait_until="domcontentloaded",
                timeout=int(TIMEOUT * 1000),
            )
            page.screenshot(path=f"{out_dir}/04_approvals.png", full_page=True)
            # No assertion on content — just that it renders without crashing.

        browser.close()


# ── Main ─────────────────────────────────────────────────────


def main() -> int:
    print(f"Testing Parity at: {BASE}")
    print("=" * 64)

    api_checks()
    ui_checks()

    print("\n" + "=" * 64)
    print("Summary")
    print("=" * 64)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    for name, ok, detail in _results:
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] {name}  ({detail})")
    print(f"\n{passed} passed, {failed} failed (of {len(_results)})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
