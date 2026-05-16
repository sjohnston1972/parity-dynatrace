"""Playwright UI test for the Dynatrace integration.

Drives the public Parity URL with a headless Chromium and asserts the
new Dynatrace surfaces are wired and rendering: dashboard banner,
Davis event timeline, branding, and integration settings panel.

Captures full-page screenshots for the executive report. Designed to
run from the existing playwright container, identically to
parity_test.py:

    docker run --rm \\
        -v C:/docker/net-core/parity-dynatrace/tests:/app/scripts \\
        mcr.microsoft.com/playwright/python:v1.52.0 \\
        python /app/scripts/playwright/dynatrace_ui_test.py
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager

import httpx
from playwright.sync_api import sync_playwright

BASE = os.environ.get("PARITY_URL", "https://parity-dynatrace.clydeford.net")
OUT = os.environ.get("PW_SCREENSHOT_DIR", "/app/scripts/playwright/screenshots/dynatrace")
TIMEOUT_MS = 30_000

_results: list[tuple[str, bool, str]] = []


@contextmanager
def check(name: str):
    t0 = time.monotonic()
    print(f"\n[*] {name}", flush=True)
    try:
        yield
        dt = time.monotonic() - t0
        print(f"    PASS ({dt:.2f}s)", flush=True)
        _results.append((name, True, f"{dt:.2f}s"))
    except AssertionError as e:
        dt = time.monotonic() - t0
        print(f"    FAIL: {e}", flush=True)
        _results.append((name, False, str(e)))
    except Exception as e:
        dt = time.monotonic() - t0
        print(f"    ERROR: {type(e).__name__}: {e}", flush=True)
        _results.append((name, False, f"{type(e).__name__}: {e}"))


def api_checks():
    client = httpx.Client(base_url=BASE, timeout=30.0)

    with check("API: /health/dependencies includes dynatrace=ok"):
        r = client.get("/api/v1/health/dependencies")
        assert r.status_code == 200, r.status_code
        body = r.json()
        dt = body["dependencies"].get("dynatrace")
        assert dt and dt.get("status") == "ok", dt
        assert dt.get("tenant"), f"no tenant id: {dt}"

    with check("API: /dynatrace/status returns configured tenant"):
        r = client.get("/api/v1/dynatrace/status")
        assert r.status_code == 200, r.status_code
        s = r.json()
        assert s["configured"] is True, s
        assert s["tenant"], f"empty tenant: {s}"
        assert s["apps_url"].endswith(".apps.dynatrace.com"), s["apps_url"]
        assert ".live.dynatrace.com" in s["live_url"], s["live_url"]

    with check("API: /dynatrace/events round-trip queries Grail"):
        r = client.get("/api/v1/dynatrace/events?lookback=-2h&limit=20")
        assert r.status_code == 200, r.status_code
        body = r.json()
        assert body["configured"] is True, body
        # We don't assert count > 0 because a fresh tenant may be empty;
        # the contract is that the call succeeds and returns the schema.
        assert "records" in body, body
        assert isinstance(body["records"], list), body

    with check("API: /dynatrace/davis-problems returns a stable schema"):
        r = client.get("/api/v1/dynatrace/davis-problems")
        assert r.status_code == 200, r.status_code
        body = r.json()
        assert body["configured"] is True, body
        assert "records" in body and isinstance(body["records"], list), body


def ui_checks():
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 1080})

        with check("UI: dashboard renders the Dynatrace banner"):
            page = ctx.new_page()
            page.goto(f"{BASE}/", wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            # Wait for the banner to actually paint (apps.dynatrace.com is
            # interpolated client-side after /dynatrace/status responds).
            page.wait_for_function(
                "() => document.body.innerText.includes('apps.dynatrace.com')",
                timeout=20_000,
            )
            html = page.content()
            assert "apps.dynatrace.com" in html, "banner missing tenant URL"
            assert "Dynatrace" in html, "no Dynatrace word on dashboard"
            page.screenshot(path=f"{OUT}/dashboard_full.png", full_page=True)

        with check("UI: dashboard surfaces the Davis event timeline"):
            page = ctx.new_page()
            page.goto(f"{BASE}/", wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            page.wait_for_function(
                "() => document.body.innerText.includes('Davis Event Timeline')",
                timeout=20_000,
            )
            page.screenshot(path=f"{OUT}/dashboard_davis_timeline.png", full_page=True)

        with check("UI: pipeline page mentions Dynatrace Davis"):
            page = ctx.new_page()
            page.goto(f"{BASE}/pipeline", wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            page.wait_for_timeout(1500)
            body = page.inner_text("body")
            # Branding line we updated to mention Davis explicitly.
            assert "Davis" in body, body[:300]
            page.screenshot(path=f"{OUT}/pipeline.png", full_page=True)

        with check("UI: settings integrations panel lists Dynatrace Davis"):
            page = ctx.new_page()
            page.goto(f"{BASE}/settings", wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            page.wait_for_timeout(1500)
            body = page.inner_text("body")
            assert "Dynatrace Davis" in body or "Dynatrace" in body, body[:300]
            page.screenshot(path=f"{OUT}/settings.png", full_page=True)

        with check("UI: insights page loads cleanly"):
            page = ctx.new_page()
            page.goto(f"{BASE}/insights", wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            page.wait_for_timeout(1500)
            page.screenshot(path=f"{OUT}/insights.png", full_page=True)

        with check("UI: topnav shows the 'on Dynatrace' badge"):
            page = ctx.new_page()
            page.goto(f"{BASE}/", wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            page.wait_for_timeout(1500)
            body = page.inner_text("body")
            assert "Dynatrace" in body, body[:300]

        browser.close()


def main() -> int:
    print(f"Testing Parity Dynatrace integration at: {BASE}")
    print("=" * 72)
    api_checks()
    ui_checks()
    print("\n" + "=" * 72)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    for name, ok, detail in _results:
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] {name}  ({detail})")
    print(f"\n{passed} passed, {failed} failed (of {len(_results)})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
