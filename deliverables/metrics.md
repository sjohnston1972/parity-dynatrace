# Parity — Metrics Catalog

Every signal Parity can emit to Dynatrace, organised by source.

The goal is one operator-friendly inventory of *what we can measure and why*, so when we wire each one into the Dynatrace ingest path we know exactly what dimensions to attach, what type of metric it is, and what kind of question it answers in Davis/DQL.

---

## How these reach Dynatrace

Parity already has four ingest paths configured in `backend/integrations/dynatrace.py` (`DynatraceWriter`):

| Path | Endpoint | Use it for | Scope required |
|---|---|---|---|
| **Events** | `/api/v2/events/ingest` (CUSTOM_INFO / CUSTOM_DEPLOYMENT) | Discrete moments — a snapshot finished, a finding was raised, a container restarted. Rich properties, queryable via DQL `fetch events`. | `environment-api:events:write` |
| **Metrics** | `/api/v2/metrics/ingest` (line-protocol) | Continuous numeric series — request rate, latency p95, token spend per minute. Cheap to chart, alert on, and aggregate. | `environment-api:metrics:write` |
| **Logs** | `/api/v2/logs/ingest` | Structured log lines for after-the-fact forensics. | `environment-api:logs:write` |
| **BizEvents** | `/api/v2/bizevents/ingest` | CloudEvents-shaped business events for the Davis workflow side. | `storage:bizevents:write` |

The capability probe at startup decides which paths are live; everything below is annotated with the path that fits best.

**Naming convention** — all Parity metrics use the prefix `parity.<area>.<name>` (e.g. `parity.http.requests`, `parity.gemini.tokens`). Self-monitor events use the property `source = "parity-self"` and `parity.self.category = <area>` so DQL can pivot cleanly.

**Status legend** — each row is tagged:
- **emitted** — already wired up in the codebase as of today
- **planned** — collection point exists; the line just needs adding to the periodic emitter or metric ingest
- **candidate** — worth adding next; not yet instrumented

---

## 1. HTTP / FastAPI request layer

Captured by the `request_metrics_middleware` in `backend/services/self_monitor.py:104`. Every inbound request bumps a ring counter with timestamp + latency. The 60-second rollup is sent as a self-monitor event; the per-path counters can also be flushed as line-protocol metrics.

| Metric | Type | Dimensions | Description | Status |
|---|---|---|---|---|
| `parity.http.requests` | counter | path, method, status_class | Total HTTP requests served. Rising baseline = healthy UI traffic; sudden zero = backend dead or middleware bypassed. | emitted (rollup + per-path event in http-by-path category) |
| `parity.http.errors` | counter | path, status_code | 5xx responses. The signal for "Parity itself is broken" rather than "the network is broken". Page on rate > 0 sustained. | emitted (rollup) |
| `parity.http.client_errors` | counter | path, status_code | 4xx responses. Usually frontend bugs or stale clients; alert on sudden spike. | candidate |
| `parity.http.latency_ms` | gauge / histogram | path, method | Per-request elapsed time. p50/p95/p99 needed; emit as sample summary every minute. | emitted (avg/max only) |
| `parity.http.requests_in_flight` | gauge | — | Concurrent open requests. Detects request pileups before they become 504s. | candidate |
| `parity.http.websocket.connections` | gauge | route | Live WebSocket / SSE clients (activity feed, pipeline status). Telegraphs UI fan-out. | candidate |
| `parity.http.sse.events_sent` | counter | stream | Activity events pushed to subscribers. Pairs with WebSocket gauge to spot stuck consumers. | candidate |

---

## 2. MCP tool calls (Dynatrace MCP, future others)

Every call through `DynatraceClient._call_tool` is wrapped by `mcp_call_timed` (`self_monitor.py:131`). MCP is where Parity reaches *into* Davis — high latency or error rate here is the leading indicator that Dynatrace ingest is starving.

| Metric | Type | Dimensions | Description | Status |
|---|---|---|---|---|
| `parity.mcp.calls` | counter | tool, transport (stdio/http) | Total MCP tool invocations. Charted next to `parity.gemini.calls` shows agent activity. | emitted (rollup + per-tool event in mcp-by-tool category) |
| `parity.mcp.errors` | counter | tool, error_class | Failures returned from the MCP server or transport. | emitted (rollup) |
| `parity.mcp.latency_ms` | histogram | tool | Per-tool latency. Different tools have very different baselines — `execute_dql` is seconds, `list_problems` is milliseconds. | emitted (avg only) |
| `parity.mcp.session.connects` | counter | server | Streamable-HTTP sessions opened. High churn = we're reconnecting per call instead of pooling. | candidate |
| `parity.mcp.session.duration_ms` | histogram | server | Lifetime of an MCP session. | candidate |
| `parity.mcp.dql.records_returned` | gauge | query_kind | Result-set size from `execute_dql`. Catches Grail queries that return zero (mis-scoped) or too many (paging bug). | candidate |
| `parity.mcp.dql.poll_iterations` | counter | — | How many times we polled `query:poll` before SUCCEEDED. Pegged to 5 means Grail is slow. | candidate |
| `parity.mcp.problems_listed` | gauge | — | Number of open Davis problems returned by `list_problems`. Drives the ingest pipeline's "work to do" view. | candidate |

---

## 3. Gemini / Vertex AI calls

Wrapped at `backend/integrations/gemini.py:106` (`gemini_call_timed`) plus the agent-side calls that go through ADK. Token-spend visibility is the single most important thing in this layer — Gemini Pro at full thinking budget costs real money.

