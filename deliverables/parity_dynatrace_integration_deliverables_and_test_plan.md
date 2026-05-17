# Parity-Dynatrace Integration Deliverables & Test Plan

## Overview

This document defines the architecture, deliverables, telemetry strategy, and validation test plans for integrating the internal platform **Parity-Dynatrace** into an observability ecosystem powered by:

- Cisco network intelligence (pyATS-based)
- Google Gemini reasoning agent
- Dynatrace observability platform

Parity-Dynatrace is a **containerised observability and intelligence layer** that sits between infrastructure and observability systems.

It is responsible for:

> Generating high-quality, enriched telemetry about the behaviour of the *platform itself*, and feeding it into Dynatrace for full-stack observability.

---

# 1. System Definition

## Parity-Dynatrace (P-DT)

Parity-Dynatrace is a distributed Docker-based system composed of:

- Network intelligence ingestion services
- AI reasoning agents (Gemini)
- Correlation and event synthesis engines
- API orchestration services
- Telemetry exporters
- Internal observability probes

It generates:

- Internal application metrics
- Workflow traces
- Agent reasoning logs
- Tool usage telemetry
- Correlation outputs
- System health signals

---

# 2. Integration Objective

The goal is to provide **recursive observability**:

> Dynatrace observes Parity-Dynatrace, which itself observes networks and Dynatrace.

This enables:

- Full-stack visibility of the reasoning system itself
- Debugging of AI decisions
- Operational transparency of tool usage
- Performance tracking of correlation logic
- Failure detection inside the intelligence layer

---

# 3. Observability Targets (Inside Parity-Dynatrace)

Parity-Dynatrace must expose telemetry for:

## 3.1 AI Agent Behaviour

- Prompt execution count
- Tool calls per session
- Tool latency
- Reasoning depth (number of steps)
- Confidence score distributions
- Hallucination detection flags

---

## 3.2 Correlation Engine

- Event correlation latency
- Match confidence scores
- False correlation rate
- Timeline reconstruction accuracy

---

## 3.3 Network Intelligence Pipeline

- pyATS ingestion latency
- snapshot diff processing time
- topology resolution success rate
- failed parsing events

---

## 3.4 Dynatrace Integration Layer

From entity["company","Dynatrace","software observability and application performance monitoring company"]:

- API request success/failure rate
- API latency (Problems, Metrics, Topology)
- ingestion throughput
- event enrichment delay

Official API reference:
https://docs.dynatrace.com/docs/discover-dynatrace/references/dynatrace-api

---

## 3.5 Container & Runtime Layer

- CPU usage per container
- Memory usage per service
- Restart counts
- Docker health status
- Inter-service latency

---

## 3.6 Gemini Agent Layer

- prompt execution time
- token usage per request
- tool call success/failure
- reasoning chain length
- hypothesis count per incident

---

# 4. Telemetry Export Architecture

## 4.1 Export Flow

```text
Parity-Dynatrace Services
        ↓
Telemetry Aggregation Layer
        ↓
OpenTelemetry Collector
        ↓
Dynatrace Ingestion API
        ↓
Dynatrace Observability Platform
```

---

## 4.2 Telemetry Types

### Metrics
- agent_latency_ms
- correlation_confidence_score
- tool_call_success_rate
- dynatrace_api_latency

### Logs
- agent reasoning traces
- tool invocation logs
- error traces
- correlation decisions

### Traces
- end-to-end request flows
- agent → tool → response chains
- cross-service execution graphs

---

# 5. Key Deliverables

---

# Deliverable 1 — Internal Telemetry Instrumentation Layer

## Objective
Instrument all Parity-Dynatrace services for observability.

## Requirements

- OpenTelemetry instrumentation across all services
- Standardised metric naming conventions
- Structured JSON logging
- Trace context propagation
- Correlation IDs across all agent actions

## Validation

- 100% service coverage
- No uninstrumented containers
- Trace continuity across service boundaries

---

# Deliverable 2 — Gemini Agent Observability Exporter

## Objective
Expose internal AI reasoning as observability signals.

## Requirements

- Export tool usage metrics
- Export reasoning depth metrics
- Export confidence scores
- Export failure and retry events

## Example Metrics

- gemini_prompt_duration_ms
- gemini_tool_calls_total
- gemini_confidence_score

## Validation

- Every agent invocation produces trace
- Tool usage always logged
- No silent failures

---

# Deliverable 3 — Correlation Engine Telemetry Layer

## Objective
Expose correlation logic as first-class observability data.

## Requirements

