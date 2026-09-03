# LogCouncil Product Contract

Status: MVP contract  
Version: 0.1  
Last updated: 2026-09-03

## 1. Product promise

LogCouncil accepts logs supplied by a user and returns an evidence-bound incident explanation plus safe, prioritized next actions.

The product must help a user answer:

1. What happened?
2. When did it start, change, and recover?
3. Which services, hosts, requests, or traces were affected?
4. What root-cause hypotheses are supported by the supplied logs?
5. What should the user inspect or do next?

LogCouncil must never present an unsupported hypothesis as a confirmed root cause.

## 2. Inputs

The MVP accepts:

- pasted log text;
- `.log`, `.txt`, and `.jsonl` files;
- JSONL records with a message and optional timestamp, level, service, host, request ID, or trace ID;
- common text logs containing a timestamp, level, optional source, and message.

Every non-empty input line must either become a `LogEvent` or produce a visible data-quality issue. Unknown lines are preserved as raw evidence.

The MVP analyzes logs only. Metrics, distributed traces, packet captures, industrial alarm-code sequences, and infrastructure control-plane access are outside the input contract.

## 3. Outputs

Every completed analysis returns:

- an incident summary;
- affected entities and time window, when discoverable;
- one or more ranked hypotheses;
- confidence for each hypothesis;
- supporting and contradicting event IDs;
- an evidence chain that links claims back to source logs;
- prioritized next actions;
- missing evidence or requested additional logs;
- a complete Agent activity and handoff ledger.

The UI and JSON report must distinguish three information classes:

- **Observed**: directly present in a supplied log event.
- **Inferred**: a hypothesis derived from one or more cited events.
- **Recommended**: a proposed user action, not an executed action.

## 4. Epistemic behavior

An analysis may end in one of three states:

### Supported hypothesis

The logs contain a coherent sequence and enough independent evidence to rank a leading explanation. The product reports it as a likely cause with confidence and caveats.

### Competing hypotheses

Two or more explanations remain plausible. The product ranks them, shows the evidence for and against each one, and recommends the next discriminating check.

### Insufficient evidence

The logs show a symptom but cannot establish a cause. The product says so and requests specific additional logs, sources, identifiers, or time windows.

Absence of evidence is not evidence of absence. A missing service or time range must be reported as a coverage limitation.

## 5. Agent responsibilities

- **Parser** normalizes input without discarding unknown lines. It is a deterministic ingestion component, not a reasoning Agent.
- **Pattern Agent** detects repeated templates, bursts, retries, rare failures, and severity changes.
- **Timeline Agent** reconstructs event order, onset, propagation, and recovery.
- **Correlation Agent** connects events by service, host, request ID, trace ID, and bounded time proximity.
- **Root Cause Agent** compares competing explanations using only registered evidence IDs.
- **Reviewer Agent** checks unsupported claims, counter-evidence, alternative causes, and missing coverage.
- **Coordinator** validates handoffs and emits the final report only after review.

Agents exchange typed findings and evidence references. Free-form Agent text cannot add evidence to the ledger.

## 6. Safety boundary

The MVP is read-only:

- it does not execute remediation commands;
- it does not connect to production systems;
- it does not restart, deploy, scale, delete, or modify resources;
- it does not upload user logs to an external service;
- it does not require an LLM or API key.

Recommended commands must be shown as suggestions with purpose, expected evidence, risk, and rollback notes where applicable. Any future execution feature requires a separate approval contract.

## 7. Privacy boundary

Analysis is local by default. Reports must not duplicate secrets discovered in logs. Before a future external LLM adapter receives data, a redaction layer and explicit opt-in will be required.

The MVP should detect and redact common bearer tokens, API keys, passwords, cookies, and authorization headers from rendered summaries and exported reports. Original local evidence remains unchanged unless the user explicitly exports a redacted copy.

## 8. Dataset policy

Primary public datasets:

- **Loghub OpenStack** for raw text-log parsing, template extraction, and anomaly analysis.
- **RCAEval RE3-OB logs only** for microservice log RCA and ground-truth evaluation.

RCAEval metrics and traces are intentionally excluded. ALPI alarm-code events are not part of this project.

Small synthetic logs are allowed only as deterministic test fixtures for malformed input, duplicate IDs, missing timestamps, handoff failures, reviewer challenges, and CI smoke tests. They must be labeled synthetic and are not product evidence.

External datasets remain outside Git. The repository stores only download instructions, provenance, checksums, adapters, and derived test metadata permitted by the source license.

## 9. MVP acceptance criteria

Given a supported log file, a user must be able to:

1. start an analysis without an API key;
2. inspect parse coverage and all rejected or fallback lines;
3. see Pattern, Timeline, and Correlation investigations as separate activities;
4. inspect every Agent handoff;
5. click every cited event ID and reach the original log line;
6. distinguish observations, hypotheses, contradictions, and recommendations;
7. receive a specific request for more evidence when a cause cannot be established;
8. export a deterministic JSON report;
9. replay the same input and receive the same evidence references and conclusions;
10. run the unit and integration test suite without downloading external datasets.

No-consensus and Agent-failure paths are required product states, not exceptional UI crashes.

## 10. Non-goals for the MVP

- autonomous remediation;
- production environment access;
- metrics or trace analysis;
- model training or anomaly prediction;
- security event investigation;
- conversational memory across unrelated incidents;
- claiming universal root-cause accuracy from a limited benchmark.
