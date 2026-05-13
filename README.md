# Parity

Day-2 network operations powered by **Dynatrace** observability and **Gemini** reasoning. Parity ingests Davis-detected problems from Dynatrace, drafts remediation with Google ADK agents, requires human approval, applies fixes against network devices via pyATS, then re-queries Dynatrace and the device to verify the fix landed.

**The loop:** Dynatrace sees → Gemini reasons → you approve → Parity acts → Dynatrace verifies.

Built as a submission to the [Google Cloud Rapid Agent Hackathon](https://rapid-agent.devpost.com/) — Dynatrace partner track.

## Status

Initial scaffold. The backend code structure, data model, frontend, and approval/execution plumbing are inherited from a prior private project (kopis). The three rewires that make this Parity rather than kopis happen next:

- **Rewire 1 — LLM:** swap the Anthropic client for Gemini on Vertex AI.
- **Rewire 2 — Agents:** replace LangGraph with Google ADK (`SequentialAgent` + `LlmAgent`s).
- **Rewire 3 — Detection:** wire in the Dynatrace MCP server as the problem source and the verification check.

## Running locally

```bash
cp .env.example .env       # fill in secrets
docker compose up -d       # postgres, chromadb, dynatrace-mcp stub, backend, frontend
```

Open http://localhost:8211 for the UI, http://localhost:8210/docs for the OpenAPI spec.

## Licence

Apache 2.0 — see [LICENSE](LICENSE).