- Emit correlation confidence per event
- Emit matched vs unmatched event ratios
- Emit timeline reconstruction accuracy

## Validation

- 100% correlation decisions are traceable
- No hidden heuristic decisions

---

# Deliverable 4 — Dynatrace Feedback Loop Integration

## Objective
Parity-Dynatrace must both:
- ingest Dynatrace data
- emit enriched Dynatrace-compatible telemetry back into Dynatrace

## Requirements

- Event enrichment forwarding
- Synthetic problem generation for validation
- Custom event types for network intelligence

## Validation

- Enriched events appear in Dynatrace UI
- Events correlate correctly with original problems

---

# Deliverable 5 — System Health Model

## Objective
Model Parity-Dynatrace itself as a monitored system.

## Requirements

- Define service health scores
- Track degradation in internal pipelines
- Detect AI reasoning slowdowns
- Monitor tool failure rates

## Example Health Signals

- Agent degradation score
- Correlation engine instability index
- ingestion backlog size

## Validation

- System can self-report degradation
- Alerts generated when internal pipelines fail

---

# Deliverable 6 — Recursive Observability Integration

## Objective
Enable Dynatrace to observe Parity-Dynatrace observing Dynatrace.

## Requirements

- Avoid feedback loops
- Detect recursive event amplification
- Prevent alert storms

## Validation

- No infinite alert recursion
- Controlled event propagation

---

# Deliverable 7 — Performance Benchmarking Framework

## Objective
Measure efficiency of AI-driven observability system.

## Metrics

- End-to-end insight generation latency
- Tool call efficiency
- Correlation accuracy under load
- System throughput under incident spikes

## Validation

- System maintains SLA under load
- Degradation patterns are measurable

---

# Deliverable 8 — Observability Data Schema Standardisation

## Objective
Standardise all emitted telemetry.

## Requirements

- Consistent naming conventions
- OpenTelemetry compliance
- Structured event schema
- Versioned telemetry contracts

## Validation

- Schema validation enforced
- No unstructured telemetry in production

---

# 6. Test Plan

---

# Category A — Telemetry Integrity

## Test A1 — Full Instrumentation Coverage

### Scenario
Verify all services emit telemetry.

### Pass Criteria
- No missing spans
- No uninstrumented containers

---

## Test A2 — Trace Continuity

### Scenario
Single request through system.

### Pass Criteria
- End-to-end trace exists
- No broken spans

---

# Category B — AI Observability Correctness

## Test B1 — Agent Visibility

### Scenario
Trigger multiple Gemini reasoning calls.

### Pass Criteria
- All reasoning steps logged
- Tool calls visible in traces

---

## Test B2 — Tool Call Accuracy

### Scenario
Induce tool failure.

### Pass Criteria
- Failure logged correctly
- Retry captured

---

# Category C — Dynatrace Integration Validation

## Test C1 — Event Ingestion

### Scenario
Emit synthetic telemetry into Dynatrace.

### Pass Criteria
- Event appears in Dynatrace UI

---

## Test C2 — Problem Correlation

### Scenario
Inject Dynatrace problem + internal event.

### Pass Criteria
- Correct correlation displayed

---

# Category D — Recursive Observability Safety

## Test D1 — Feedback Loop Prevention

### Scenario
Generate Dynatrace alert from Parity-DT event.

### Pass Criteria
- No infinite alert loop
- Controlled propagation

---

## Test D2 — Event Amplification Control

### Scenario
High-volume telemetry spike.

### Pass Criteria
- System remains stable
- No cascading alert storms

---

# Category E — System Health Modelling

## Test E1 — Internal Degradation Detection

### Scenario
Slow correlation engine.

### Pass Criteria
- Self-alert generated
- Health score reduced

---

## Test E2 — Container Failure Recovery

### Scenario
Restart Gemini container.

### Pass Criteria
- Recovery detected
- No data loss

---

# Category F — Performance & Scale

## Test F1 — High Load Scenario

### Scenario
1000 concurrent events.

### Pass Criteria
- No data loss
- Acceptable latency maintained

---

## Test F2 — Burst Traffic Handling

### Scenario
Incident spike simulation.

### Pass Criteria
- System remains responsive

---

# 7. Key Success Metrics

| Metric | Target |
|------|--------|
| Telemetry coverage | 100% |
| Trace completeness | >98% |
| Agent observability coverage | 100% |
| Correlation accuracy | >85% |
| Internal system MTTR visibility | <1 min |
| Dynatrace ingestion success rate | >99% |
| Recursive loop prevention success | 100% |

---

# 8. Architectural Principle