| Metric | Type | Dimensions | Description | Status |
|---|---|---|---|---|
| `parity.gemini.calls` | counter | model, agent_node | Total LLM invocations. | emitted (rollup) |
| `parity.gemini.errors` | counter | model, error_class | RPC failures, quota, safety blocks, finish_reason != STOP. | emitted (rollup) |
| `parity.gemini.latency_ms` | histogram | model, agent_node | End-to-end latency including network. | emitted (avg only) |
| `parity.gemini.tokens.input` | counter | model | Prompt tokens billed. | planned |
| `parity.gemini.tokens.output` | counter | model | Candidate (visible) tokens. | planned |
| `parity.gemini.tokens.thoughts` | counter | model | 2.5 "thinking" tokens — invisible but billed. The hidden cost line. | planned |
| `parity.gemini.tokens.total` | counter | model | Sum of the three above; the cost-control headline. | emitted (sum only) |
| `parity.gemini.tokens.per_call` | histogram | model | Distribution of token spend per call. Catches a single prompt blowing the budget. | candidate |
| `parity.gemini.finish_reason` | counter | model, reason | STOP / MAX_TOKENS / SAFETY / RECITATION / OTHER. SAFETY spikes mean a prompt regression. | candidate |
| `parity.gemini.tier_split` | counter | tier (flash-lite/flash/pro) | Routing distribution. If "pro" is doing 90% of work the cheap-tier router is broken. | candidate |
| `parity.gemini.adk.tool_calls` | counter | agent, tool | ADK tools invoked from within an LlmAgent. Distinct from MCP — these are the Python tool wrappers. | candidate |
| `parity.gemini.adk.confirmations` | counter | agent, outcome (granted/denied) | ADK tool-confirmation outcomes. Audit trail for human-gated agent actions. | candidate |

---

## 4. pyATS snapshots

`backend/services/snapshot_engine.py` is the workhorse. One snapshot = connect to a device, learn N features, persist. Every completed snapshot calls `snapshot_record` and fires an individual event so the dashboard can pivot per device, per trigger, per feature count.

| Metric | Type | Dimensions | Description | Status |
|---|---|---|---|---|
| `parity.snapshot.runs` | counter | trigger (manual/schedule/pre-exec/post-exec), result | Snapshot operations completed. | emitted (rollup) |
| `parity.snapshot.duration_s` | histogram | hostname, device_type, trigger | Wall-clock time from connect → disconnect. p95 climbing means a device is slow / link is degraded. | emitted (avg only) |
| `parity.snapshot.feature_count` | gauge | hostname | Number of pyATS features successfully learned (out of the per-type list — 8 for routers, 10 for switches). Drops below baseline = parser bug or platform change. | emitted (sum only) |
| `parity.snapshot.size_bytes` | gauge | hostname | Serialized snapshot_data JSON size. Growth pattern correlates with topology growth or stuck logs. | emitted (per-snapshot event) |
| `parity.snapshot.connect_failures` | counter | hostname, reason | SSH timeouts, auth fails, "device not in testbed". Top of the alert tree for "did we lose a device?". | candidate |
| `parity.snapshot.feature_failures` | counter | hostname, feature | Per-feature `learn()` failures. A specific feature failing repeatedly across devices = parser/genie version skew. | candidate |
| `parity.snapshot.golden_age_seconds` | gauge | hostname | Seconds since the device's current golden snapshot was blessed. Drives the "baseline is stale" warning. | candidate |
| `parity.snapshot.diff.changes` | gauge | hostname, mode (rolling/golden) | Number of leaf-level diffs vs comparison snapshot. Spikes correlate with real config drift. | candidate |
| `parity.snapshot.diff.duration_ms` | histogram | hostname, mode | How long the recursive diff took. Spotting accidental O(n²) regressions. | candidate |
| `parity.snapshot.schedule.runs` | counter | schedule_id, hostname | Scheduled-snapshot fires (APScheduler triggered). | candidate |
| `parity.snapshot.schedule.missed` | counter | schedule_id, reason | A scheduled run skipped because a previous one was still running, or APScheduler misfired. | candidate |
| `parity.snapshot.concurrency` | gauge | — | Active snapshot threads (semaphore at 20). Saturation = batch snapshots are queueing. | candidate |
| `parity.snapshot.queue_depth` | gauge | — | Devices waiting to be snapshotted in the current run. | candidate |

---

## 5. Docker container health

`_collect_container_stats` in `self_monitor.py:207` reads stats from the Docker socket every minute and emits one event per container with `parity.self.category = "container"`. These are the metrics that prove *Parity itself* is healthy — distinct from the network it watches.

| Metric | Type | Dimensions | Description | Status |
|---|---|---|---|---|
| `parity.container.cpu_pct` | gauge | container_name | CPU usage percent per container. Backend pinned at 100% = stuck loop. | emitted |
| `parity.container.mem_mb` | gauge | container_name | RSS in MB. | emitted |
| `parity.container.mem_limit_mb` | gauge | container_name | Compose memory limit; ratio against `mem_mb` gives headroom %. | emitted |
| `parity.container.mem_pct` | gauge | container_name | Derived percentage. Easier to alert on than raw MB. | candidate |
| `parity.container.restarts` | counter | container_name | Docker `RestartCount`. Anything increasing = crash loop. | emitted |
| `parity.container.status` | enum gauge | container_name, status | running / exited / restarting / paused. | emitted (as property) |
| `parity.container.health` | enum gauge | container_name, health | Docker HEALTHCHECK state — healthy / unhealthy / starting / n/a. | emitted (as property) |
| `parity.container.net_rx_bytes` | counter | container_name, interface | Network bytes received. Helps spot a wedged worker that stopped polling. | candidate |
| `parity.container.net_tx_bytes` | counter | container_name, interface | Network bytes sent. | candidate |
| `parity.container.block_io_read_bytes` | counter | container_name | Disk read bytes. | candidate |
| `parity.container.block_io_write_bytes` | counter | container_name | Disk write bytes — useful for catching runaway snapshot persistence. | candidate |
| `parity.container.pids` | gauge | container_name | Process count inside the container. | candidate |
| `parity.container.uptime_s` | gauge | container_name | Seconds since last start. Pairs with `restarts` to make crash loops obvious. | candidate |
| `parity.host.disk.used_gb` | gauge | mount | Disk used on the host volume backing Postgres + Chroma. Snapshots aren't free — JSONB grows. | candidate |
| `parity.host.disk.free_gb` | gauge | mount | Free disk. The line that pages oncall before Postgres goes read-only. | candidate |
| `parity.host.disk.pct_used` | gauge | mount | Percent full. | candidate |

---

## 6. Findings (pipeline output)

Each finding emitted by the per-device pipeline is already pushed out as a `CUSTOM_DEPLOYMENT` Davis event (`emit_finding_created` / `emit_finding_resolved`). The aggregate counters below are the rollup view.

