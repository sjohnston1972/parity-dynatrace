# Parity — Test Plan

This document describes the automated test suite for Parity and the
manual demo checks that complement it. Both run against a public
Cloudflare-fronted endpoint so the entire delivery path — tunnel,
nginx, FastAPI, Gemini, Dynatrace MCP — is exercised end-to-end.

## Environment under test

| Component | Where | How verified |
|---|---|---|
| Public URL | https://parity-dynatrace.clydeford.net | Cloudflare DNS + tunnel ingress |
| Frontend | `parity-frontend` (nginx 8211) | Reverse-proxy `/api/` to backend |
| Backend | `parity-backend` (FastAPI 8210) | uvicorn + alembic on boot |
| Postgres | `parity-postgres` (5434) | health: `pg_isready` |
| ChromaDB | `parity-chromadb` (8102) | health: `/api/v1/heartbeat` |
| Dynatrace MCP stub | `parity-dt-mcp` (8220) | health: `/health` (Starlette sibling route) |
| Gemini | Vertex AI `us-central1`, project `parity-dynatrace` | `/health/dependencies` probe round-trips a token through `gemini-2.5-flash-lite` |
| Grafana inventory | reused `snmp-grafana` on `net_core` | inventory pulled at backend startup |

Side-by-side guarantee: every container, port, volume, DB, and network
name is distinct from the parent kopis stack. Kopis containers and
volumes are never modified.

## Automated suite — `tests/playwright/parity_test.py`

Nineteen checks. Run via the user's existing playwright image:

```powershell
docker run --rm `
  -v "C:\docker\net-core\parity-dynatrace\tests:/app/scripts" `
  playwright-playwright `
  bash -c 'pip install --quiet httpx && python /app/scripts/playwright/parity_test.py'
```

Override the target with `-e PARITY_URL=http://localhost:8210`. Exits 0
only when every check passes; prints a summary table either way.
Screenshots from the UI checks land in `tests/playwright/screenshots/`.

### Coverage

**Health & smoke (3)**
1. `GET /api/v1/health` — `{ok, parity}`.
2. `GET /api/v1/health/dependencies` — postgres, chromadb, gemini, grafana all `ok`.
3. `GET /api/v1/llm/ping` — Gemini round-trip returns `PARITY-OK`.

**Dynatrace MCP integration (3)**
4. `GET /api/v1/dynatrace/problems` — pass-through from FastMCP stub returns three canned Davis problems.
5. `POST /api/v1/dynatrace/ingest` — idempotent: first call creates 3, second call updates 3 (no duplicates).
6. `GET /api/v1/findings?source=dynatrace` — three findings persisted with `source=dynatrace`, `snapshot_id` null, `device_id` resolved when the affected entity matches a known host (S1-R1, S2-R1).

**ADK chat assistant (2)**
7. `POST /api/v1/chat` (open-ended question) — agent autonomously selects a tool, SSE stream contains `tool_use`, `tool_result`, `text`, `[DONE]`.
8. `POST /api/v1/chat` (directed) — answer demonstrably calls `list_findings`/`list_incidents` and references seeded Dynatrace problem titles.

**Read-only REST surface (4)**
9. `GET /api/v1/devices` — Grafana-sourced inventory returns ≥10 devices.
10. `GET /api/v1/dashboard/metrics` — non-empty dict.
11. `GET /api/v1/topology` — responds 200.
12. `GET /api/v1/approvals` — responds 200 (queue may be empty).

**Schema + observability (2)**
13. Dynatrace-origin findings have `snapshot_id=null` and at least one has `device_id` resolved (verifies migration 006 and the hostname matcher).
14. `GET /docs` — OpenAPI page renders.
15. Gemini 2.5 thinking-token accounting — `/llm/ping` returns `tokens.thoughts > 0`.

**UI (4)**
16. Dashboard route renders.
17. Insights route renders.
18. Devices route renders and lists at least one known hostname.
19. Approvals route renders.

### What the automated suite does *not* cover

- The Detect → Investigate → Reason agent pipeline that drafts remediation from an ingested Dynatrace finding. The chat assistant proves ADK + Gemini + tool use end-to-end; the remediation pipeline is a follow-on once the canned problems are sufficiently rich.
- pyATS execution against real network devices (requires homelab reachability and is outside the hackathon demo loop).
- Slack and Jira side-effects on approvals (configured in `.env`, exercised manually only).
- Re-verification step (post-fix Dynatrace re-query). Will be added when the remediation pipeline lands.

## Manual demo checks

For the 3-minute submission video:

1. **Open Dashboard at https://parity-dynatrace.clydeford.net** — show the Lumina design system rendering, the inventory tile populated from Grafana.
2. **POST `/api/v1/dynatrace/ingest`** — show the JSON response with `created/updated/skipped` counts, then refresh Insights to show three new dynatrace-source findings with severity badges.
3. **Open the chat panel** — ask "Show me the current Dynatrace findings", agent calls `list_findings`, returns BGP / Interface / Synthetic.
4. **Click a finding** — show the Davis evidence preserved in `evidence` JSONB (event/metric timeline).
5. **Approvals page** — empty for now; narrate the planned remediation flow.

## Failure procedures

- **Build collision (`image already exists`)**: spurious BuildKit dedup, harmless. Re-run `docker compose up -d --force-recreate <service>`.
- **`Invalid Host header` (421)**: FastMCP DNS-rebinding protection rejected a non-localhost request — confirm `transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)` is still set in `docker/dynatrace-mcp-stub/server.py`.
- **`relation "settings" does not exist`** on backend startup: migrations didn't run. The Dockerfile CMD chains `alembic upgrade head`; if you've baked a new image without the migration files, rebuild.
- **`Cannot install ... fastapi==0.115.12 ...`**: pip resolver hit a stale lock. We loosened FastAPI/pydantic pins; re-pull `requirements.txt`.
- **Gemini 404 on a model name**: `*-latest` aliases don't resolve on Vertex. Use `gemini-2.5-flash` / `gemini-2.5-pro` / `gemini-2.5-flash-lite`.

## Continuous-test stance during the contest

Re-run the Playwright suite after every notable commit. Each rewire
landed during this session was followed by an end-to-end pass. The
suite finishes in well under a minute (most checks are sub-second; the
chat checks dominate at ~5s each because Gemini 2.5 spends thinking
tokens).
