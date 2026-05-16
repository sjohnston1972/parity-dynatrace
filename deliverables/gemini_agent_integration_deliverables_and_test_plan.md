# Gemini Agent Integration Deliverables & Test Plan

## Overview

This document defines the deliverables, architecture, tool access model, behaviours, and validation test plans for integrating a Google Gemini-based reasoning agent into an existing network intelligence platform.

The existing platform already includes:

- Cisco pyATS-based network state collection
- Structured snapshot comparison and diff engine
- AI-driven network insight generation
- Dynatrace observability integration
- Correlation engine between network changes and runtime telemetry

The Gemini agent extends this system into:

> A multi-tool autonomous network reasoning and investigation engine.

The goal is to evolve the agent from a passive diff analyser into an active investigative and orchestration layer.

---

# Agent Definition

## Primary Role

The Gemini agent operates as:

### Network Intelligence Orchestrator Agent

It is responsible for:

- Autonomous investigation of network changes and incidents
- Tool-driven data gathering across network and observability systems
- Hypothesis generation and validation
- Root cause analysis and correlation reasoning
- Risk prediction and change impact assessment
- Narrative generation for technical and executive audiences

---

# Core Capabilities

The agent must support the following functional domains:

## 1. Change Analysis

- Interpret pyATS diffs semantically
- Identify intent behind configuration changes
- Classify risk levels of changes
- Predict potential impact domains

## 2. Incident Investigation

- Pull and analyse runtime incidents
- Correlate network changes with service degradation
- Construct event timelines
- Identify root cause candidates

## 3. Topology Reasoning

- Understand network graphs and dependencies
- Map service-to-infrastructure relationships
- Perform path tracing and blast radius analysis

## 4. Hypothesis Engine

- Generate multiple possible causes
- Rank hypotheses by likelihood
- Request additional data when required
- Validate or reject hypotheses using tools

## 5. Predictive Risk Analysis

- Forecast impact of planned changes
- Identify high-risk configurations before deployment
- Detect instability patterns

## 6. Post-Change Validation

- Confirm intended outcomes
- Detect unintended side effects
- Compare pre and post state with runtime telemetry

---

# Tooling Model

The Gemini agent must operate as a tool-using system.

Each tool call must be deterministic, structured, and auditable.

---

# Core Tool Set

## A. Network State Tools (pyATS Domain)

### 1. get_network_snapshot
Returns structured device state across the estate.

### 2. diff_snapshots
Performs semantic comparison between two network states.

### 3. get_device_neighbors
Returns CDP/LLDP adjacency data.

### 4. get_routing_table
Retrieves BGP/OSPF/IS-IS routing information.

### 5. get_interface_health
Returns interface statistics including errors, drops, utilisation.

---

## B. Observability Tools (Dynatrace Domain)

### 6. get_problems
Retrieves active incidents and alerts.

### 7. get_service_topology
Returns service dependency graphs.

### 8. get_metrics
Retrieves performance telemetry (latency, errors, throughput).

### 9. get_anomalies
Returns AI-detected anomalies.

### 10. get_traces
Retrieves distributed transaction traces.

---

## C. Correlation Tools

### 11. correlate_event_timeline
Combines:
- network changes
- telemetry anomalies
- incident timelines

### 12. find_nearby_changes
Detects concurrent or competing changes in time window.

---

## D. Topology and Path Analysis Tools

### 13. trace_network_path
Computes actual network forwarding path between endpoints.

### 14. map_service_dependency
Maps application services to infrastructure components.

### 15. blast_radius_analysis
Determines downstream impact of a failure or change.

---

## E. Knowledge and Learning Tools

### 16. retrieve_similar_incidents
Finds historical incidents with similar signatures.

### 17. get_remediation_history
Retrieves previously successful fixes.

---

## F. Adaptive Investigation Tools

### 18. request_additional_data
Allows agent to request missing telemetry or state information.

---

# Agent Operating Modes

The agent must support multiple operational modes:

## Mode 1 — Diff Analyst
- Focus: configuration and state changes
- Output: change explanation and risk

## Mode 2 — Incident Investigator
- Focus: Dynatrace problems and telemetry
- Output: root cause and timeline

## Mode 3 — Change Risk Reviewer
- Focus: predictive analysis before deployment
- Output: risk forecast and warnings

## Mode 4 — Forensic Investigator
- Focus: post-incident deep analysis
- Output: full RCA report

## Mode 5 — Network Detective
- Focus: recursive tool-based exploration
- Output: evidence-driven discovery

---

# Agent Workflow

The agent must follow a structured investigation loop:

## Step 1 — Trigger Detection
- change event OR incident OR user query

## Step 2 — Hypothesis Generation
- generate multiple plausible causes