| Metric | Type | Dimensions | Description | Status |
|---|---|---|---|---|
| `parity.findings.created` | counter | severity, category, source (pyats/dynatrace), confidence_bucket | Findings raised. Splits cleanly by source so you can ask "what % of findings did Davis surface vs pyATS?". | emitted (per-event) |
| `parity.findings.resolved` | counter | severity, category, phase (auto/manual/timeout) | Findings closed. Phase distinguishes self-recovered vs operator-fixed vs Parity-remediated. | emitted (per-event) |
| `parity.findings.open` | gauge | severity, category | Currently open findings — should be query-derived from the events stream, or emitted as a periodic gauge. | emitted (rollup, by_<severity> dimensions in findings-rollup category) |
| `parity.findings.duration_s` | histogram | severity, category | Time-to-resolution (created → resolved). The SLA chart. | candidate |
| `parity.findings.dismissed` | counter | severity, reason | Operator-dismissed findings — high rate = noisy detector, tune the agent. | candidate |
| `parity.findings.dedupe_skipped` | counter | category | Findings the correlation step dropped as duplicates. Validates the correlator is working. | candidate |
| `parity.findings.with_recommendation` | counter | severity | Findings the recommendation agent produced commands for. Ratio vs total = recommendation coverage. | candidate |

---

## 7. Incidents (correlation output)

`backend/services/correlation.py` groups findings into incidents. Each incident is one operator-facing unit of work.

| Metric | Type | Dimensions | Description | Status |
|---|---|---|---|---|
| `parity.incidents.created` | counter | severity, device_count_bucket | New incidents. | candidate |
| `parity.incidents.findings_per_incident` | histogram | — | How many findings rolled up into one incident — measures correlation effectiveness. | candidate |
| `parity.incidents.cross_device` | counter | — | Incidents spanning >1 device. The hard ones. | candidate |
| `parity.incidents.entity_extraction_hits` | counter | entity_type (ipv4/intf/mac/prefix) | Entities pulled out of finding evidence to drive grouping. | candidate |
| `parity.incidents.resolved` | counter | phase | Incidents closed. | candidate |
| `parity.incidents.mean_time_to_correlate_ms` | histogram | — | Time from first finding to incident creation. | candidate |

---

## 8. Approvals + execution

`approval_service` and `execution_engine`. This is the human-in-the-loop layer — every metric here is audit-grade.

| Metric | Type | Dimensions | Description | Status |
|---|---|---|---|---|
| `parity.approvals.queued` | counter | severity, device_type | Approvals created from a recommendation. | candidate |
| `parity.approvals.approved` | counter | approver, severity | Operator approved. | emitted (approval category event w/ action=approved) |
| `parity.approvals.denied` | counter | approver, severity, reason | Operator denied. Reason text fed to the model improves future recs. | emitted (approval category event w/ action=denied) |
| `parity.approvals.expired` | counter | — | Pending approvals expired via TTL sweep. | emitted (approval category event w/ action=expired) |
| `parity.approvals.time_to_decision_s` | histogram | severity | Queue depth in human-time. The "is oncall responsive?" SLO. | emitted (approval event property time_to_decision_s) |
| `parity.approvals.orphaned_on_restart` | counter | — | Stuck-in-approved approvals reset by `_reset_orphaned_approvals` at boot. Anything > 0 is a hard signal. | candidate |
| `parity.execution.attempts` | counter | hostname, command_count | Approved-recommendation runs the executor started. | candidate |
| `parity.execution.success` | counter | hostname | Runs where every command completed without error. | emitted (approval event w/ action=executed, success=true) |
| `parity.execution.failures` | counter | hostname, phase (connect/exec/verify) | Failed runs, split by which phase broke. | emitted (approval event w/ action=execution_failed, success=false) |
| `parity.execution.duration_s` | histogram | hostname | End-to-end runtime (includes pre-flight snapshot + commands + verify snapshot). | candidate |
| `parity.execution.preflight.symptom_present` | counter | hostname, finding_category | Pre-flight check confirmed symptom — execution proceeded. | candidate |
| `parity.execution.preflight.symptom_resolved` | counter | hostname, finding_category | Symptom already gone — execution skipped. Catches self-healing & race conditions. | candidate |
| `parity.execution.commands_sent` | counter | hostname, command_type | Total CLI commands pushed to devices. Sanity-check on blast radius. | candidate |
| `parity.execution.verify.return_to_baseline` | counter | hostname, mode (golden/rolling) | Post-execution verify snapshot matched baseline — true confirmation of fix. | candidate |
| `parity.execution.verify.drift_remaining` | counter | hostname | Post-execution diff still showed changes vs golden. The "did it actually work?" miss column. | candidate |

---

## 9. ADK agent activity bus

`backend/services/activity.py` already classifies every agent step by node, model, model_tier, device, and outcome. It's an in-memory timeline today; emitting it as Davis events gives a permanent record.

| Metric | Type | Dimensions | Description | Status |
|---|---|---|---|---|
| `parity.agent.activity.started` | counter | node, model_tier, device | Agent node invocations. Node names: detect / investigate / reason / recommend / verify / chat. | candidate |
| `parity.agent.activity.completed` | counter | node, model_tier, device | Successful completions. | candidate |
| `parity.agent.activity.failed` | counter | node, model_tier, device, error_class | Failed steps. | candidate |
| `parity.agent.activity.duration_ms` | histogram | node, model_tier | Per-step latency. The chart that tells you which agent step is the slow one. | candidate |
| `parity.agent.activity.in_flight` | gauge | node | Currently running agent steps. | candidate |
| `parity.agent.history.depth` | gauge | — | Activity history buffer fill (capped at 100). Approaching cap = events generated faster than consumers can read. | candidate |
| `parity.agent.chat.tools_called` | counter | tool_name | Which chat-agent tools the model picked. Strongly biased usage hints at prompt issues. | candidate |
| `parity.agent.chat.tokens_per_turn` | histogram | — | Token spend per chat turn. | candidate |

---

## 10. Scheduler / cron

`backend/services/scheduler.py` runs APScheduler for inventory refresh + persistent snapshot schedules.

| Metric | Type | Dimensions | Description | Status |
|---|---|---|---|---|
| `parity.scheduler.jobs.registered` | gauge | — | Total APScheduler jobs in the store. | candidate |
| `parity.scheduler.jobs.fired` | counter | job_id, job_type | Job executions started. | candidate |
| `parity.scheduler.jobs.missed` | counter | job_id, reason | Coalesced or skipped fires. APScheduler signals these via listener events. | candidate |
| `parity.scheduler.jobs.duration_ms` | histogram | job_id | Per-job runtime. | candidate |
| `parity.scheduler.inventory.refresh_age_s` | gauge | — | Seconds since last inventory refresh — pairs with the API's `last_refreshed`. | candidate |
| `parity.scheduler.persistent_schedules.loaded` | gauge | — | Schedules hydrated from DB at boot. | candidate |