Parity-Dynatrace is not just a toolchain.

It is a:

> self-observing intelligence layer that generates its own operational truth signals.

The defining capability is:

- It observes infrastructure
- It observes applications
- It observes itself
- It emits all three as unified telemetry into Dynatrace

---

# 9. Final Statement

The system succeeds when:

> Every decision made by AI, every tool call, and every correlation can be reconstructed, observed, and validated inside Dynatrace as a first-class operational signal.

## Evidence — as-built attestation (2026-05-16 20:01 UTC, build 3715998)

### PD-1.1 OpenTelemetry instrumentation across all services

- **Status:** PARTIAL — Davis-events telemetry, not OTel-native yet
- **Detail:** Self-monitor sends every observability signal as CUSTOM_INFO Davis events (parity-self source); OpenTelemetry SDK migration is the eventual canonical path but events already serve the equivalent role for Davis.
- **Artefacts:**
    - code: backend/services/self_monitor.py

### PD-1.2 Standardized metric naming

- **Status:** EMITTED — verified live
- **Detail:** All metrics follow parity.<area>.<name> convention. Live DQL: rollup=29, container=174, snapshot=2, net-*=661 events in last hour.
- **Artefacts:**
    - code: backend/services/self_monitor.py + device_metrics_emitter.py
    - doc: metrics.md (140+ self metrics, ~22k device series catalogued)

### PD-1.3 Structured JSON logging + trace context propagation

- **Status:** PARTIAL
- **Detail:** All backend logs are structlog JSONRenderer-emitted. Trace context propagation across MCP/HTTP boundaries is a candidate — would require W3C trace-context headers.
- **Artefacts:**
    - code: backend/main.py (structlog config)

### PD-2.1 Tool usage metrics export

- **Status:** EMITTED — verified live
- **Detail:** mcp_call_timed wraps every tool call; per-tool counts in mcp_by_tool dict; aggregated to Davis via rollup events. Confirmed via DQL.
- **Artefacts:**
    - code: backend/services/self_monitor.py:mcp_call_timed
    - dql confirm: 29 rollup events with mcp_calls_60s in last hour

### PD-2.2 Reasoning depth + confidence export

- **Status:** EMITTED — implemented
- **Detail:** Every finding event carries parity.severity, parity.category, parity.confidence as properties. Per-event queryable via DQL.
- **Artefacts:**
    - code: backend/integrations/dynatrace.py:DynatraceWriter._finding_payload

### PD-2.3 Failure and retry event tracking

- **Status:** EMITTED — verified live
- **Detail:** mcp_error_counter + gemini_error_counter + http_error_counter all roll up; DT writer self-stats (dt_events_sent / dt_events_rejected) added.
- **Artefacts:**
    - code: backend/services/self_monitor.py — dt_events_record

### PD-3.1 Correlation confidence per event

- **Status:** EMITTED — verified live
- **Detail:** Every CUSTOM_DEPLOYMENT event Parity fires includes parity.confidence and parity.correlation_key — DQL-queryable.
- **Artefacts:**
    - code: backend/integrations/dynatrace.py:_finding_payload

### PD-3.2 Matched vs unmatched event ratio tracking

- **Status:** EMITTED — verified live (build 20a3050)
- **Detail:** Self-monitor rollup `davis-coverage-rollup` emits `parity.findings.with_davis_pct` every minute with `with_davis`, `without_davis`, `total` dimensions. Computed from a 1h Finding scan in `_collect_davis_assessment_ratio`, with the same rejection-string filter the FindingRead validator uses so the percentage reflects *usable* Davis assessments.
- **Artefacts:**
    - code: backend/services/self_monitor.py:_collect_davis_assessment_ratio
    - metric: parity.findings.with_davis_pct (category=davis-coverage-rollup)

### PD-4.1 Event enrichment forwarding

- **Status:** EMITTED — verified live
- **Detail:** Davis Workflow 'parity · open Davis problem on high-severity finding' (id 1dd0daeb-…) fires on every parity event with severity in {high,critical} and relays as Davis AVAILABILITY events.
- **Artefacts:**
    - workflow: https://kea15603.apps.dynatrace.com/ui/apps/dynatrace.automations/workflows/1dd0daeb-2f5c-4c7b-b630-85d8f3b589a3

### PD-4.2 Synthetic problem generation for validation

- **Status:** EMITTED — implemented
- **Detail:** Davis problem stub (docker/dynatrace-mcp-stub) admin endpoints let the test suite flip canned problem state to drive end-to-end lifecycle scenarios (Scenario D / DT-4.1 PASS).
- **Artefacts:**
    - code: docker/dynatrace-mcp-stub/server.py — /admin/close-problem, /admin/reopen-problem

