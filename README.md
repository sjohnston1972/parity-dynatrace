# Parity

Day-2 network operations powered by **Dynatrace** observability and **Gemini** reasoning. Parity ingests Davis-detected problems from Dynatrace, has Google ADK agents (running on Gemini 2.5 on Vertex AI) reason about them, requires human approval, will apply fixes against network devices via pyATS, then re-queries Dynatrace and the device to verify the fix.

**The loop:** Dynatrace sees → Gemini reasons → you approve → Parity acts → Dynatrace verifies.

Built as a submission to the [Google Cloud Rapid Agent Hackathon](https://rapid-agent.devpost.com/) — Dynatrace partner track.

**Live demo:** https://parity-dynatrace.clydeford.net  
**Repo:** https://github.com/sjohnston1972/parity-dynatrace

## What works today

- **Backend on Gemini.** `GeminiClient` calls Vertex AI with Application Default Credentials — no API keys. Health probe round-trips a real token through `gemini-2.5-flash-lite` on every `/api/v1/health/dependencies` call.
- **ADK chat assistant.** `LlmAgent` running `gemini-2.5-flash`, twelve tools wrapped from `services/chat_tools.py`. Streams SSE back to the React UI (`tool_use` / `tool_result` / `text` / `[DONE]`).
- **Dynatrace MCP integration.** A FastMCP stub server (`docker/dynatrace-mcp-stub/`) speaks the streamable-HTTP MCP protocol and exposes `list_problems`, `find_entity_by_name`, `execute_dql` with canned Davis-style payloads. The backend uses the official `mcp` Python SDK to talk to it. Swap the URL in `.env` to point at the real `@dynatrace-oss/dynatrace-mcp-server` once you have a tenant.
- **Ingestion.** `POST /api/v1/dynatrace/ingest` pulls open problems and upserts them as `Finding` rows (idempotent on Dynatrace `problemId`).
- **Cloudflare tunnel.** Public hostname `parity-dynatrace.clydeford.net` routes to the frontend through an existing `cloudflared` deployment.
- **Reused inventory.** Device list comes from a shared Grafana the operator already runs. Saves provisioning a new SNMP-discovery stack.
- **19-check E2E suite.** `tests/playwright/parity_test.py` exercises API + UI end-to-end via the public URL. See [TEST_PLAN.md](TEST_PLAN.md).

## What's planned (not yet shipped)

The README's headline loop has six steps; three are wired today.

| Step | Status |
|---|---|
| Detect — Dynatrace problem → Finding | **Done** |
| Investigate — chat assistant tools | **Done (via chat agent)** |
| Reason — autonomous remediation drafting | **Pending** (ADK `SequentialAgent` — Rewire 2.5) |
| Approve — human-in-the-loop UI/Slack | **UI/Jira ready; no recommendations to approve yet** |
| Act — pyATS execution | **Wired, blocked on Reason step** |
| Verify — Dynatrace re-query | **Pending** |

Rewire 2.5 is the natural next milestone: an ADK `SequentialAgent` of `LlmAgent`s (Investigate → Reason) that consumes a Dynatrace-source finding and emits a `Recommendation` + `Approval` row. That unblocks the rest.

## Running locally

```bash
cp .env.example .env
# Set POSTGRES_PASSWORD; the rest have working defaults.
gcloud auth application-default login   # one-time, on the host
gcloud services enable aiplatform.googleapis.com --project=parity-dynatrace
docker compose up -d
```

Open <http://localhost:8211> for the UI, <http://localhost:8210/docs> for the OpenAPI spec.

Side-by-side guarantee: every container, port, volume, DB name, and network name is distinct from any other stack on the host. Parity runs alongside without collision.

## Testing

```powershell
docker run --rm `
  -v "${PWD}\tests:/app/scripts" `
  playwright-playwright `
  bash -c 'pip install --quiet httpx && python /app/scripts/playwright/parity_test.py'
```

Nineteen checks, ~60 seconds total. See [TEST_PLAN.md](TEST_PLAN.md) for the matrix and manual-demo checklist.

## Architecture

```
┌───────────────────────────────────────────────────────────┐
│  Cloudflare Tunnel — parity-dynatrace.clydeford.net       │
└────────────────────────┬──────────────────────────────────┘
                         │
            ┌────────────▼────────────┐
            │  parity-frontend (nginx)│  Vite + React 19 + Tailwind 4
            └────────────┬────────────┘
                         │ /api/* /ws/*
            ┌────────────▼────────────┐
            │  parity-backend (FastAPI│  uvicorn + alembic on boot
            │  + ADK + google-genai)  │
            └─┬─────────┬─────────┬───┘
              │         │         │
   ┌──────────▼─┐ ┌─────▼────┐ ┌──▼─────────────────┐
   │ Postgres   │ │ ChromaDB │ │ parity-dt-mcp      │
   │ (parity-   │ │ (vectors)│ │ (FastMCP stub      │
   │  postgres) │ │          │ │  /mcp + /health)   │
   └────────────┘ └──────────┘ └────────┬───────────┘
                                        │
                  ┌─────────────────────▼─────────────────┐
                  │  Real Dynatrace MCP server (later)    │
                  │  @dynatrace-oss/dynatrace-mcp-server  │
                  └───────────────────────────────────────┘

External shared services (re-used, untouched):
  • snmp-grafana       — device inventory source
  • cloudflared tunnel — public ingress
  • Jira + Slack       — approval notifications

LLM at runtime: Gemini 2.5 (flash / pro / flash-lite) on Vertex AI
                via Application Default Credentials — no API keys.
```

## Licence

Apache 2.0 — see [LICENSE](LICENSE).