---

## 11. Dynatrace integration self-stats

The writer itself is worth measuring — silent fan-out failures are the easiest bug to miss.

| Metric | Type | Dimensions | Description | Status |
|---|---|---|---|---|
| `parity.dt.events.sent` | counter | event_type, action | Events accepted by `/events/ingest`. | candidate |
| `parity.dt.events.rejected` | counter | status_code | 4xx/5xx from Dynatrace ingest — wrong scope, malformed payload, throttled. | candidate |
| `parity.dt.logs.sent` | counter | severity | Log lines pushed if the logs:write scope was granted. | candidate |
| `parity.dt.bizevents.sent` | counter | type | BizEvents pushed if storage:bizevents:write was granted. | candidate |
| `parity.dt.metrics.sent` | counter | metric | Line-protocol metrics pushed. | candidate |
| `parity.dt.entities.registered` | counter | type | Custom devices created. | candidate |
| `parity.dt.capability.events` | gauge | — | 0/1 — events:write scope is live. | candidate |
| `parity.dt.capability.logs` | gauge | — | 0/1 — logs:write scope is live. | candidate |
| `parity.dt.capability.bizevents` | gauge | — | 0/1 — bizevents:write scope is live. | candidate |
| `parity.dt.capability.metrics` | gauge | — | 0/1 — metrics:write scope is live. | candidate |
| `parity.dt.capability.entities` | gauge | — | 0/1 — entities:write scope is live. | candidate |
| `parity.dt.dql.queries` | counter | query_kind | DQL queries the writer issued for read-back. | candidate |
| `parity.dt.dql.poll_failures` | counter | — | Grail polls that hit timeout or 4xx. | candidate |

---

## 12. Database — Postgres + ChromaDB

| Metric | Type | Dimensions | Description | Status |
|---|---|---|---|---|
| `parity.db.pool.size` | gauge | — | SQLAlchemy async engine pool size. | candidate |
| `parity.db.pool.checked_out` | gauge | — | Connections in use. Saturation = handler holding too long. | candidate |
| `parity.db.pool.wait_ms` | histogram | — | Time waiting for a free connection. | candidate |
| `parity.db.query.duration_ms` | histogram | table, operation | SQL latency. Add via SQLAlchemy event hooks. | candidate |
| `parity.db.transactions.rolled_back` | counter | reason | Failed transactions. | candidate |
| `parity.db.rows.snapshots.total` | gauge | — | Snapshot table size; pairs with disk usage chart. | candidate |
| `parity.db.rows.findings.total` | gauge | status | Findings by status. | candidate |
| `parity.db.rows.approvals.pending` | gauge | — | Pending approvals — operator-facing backlog. | candidate |
| `parity.vector.documents` | gauge | collection | ChromaDB document count per collection. | candidate |
| `parity.vector.query.duration_ms` | histogram | collection | Vector search latency. | candidate |
| `parity.vector.query.results_returned` | histogram | collection | Result-set size — catches empty-collection regressions. | candidate |

---

## 13. Inventory

`backend/services/inventory.py` reconciles devices from Grafana / topology source.

| Metric | Type | Dimensions | Description | Status |
|---|---|---|---|---|
| `parity.inventory.devices.total` | gauge | platform, device_type | Devices in the inventory. | candidate |
| `parity.inventory.devices.last_seen_age_s` | gauge | hostname | Per-device staleness — seconds since most-recent telemetry. The "is this device reachable?" line. | candidate |
| `parity.inventory.refresh.runs` | counter | result (ok/error) | Refresh executions. | candidate |
| `parity.inventory.refresh.duration_ms` | histogram | — | Reconciliation latency. | candidate |
| `parity.inventory.refresh.added` | counter | — | New devices discovered in this refresh. | candidate |
| `parity.inventory.refresh.removed` | counter | — | Devices missing from source. | candidate |

---

## 14. Process / Python runtime

Generic Python self-stats — cheap to collect from `psutil` + `gc`, useful for the "is the backend healthy" dashboard panel.

| Metric | Type | Dimensions | Description | Status |
|---|---|---|---|---|
| `parity.process.cpu_pct` | gauge | — | Backend process CPU. | candidate |
| `parity.process.rss_mb` | gauge | — | Resident memory. | candidate |
| `parity.process.threads` | gauge | — | OS threads. pyATS spawns these via `asyncio.to_thread`. | candidate |
| `parity.process.fds_open` | gauge | — | Open file descriptors. Leak detector. | candidate |
| `parity.process.uptime_s` | gauge | — | Seconds since boot. Resets indicate a restart even when the container restart count missed it. | candidate |
| `parity.process.gc.collections` | counter | generation | GC frequency. Spikes correlate with latency hiccups. | candidate |
| `parity.process.asyncio.tasks` | gauge | — | Live `asyncio.Task` count. The self-monitor itself plus snapshot workers contribute here. | candidate |
| `parity.process.event_loop.lag_ms` | gauge | — | Wall-clock vs scheduled sleep delta. Anything > a few hundred ms = the loop is starving. | candidate |

---

## 15. Integration touchpoints (Jira / Slack / Grafana)

Wrappers in `backend/integrations/`. None are wired to self-monitor today.

| Metric | Type | Dimensions | Description | Status |
|---|---|---|---|---|
| `parity.jira.tickets.created` | counter | severity, project | Jira tickets opened from findings/incidents. | candidate |
| `parity.jira.tickets.updated` | counter | transition | Status transitions. | candidate |
| `parity.jira.api.errors` | counter | endpoint, status_code | Jira REST failures. | candidate |
| `parity.slack.messages.sent` | counter | channel, severity | Slack notifications dispatched. | candidate |
| `parity.slack.api.errors` | counter | error | Slack rate limits / auth errors. | candidate |
| `parity.grafana.queries` | counter | datasource | Grafana / Prometheus reads from `integrations/grafana.py`. | candidate |
| `parity.grafana.query.duration_ms` | histogram | datasource | Per-query latency. | candidate |