## Step 3 — Tool Execution
- query network state
- query observability platform
- gather topology data

## Step 4 — Correlation Analysis
- align timestamps
- evaluate dependencies
- score likelihoods

## Step 5 — Decision Making
- select root cause or ranked causes

## Step 6 — Evidence-Based Output
- include reasoning
- include confidence scoring
- include supporting data references

---

# Deliverables

## Deliverable 1 — Tool-Enabled Agent Framework

### Objective
Implement Gemini as a tool-using orchestration agent.

### Requirements
- Structured tool calling interface
- Audit logging of all tool usage
- Deterministic tool response parsing
- Support for multi-step reasoning chains

### Validation
- All tool calls must be logged
- No hallucinated data without tool verification

---

## Deliverable 2 — Multi-Source Correlation Engine

### Objective
Correlate network changes with runtime observability data.

### Requirements
- Temporal alignment engine
- Cross-domain correlation logic
- Confidence scoring model

### Output Example
- Change → impact mapping
- Service-level impact identification

---

## Deliverable 3 — Hypothesis Generation Engine

### Objective
Enable multi-cause reasoning for incidents.

### Requirements
- Generate multiple candidate causes
- Rank hypotheses by likelihood
- Validate using tools

### Validation
- At least 2 competing hypotheses for non-trivial incidents

---

## Deliverable 4 — Service Impact Mapping

### Objective
Map infrastructure changes to business services.

### Requirements
- Service dependency resolution
- Blast radius calculation
- Application-to-network mapping

---

## Deliverable 5 — Risk Prediction Engine

### Objective
Predict impact of proposed or detected changes.

### Requirements
- Pre-change risk scoring
- Impact prediction across services
- Confidence-adjusted scoring

---

## Deliverable 6 — Incident Timeline Reconstruction

### Objective
Reconstruct full event timeline from multiple sources.

### Requirements
- Merge network and observability events
- Build chronological incident narrative
- Highlight causal sequence

---

## Deliverable 7 — Evidence-Based Reasoning Framework

### Objective
Ensure all conclusions are backed by evidence.

### Requirements
- Every claim must reference tool output
- Confidence scoring required
- Explicit uncertainty handling

---

## Deliverable 8 — Executive and Technical Reporting

### Objective
Generate audience-specific outputs.

### Requirements
- Technical RCA format
- Executive summary format
- CAB/change management summary format

---

# Test Plan

---

## Category A — Tool Usage Validation

### Test A1 — Mandatory Tool Enforcement

Ensure agent:
- does not answer without tool usage when data is required

Pass Criteria:
- no unsupported assumptions

---

### Test A2 — Multi-Tool Orchestration

Scenario:
- incident requiring network + observability data

Pass Criteria:
- correct sequencing of tool calls

---

## Category B — Correlation Accuracy

### Test B1 — True Positive Correlation

Inject:
- network QoS change
- latency increase

Pass Criteria:
- correct causal attribution

---

### Test B2 — False Correlation Resistance

Inject:
- unrelated application failure
- benign network change

Pass Criteria:
- no incorrect attribution

---

## Category C — Hypothesis Testing

### Test C1 — Multi-Cause Incident

Scenario:
- multiple simultaneous changes

Pass Criteria:
- ranked hypotheses provided

---

### Test C2 — Insufficient Evidence

Scenario:
- missing telemetry

Pass Criteria:
- agent explicitly states uncertainty

---

## Category D — Topology Reasoning

### Test D1 — Path Accuracy

Validate:
- correct service dependency mapping

Pass Criteria:
- no incorrect topology assumptions

---

### Test D2 — Blast Radius Calculation

Scenario:
- core link failure

Pass Criteria:
- all impacted services identified

---

## Category E — Risk Prediction

### Test E1 — High Risk Change Detection

Scenario:
- routing policy modification

Pass Criteria:
- elevated risk score

---

### Test E2 — Benign Change Detection

Scenario:
- unused config cleanup

Pass Criteria:
- low risk score

---

## Category F — Reasoning Integrity

### Test F1 — Hallucination Prevention

Scenario:
- incomplete tool data

Pass Criteria:
- agent does not fabricate causes

---

### Test F2 — Confidence Calibration

Scenario:
- conflicting signals

Pass Criteria:
- reduced confidence and explanation of uncertainty

---

# Key Success Metrics

| Metric | Target |
|------|--------|
| Correlation accuracy | >85% |
| False attribution rate | <10% |
| Tool usage compliance | 100% when required |
| Hallucination rate | Near zero |
| Confidence calibration accuracy | High |
| Topology mapping accuracy | >95% |
| Incident reconstruction completeness | >90% |

---

# Final Principle

The Gemini agent must function not as a passive reasoning model, but as an active investigative system that:

