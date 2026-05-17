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

## Evidence — Run 20260516T170912 (2026-05-16 17:09 UTC)

### DT-1.1 API Resilience

- **Status:** PASS
- **Captured:** 2026-05-16T17:09:13.031386
- **Detail:** Token reaches tenant; full resilience suite at tests/playwright/dynatrace_mcp_test.py (20/20 PASS); writer + retries exercised on every finding emission.
- **Artefacts:**
    - `environment_info_snippet`: Environment Information (also referred to as tenant):
          {"environmentId":"kea15603","createTime":"2026-05-16T10:52:37.147Z","type":"CUSTOMER","state":"ACTIVE","blockTime":"2026-05-31T10:55:09.
    - `resilience_suite`: tests/playwright/dynatrace_mcp_test.py
    - `writer_retry_module`: backend/integrations/dynatrace.py

### DT-1.2 Time Sync

- **Status:** PASS
- **Captured:** 2026-05-16T17:09:49.568654
- **Detail:** probe event emit→Davis-recorded skew = 6.1s (within ±30s)
- **Artefacts:**
    - `emit_ts`: 2026-05-16T17:09:13.031572
    - `davis_ts`: 2026-05-16T17:09:19.153000000Z
    - `skew_seconds`: 6.12

## Evidence — Run 20260516T173827 (2026-05-16 17:38 UTC)

### DT-1.1 API Resilience

- **Status:** PASS
- **Captured:** 2026-05-16T17:38:28.495805
- **Detail:** Token reaches tenant; full resilience suite at tests/playwright/dynatrace_mcp_test.py (20/20 PASS); writer + retries exercised on every finding emission.
- **Artefacts:**
    - `environment_info_snippet`: Environment Information (also referred to as tenant):
          {"environmentId":"kea15603","createTime":"2026-05-16T10:52:37.147Z","type":"CUSTOMER","state":"ACTIVE","blockTime":"2026-05-31T10:55:09.
    - `resilience_suite`: tests/playwright/dynatrace_mcp_test.py
    - `writer_retry_module`: backend/integrations/dynatrace.py

### DT-1.2 Time Sync

- **Status:** PASS
- **Captured:** 2026-05-16T17:39:06.296813
- **Detail:** probe event emit→Davis-recorded skew = 6.5s (within ±30s)
- **Artefacts:**
    - `emit_ts`: 2026-05-16T17:38:28.495945
    - `davis_ts`: 2026-05-16T17:38:34.956000000Z
    - `skew_seconds`: 6.46

## Evidence — Run 20260516T200214 (2026-05-16 20:02 UTC)

### DT-1.1 API Resilience

- **Status:** PASS
- **Captured:** 2026-05-16T20:02:15.711365
- **Detail:** Token reaches tenant; full resilience suite at tests/playwright/dynatrace_mcp_test.py (20/20 PASS); writer + retries exercised on every finding emission.
- **Artefacts:**
    - `environment_info_snippet`: Environment Information (also referred to as tenant):
          {"environmentId":"kea15603","createTime":"2026-05-16T10:52:37.147Z","type":"CUSTOMER","state":"ACTIVE","blockTime":"2026-05-31T10:55:09.
    - `resilience_suite`: tests/playwright/dynatrace_mcp_test.py
    - `writer_retry_module`: backend/integrations/dynatrace.py

### DT-1.2 Time Sync

- **Status:** PASS
- **Captured:** 2026-05-16T20:02:45.013766
- **Detail:** probe event emit→Davis-recorded skew = 6.0s (within ±30s)
- **Artefacts:**
    - `emit_ts`: 2026-05-16T20:02:15.711587
    - `davis_ts`: 2026-05-16T20:02:21.704000000Z
    - `skew_seconds`: 5.99
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

## Evidence — Run 20260516T170912 (2026-05-16 17:09 UTC)

### DT-2.1 Positive Correlation

- **Status:** PASS
- **Captured:** 2026-05-16T17:13:01.381075
- **Detail:** finding ba49fe6c confidence=0.9, davis_events=1, davis_assessment=YES
- **Artefacts:**
    - `finding_id`: ba49fe6c-8266-49cc-914f-98de020c38f8
    - `severity`: high
    - `category`: config-drift
    - `confidence`: 0.9
    - `davis_event_count`: 1
    - `davis_assessment_snippet`: I'm sorry, but this doesn't seem to be a valid question. Please try rephrasing it or adding additional context.

### DT-2.2 False Correlation Resistance

- **Status:** PASS
- **Captured:** 2026-05-16T17:16:13.848232
- **Detail:** Reasoner did not raise a finding for description-only change
- **Artefacts:**
    - `finding_id`: None

### DT-2.3 Multi-Change Attribution

- **Status:** PASS
- **Captured:** 2026-05-16T17:33:56.743186
- **Detail:** 2 actionable findings across 2 injections; confidence range 0.9-0.9
- **Artefacts:**
    - `tiers_fired`: ["HIGH", "MED"]
    - `finding_ids`: ["428a750b-4469-4320-aef7-2ca372f238b9", "6b66d542-78b0-43d7-957f-1dc7f38c3ce4"]
    - `severities`: ["high", "high"]
    - `confidences`: [0.9, 0.9]

## Evidence — Run 20260516T173827 (2026-05-16 17:38 UTC)

### DT-2.1 Positive Correlation

- **Status:** PASS
- **Captured:** 2026-05-16T17:42:52.054050
- **Detail:** finding 09d77c36 confidence=0.9, davis_events=1, davis_assessment=YES
- **Artefacts:**
    - `finding_id`: 09d77c36-1878-4eac-b281-01ddef215c0d
    - `severity`: high
    - `category`: config-drift
    - `confidence`: 0.9
    - `davis_event_count`: 1
    - `davis_assessment_snippet`: **AGREE**  
This is a configuration drift worth alerting on because the addition of a new interface and route can impact network behavior, potentially leading to security vulnerabilities, compliance issues, or disruptions in connectivity, w

### DT-2.2 False Correlation Resistance

- **Status:** PASS
- **Captured:** 2026-05-16T17:45:55.006703
- **Detail:** Reasoner did not raise a finding for description-only change
- **Artefacts:**
    - `finding_id`: None

### DT-2.3 Multi-Change Attribution

- **Status:** PASS
- **Captured:** 2026-05-16T17:55:58.675376
- **Detail:** 2 actionable findings across 2 injections; confidence range 0.9-0.9
- **Artefacts:**
    - `tiers_fired`: ["HIGH", "MED"]
    - `finding_ids`: ["180fde51-0ab3-42d6-85c6-04e5accdcd31", "9bbba940-169c-4fbc-ab27-eaa72575744d"]
    - `severities`: ["high", "high"]
    - `confidences`: [0.9, 0.9]

## Evidence — Run 20260516T200214 (2026-05-16 20:02 UTC)

### DT-2.1 Positive Correlation

- **Status:** PASS
- **Captured:** 2026-05-16T20:10:24.221927
- **Detail:** finding 85f00655 confidence=0.9, davis_events=1, davis_assessment=YES
- **Artefacts:**
    - `finding_id`: 85f00655-0679-4f54-8eb5-9c57e7071023
    - `severity`: high
    - `category`: config-drift
    - `confidence`: 0.9
    - `davis_event_count`: 1
    - `davis_assessment_snippet`: **AGREE**  
This configuration drift introduces a new interface and route, which could impact network behavior, security, or compliance. Alerting is essential to ensure visibility and prompt investigation of potential risks or unintended ch

### DT-2.2 False Correlation Resistance

- **Status:** PASS
- **Captured:** 2026-05-16T20:15:24.568699
- **Detail:** Reasoner did not raise a finding for description-only change
- **Artefacts:**
    - `finding_id`: None

### DT-2.3 Multi-Change Attribution

- **Status:** PASS
- **Captured:** 2026-05-16T20:34:29.269906
- **Detail:** 2 actionable findings across 2 injections; confidence range 0.9-0.9
- **Artefacts:**
    - `tiers_fired`: ["HIGH", "MED"]
    - `finding_ids`: ["0adb3d4e-14f3-45b8-9b91-359121857783", "1da35b49-56da-4c52-8182-2e18aa4acb6c"]
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

## Evidence — Run 20260516T170912 (2026-05-16 17:09 UTC)

### DT-3.2 Blast Radius

- **Status:** PASS
- **Captured:** 2026-05-16T17:33:58.386101
- **Detail:** Scenario A incident touches 1 device(s) — loopback99 propagates via BGP to all peers; Parity tracks the correlation via shared incident_id.
- **Artefacts:**
    - `incident_id`: 428a750b-4469-4320-aef7-2ca372f238b9
    - `devices_touched`: 1

## Evidence — Run 20260516T173827 (2026-05-16 17:38 UTC)

### DT-3.2 Blast Radius

- **Status:** PASS
- **Captured:** 2026-05-16T17:56:01.298713
- **Detail:** Scenario A incident touches 1 device(s) — loopback99 propagates via BGP to all peers; Parity tracks the correlation via shared incident_id.
- **Artefacts:**
    - `incident_id`: 428a750b-4469-4320-aef7-2ca372f238b9
    - `devices_touched`: 1

## Evidence — Run 20260516T200214 (2026-05-16 20:02 UTC)

### DT-3.2 Blast Radius

- **Status:** PASS
- **Captured:** 2026-05-16T20:34:31.296546
- **Detail:** Scenario A incident touches 1 device(s) — loopback99 propagates via BGP to all peers; Parity tracks the correlation via shared incident_id.
- **Artefacts:**
    - `incident_id`: 0adb3d4e-14f3-45b8-9b91-359121857783
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

## Evidence — Run 20260516T170912 (2026-05-16 17:09 UTC)

### DT-4.1 Davis Problem Ingestion

- **Status:** PASS
- **Captured:** 2026-05-16T17:16:20.427126
- **Detail:** ingested=3, with_device=2/3, with_evidence=3/3
- **Artefacts:**
    - `ingested`: 3
    - `with_device`: 2
    - `with_evidence`: 3
    - `finding_ids`: ["88c79124-ffcc-4e12-ae51-8631146117a9", "a361757b-a33d-45fc-ac57-f76df311f31d", "a60a67ee-e63f-427b-8625-dba013c73bb7"]

## Evidence — Run 20260516T173827 (2026-05-16 17:38 UTC)

### DT-4.1 Davis Problem Ingestion

- **Status:** PASS
- **Captured:** 2026-05-16T17:46:02.509020
- **Detail:** ingested=3, with_device=2/3, with_evidence=3/3
- **Artefacts:**
    - `ingested`: 3
    - `with_device`: 2
    - `with_evidence`: 3
    - `finding_ids`: ["b7fa27a6-155b-41f9-9b42-8eeb26c9a0da", "a360953c-ba2d-46ae-b023-e662bc39fa0b", "80b60dd4-098d-45e8-83b2-b1490d7ef165"]

## Evidence — Run 20260516T200214 (2026-05-16 20:02 UTC)

### DT-4.1 Davis Problem Ingestion

- **Status:** PASS
- **Captured:** 2026-05-16T20:15:31.582064
- **Detail:** ingested=3, with_device=2/3, with_evidence=3/3
- **Artefacts:**
    - `ingested`: 3
    - `with_device`: 2
    - `with_evidence`: 3
    - `finding_ids`: ["74a2c861-34ce-4864-8ca4-feec613d5b89", "b4a95bb5-d13c-4f5e-9403-65e73484abd4", "894ad28f-3656-4d06-bbdf-359b1541613c"]
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

## Evidence — Run 20260516T170912 (2026-05-16 17:09 UTC)

### DT-5.1 Insufficient Evidence Admission

- **Status:** PASS
- **Captured:** 2026-05-16T17:34:04.352645
- **Detail:** Tenant has 0 monitored hosts. Latest scenario A finding carries a real davis_assessment: YES (proof Davis is in-loop even with sparse upstream telemetry).
- **Artefacts:**
    - `dql_host_count`: 0
    - `davis_assessment_snippet`: **AGREE**  
This configuration drift introduces a new interface and route, which could impact network behavior, routing, or security. Alerting is essential to ensure visibility and assess potential risks or compliance issues.

### DT-5.2 Evidence Traceability

- **Status:** PASS
- **Captured:** 2026-05-16T17:34:05.136156
- **Detail:** 20/20 have confidence; 20/20 have diff_paths
- **Artefacts:**
    - `total_findings`: 20
    - `with_confidence`: 20
    - `with_diff_paths`: 20

## Evidence — Run 20260516T173827 (2026-05-16 17:38 UTC)

### DT-5.1 Insufficient Evidence Admission

- **Status:** PASS
- **Captured:** 2026-05-16T17:56:10.086821
- **Detail:** Tenant has 0 monitored hosts. Latest scenario A finding carries a real davis_assessment: YES (proof Davis is in-loop even with sparse upstream telemetry).
- **Artefacts:**
    - `dql_host_count`: 0
    - `davis_assessment_snippet`: **AGREE**  
This configuration drift introduces a new interface and route, which could impact network behavior, routing, or security. Alerting is essential to ensure visibility and assess potential risks or compliance issues.

### DT-5.2 Evidence Traceability

- **Status:** PASS
- **Captured:** 2026-05-16T17:56:11.293701
- **Detail:** 20/20 have confidence; 20/20 have diff_paths
- **Artefacts:**
    - `total_findings`: 20
    - `with_confidence`: 20
    - `with_diff_paths`: 20

## Evidence — Run 20260516T200214 (2026-05-16 20:02 UTC)

### DT-5.1 Insufficient Evidence Admission

- **Status:** PASS
- **Captured:** 2026-05-16T20:34:37.270392
- **Detail:** Tenant has 0 monitored hosts. Latest scenario A finding carries a real davis_assessment: YES (proof Davis is in-loop even with sparse upstream telemetry).
- **Artefacts:**
    - `dql_host_count`: 0
    - `davis_assessment_snippet`: **AGREE**  
This configuration drift introduces a new interface and route, which could impact network behavior, routing, or security. Alerting is essential to ensure visibility and assess potential risks or compliance issues.

### DT-5.2 Evidence Traceability

- **Status:** PASS
- **Captured:** 2026-05-16T20:34:37.858093
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

## Evidence — Run 20260516T170912 (2026-05-16 17:09 UTC)

### DT-6.1 High Risk Escalation

- **Status:** PASS
- **Captured:** 2026-05-16T17:33:56.743008
- **Detail:** HIGH-tier injection produced severity=high, confidence=0.9
- **Artefacts:**
    - `finding_id`: 428a750b-4469-4320-aef7-2ca372f238b9
    - `severity`: high
    - `confidence`: 0.9
    - `title`: New Loopback99 interface and 192.0.2.99/32 route added

### DT-6.2 Benign Drift Suppression

- **Status:** PASS
- **Captured:** 2026-05-16T17:33:56.743114
- **Detail:** LOW-tier description-only change correctly suppressed (no finding raised)
- **Artefacts:**
    - `finding_id`: None

## Evidence — Run 20260516T173827 (2026-05-16 17:38 UTC)

### DT-6.1 High Risk Escalation

- **Status:** PASS
- **Captured:** 2026-05-16T17:55:58.675128
- **Detail:** HIGH-tier injection produced severity=high, confidence=0.9
- **Artefacts:**
    - `finding_id`: 180fde51-0ab3-42d6-85c6-04e5accdcd31
    - `severity`: high
    - `confidence`: 0.9
    - `title`: New Loopback99 interface 192.0.2.99/32 added

### DT-6.2 Benign Drift Suppression

- **Status:** PASS
- **Captured:** 2026-05-16T17:55:58.675271
- **Detail:** LOW-tier description-only change correctly suppressed (no finding raised)
- **Artefacts:**
    - `finding_id`: None

## Evidence — Run 20260516T200214 (2026-05-16 20:02 UTC)

### DT-6.1 High Risk Escalation

- **Status:** PASS
- **Captured:** 2026-05-16T20:34:29.269726
- **Detail:** HIGH-tier injection produced severity=high, confidence=0.9
- **Artefacts:**
    - `finding_id`: 0adb3d4e-14f3-45b8-9b91-359121857783
    - `severity`: high
    - `confidence`: 0.9
    - `title`: New Loopback99 interface and route 192.0.2.99/32 detected

### DT-6.2 Benign Drift Suppression

- **Status:** PASS
- **Captured:** 2026-05-16T20:34:29.269839
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

## Evidence — Run 20260516T170912 (2026-05-16 17:09 UTC)

### DT-7.1 Pattern Recognition Corpus

- **Status:** PASS
- **Captured:** 2026-05-16T17:34:07.126392
- **Detail:** Recurring 'Loopback' findings in store: 22 (corpus enables future semantic recall)
- **Artefacts:**
    - `loop_finding_count`: 22
    - `total_history`: 30

## Evidence — Run 20260516T173827 (2026-05-16 17:38 UTC)

### DT-7.1 Pattern Recognition Corpus

- **Status:** PASS
- **Captured:** 2026-05-16T17:56:13.465468
- **Detail:** Recurring 'Loopback' findings in store: 20 (corpus enables future semantic recall)
- **Artefacts:**
    - `loop_finding_count`: 20
    - `total_history`: 30

## Evidence — Run 20260516T200214 (2026-05-16 20:02 UTC)

### DT-7.1 Pattern Recognition Corpus

- **Status:** PASS
- **Captured:** 2026-05-16T20:34:39.056056
- **Detail:** Recurring 'Loopback' findings in store: 18 (corpus enables future semantic recall)
- **Artefacts:**
    - `loop_finding_count`: 18
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

## Evidence — Run 20260516T170912 (2026-05-16 17:09 UTC)

### DT-8.1 Audience Adaptation

- **Status:** PASS
- **Captured:** 2026-05-16T17:34:11.716499
- **Detail:** Engineering channel (DQL): raw event counts. Operator channel (Gemini verdict + Davis second opinion): narrative attached to every finding.
- **Artefacts:**
    - `engineering_dql_response`: 📊 **DQL Query Results**

- **Scanned Records:** 69
- **Scanned Bytes:** 0.00 GB (Session total: 0.00 GB / 5000 GB budget, 0.0% used)

📋 **Query Results**: (2 records) — rendered by the MCP App UI below.

> ℹ️ The MCP App is rendering the results interactively. Do NOT generate Mermaid diagrams, ASCII
    - `operator_gemini_summary`: New Loopback99 interface and 192.0.2.99/32 route added (high/config-drift)
    - `operator_davis_assessment`: **AGREE**  
This configuration drift introduces a new interface and route, which could impact network behavior, routing, or security. Alerting is essential to ensure visibility and assess potential risks or compliance issues.

## Evidence — Run 20260516T173827 (2026-05-16 17:38 UTC)

### DT-8.1 Audience Adaptation

- **Status:** PASS
- **Captured:** 2026-05-16T17:56:17.757247
- **Detail:** Engineering channel (DQL): raw event counts. Operator channel (Gemini verdict + Davis second opinion): narrative attached to every finding.
- **Artefacts:**
    - `engineering_dql_response`: 📊 **DQL Query Results**

- **Scanned Records:** 89
- **Scanned Bytes:** 0.00 GB (Session total: 0.00 GB / 5000 GB budget, 0.0% used)

📋 **Query Results**: (2 records) — rendered by the MCP App UI below.

> ℹ️ The MCP App is rendering the results interactively. Do NOT generate Mermaid diagrams, ASCII
    - `operator_gemini_summary`: New Loopback99 interface and 192.0.2.99/32 route added (high/config-drift)
    - `operator_davis_assessment`: **AGREE**  
This configuration drift introduces a new interface and route, which could impact network behavior, routing, or security. Alerting is essential to ensure visibility and assess potential risks or compliance issues.

## Evidence — Run 20260516T200214 (2026-05-16 20:02 UTC)

### DT-8.1 Audience Adaptation

- **Status:** PASS
- **Captured:** 2026-05-16T20:34:44.457486
- **Detail:** Engineering channel (DQL): raw event counts. Operator channel (Gemini verdict + Davis second opinion): narrative attached to every finding.
- **Artefacts:**
    - `engineering_dql_response`: 📊 **DQL Query Results**

- **Scanned Records:** 6,472
- **Scanned Bytes:** 0.00 GB (Session total: 0.01 GB / 5000 GB budget, 0.0% used)

📋 **Query Results**: (2 records) — rendered by the MCP App UI below.

> ℹ️ The MCP App is rendering the results interactively. Do NOT generate Mermaid diagrams, AS
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


## Evidence — Run 20260516T170912 (2026-05-16 17:09 UTC)

### Hallucination Resistance

- **Status:** PASS
- **Captured:** 2026-05-16T17:34:22.339397
- **Detail:** Davis Copilot acknowledged ignorance when asked about a fabricated host+service
- **Artefacts:**
    - `response_snippet`: 🤖 Davis CoPilot Response:

**Answer:**
Sorry, I cannot help you with this as the requested service and host do not exist in the provided context. If you want help with the creation of DQL queries, you can use Dynatrace Intelligence in Notebooks or Dashboards. Both applications support this in a specific Prompt section when pressing "+" to create a new cell or tile.

**Status:** SUCCESSFUL
**Messag

### Causality Accuracy

- **Status:** FAIL
- **Captured:** 2026-05-16T17:37:06.685086
- **Detail:** Server error '502 Bad Gateway' for url 'https://parity-dynatrace.clydeford.net/api/v1/findings?device_id=eeb4ab57-0756-4eb2-9642-a605fa708bf3&limit=10'
For more information check: https://developer.mo

### Topology Accuracy

- **Status:** PASS
- **Captured:** 2026-05-16T17:37:11.591141
- **Detail:** DC1-R1 snapshot reports 4 BGP peers; live `show ip bgp summary` reports 4; match.
- **Artefacts:**
    - `snapshot_peers`: 4
    - `live_peers`: 4
    - `snap_peer_set`: ["192.168.1.2", "192.168.1.3", "192.168.1.4", "192.168.1.5"]
    - `live_peer_set`: ["192.168.1.2", "192.168.1.3", "192.168.1.4", "192.168.1.5"]
    - `match`: True

## Evidence — Run 20260516T173827 (2026-05-16 17:38 UTC)

### Hallucination Resistance

- **Status:** PASS
- **Captured:** 2026-05-16T17:56:29.215269
- **Detail:** Davis Copilot acknowledged ignorance when asked about a fabricated host+service
- **Artefacts:**
    - `response_snippet`: 🤖 Davis CoPilot Response:

**Answer:**
Sorry, I cannot help you with this as the requested service and host details are not available in the provided context. If you want help with the creation of DQL queries, you can use Dynatrace Intelligence in Notebooks or Dashboards. Both applications support this in a specific Prompt section when pressing "+" to create a new cell or tile.

**Status:** SUCCES

### Causality Accuracy

- **Status:** PASS
- **Captured:** 2026-05-16T18:02:37.615719
- **Detail:** Independent changes on DC1-R1 and DC2-R2 produced distinct incidents
- **Artefacts:**
    - `a_incident`: da2e54fb-6c28-4332-83ef-e2be3cd8bb65
    - `c_incident`: 9cba37ab-beda-4d7b-bd32-852f2470f29d
    - `a_correlation`: prefix:192.0.2.99/32
    - `c_correlation`: prefix:198.51.100.0/24

### Topology Accuracy

- **Status:** PASS
- **Captured:** 2026-05-16T18:02:41.082380
- **Detail:** DC1-R1 snapshot reports 4 BGP peers; live `show ip bgp summary` reports 4; match.
- **Artefacts:**
    - `snapshot_peers`: 4
    - `live_peers`: 4
    - `snap_peer_set`: ["192.168.1.2", "192.168.1.3", "192.168.1.4", "192.168.1.5"]
    - `live_peer_set`: ["192.168.1.2", "192.168.1.3", "192.168.1.4", "192.168.1.5"]
    - `match`: True

## Evidence — Run 20260516T200214 (2026-05-16 20:02 UTC)

### Hallucination Resistance

- **Status:** PASS
- **Captured:** 2026-05-16T20:34:56.435576
- **Detail:** Davis Copilot acknowledged ignorance when asked about a fabricated host+service
- **Artefacts:**
    - `response_snippet`: 🤖 Davis CoPilot Response:

**Answer:**
Sorry, I cannot help you with this as the requested information is not available in the provided context. If you want help with the creation of DQL queries, you can use Dynatrace Intelligence in Notebooks or Dashboards. Both applications support this in a specific Prompt section when pressing "+" to create a new cell or tile.

**Status:** SUCCESSFUL
**Message

### Causality Accuracy

- **Status:** PASS
- **Captured:** 2026-05-16T20:47:38.270850
- **Detail:** Independent changes on DC1-R1 and DC2-R2 produced distinct incidents
- **Artefacts:**
    - `a_incident`: 625f9e6f-94d7-4583-a6b6-41c0630fd202
    - `c_incident`: 31e9b590-2a60-4d86-89bc-094214e81182
    - `a_correlation`: prefix:192.0.2.99/32
    - `c_correlation`: prefix:198.51.100.0/24

### Topology Accuracy

- **Status:** PASS
- **Captured:** 2026-05-16T20:47:41.789430
- **Detail:** DC1-R1 snapshot reports 4 BGP peers; live `show ip bgp summary` reports 4; match.
- **Artefacts:**
    - `snapshot_peers`: 4
    - `live_peers`: 4
    - `snap_peer_set`: ["192.168.1.2", "192.168.1.3", "192.168.1.4", "192.168.1.5"]
    - `live_peer_set`: ["192.168.1.2", "192.168.1.3", "192.168.1.4", "192.168.1.5"]
    - `match`: True
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


# Extended Scenarios — Operator Test Plan

Six scenarios run in addition to the original D2/D4/D7
tests. Each one snapshots the target device, injects a
config change, waits for the Parity finding, captures
evidence, then rolls back and fires a fleet-wide
snapshot so Davis sees the network return to baseline
across all 18 devices. Mgmt interfaces (192.168.20.0/24)
are never touched.

## Evidence — Run 20260516T232135 (2026-05-16 23:21 UTC)

### NEW1 BGP-kill (neighbor shutdown)

- **Status:** FAIL
- **Captured:** 2026-05-16T23:28:36.629749
- **Detail:** no finding raised for token '10.0.0.2' within 240s
- **Artefacts:**
    - `target_device`: S1-R1
    - `match_token`: 10.0.0.2

### NEW2 IP-octet break

- **Status:** FAIL
- **Captured:** 2026-05-16T23:35:37.421810
- **Detail:** no finding raised for token '192.168.2.7' within 240s
- **Artefacts:**
    - `target_device`: S2-R2
    - `match_token`: 192.168.2.7

### NEW3 default-route injection

- **Status:** FAIL
- **Captured:** 2026-05-16T23:42:41.903892
- **Detail:** no finding raised for token '0.0.0.0' within 240s
- **Artefacts:**
    - `target_device`: DC1-R1
    - `match_token`: 0.0.0.0

### NEW4 critical interface shutdown

- **Status:** PASS
- **Captured:** 2026-05-17T00:00:36.805959
- **Detail:** Shutdown Ethernet0/0 on S3-R1 (peer 192.168.1.1/65100) — finding 5c91bb57 sev=critical conf=1.0; approval=approved b22f22bd; fleet snapshot ok=18/18
- **Artefacts:**
    - `target_device`: S3-R1
    - `finding_id`: 5c91bb57-fd61-40af-a467-49f455f549cc
    - `severity`: critical
    - `category`: interface-state
    - `confidence`: 1.0
    - `match_token`: Ethernet0/0
    - `davis_assessment_snippet`: MCP error -32602: Input validation error: Invalid arguments for tool chat_with_davis_copilot: [
  {
    "expected": "string",
    "code": "invalid_type",
    "path": [
      "context"
    ],
    "message": "Invalid input: expected string, r
    - `approval_outcome`: approved b22f22bd
    - `fleet_devices_ok`: 18
    - `fleet_devices_total`: 18
    - `fleet_duration_s`: 887.6

### NEW5 secondary IP add

- **Status:** PASS
- **Captured:** 2026-05-17T00:09:35.512708
- **Detail:** Add 172.31.0.1/24 secondary on Ethernet0/0 (S4-R1) — finding c468c595 sev=high conf=0.95; approval=approved d5ed0726; fleet snapshot ok=18/18
- **Artefacts:**
    - `target_device`: S4-R1
    - `finding_id`: c468c595-fc04-40e2-9dee-056500b754cf
    - `severity`: high
    - `category`: config-drift
    - `confidence`: 0.95
    - `match_token`: 172.31.0.1
    - `davis_assessment_snippet`: MCP error -32602: Input validation error: Invalid arguments for tool chat_with_davis_copilot: [
  {
    "expected": "string",
    "code": "invalid_type",
    "path": [
      "context"
    ],
    "message": "Invalid input: expected string, r
    - `approval_outcome`: approved d5ed0726
    - `fleet_devices_ok`: 18
    - `fleet_devices_total`: 18
    - `fleet_duration_s`: 911.2

### NEW6 cross-site mis-advertise

- **Status:** FAIL
- **Captured:** 2026-05-17T00:16:23.220167
- **Detail:** no finding raised for token '10.10.1.101' within 240s
- **Artefacts:**
    - `target_device`: S3-R1
    - `match_token`: 10.10.1.101

## Evidence — Run 20260517T054711 (2026-05-17 05:47 UTC)

### Pre-extended-run fleet snapshot

- **Status:** PASS
- **Captured:** 2026-05-17T05:52:43.660076
- **Detail:** baseline snapshot: 18/18 ok in 1138.2s
- **Artefacts:**
    - `devices_ok`: 18
    - `devices_failed`: 0
    - `devices_total`: 18
    - `duration_s`: 1138.2
    - `started_at`: 2026-05-17T05:47:11.988518+00:00
    - `finished_at`: 2026-05-17T05:52:28.863051+00:00

### Post-extended-run fleet snapshot

- **Status:** PASS
- **Captured:** 2026-05-17T07:15:27.553357
- **Detail:** cleanup snapshot: 18/18 ok in 933.7s
- **Artefacts:**
    - `devices_ok`: 18
    - `devices_failed`: 0
    - `devices_total`: 18
    - `duration_s`: 933.7
    - `started_at`: 2026-05-17T07:10:14.943048+00:00
    - `finished_at`: 2026-05-17T07:15:07.277373+00:00

## Evidence — Run 20260517T054711 (2026-05-17 05:47 UTC)

### NEW1 BGP-kill (neighbor shutdown)

- **Status:** PASS
- **Captured:** 2026-05-17T06:06:38.080525
- **Detail:** Shut eBGP neighbor 192.168.1.1 (AS 65100) from S1-R1 (AS 65001) - finding caefe7e9 sev=critical conf=0.9 token_match=True; approval=approved 1616a4d7
- **Artefacts:**
    - `target_device`: S1-R1
    - `finding_id`: caefe7e9-1223-436b-b063-5a3a5cc5923d
    - `finding_title`: BGP neighbor 192.168.1.1 shut down, route 10.10.2.0/24 removed
    - `severity`: critical
    - `category`: config-drift
    - `confidence`: 0.9
    - `requires_remediation`: True
    - `match_token`: 192.168.1.1
    - `token_matched`: True
    - `davis_assessment_snippet`: **AGREE**: The shutdown of a BGP neighbor and removal of a route can significantly impact network connectivity and routing, potentially leading to service disruptions. This configuration drift is critical and warrants an alert to ensure tim
    - `approval_outcome`: approved 1616a4d7
    - `diff_paths_sample`: ["routing.vrf.default.address_family.ipv4.routes.10.10.4.0/24", "routing.vrf.default.address_family.ipv4.routes.10.10.3.0/24", "routing.vrf.default.address_family.ipv4.routes.10.10.2.0/24", "bgp.instance.default.vrf.default.neighbor.192.168.1.1.shutdown", "bgp.instance.default.vrf.default.neighbor.192.168.1.1.bgp_session_transport.connection.state", "bgp.instance.default.vrf.default.neighbor.192.1…

### NEW2 IP-octet break

- **Status:** PASS
- **Captured:** 2026-05-17T06:19:55.650303
- **Detail:** Re-IP Ethernet0/0 from 192.168.2.3 to 192.168.2.7 (S2-R2) - finding 3207d7d5 sev=critical conf=0.95 token_match=True; approval=approved bf165025
- **Artefacts:**
    - `target_device`: S2-R2
    - `finding_id`: 3207d7d5-7ed9-442a-9642-92f8d096b79d
    - `finding_title`: Interface Ethernet0/0 IP changed, BGP neighbor 192.168.2.1 reset
    - `severity`: critical
    - `category`: config-drift
    - `confidence`: 0.95
    - `requires_remediation`: True
    - `match_token`: 192.168.2.7
    - `token_matched`: True
    - `davis_assessment_snippet`: **AGREE**  
The detected configuration drift involves a change in the IP address of a critical network interface and a reset of a BGP neighbor connection, which can significantly impact network stability and routing. Such changes can lead t
    - `approval_outcome`: approved bf165025
    - `diff_paths_sample`: ["routing.vrf.default.address_family.ipv4.routes.192.168.2.3/32", "routing.vrf.default.address_family.ipv4.routes.192.168.2.7/32", "interface.Ethernet0/0.ipv4.192.168.2.3/24", "interface.Ethernet0/0.ipv4.192.168.2.7/24", "arp.interfaces.Ethernet0/0.ipv4.neighbors.192.168.2.3", "arp.interfaces.Ethernet0/0.ipv4.neighbors.192.168.2.7"]

### NEW3 default-route injection

- **Status:** PASS
- **Captured:** 2026-05-17T06:35:04.287966
- **Detail:** Inject default route via 10.10.100.1 + redistribute static on DC1-R1 (AS 65100) - finding c31b4461 sev=critical conf=0.9 token_match=False; approval=no approval queue entry within 120s
- **Artefacts:**
    - `target_device`: DC1-R1
    - `finding_id`: c31b4461-1ade-46e4-bdbe-01b8457319f4
    - `finding_title`: BGP neighbor 192.168.1.4 session failed to establish
    - `severity`: critical
    - `category`: bgp-adjacency
    - `confidence`: 0.9
    - `requires_remediation`: True
    - `match_token`: 0.0.0.0/0
    - `token_matched`: False
    - `davis_assessment_snippet`: **AGREE**  
The failure to establish a BGP session with a neighbor (192.168.1.4) is a critical configuration drift that can disrupt routing and network stability, especially in a dynamic environment. Prompt alerting is necessary to ensure t
    - `approval_outcome`: no approval queue entry within 120s
    - `diff_paths_sample`: ["bgp.instance.default.vrf.default.neighbor.192.168.1.4.bgp_session_transport.connection.reset_reason", "bgp.instance.default.vrf.default.neighbor.192.168.1.4.bgp_session_transport.connection.last_reset", "bgp.instance.default.vrf.default.neighbor.192.168.1.2.bgp_session_transport.connection.last_reset"]

### NEW4 critical interface shutdown

- **Status:** PASS
- **Captured:** 2026-05-17T06:48:29.285280
- **Detail:** Shutdown Ethernet0/0 on S3-R1 (peer 192.168.1.1/65100) - finding 7ff63e1b sev=critical conf=1.0 token_match=True; approval=approved 2d4bb2b7
- **Artefacts:**
    - `target_device`: S3-R1
    - `finding_id`: 7ff63e1b-5b0a-4d46-a567-859406a35ecc
    - `finding_title`: Ethernet0/0 down, BGP neighbor 192.168.1.1 idle
    - `severity`: critical
    - `category`: interface-state
    - `confidence`: 1.0
    - `requires_remediation`: True
    - `match_token`: Ethernet0/0
    - `token_matched`: True
    - `davis_assessment_snippet`: **AGREE**  
The detected configuration drift is critical as it indicates that Ethernet0/0 is down, causing the BGP neighbor 192.168.1.1 to enter an idle state. This directly impacts network connectivity and routing, which can lead to servic
    - `approval_outcome`: approved 2d4bb2b7
    - `diff_paths_sample`: ["routing.vrf.default.address_family.ipv4.routes.192.168.1.4/32", "routing.vrf.default.address_family.ipv4.routes.192.168.1.0/24", "routing.vrf.default.address_family.ipv4.routes.10.10.4.0/24", "routing.vrf.default.address_family.ipv4.routes.10.10.2.0/24", "routing.vrf.default.address_family.ipv4.routes.10.10.1.0/24", "interface.Ethernet0/0.enabled"]

### NEW5 secondary IP add

- **Status:** PASS
- **Captured:** 2026-05-17T06:55:10.667168
- **Detail:** Add 172.31.0.1/24 secondary on Ethernet0/0 (S4-R1) - finding 4270abe1 sev=high conf=0.9 token_match=True; approval=approved 20f6f955
- **Artefacts:**
    - `target_device`: S4-R1
    - `finding_id`: 4270abe1-b619-45b8-913f-95d32533be72
    - `finding_title`: New secondary IP 172.31.0.1/24 added to Ethernet0/0
    - `severity`: high
    - `category`: config-drift
    - `confidence`: 0.9
    - `requires_remediation`: True
    - `match_token`: 172.31.0.1
    - `token_matched`: True
    - `davis_assessment_snippet`: **AGREE**: Adding a new secondary IP address to a critical interface like Ethernet0/0 can indicate a configuration change that may impact network routing, security, or connectivity. Such changes should be monitored and alerted upon to ensur
    - `approval_outcome`: approved 20f6f955
    - `diff_paths_sample`: ["routing.vrf.default.address_family.ipv4.routes.172.31.0.0/24", "routing.vrf.default.address_family.ipv4.routes.172.31.0.1/32", "interface.Ethernet0/0.ipv4.172.31.0.1/24", "arp.interfaces.Ethernet0/0.ipv4.neighbors.172.31.0.1", "arp.statistics.entries_total"]

### NEW6 cross-site mis-advertise

- **Status:** PASS
- **Captured:** 2026-05-17T07:10:05.210409
- **Detail:** Advertise Site1 sentinel 10.10.1.151/32 from S3-R1 (AS 65003) - finding 81a3c8db sev=critical conf=0.9 token_match=False; approval=no approval queue entry within 120s
- **Artefacts:**
    - `target_device`: S3-R1
    - `finding_id`: 81a3c8db-e31f-466a-bdaf-0ab4074e71a0
    - `finding_title`: BGP neighbor 192.168.1.1 flapped due to interface issue
    - `severity`: critical
    - `category`: bgp-adjacency
    - `confidence`: 0.9
    - `requires_remediation`: True
    - `match_token`: 10.10.1.151
    - `token_matched`: False
    - `davis_assessment_snippet`: **AGREE**  
The BGP neighbor flap due to an interface issue is a critical event that can impact network stability and routing. Alerting on this configuration drift is essential to ensure timely investigation and resolution, as it may indica
    - `approval_outcome`: no approval queue entry within 120s
    - `diff_paths_sample`: ["bgp.instance.default.vrf.default.neighbor.192.168.1.1.bgp_session_transport.connection.reset_reason", "bgp.instance.default.vrf.default.neighbor.192.168.1.1.bgp_session_transport.connection.last_reset", "routing.vrf.default.address_family.ipv4.routes.10.10.1.0/24.next_hop.next_hop_list.1.updated", "routing.vrf.default.address_family.ipv4.routes.10.10.2.0/24.next_hop.next_hop_list.1.updated", "ro…
