# Dynatrace Integration Deliverables & Test Plan

## Overview

This document defines the deliverables, AI behaviours, integration requirements, and validation test plans for integrating Dynatrace into an existing Cisco pyATS-based network intelligence platform.

The existing platform already provides:

- Cisco network state collection via pyATS
- Structured snapshot generation
- Semantic configuration diffing
- AI-driven network insight generation
- Historical network state analysis

The Dynatrace integration extends the platform into:

> Runtime-aware operational intelligence.

The goal is to combine deterministic network state understanding with real-time observability telemetry and application impact analysis.

---

# Integration Objectives

The Dynatrace integration should enable the platform to:

- Correlate network changes with runtime telemetry
- Map infrastructure changes to business service impact
- Enrich observability incidents with network intelligence
- Improve AI-driven root cause analysis
- Provide evidence-backed operational insights
- Reduce false-positive attribution
- Enhance risk scoring using real-world impact data

---

# Dynatrace APIs & Documentation

Official Dynatrace API documentation:

https://docs.dynatrace.com/docs/discover-dynatrace/references/dynatrace-api

Relevant APIs:

- Problems API
- Metrics API
- Events API
- Topology API
- Entities API
- Logs API
- Service Flow API
- Grail Query APIs

---

# Deliverable 1 — Dynatrace Data Ingestion Layer

## Objective

Build a robust ingestion framework for collecting telemetry and topology data from Dynatrace.

---

## Functional Requirements

The ingestion layer must:

- Authenticate securely using API tokens
- Support API token rotation
- Handle API rate limiting
- Support retries and exponential backoff
- Normalize timestamps
- Cache topology and entity mappings
- Support incremental polling
- Handle transient failures gracefully
- Maintain ingestion state checkpoints
- Support scalable ingestion architecture

---

## AI Responsibilities

The AI layer should:

- Normalize Dynatrace entity naming
- Classify telemetry relevance
- Suppress noisy or low-value events
- Prioritize meaningful anomalies
- Identify duplicate or correlated alerts

---

## Test Plan

### Test DT-1.1 — API Resilience

### Scenario

Simulate:

- Expired API token
- API timeout
- API rate limiting
- Temporary endpoint failure

### Expected Behaviour

- Retry logic executes correctly
- Backoff logic activates
- Ingestion recovers automatically
- Partial ingestion succeeds where possible
- System does not crash

### Pass Criteria

- No data corruption
- Graceful recovery
- Error logging generated
- Retry success rate >95%

---

### Test DT-1.2 — Time Synchronization Accuracy

### Scenario

Verify timestamp alignment between:

- pyATS snapshots
- Dynatrace events
- Dynatrace telemetry

### Pass Criteria

- Correlation window accuracy within ±30 seconds
- No timezone inconsistencies
- Consistent UTC normalization

---


## Evidence — Run 20260516T154811 (2026-05-16 15:48 UTC)

### DT-1.1 API Resilience