### PD-4.3 Custom event types for network intelligence

- **Status:** EMITTED — verified live
- **Detail:** Two distinct event types in use today: CUSTOM_DEPLOYMENT for finding lifecycle, CUSTOM_INFO for parity-self/network-device metrics. Categories pivot via parity.self.category and parity.action.
- **Artefacts:**
    - code: backend/integrations/dynatrace.py:DynatraceWriter

### PD-5.1 Service health scores

- **Status:** EMITTED — verified live (build 20a3050)
- **Detail:** Per-minute composite `parity.health.score` ∈ [0,100] emitted from the self-monitor rollup. Weighted: container_ratio×0.4 + api_success_rate×0.3 + mcp_success_rate×0.3. Each input dimension is also surfaced as a property so a dashboard tile can break it down. Single-number "is Parity itself healthy right now" signal.
- **Artefacts:**
    - code: backend/services/self_monitor.py:_emit_self_to_dynatrace (health-score block)
    - metric: parity.health.score (category=health-score)

### PD-5.2 Pipeline degradation detection

- **Status:** EMITTED — workflow wired
- **Detail:** Parity self-watchdog Davis Workflow (b091a255-…) fires on any parity-self/container with status != 'running' — turns container unhealth into a Davis-relayed event.
- **Artefacts:**
    - workflow: https://kea15603.apps.dynatrace.com/ui/apps/dynatrace.automations/workflows/b091a255-8edb-4d3c-a8a4-36ba7ee6162b

### PD-5.3 AI reasoning slowdown detection

- **Status:** PARTIAL — data captured, alert not yet
- **Detail:** gemini_avg_latency_ms + mcp_avg_latency_ms in every rollup; the Self-Monitoring dashboard charts both. Davis anomaly-detection analyzer on those series would surface slowdowns.
- **Artefacts:**
    - dashboard: https://kea15603.apps.dynatrace.com/ui/apps/dynatrace.dashboards/dashboard/parity-self-monitor-dashboard-v1

### PD-6.1 Feedback loop prevention

- **Status:** EMITTED — by design
- **Detail:** Self-monitor events carry source==parity-self (NOT source==parity), so they cannot retrigger the finding-relay workflow which only matches source==parity.
- **Artefacts:**
    - code: backend/services/self_monitor.py:emit_self_metric

### PD-6.2 Event amplification control

- **Status:** EMITTED — paced
- **Detail:** Network device emitter throttles to ~50 events/s via 20ms sleep; MCP test suite throttled to 5/20s rate limit; finding emission is one-per-lifecycle-moment.
- **Artefacts:**
    - code: backend/services/device_metrics_emitter.py — _PACE_SLEEP_S = 0.02

### PD-7.1 End-to-end insight latency measurement

- **Status:** EMITTED — verified live
- **Detail:** Snapshot duration + reasoner latency captured per-finding; deliverables suite measures end-to-end remediation loop time (DT-2.1 PASS: ~84s create-to-Davis).
- **Artefacts:**
    - test: scripts/deliverables_test_suite.py:deliverable_2 (DT-2.1 timing)

### PD-7.2 Correlation accuracy under load

- **Status:** PARTIAL — small-fleet only
- **Detail:** Cross-platform AI tests verify correlation correctness (CrossAI Causality Accuracy PASS — distinct incidents for unrelated drift). Sustained load is a candidate.
- **Artefacts:**
    - test: scripts/deliverables_test_suite.py:cross_platform_ai (Causality Accuracy PASS)

### PD-8.1 Consistent naming and OpenTelemetry compliance

- **Status:** EMITTED — consistent naming
- **Detail:** All Parity events use parity.<area>.<name> attributes. metrics.md catalogues every metric + dimensions. Full OTel compliance is a candidate (currently Davis CUSTOM_INFO not OTel resource model).
- **Artefacts:**
    - doc: metrics.md

### PD-8.2 Schema versioning

- **Status:** EMITTED — verified live (build 20a3050)
- **Detail:** Every parity / parity-self event now carries `parity.schema_version="2"`. Downstream DQL panels filter on it so a future v3 rollout doesn't silently merge with v2 data. Added in both `_finding_payload` (CUSTOM_DEPLOYMENT events) and `emit_self_metric` (CUSTOM_INFO events).
- **Artefacts:**
    - code: backend/integrations/dynatrace.py:DynatraceWriter._finding_payload + emit_self_metric