---

## What gets emitted today vs. what's planned

The current minute-by-minute emission from `self_monitor._emit_self_to_dynatrace` covers:

- **Rollup event** (`category=rollup`) — HTTP req/error/latency, MCP calls/errors/latency, Gemini calls/errors/latency/tokens, snapshot count + duration + features, container count.
- **Per-container event** (`category=container`) — one per container with cpu/mem/restarts/status/health.
- **Per-snapshot event** (`category=snapshot`) — fired the moment each snapshot completes, with device, duration, feature_count, size, trigger.
- **Per-finding event** (`CUSTOM_DEPLOYMENT`) — every created/resolved finding, with severity/category/confidence/device/correlation_key/incident_id.

Everything tagged **candidate** above is a worthwhile next step but unimplemented. The recommended phasing:

1. **Promote rollup gauges to line-protocol metrics** so DQL chart panels are cheap. The event-stream rollup stays as the audit trail; the line-protocol metric becomes the live chart.
2. **Per-path HTTP + per-tool MCP histograms** — these counters already exist in `http_by_path` and `mcp_by_tool`; just flush them.
3. **Finding lifecycle counters** — the events are emitted; counting them in self-monitor closes the loop.
4. **Approval + execution metrics** — highest operator value (SLO charts) for least code (hook into `approval_service.mark_*` and `execution_engine.execute_approved`).
5. **Disk + process self-stats** — `psutil` one-liners; the dashboard "Parity host health" tile.
6. **Agent activity bus → events** — convert the in-memory `ActivityBus` history into Davis events so the demo's pipeline timeline is replayable after a restart.

Total catalog: **~140 distinct metrics across 15 areas**. About 18 emitted today; the rest are instrumentation points that already have a collection callsite in the code — they just need a line added to the periodic emitter.

---

# Part 2 — Network device metrics

Everything above is Parity-the-application reporting on itself. This section is Parity-the-network-tool reporting on the devices it watches. The numbers here are the ones the operator actually cares about for "is the network healthy?".

Three sources, all already wired into the codebase:

| Source | Mechanism | Cadence | Where it lives |
|---|---|---|---|
| **pyATS / Genie feature models** | SSH connect + `device.learn(<feature>)` returns a structured Python tree | Per snapshot (manual or scheduled, typically every 15–60 min) | `backend/services/snapshot_engine.py`, persisted to `snapshots.snapshot_data` JSONB |
| **SNMP via Telegraf → InfluxDB** | Telegraf polls each device every 60s, writes to measurements `cisco` / `fortinet`; Grafana proxies queries | Continuous (60s) | `backend/integrations/grafana.py` |
| **`run_show_command`** | Ad-hoc SSH show command via the chat agent's safe runner | On-demand | `backend/services/chat_tools.py` |

All device metrics carry **`hostname`** as a primary dimension; most carry one of **`interface`**, **`vrf`**, **`vlan`**, **`peer_ip`**, **`area`**, **`group`**, or **`protocol`** as a secondary. Most map cleanly to Dynatrace line-protocol metric ingest — a couple are better as events (interface flap, peer down moment).

Naming convention: `parity.net.<feature>.<measure>`. Feature names match the Genie module so the DQL filter is obvious.

---

## 16. Interface metrics (pyATS `interface` + SNMP)

The single biggest data surface. A 30-device homelab with ~12 interfaces per device is 360 interface objects per snapshot; each Genie interface entry exposes ~40 fields. Most are gauges; counters are taken as raw cumulative values so Dynatrace can rate them.

| Metric | Type | Dimensions | Description | Source |
|---|---|---|---|---|
| `parity.net.intf.admin_up` | enum gauge | hostname, interface | 1 if admin status = up, 0 otherwise. Operator-shutdown detector. | pyATS |
| `parity.net.intf.oper_up` | enum gauge | hostname, interface | 1 if line protocol = up. The single most important interface signal. | pyATS + SNMP `ifOperStatus` |
| `parity.net.intf.flap_count` | counter | hostname, interface | Count of oper-status transitions observed between snapshots. Computed by diffing. | derived |
| `parity.net.intf.last_change_age_s` | gauge | hostname, interface | Seconds since last status change. | pyATS + SNMP `ifLastChange` |
| `parity.net.intf.bandwidth_kbps` | gauge | hostname, interface | Configured bandwidth (Cisco BW). Pairs with utilization. | pyATS |
| `parity.net.intf.speed_mbps` | gauge | hostname, interface | Negotiated link speed. Drop from 1000→100 = autonegotiation regression. | pyATS + SNMP `ifSpeed` |
| `parity.net.intf.duplex_full` | enum gauge | hostname, interface | 1 = full duplex, 0 = half. Half on a trunk = bad day. | pyATS |
| `parity.net.intf.mtu` | gauge | hostname, interface | Configured MTU. Mismatch detection across a link. | pyATS + SNMP `ifMtu` |
| `parity.net.intf.in_octets` | counter | hostname, interface | Bytes received (raw cumulative, let Dynatrace compute rate). | SNMP `ifHCInOctets` |
| `parity.net.intf.out_octets` | counter | hostname, interface | Bytes sent. | SNMP `ifHCOutOctets` |
| `parity.net.intf.in_pkts` | counter | hostname, interface | Packets received. | SNMP `ifHCInUcastPkts` etc. |
| `parity.net.intf.out_pkts` | counter | hostname, interface | Packets sent. | SNMP `ifHCOutUcastPkts` etc. |
| `parity.net.intf.in_utilization_pct` | gauge | hostname, interface | Derived: `in_octets_rate × 8 / bandwidth`. Saturation chart. | derived |
| `parity.net.intf.out_utilization_pct` | gauge | hostname, interface | Derived outbound utilization. | derived |
| `parity.net.intf.in_errors` | counter | hostname, interface | Input errors total. Anything climbing = cabling / SFP / CRC. | pyATS + SNMP `ifInErrors` |
| `parity.net.intf.out_errors` | counter | hostname, interface | Output errors. | pyATS + SNMP `ifOutErrors` |
| `parity.net.intf.in_discards` | counter | hostname, interface | Input drops — usually QoS or buffer exhaustion. | pyATS + SNMP `ifInDiscards` |
| `parity.net.intf.out_discards` | counter | hostname, interface | Output drops. | pyATS + SNMP `ifOutDiscards` |
| `parity.net.intf.crc_errors` | counter | hostname, interface | CRC specifically — physical layer issue. | pyATS |
| `parity.net.intf.input_queue_drops` | counter | hostname, interface | Hold-queue drops on input ring. | pyATS |
| `parity.net.intf.output_queue_drops` | counter | hostname, interface | Hold-queue drops on output ring. | pyATS |
| `parity.net.intf.runts` | counter | hostname, interface | Short frames received. | pyATS |
| `parity.net.intf.giants` | counter | hostname, interface | Oversized frames. MTU mismatch fingerprint. | pyATS |
| `parity.net.intf.collisions` | counter | hostname, interface | Late + early collisions; half-duplex symptom. | pyATS |
| `parity.net.intf.broadcasts_in` | counter | hostname, interface | Broadcast packets received. Sudden spike = broadcast storm. | pyATS + SNMP |
| `parity.net.intf.multicasts_in` | counter | hostname, interface | Multicast packets received. | pyATS + SNMP |
| `parity.net.intf.encapsulation` | string property | hostname, interface, encap | ARPA / dot1q / mpls / pppoe — emit as event property, not metric. | pyATS |
| `parity.net.intf.vlan` | gauge | hostname, interface | Access VLAN ID (switches). | pyATS |
| `parity.net.intf.trunk_native_vlan` | gauge | hostname, interface | Native VLAN on a trunk. Mismatch = security finding. | pyATS |
| `parity.net.intf.trunk_allowed_count` | gauge | hostname, interface | Number of VLANs allowed on trunk. | pyATS |
| `parity.net.intf.ipv4.addresses` | gauge | hostname, interface | Count of v4 addresses. Going from 1→0 between snapshots = config drift. | pyATS |
| `parity.net.intf.ipv6.addresses` | gauge | hostname, interface | Count of v6 addresses. | pyATS |
| `parity.net.intf.port_channel.bundled` | enum gauge | hostname, port-channel, member | 1 if member is bundled in the LAG, 0 if suspended/standalone. | pyATS |
| `parity.net.intf.port_channel.member_count` | gauge | hostname, port-channel | Active members in bundle. Drop = redundancy loss. | pyATS |
| `parity.net.intf.qos.policy_applied` | enum gauge | hostname, interface, direction | 1 if a service-policy is bound. | pyATS |