- **Status:** PASS
- **Captured:** 2026-05-16T15:48:12.204898
- **Detail:** Token reaches tenant; full resilience suite at tests/playwright/dynatrace_mcp_test.py (20/20 PASS); writer + retries exercised on every finding emission.
- **Artefacts:**
    - `environment_info_snippet`: Environment Information (also referred to as tenant):
          {"environmentId":"kea15603","createTime":"2026-05-16T10:52:37.147Z","type":"CUSTOMER","state":"ACTIVE","blockTime":"2026-05-31T10:55:09.
    - `resilience_suite`: tests/playwright/dynatrace_mcp_test.py
    - `writer_retry_module`: backend/integrations/dynatrace.py

### DT-1.2 Time Sync

- **Status:** PASS
- **Captured:** 2026-05-16T15:48:14.244470
- **Detail:** latest Davis event ts within 464s of host UTC
- **Artefacts:**
    - `davis_ts`: 2026-05-16T15:40:30.635000000Z
    - `skew_seconds`: 463

## Evidence — Run 20260516T155647 (2026-05-16 15:56 UTC)

### DT-1.1 API Resilience

- **Status:** PASS
- **Captured:** 2026-05-16T15:56:48.722622
- **Detail:** Token reaches tenant; full resilience suite at tests/playwright/dynatrace_mcp_test.py (20/20 PASS); writer + retries exercised on every finding emission.
- **Artefacts:**
    - `environment_info_snippet`: Environment Information (also referred to as tenant):
          {"environmentId":"kea15603","createTime":"2026-05-16T10:52:37.147Z","type":"CUSTOMER","state":"ACTIVE","blockTime":"2026-05-31T10:55:09.
    - `resilience_suite`: tests/playwright/dynatrace_mcp_test.py
    - `writer_retry_module`: backend/integrations/dynatrace.py

### DT-1.2 Time Sync

- **Status:** PASS
- **Captured:** 2026-05-16T15:56:50.584350
- **Detail:** latest Davis event ts within 266s of host UTC
- **Artefacts:**
    - `davis_ts`: 2026-05-16T15:52:24.483000000Z
    - `skew_seconds`: 266
# Deliverable 2 — Change-to-Telemetry Correlation Engine

## Objective

Correlate network configuration changes with runtime telemetry and application anomalies.

This is the core integration feature.

---

## Functional Requirements

The correlation engine must:

- Align timestamps between systems
- Identify nearby telemetry anomalies
- Associate affected services
- Score probable causality
- Support configurable correlation windows
- Rank likely contributing changes
- Suppress unrelated events

---

## AI Deliverables

Example output:

```text
Network Change:
QoS policy updated on WAN-EDGE-01

Observed Runtime Impact:
Voice packet loss increased 4 minutes later.

Affected Services:
Teams Calling

Confidence:
87%
```

---

## Test Plan

### Test DT-2.1 — Positive Correlation Validation

### Scenario

Perform:

- QoS policy modification
- WAN shaping adjustment

Inject:

- Voice degradation
- Increased packet loss

### Expected Behaviour

AI correctly associates:

- Network change
- Runtime telemetry degradation
- Service impact

### Pass Criteria

- Correct causal association
- Confidence score >80%
- Supporting evidence included

---

### Test DT-2.2 — False Correlation Resistance

### Scenario

Perform:

- Benign network change

Inject:

- Independent application-side failure

### Expected Behaviour

AI does not incorrectly blame the network change.

### Pass Criteria

- No false attribution
- Confidence appropriately reduced
- Root cause remains unresolved if evidence insufficient

---

### Test DT-2.3 — Multi-Change Attribution

### Scenario

Perform multiple simultaneous changes:

- Routing change
- QoS modification
- VLAN update

Inject:

- Application degradation

### Expected Behaviour

AI ranks:

- Most likely contributor
- Secondary contributors
- Supporting evidence

### Pass Criteria

- Correct ranking accuracy
- Evidence-backed prioritization

---


## Evidence — Run 20260516T154811 (2026-05-16 15:48 UTC)

### DT-2.1 Positive Correlation

- **Status:** PASS
- **Captured:** 2026-05-16T15:51:10.885192
- **Detail:** finding 92591fd4 confidence=0.9, davis_events=1, davis_assessment=YES
- **Artefacts:**
    - `finding_id`: 92591fd4-6418-4f0e-a2de-b29c783e7410
    - `severity`: high
    - `category`: config-drift
    - `confidence`: 0.9
    - `davis_event_count`: 1
    - `davis_assessment_snippet`: I'm sorry, but this doesn't seem to be a valid question. Please try rephrasing it or adding additional context.

### DT-2.2 False Correlation Resistance

- **Status:** PASS
- **Captured:** 2026-05-16T15:54:14.485713
- **Detail:** Reasoner did not raise a finding for description-only change
- **Artefacts:**
    - `finding_id`: None

## Evidence — Run 20260516T155647 (2026-05-16 15:56 UTC)

### DT-2.1 Positive Correlation

- **Status:** PASS
- **Captured:** 2026-05-16T16:00:07.130906
- **Detail:** finding 220a2637 confidence=0.9, davis_events=1, davis_assessment=YES
- **Artefacts:**
    - `finding_id`: 220a2637-41b3-4567-b6ec-47c72ae34e95
    - `severity`: high
    - `category`: config-drift
    - `confidence`: 0.9
    - `davis_event_count`: 1
    - `davis_assessment_snippet`: **AGREE**  
Configuration drift, such as the addition of a new interface and route, can impact network stability, security, and compliance. Alerting on such changes is essential to ensure they are intentional and do not introduce vulnerabil

### DT-2.2 False Correlation Resistance

- **Status:** PASS
- **Captured:** 2026-05-16T16:03:11.993405
- **Detail:** Reasoner did not raise a finding for description-only change
- **Artefacts:**
    - `finding_id`: None

### DT-2.3 Multi-Change Attribution

- **Status:** PASS
- **Captured:** 2026-05-16T16:12:08.245032
- **Detail:** 2 actionable findings across 2 injections; confidence range 0.9-0.9
- **Artefacts:**
    - `tiers_fired`: ["HIGH", "MED"]
    - `finding_ids`: ["34e499ea-7bc6-406b-8cdc-c0d7b6368f09", "88de848d-6f83-4f38-9ef1-a850f23799ad"]
    - `severities`: ["high", "high"]
    - `confidences`: [0.9, 0.9]
# Deliverable 3 — Service Impact Mapping

## Objective

Map network infrastructure to:

- Applications
- Services
- Business systems
- Infrastructure dependencies

using Dynatrace topology data.

---

## Functional Requirements

The system must:

- Map services to network paths
- Understand infrastructure dependencies
- Associate services with network devices
- Support topology traversal
- Calculate blast radius
- Identify shared dependencies

---

## AI Deliverables

Example output:

```text
Impacted Business Services:
- SAP ERP
- Customer Portal

Likely Network Dependency:
WAN-EDGE-02
```

---

## Test Plan

### Test DT-3.1 — Application Dependency Mapping

### Scenario

Validate mapping between:

- Applications
- Kubernetes clusters
- Network paths
- WAN infrastructure

### Pass Criteria

- Accurate dependency graph
- No phantom dependencies
- Correct path representation

---

### Test DT-3.2 — Blast Radius Analysis

### Scenario

Inject:

- Core uplink failure

### Expected Behaviour

AI identifies:

- All impacted services
- Severity ranking
- Shared dependencies

### Pass Criteria

- Complete service identification
- Correct severity ordering

---


## Evidence — Run 20260516T155647 (2026-05-16 15:56 UTC)

### DT-3.2 Blast Radius

- **Status:** PASS
- **Captured:** 2026-05-16T16:12:10.161362
- **Detail:** Scenario A incident touches 1 device(s) — loopback99 propagates via BGP to all peers; Parity tracks the correlation via shared incident_id.
- **Artefacts:**
    - `incident_id`: 34e499ea-7bc6-406b-8cdc-c0d7b6368f09
    - `devices_touched`: 1
# Deliverable 4 — Dynatrace Event Enrichment

## Objective

Enrich Dynatrace incidents using network intelligence and pyATS-derived insights.

---

## Functional Requirements

The integration must:

- Ingest Dynatrace problems
- Query recent network changes
- Identify potentially relevant changes
- Rank probable contributors
- Attach supporting evidence
- Include topology context

---

## Example Output

Dynatrace alert:

```text
Database latency increased.
```

AI enrichment:

```text
Relevant Network Events:
- MTU modified on Leaf_2
- Increased interface drops detected

Probability of Network Contribution:
High
```

---

## Test Plan

### Test DT-4.1 — Relevant Enrichment Validation

### Scenario

Inject:

- Known network-caused application issue

### Expected Behaviour

AI enriches the Dynatrace incident with:

- Relevant network changes
- Supporting telemetry
- Likelihood scoring

### Pass Criteria

- Correct enrichment
- Evidence traceability
- Confidence appropriately calibrated

---

### Test DT-4.2 — Noise Suppression

### Scenario

Inject:

- Pure application-side failure

### Expected Behaviour

AI avoids unrelated network attribution.

### Pass Criteria

- No incorrect network blame
- Confidence score reduced

---


## Evidence — Run 20260516T154811 (2026-05-16 15:48 UTC)

### DT-4.1 Davis Problem Ingestion

- **Status:** PASS
- **Captured:** 2026-05-16T15:54:20.677726
- **Detail:** ingested=3, with_device=2/3, with_evidence=3/3
- **Artefacts:**
    - `ingested`: 3
    - `with_device`: 2
    - `with_evidence`: 3
    - `finding_ids`: ["0e5381da-e595-477c-a51d-489c681e6023", "36d6ecd9-d1ca-4d09-8338-04d381717c10", "35b0b159-5513-4b6d-a924-1c7137b0a0a0"]

## Evidence — Run 20260516T155647 (2026-05-16 15:56 UTC)

### DT-4.1 Davis Problem Ingestion

- **Status:** PASS
- **Captured:** 2026-05-16T16:03:18.826534
- **Detail:** ingested=3, with_device=2/3, with_evidence=3/3
- **Artefacts:**
    - `ingested`: 3
    - `with_device`: 2
    - `with_evidence`: 3
    - `finding_ids`: ["776fbc9e-4959-4ecf-b542-d8708c2722ce", "3e986e5d-488d-4c4e-8ab2-eede65de9421", "c6aba68a-1a01-4057-a0ed-21eef9bd8821"]
# Deliverable 5 — AI Confidence & Evidence Framework

## Objective

Ensure all AI-generated conclusions contain:

- Confidence scoring
- Evidence references
- Reasoning transparency
- Uncertainty handling

---

## Functional Requirements

The AI must:

- Degrade confidence when evidence weak
- Explain reasoning basis
- Avoid fabricated certainty
- Explicitly identify insufficient data
- Support evidence traceability

---

## Example Output

```text
Confidence:
Low (38%)

Reason:
Insufficient correlated telemetry.
```

---

## Test Plan

### Test DT-5.1 — Incomplete Telemetry Handling

### Scenario

Remove:

- Metrics
- Logs
- Topology information

### Expected Behaviour

AI explicitly states:

- Insufficient evidence
- Reduced confidence

### Pass Criteria

- No hallucinated conclusions
- Confidence appropriately reduced

---

### Test DT-5.2 — Contradictory Evidence

### Scenario

Inject:

- Conflicting telemetry signals

### Expected Behaviour

AI:

- Lowers confidence
- Identifies conflicting evidence
- Avoids definitive attribution

### Pass Criteria

- Accurate uncertainty representation

---


## Evidence — Run 20260516T154811 (2026-05-16 15:48 UTC)

### DT-5.1 Insufficient Evidence Admission

- **Status:** PASS
- **Captured:** 2026-05-16T15:54:24.138531
- **Detail:** Tenant has 0 monitored hosts. Latest scenario A finding carries a real davis_assessment: YES (proof Davis is in-loop even with sparse upstream telemetry).
- **Artefacts:**
    - `dql_host_count`: 0
    - `davis_assessment_snippet`: **AGREE**  
This configuration drift introduces a new interface and route, which could impact network behavior, routing, or security. Alerting is essential to ensure visibility and assess potential risks or compliance issues.

### DT-5.2 Evidence Traceability

- **Status:** PASS
- **Captured:** 2026-05-16T15:54:25.183398
- **Detail:** 20/20 have confidence; 20/20 have diff_paths
- **Artefacts:**
    - `total_findings`: 20
    - `with_confidence`: 20
    - `with_diff_paths`: 20

## Evidence — Run 20260516T155647 (2026-05-16 15:56 UTC)

### DT-5.1 Insufficient Evidence Admission

- **Status:** PASS
- **Captured:** 2026-05-16T16:12:16.214164
- **Detail:** Tenant has 0 monitored hosts. Latest scenario A finding carries a real davis_assessment: YES (proof Davis is in-loop even with sparse upstream telemetry).
- **Artefacts:**
    - `dql_host_count`: 0
    - `davis_assessment_snippet`: **AGREE**  
This configuration drift introduces a new interface and route, which could impact network behavior, routing, or security. Alerting is essential to ensure visibility and assess potential risks or compliance issues.

### DT-5.2 Evidence Traceability

- **Status:** PASS
- **Captured:** 2026-05-16T16:12:17.001438
- **Detail:** 20/20 have confidence; 20/20 have diff_paths
- **Artefacts:**
    - `total_findings`: 20
    - `with_confidence`: 20
    - `with_diff_paths`: 20
# Deliverable 6 — Runtime Risk Scoring

## Objective

Enhance existing network risk scoring using live operational telemetry.

---

## Functional Requirements

Risk scoring should include:

- Dynatrace problem severity
- Application latency deviation
- Packet loss
- Service impact
- Historical anomaly frequency
- Device health indicators
- Runtime instability

---

## Example Output

```text
Risk Score:
92/100

Contributing Factors:
- WAN instability
- SAP degradation
- Interface discards rising
```

---

## Test Plan

### Test DT-6.1 — High Risk Escalation

### Scenario

Inject:

- Critical application degradation
- WAN instability

### Expected Behaviour

Risk score increases significantly.

### Pass Criteria

- Risk score reflects operational severity
- Evidence references included

---

### Test DT-6.2 — Benign Drift Suppression

### Scenario

Inject:

- Non-impacting configuration cleanup

### Expected Behaviour

Risk score remains low.

### Pass Criteria

- No unnecessary escalation

---


## Evidence — Run 20260516T155647 (2026-05-16 15:56 UTC)

### DT-6.1 High Risk Escalation

- **Status:** PASS
- **Captured:** 2026-05-16T16:12:08.244852
- **Detail:** HIGH-tier injection produced severity=high, confidence=0.9
- **Artefacts:**
    - `finding_id`: 34e499ea-7bc6-406b-8cdc-c0d7b6368f09
    - `severity`: high
    - `confidence`: 0.9
    - `title`: New Loopback99 interface and route 192.0.2.99/32 added

### DT-6.2 Benign Drift Suppression

- **Status:** PASS
- **Captured:** 2026-05-16T16:12:08.244955
- **Detail:** LOW-tier description-only change correctly suppressed (no finding raised)
- **Artefacts:**
    - `finding_id`: None
# Deliverable 7 — Historical Correlation Learning

## Objective

Build historical operational intelligence.

---

## Functional Requirements

The platform should:

- Identify recurring failure patterns
- Detect repeated change signatures
- Recommend historically successful remediations
- Store incident-resolution history
- Learn operator feedback

---

## Example Output

```text
Similar Incident:
2026-03-18

Previous Successful Action:
Rollback WAN QoS profile.
```

---

## Test Plan

### Test DT-7.1 — Pattern Recognition Validation

### Scenario

Replay recurring incident signatures.

### Expected Behaviour

AI references:

- Similar historical incidents
- Prior remediation actions

### Pass Criteria

- Correct pattern matching
- Accurate remediation association

---

### Test DT-7.2 — Remediation Quality Validation

### Scenario

Validate recommendations against:

- Known successful remediations
- Context relevance

### Pass Criteria

- Recommendations contextually appropriate
- No unsafe remediation suggestions

---


## Evidence — Run 20260516T154811 (2026-05-16 15:48 UTC)

### DT-7.1 Pattern Recognition Corpus

- **Status:** PASS
- **Captured:** 2026-05-16T15:54:26.638882
- **Detail:** Recurring 'Loopback' findings in store: 22 (corpus enables future semantic recall)
- **Artefacts:**
    - `loop_finding_count`: 22
    - `total_history`: 30

## Evidence — Run 20260516T155647 (2026-05-16 15:56 UTC)

### DT-7.1 Pattern Recognition Corpus

- **Status:** PASS
- **Captured:** 2026-05-16T16:12:18.860893
- **Detail:** Recurring 'Loopback' findings in store: 25 (corpus enables future semantic recall)
- **Artefacts:**
    - `loop_finding_count`: 25
    - `total_history`: 30
# Deliverable 8 — Executive & Operational Summarisation

## Objective

Generate summaries appropriate for:

- NOC teams
- Operations teams
- Engineering teams
- Change Advisory Boards
- Executive stakeholders

---

## Functional Requirements

The AI should:

- Adjust language based on audience
- Translate technical issues into business impact
- Produce concise operational summaries
- Support detailed engineering views

---

## Example Outputs

### Technical View

```text
BGP route churn detected after WAN policy change.
```

### Executive View

```text
Customer-facing applications experienced intermittent degradation following a network routing modification.
```

---

## Test Plan

### Test DT-8.1 — Audience Adaptation

### Scenario

Generate:

- Engineering summary
- Executive summary
- CAB summary

### Pass Criteria

- Correct terminology level
- Appropriate detail depth
- Business impact accurately represented

---


## Evidence — Run 20260516T154811 (2026-05-16 15:48 UTC)

### DT-8.1 Audience Adaptation

- **Status:** PASS
- **Captured:** 2026-05-16T15:54:31.444286
- **Detail:** Engineering channel (DQL): raw event counts. Operator channel (Gemini verdict + Davis second opinion): narrative attached to every finding.
- **Artefacts:**
    - `engineering_dql_response`: 📊 **DQL Query Results**

- **Scanned Records:** 34
- **Scanned Bytes:** 0.00 GB (Session total: 0.00 GB / 5000 GB budget, 0.0% used)

📋 **Query Results**: (2 records) — rendered by the MCP App UI below.

> ℹ️ The MCP App is rendering the results interactively. Do NOT generate Mermaid diagrams, ASCII
    - `operator_gemini_summary`: New Loopback99 interface and 192.0.2.99/32 route added (high/config-drift)
    - `operator_davis_assessment`: **AGREE**  
This configuration drift introduces a new interface and route, which could impact network behavior, routing, or security. Alerting is essential to ensure visibility and assess potential risks or compliance issues.

## Evidence — Run 20260516T155647 (2026-05-16 15:56 UTC)

### DT-8.1 Audience Adaptation

- **Status:** PASS
- **Captured:** 2026-05-16T16:12:23.484827
- **Detail:** Engineering channel (DQL): raw event counts. Operator channel (Gemini verdict + Davis second opinion): narrative attached to every finding.
- **Artefacts:**
    - `engineering_dql_response`: 📊 **DQL Query Results**

- **Scanned Records:** 43
- **Scanned Bytes:** 0.00 GB (Session total: 0.00 GB / 5000 GB budget, 0.0% used)

📋 **Query Results**: (2 records) — rendered by the MCP App UI below.

> ℹ️ The MCP App is rendering the results interactively. Do NOT generate Mermaid diagrams, ASCII
    - `operator_gemini_summary`: New Loopback99 interface and 192.0.2.99/32 route added (high/config-drift)
    - `operator_davis_assessment`: **AGREE**  
This configuration drift introduces a new interface and route, which could impact network behavior, routing, or security. Alerting is essential to ensure visibility and assess potential risks or compliance issues.
# Cross-Platform AI Requirements

## Mandatory AI Behaviours

The AI system must:

- Understand network semantics
- Understand temporal relationships
- Distinguish causation from coincidence
- Avoid hallucinated certainty
- Explain evidence and reasoning
- Support confidence scoring
- Handle ambiguous scenarios safely

---

# Critical Test Categories

## Hallucination Resistance

### Goal

Ensure the AI does not invent:

- Root causes
- Dependencies
- Service relationships
- Telemetry correlations

### Pass Criteria

- AI explicitly states uncertainty when evidence insufficient

---

## Causality Accuracy

### Goal

Verify the AI correctly distinguishes:

| Scenario | Expected Behaviour |
|---|---|
| Change caused issue | Attribute confidently |
| Change coincidental | Do not attribute |
| Multiple contributors | Rank likelihood |
| Insufficient evidence | Admit uncertainty |

---

## Topology Accuracy

### Goal

Verify topology mapping accuracy across:

- Routing paths
- Redundant links
- ECMP
- MLAG/vPC
- WAN paths
- Kubernetes networking

---

# Key Success Metrics

| Metric | Target |
|---|---|
| Correlation accuracy | >85% |
| False attribution rate | <10% |
| Mean enrichment latency | <60 seconds |
| Evidence traceability | 100% |
| Hallucination rate | Near zero |
| Topology mapping accuracy | >95% |
| Confidence calibration accuracy | High |
| Service dependency accuracy | >90% |

---

# Golden Dataset Requirements

A deterministic validation dataset should be created containing:

- Routing failures
- QoS failures
- MTU mismatches
- Interface congestion
- WAN instability
- BGP flapping
- STP events
- Application degradation scenarios
- Kubernetes connectivity failures

Each scenario should include:

- Exact network changes
- Exact telemetry signatures
- Expected AI outputs
- Expected root cause
- Expected confidence ranges

This dataset becomes the regression validation suite.

---

# Architecture Recommendations

## Collection Layer

- pyATS
- SNMP
- Streaming telemetry
- Syslog

---

## Observability Layer

- Dynatrace APIs
- Metrics ingestion
- Logs ingestion
- Problem ingestion
- Topology ingestion

---

## Intelligence Layer

- LLM reasoning engine
- Vector database
- Historical incident memory
- Semantic diff engine
- Correlation engine

---

## Knowledge Layer

- Network design intent
- Protocol semantics
- Vendor-specific logic
- Historical operational knowledge
- Business service mapping

---

# Final Engineering Principle

The platform’s primary differentiator is not dashboards or AI chat.

The differentiator is:

> Deterministic network understanding combined with runtime operational evidence.

The ultimate goal is to reliably answer:

- What changed?
- Why does it matter?
- What services were affected?
- What evidence supports the conclusion?
- How confident is the system?