- interrogates infrastructure
- queries observability systems
- builds evidence-based narratives
- continuously validates hypotheses

Its success is defined by:

> correctness of reasoning grounded in tool-derived evidence, not language fluency alone.

## Evidence — as-built attestation (2026-05-16 20:01 UTC, build 3715998)

### GA-1.1 Structured tool calling interface

- **Status:** EMITTED — implemented
- **Detail:** ADK Agent + MCP tool calls; DynatraceClient._call_tool wraps every tool call with mcp_call_timed; chat agent tools registered in backend/services/chat_tools.py.
- **Artefacts:**
    - code: backend/integrations/dynatrace.py:DynatraceClient._call_tool
    - code: backend/services/chat_tools.py
    - test: tests/playwright/dynatrace_mcp_test.py (20/20 PASS — every MCP tool exercised)

### GA-1.2 Audit logging of tool usage

- **Status:** EMITTED — verified live
- **Detail:** Every MCP tool call is logged + counted via mcp_call_timed (services/self_monitor.py); the 60s rollup pushes mcp_calls_60s + mcp_avg_latency_ms to Davis as parity-self events. Per-tool bucketed in mcp_by_tool dict.
- **Artefacts:**
    - code: backend/services/self_monitor.py:mcp_call_timed
    - dql: fetch events filter source=="parity-self" filter parity.self.category=="rollup" fields parity.self.mcp_calls_60s

### GA-1.3 Multi-step reasoning chain support

- **Status:** EMITTED — implemented
- **Detail:** ADK chat agent in backend/agents/chat_agent.py runs multi-turn with tool_use --> tool_result --> text iteration; tested end-to-end by tests/playwright/parity_test.py (chat scenarios) — every chat response includes at least one tool_use event.
- **Artefacts:**
    - code: backend/agents/chat_agent.py
    - test: tests/playwright/parity_test.py — 'POST /api/v1/chat returns SSE tool_use + text'

### GA-2.1 Temporal alignment of network + observability data

- **Status:** EMITTED — verified live
- **Detail:** Snapshot timestamps and Davis-event timestamps verified within ±seconds (DT-1.2 PASS in deliverables run); reasoner consumes both rolling and golden diff dicts via dynatrace_reasoner._reason_via_gemini.
- **Artefacts:**
    - code: backend/services/dynatrace_reasoner.py:_reason_via_gemini
    - test: scripts/deliverables_test_suite.py:deliverable_1 (DT-1.2 PASS)

### GA-2.2 Cross-domain correlation logic

- **Status:** EMITTED — implemented
- **Detail:** backend/services/correlation.py groups findings into incidents by shared correlation_key (prefix, interface). DT-3.2 Blast Radius test confirms incident_id propagates across multiple devices.
- **Artefacts:**
    - code: backend/services/correlation.py
    - test: scripts/deliverables_test_suite.py (DT-3.2 PASS — 'Independent changes produced distinct incidents')

### GA-2.3 Confidence scoring for correlations

- **Status:** EMITTED — verified live
- **Detail:** Every finding carries a 0.0-1.0 confidence from Gemini's verdict; DT-5.2 PASS confirms 20/20 findings carry confidence.
- **Artefacts:**
    - schema: Finding.confidence column
    - test: scripts/deliverables_test_suite.py (DT-5.2 PASS)

### GA-3.1 Multi-cause reasoning for incidents