---

## 17. OSPF metrics (pyATS `ospf`)

| Metric | Type | Dimensions | Description |
|---|---|---|---|
| `parity.net.ospf.processes` | gauge | hostname | Number of OSPF processes configured. |
| `parity.net.ospf.areas` | gauge | hostname, process_id | Areas the process participates in. |
| `parity.net.ospf.neighbors.total` | gauge | hostname, process_id, area | Total neighbors known. |
| `parity.net.ospf.neighbors.full` | gauge | hostname, area | Neighbors in FULL state. Should equal `total` on a healthy network. |
| `parity.net.ospf.neighbors.state` | enum gauge | hostname, peer_router_id, interface, state | One row per peer with state in {DOWN, ATTEMPT, INIT, 2WAY, EXSTART, EXCHANGE, LOADING, FULL}. |
| `parity.net.ospf.neighbors.uptime_s` | gauge | hostname, peer_router_id | Adjacency uptime — resets to 0 detect flaps. |
| `parity.net.ospf.neighbors.dead_timer_s` | gauge | hostname, interface | Configured dead interval. Mismatch fingerprint. |
| `parity.net.ospf.neighbors.hello_timer_s` | gauge | hostname, interface | Configured hello interval. |
| `parity.net.ospf.lsdb.lsa_count` | gauge | hostname, area, lsa_type | LSDB entries per type. Sudden growth = link flap or external advertisement bug. |
| `parity.net.ospf.spf.runs` | counter | hostname, process_id | SPF recalculation count. High rate = instability. |
| `parity.net.ospf.dr` | enum gauge | hostname, interface | 1 if this router is DR on the segment. |
| `parity.net.ospf.bdr` | enum gauge | hostname, interface | 1 if BDR. |
| `parity.net.ospf.retransmits` | counter | hostname, peer_router_id | Retransmitted LSAs — link quality signal. |

---

## 18. BGP metrics (pyATS `bgp`)

| Metric | Type | Dimensions | Description |
|---|---|---|---|
| `parity.net.bgp.local_as` | gauge | hostname, vrf | Local AS number — emit so DQL can group by AS. |
| `parity.net.bgp.peers.total` | gauge | hostname, vrf, afi_safi | Configured peer count. |
| `parity.net.bgp.peers.established` | gauge | hostname, vrf, afi_safi | Peers in Established state. Should equal `total`. |
| `parity.net.bgp.peer.state` | enum gauge | hostname, peer_ip, peer_as, state | One row per peer with state in {Idle, Connect, Active, OpenSent, OpenConfirm, Established}. |
| `parity.net.bgp.peer.uptime_s` | gauge | hostname, peer_ip | Session uptime. Reset = flap. |
| `parity.net.bgp.peer.prefixes_received` | gauge | hostname, peer_ip, afi_safi | Prefixes received from peer. Drop to 0 = peer withdrawn everything. |
| `parity.net.bgp.peer.prefixes_accepted` | gauge | hostname, peer_ip, afi_safi | Prefixes that passed inbound policy. |
| `parity.net.bgp.peer.prefixes_sent` | gauge | hostname, peer_ip, afi_safi | Prefixes advertised to peer. |
| `parity.net.bgp.peer.prefixes_denied` | counter | hostname, peer_ip | Prefixes filtered by inbound policy. |
| `parity.net.bgp.peer.last_reset_reason` | string property | hostname, peer_ip, reason | Property on a state-change event — emit when state changes. |
| `parity.net.bgp.peer.keepalive_s` | gauge | hostname, peer_ip | Configured keepalive timer. |
| `parity.net.bgp.peer.holdtime_s` | gauge | hostname, peer_ip | Hold timer. Mismatch with peer causes flap loops. |
| `parity.net.bgp.peer.messages_in` | counter | hostname, peer_ip | BGP messages received. |
| `parity.net.bgp.peer.messages_out` | counter | hostname, peer_ip | BGP messages sent. |
| `parity.net.bgp.peer.capabilities` | gauge | hostname, peer_ip, capability | One row per negotiated capability — `route-refresh`, `mp-bgp ipv4 unicast`, etc. |
| `parity.net.bgp.rib.prefixes.total` | gauge | hostname, vrf, afi_safi | Total prefixes in BGP table. |
| `parity.net.bgp.rib.prefixes.best` | gauge | hostname, vrf, afi_safi | Best-path prefixes installed in RIB. |

---

## 19. Routing table metrics (pyATS `routing`)

| Metric | Type | Dimensions | Description |
|---|---|---|---|
| `parity.net.routing.routes.total` | gauge | hostname, vrf, afi | Total routes in RIB. Drop to defaults-only = upstream withdrawn. |
| `parity.net.routing.routes.by_protocol` | gauge | hostname, vrf, protocol | Routes per protocol (connected, static, ospf, bgp, eigrp). |
| `parity.net.routing.default_route_present` | enum gauge | hostname, vrf | 1 if 0.0.0.0/0 in RIB, else 0. Reachability sanity check. |
| `parity.net.routing.next_hops.total` | gauge | hostname, vrf | Distinct next-hops in use. |
| `parity.net.routing.ecmp_paths.max` | gauge | hostname, vrf | Maximum parallel paths for any prefix. Catches lost LB paths. |
| `parity.net.routing.recursive_lookup_failures` | counter | hostname | Routes flagged as unresolved. |

---

## 20. ARP / Neighbor metrics (pyATS `arp`)

| Metric | Type | Dimensions | Description |
|---|---|---|---|
| `parity.net.arp.entries.total` | gauge | hostname, vrf, interface | ARP entries. Growth correlates with subnet host count. |
| `parity.net.arp.entries.static` | gauge | hostname | Static ARP entries (security-significant). |
| `parity.net.arp.entries.incomplete` | gauge | hostname | Incomplete entries — peer not responding. |
| `parity.net.arp.churn` | counter | hostname | Entries added/removed between snapshots. High churn = host churn or duplicate-IP. |
| `parity.net.arp.duplicate_ip_detected` | counter | hostname, ip | Count of IPs mapping to >1 MAC across the table. Hard finding. |

---

## 21. VLAN metrics (pyATS `vlan`, switches only)

| Metric | Type | Dimensions | Description |
|---|---|---|---|
| `parity.net.vlan.total` | gauge | hostname | VLANs configured. |
| `parity.net.vlan.active` | gauge | hostname | VLANs in active state. |
| `parity.net.vlan.suspended` | gauge | hostname | Suspended VLANs — almost always unintentional. |
| `parity.net.vlan.ports_assigned` | gauge | hostname, vlan_id | Access ports in a VLAN. |
| `parity.net.vlan.spans_orphaned` | gauge | hostname | VLANs with no member ports. Cruft detector. |

---

## 22. Spanning-tree metrics (pyATS `spanning_tree`, switches only)

| Metric | Type | Dimensions | Description |
|---|---|---|---|
| `parity.net.stp.mode` | enum gauge | hostname, mode (pvst/rapid-pvst/mst) | STP mode in use. |
| `parity.net.stp.instances` | gauge | hostname | STP instances (MST) or per-VLAN trees. |
| `parity.net.stp.root_for_vlan` | enum gauge | hostname, vlan_id | 1 if this switch is the root bridge. Useful for "did the root move?" alert. |
| `parity.net.stp.root_changes` | counter | hostname | Root changes observed across snapshots. Each is a topology event. |
| `parity.net.stp.topology_changes` | counter | hostname, vlan_id | TC count from `show spanning-tree`. |
| `parity.net.stp.ports.forwarding` | gauge | hostname, vlan_id | Ports in forwarding state. |
| `parity.net.stp.ports.blocking` | gauge | hostname, vlan_id | Ports in blocking. |
| `parity.net.stp.ports.alternate` | gauge | hostname, vlan_id | Alternate ports — RSTP fast-failover candidates. |
| `parity.net.stp.bpdu_guard_errdisabled` | counter | hostname, interface | BPDU-guard shutdowns. Each is a security event. |
| `parity.net.stp.loop_guard_inconsistent` | gauge | hostname, interface | Loop-guard-inconsistent ports. |

---

## 23. HSRP / FHRP metrics (pyATS `hsrp`)

| Metric | Type | Dimensions | Description |
|---|---|---|---|
| `parity.net.hsrp.groups` | gauge | hostname | HSRP groups configured. |
| `parity.net.hsrp.state` | enum gauge | hostname, group_id, interface, state | State in {Initial, Listen, Speak, Standby, Active}. The active/standby health line. |
| `parity.net.hsrp.priority` | gauge | hostname, group_id | Configured priority. |
| `parity.net.hsrp.preempt` | enum gauge | hostname, group_id | 1 if preempt configured. |
| `parity.net.hsrp.state_changes` | counter | hostname, group_id | Transitions observed between snapshots. Frequent flips = network issue. |
| `parity.net.hsrp.active_router` | string property | hostname, group_id, active_ip | Whose hostname/IP is Active. Emit as event property at transitions. |

---

## 24. VRF metrics (pyATS `vrf`)

| Metric | Type | Dimensions | Description |
|---|---|---|---|
| `parity.net.vrf.total` | gauge | hostname | VRFs configured. |
| `parity.net.vrf.interfaces_per_vrf` | gauge | hostname, vrf | Interfaces bound to each VRF. Drift = mis-configured customer port. |
| `parity.net.vrf.afi_count` | gauge | hostname, vrf | Active address-families (ipv4/ipv6). |
| `parity.net.vrf.rd` | string property | hostname, vrf, rd | Route distinguisher (event property, not metric). |

---

## 25. Platform / hardware metrics (pyATS `platform` + SNMP)