- **Status:** PARTIAL — single-cause today
- **Detail:** The reasoner produces ONE primary category + verdict per finding. Multi-cause hypothesis ranking is on the roadmap (Davis Copilot dual-reasoner is the seed: every finding now carries davis_assessment alongside Gemini's verdict).
- **Artefacts:**
    - code: backend/services/dynatrace_reasoner.py:_call_davis_for_second_opinion
    - evidence: Finding.evidence.davis_assessment populated on every finding (Insights/Incident Log shows both)

### GA-3.2 Hypothesis ranking by likelihood

- **Status:** candidate — not yet built
- **Detail:** Today: one verdict + one Davis second-opinion. Build path: prompt Gemini Pro to produce ranked alternatives and a per-hypothesis confidence; render as a sortable list in the finding detail modal.

### GA-3.3 Tool-driven hypothesis validation

- **Status:** PARTIAL — agent uses tools today
- **Detail:** Chat agent can be asked to validate a finding — it autonomously picks tools (list_findings, get_snapshot_diff, execute_dql via Davis Copilot) to gather supporting evidence. Not yet exposed as a 'validate' button.
- **Artefacts:**
    - code: backend/services/chat_tools.py

### GA-4.1 Service dependency resolution

- **Status:** candidate — needs Dynatrace SERVICE entities
- **Detail:** Blocked on the tenant having no OneAgent SERVICE entities yet. Code path is ready: find_entity_by_name + execute_dql via the real MCP would resolve the moment services appear.
- **Artefacts:**
    - code: backend/integrations/dynatrace.py:DynatraceClient.find_entity_by_name

### GA-4.2 Blast radius calculation

- **Status:** EMITTED — implemented
- **Detail:** Incident model tracks affected_device_count; the Incident Log UI shows blast radius per incident.
- **Artefacts:**
    - code: backend/services/correlation.py
    - ui: frontend/src/pages/Incidents.jsx (affected_device_count chip)
    - test: scripts/deliverables_test_suite.py (DT-3.2 PASS)

### GA-4.3 Application-to-network mapping

- **Status:** candidate — needs OneAgent topology
- **Detail:** Same blocker as GA-4.1 — needs a populated tenant.

### GA-5.1 Pre-change risk scoring

- **Status:** PARTIAL — verdict carries risk_level
- **Detail:** Every Gemini verdict emits risk_level ∈ {low,medium,high}; rendered as a chip on every Insights card. Pre-execution risk via the reasoner's risk_level on the recommendation.
- **Artefacts:**
    - code: backend/services/dynatrace_reasoner.py — verdict.risk_level
    - ui: frontend/src/pages/Insights.jsx — risk-level chip

### GA-5.2 Impact prediction across services

- **Status:** candidate — needs OneAgent topology
- **Detail:** Same blocker as service-impact mapping.

### GA-5.3 Confidence-adjusted scoring

- **Status:** PARTIAL
- **Detail:** Finding.confidence × severity drives the dashboard's anomaly tile colour; explicit confidence-adjustment formula in pipeline activity calculations.
- **Artefacts:**
    - code: backend/api/routes/dashboard.py

### GA-6.1 Event merging from network + observability sources

- **Status:** EMITTED — verified live
- **Detail:** Davis Event Timeline on /dynatrace page merges parity (network) + parity-self (observability) events; the Incident Log links each lifecycle moment to its Davis event_id.
- **Artefacts:**
    - ui: frontend/src/pages/Dynatrace.jsx (DavisTimeline)
    - ui: frontend/src/pages/Incidents.jsx (lifecycle expandable rows)

### GA-6.2 Chronological narrative building

- **Status:** PARTIAL
- **Detail:** Incident expandable row narrates: finding raised --> Davis reviewed --> approved --> executed --> resolved with timestamps for each phase. Free-text narrative generation is a candidate.
- **Artefacts:**
    - ui: frontend/src/pages/Incidents.jsx

### GA-7.1 Reference-backed claims

- **Status:** EMITTED — verified live
- **Detail:** Every finding has evidence.diff_paths citing the exact snapshot leaves that triggered it; Davis Copilot responses include 'Sources' references when calling via MCP (visible in chat_with_davis_copilot raw output).
- **Artefacts:**
    - schema: Finding.evidence.diff_paths
    - test: scripts/deliverables_test_suite.py (DT-5.2 PASS — 20/20 carry diff_paths)

### GA-7.2 Confidence scoring and uncertainty handling

- **Status:** EMITTED — verified live
- **Detail:** Confidence field on every finding + risk_level + Davis acknowledges ignorance when asked about fabricated entities (CrossAI Hallucination Resistance PASS).
- **Artefacts:**
    - test: scripts/deliverables_test_suite.py:cross_platform_ai (Hallucination Resistance PASS)

### GA-8.1 Technical RCA format

- **Status:** EMITTED — implemented
- **Detail:** Insights and Incident Log pages render Gemini reasoning + Davis assessment + remediation commands per finding; the executive HTML bulletin (E2E_TEST_RESULTS.html) is the report-ready artefact.
- **Artefacts:**
    - ui: frontend/src/pages/Insights.jsx, frontend/src/pages/Incidents.jsx
    - doc: tests/playwright/E2E_TEST_RESULTS.html

### GA-8.2 Executive summary format

- **Status:** EMITTED — implemented
- **Detail:** Executive HTML bulletin (E2E_TEST_RESULTS.html) is the canonical exec format; Insights page Executive Summary block surfaces risk score + ready-to-apply count for an at-a-glance view.
- **Artefacts:**
    - doc: tests/playwright/E2E_TEST_RESULTS.html
    - ui: frontend/src/pages/Insights.jsx (Executive Summary panel)

### GA-8.3 CAB / change management format

- **Status:** EMITTED — implemented
- **Detail:** Every approval has a Jira PSR ticket (auto-created at finding time via integrations/jira.py); jira_url surfaces on Insights cards, Incident Log rows, Davis on Gemini panel.
- **Artefacts:**
    - code: backend/integrations/jira.py
    - test: latest run shows PSR-1xx tickets present on every actionable finding