| Metric | Type | Dimensions | Description |
|---|---|---|---|
| `parity.net.platform.uptime_s` | gauge | hostname | Device uptime. Reset = unplanned reload. |
| `parity.net.platform.cpu_pct_5s` | gauge | hostname | CPU 5-second average. Spike-detection. |
| `parity.net.platform.cpu_pct_1m` | gauge | hostname | CPU 1-minute. |
| `parity.net.platform.cpu_pct_5m` | gauge | hostname | CPU 5-minute. Capacity planning. |
| `parity.net.platform.memory_used_bytes` | gauge | hostname, pool (processor/io) | Memory used by pool. |
| `parity.net.platform.memory_free_bytes` | gauge | hostname, pool | Free memory. |
| `parity.net.platform.memory_used_pct` | gauge | hostname, pool | Derived — easier alert target. |
| `parity.net.platform.modules.total` | gauge | hostname | Hardware modules present. |
| `parity.net.platform.modules.ok` | gauge | hostname | Modules in OK state. |
| `parity.net.platform.psu.total` | gauge | hostname | Power supplies present. |
| `parity.net.platform.psu.ok` | gauge | hostname | PSUs in OK state. Going from 2→1 is the redundancy-loss alert. |
| `parity.net.platform.fan.total` | gauge | hostname | Fans present. |
| `parity.net.platform.fan.ok` | gauge | hostname | Fans in OK state. |
| `parity.net.platform.temperature_c` | gauge | hostname, sensor | Per-sensor temperature reading. |
| `parity.net.platform.temperature_status` | enum gauge | hostname, sensor, status | normal / warning / critical / shutdown. |
| `parity.net.platform.image` | string property | hostname, version | Running IOS/IOS-XE/NX-OS version (event property). Image change = audit signal. |
| `parity.net.platform.serial` | string property | hostname, serial | Chassis serial — identity for Dynatrace custom-device mapping. |
| `parity.net.platform.config_register` | string property | hostname, value | Cisco config-register — wrong value at next reload = bricked device. |
| `parity.net.platform.last_reload_reason` | string property | hostname, reason | "power-on" / "reload command" / "watchdog" / "crash". Each event is a finding candidate. |

---

## 26. Diff / drift metrics (derived from snapshot comparison)

`get_snapshot_diff` in `snapshot_engine.py` produces rich diffs. The summary numbers are great Dynatrace gauges.

| Metric | Type | Dimensions | Description |
|---|---|---|---|
| `parity.net.diff.total_changes` | gauge | hostname, mode (rolling/golden), feature | Total leaf-level differences. |
| `parity.net.diff.added` | gauge | hostname, mode, feature | Keys added since baseline. |
| `parity.net.diff.removed` | gauge | hostname, mode, feature | Keys removed. |
| `parity.net.diff.changed` | gauge | hostname, mode, feature | Keys with value changes. |
| `parity.net.diff.baseline_age_s` | gauge | hostname | Age of the comparison snapshot. |
| `parity.net.drift.devices_with_diff` | gauge | feature | Across the fleet, how many devices diff from golden right now. |
| `parity.net.drift.score` | gauge | hostname | Composite drift score (weighted: oper-status changes > config changes > counter changes). |

---

## 27. Reachability / connectivity metrics (via `run_show_command` + SNMP)

The chat agent's safe runner supports `ping` / `traceroute` — same numbers Telegraf already collects. Easy to emit as either continuous metrics or on-demand probe events.

| Metric | Type | Dimensions | Description |
|---|---|---|---|
| `parity.net.reach.icmp.success` | enum gauge | hostname, target | 1 if last ping succeeded. |
| `parity.net.reach.icmp.rtt_ms` | gauge | hostname, target | Round-trip time. |
| `parity.net.reach.icmp.loss_pct` | gauge | hostname, target | Loss across the probe burst (typically 5 packets). |
| `parity.net.reach.traceroute.hop_count` | gauge | hostname, target | Hop count to destination — change indicates path change. |
| `parity.net.reach.traceroute.changed` | counter | hostname, target | Path diffs between snapshots. |
| `parity.net.snmp.reachable` | enum gauge | hostname | 1 if Telegraf got a response in the last poll interval. The Davis-friendly availability signal. |
| `parity.net.ssh.reachable` | enum gauge | hostname | 1 if last pyATS snapshot connected successfully. |

---

## 28. Security / configuration findings (derived)

The detect agent already emits findings for many of these; lifting the *categories* into counter metrics gives a rolled-up trend chart in Dynatrace.

| Metric | Type | Dimensions | Description |
|---|---|---|---|
| `parity.net.security.aaa_misconfig` | gauge | hostname | 1 if AAA isn't configured correctly. |
| `parity.net.security.snmp_v2_in_use` | gauge | hostname | 1 if v2c community strings present (compliance hit). |
| `parity.net.security.default_credentials` | gauge | hostname | 1 if a default username is configured. |
| `parity.net.security.acl_count` | gauge | hostname | ACLs configured. |
| `parity.net.security.acl_hit_counters` | counter | hostname, acl, sequence | ACE hit counts from `show access-list`. |
| `parity.net.security.failed_logins` | counter | hostname | Login failures from `show login`. |
| `parity.net.security.unsaved_config` | enum gauge | hostname | 1 if running-config != startup-config (lost on reload). |
| `parity.net.config.lines` | gauge | hostname | running-config line count. Sudden drop = someone wiped config. |
| `parity.net.config.last_change_age_s` | gauge | hostname | Time since last config change (from `show running-config | include Last config`). |

---

## Volume estimate

For a 30-device homelab (mix of routers + switches), at the metric counts above:

- **Interface metrics**: 30 devices × ~12 interfaces × ~35 metrics ≈ **12,600 series**
- **OSPF**: 30 × ~5 neighbors × ~13 metrics ≈ **2,000 series**
- **BGP**: 30 × ~4 peers × ~17 metrics ≈ **2,000 series**
- **Routing**: 30 × ~5 VRFs × ~6 metrics ≈ **900 series**
- **ARP / VLAN / STP / HSRP / VRF / Platform**: ≈ **3,000 series combined**
- **Diff / drift / reachability / security**: ≈ **1,500 series**

That's roughly **22,000 device time-series** per snapshot cadence. Add the ~140 Parity self-metrics and the headline is **about 22k device + 140 self = ~22,000 total series**. Well within Dynatrace's per-tenant limits, but worth being deliberate about which we send as line-protocol metrics (cheap to chart, every minute) vs. event properties (richer, but discrete).

**Recommended split:**
- **Send as metrics** every minute: interface counters/utilization, BGP/OSPF state-up totals, CPU/mem/temp, prefix counts, reachability, diff totals.
- **Send as events** on transition: interface flap, BGP peer state change, OSPF adjacency change, HSRP state change, STP root change, config change, reload, security finding raised.
- **Send as bizevents**: every approval lifecycle moment (queued → approved → executed → verified) so the Davis workflow side can drive automation.

