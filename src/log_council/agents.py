from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .models import AgentFinding, Evidence, Hypothesis, LogEvent


def _contains(event: LogEvent, *terms: str) -> bool:
    haystack = f"{event.service} {event.message}".lower()
    return any(term in haystack for term in terms)


def _ev(event: LogEvent, reason: str, stance: str = "supporting") -> Evidence:
    return Evidence(event.id, reason, stance)  # type: ignore[arg-type]


class PatternAgent:
    name = "Pattern Agent"

    def analyze(self, events: list[LogEvent]) -> AgentFinding:
        failures = [e for e in events if e.level in {"ERROR", "CRITICAL", "FATAL"}]
        pool = [e for e in events if _contains(e, "pool", "connection limit", "connections approaching")]
        normalized = Counter(
            re.sub(r"\b\d+(?:\.\d+)?\b", "#", e.message.lower()) for e in failures
        )
        repeated = max(normalized.values(), default=0)
        evidence = [_ev(e, "Repeated resource-pressure or connection symptom") for e in pool[:4]]
        if not evidence:
            evidence = [_ev(e, "High-severity event") for e in failures[:4]]
        if pool:
            title = "Connection pressure pattern detected"
            summary = f"Found {len(pool)} connection/pool signals and {len(failures)} high-severity events."
        elif failures:
            title = "Failure cluster detected"
            summary = f"Found {len(failures)} high-severity events; the largest normalized pattern repeats {repeated} times."
        else:
            title = "No dominant failure pattern"
            summary = "The sample contains no ERROR/CRITICAL events; conclusions should remain tentative."
        confidence = min(0.96, 0.45 + len(evidence) * 0.11 + min(repeated, 3) * 0.04)
        return AgentFinding(
            agent=self.name, title=title, summary=summary, confidence=confidence,
            evidence=evidence,
            details=[
                f"High-severity events: {len(failures)}",
                f"Connection/pool signals: {len(pool)}",
                f"Largest repeated failure pattern: {repeated}",
            ],
        )


class TimelineAgent:
    name = "Timeline Agent"

    def analyze(self, events: list[LogEvent]) -> AgentFinding:
        ordered = sorted(events, key=lambda e: (e.timestamp is None, e.timestamp or 0))
        slow = next((e for e in ordered if _contains(e, "slow query", "latency", "took ")), None)
        pressure = next((e for e in ordered if _contains(e, "pool at capacity", "pool exhausted", "connection limit")), None)
        timeout = next((e for e in ordered if _contains(e, "timeout", "timed out", "504")), None)
        recovery = next((e for e in ordered if _contains(e, "recovered", "returned to baseline", "latency normal")), None)
        milestones = [item for item in (slow, pressure, timeout, recovery) if item]
        evidence = [_ev(event, "Chronological milestone") for event in milestones]
        if len(milestones) >= 3:
            title = "Ordered degradation chain established"
            summary = "A precursor, resource-pressure symptom, downstream failure, and/or recovery appear in causal order."
            confidence = 0.87 if recovery else 0.79
        else:
            title = "Timeline is incomplete"
            summary = "Too few distinct milestones are present to establish a strong causal sequence."
            confidence = 0.48 + len(milestones) * 0.08
        return AgentFinding(
            agent=self.name, title=title, summary=summary, confidence=min(confidence, 0.9),
            evidence=evidence,
            details=[f"{event.timestamp_text} · {event.service} · {event.message}" for event in milestones],
        )


@dataclass(frozen=True)
class CauseRule:
    title: str
    explanation: str
    terms: tuple[str, ...]
    actions: tuple[str, ...]
    chain: tuple[str, ...]


CAUSE_RULES = (
    CauseRule(
        "Database connection pool exhaustion",
        "Database work held connections long enough to exhaust the application pool, queue requests, and trigger upstream timeouts.",
        ("slow query", "pool at capacity", "pool exhausted", "timed out waiting for database", "connection limit"),
        ("Inspect the slowest database queries and their query plans.", "Alert on pool wait time and pool utilization.", "Apply a bounded query/index fix before increasing pool size."),
        ("Slow database operation", "Connection pool saturation", "Request queueing", "Upstream timeout"),
    ),
    CauseRule(
        "Memory exhaustion or process pressure",
        "Memory pressure caused allocation failures, process termination, or repeated restarts.",
        ("out of memory", "oom", "killed process", "heap", "memory limit"),
        ("Capture memory profiles around the incident window.", "Review container limits and restart counts.", "Add memory saturation alerts."),
        ("Memory growth", "Resource limit reached", "Process disruption", "Request failures"),
    ),
    CauseRule(
        "Network or upstream dependency failure",
        "Connectivity or upstream response failures propagated into request timeouts.",
        ("connection refused", "dns", "network unreachable", "upstream timeout", "tls handshake"),
        ("Check dependency health and network telemetry.", "Correlate failures by trace ID.", "Validate timeout and retry budgets."),
        ("Dependency degradation", "Connection failures", "Retry/queue pressure", "Request timeout"),
    ),
    CauseRule(
        "Authentication or credential failure",
        "Rejected or expired credentials prevented normal service-to-service access.",
        ("unauthorized", "forbidden", "token expired", "invalid credential", "401", "403"),
        ("Validate credential rotation and expiry timestamps.", "Audit authorization policy changes.", "Add expiry-window alerts."),
        ("Credential or policy change", "Authorization rejected", "Dependency unavailable", "Request failure"),
    ),
)


class RootCauseAgent:
    name = "Root Cause Agent"

    def analyze(self, events: list[LogEvent]) -> tuple[AgentFinding, list[Hypothesis], CauseRule]:
        scored: list[tuple[int, CauseRule, list[LogEvent]]] = []
        for rule in CAUSE_RULES:
            matched = [e for e in events if _contains(e, *rule.terms)]
            diversity = len({term for term in rule.terms if any(_contains(e, term) for e in events)})
            score = len(matched) + diversity * 2
            scored.append((score, rule, matched))
        scored.sort(key=lambda item: item[0], reverse=True)
        hypotheses: list[Hypothesis] = []
        for score, rule, matched in scored[:3]:
            confidence = min(0.92, 0.28 + score * 0.07)
            hypotheses.append(Hypothesis(
                title=rule.title,
                explanation=rule.explanation,
                confidence=confidence,
                supporting=[_ev(event, f"Matches {rule.title.lower()}") for event in matched[:5]],
            ))
        best_score, best, matched = scored[0]
        finding = AgentFinding(
            agent=self.name,
            title=best.title if best_score else "Insufficient evidence for a root cause",
            summary=best.explanation if best_score else "No known cause pattern has enough evidence.",
            confidence=hypotheses[0].confidence if best_score else 0.25,
            evidence=[_ev(event, "Supports leading root-cause hypothesis") for event in matched[:5]],
            details=[f"Compared {len(CAUSE_RULES)} competing cause families.", f"Leading rule score: {best_score}."],
        )
        return finding, hypotheses, best


class ReviewerAgent:
    name = "Reviewer Agent"

    def analyze(self, events: list[LogEvent], hypotheses: list[Hypothesis]) -> AgentFinding:
        leading = hypotheses[0]
        deployments = [e for e in events if _contains(e, "deploy", "release", "version")]
        recovery = [e for e in events if _contains(e, "recovered", "returned to baseline", "latency normal")]
        healthy = [e for e in events if e.level == "INFO" and _contains(e, "completed", "healthy", "baseline")]
        evidence: list[Evidence] = []
        details: list[str] = []
        if deployments:
            event = deployments[0]
            leading.contradicting.append(_ev(event, "Recent deployment is a competing trigger", "contradicting"))
            evidence.append(_ev(event, "Challenged the leading cause with deployment timing", "contradicting"))
            details.append("Competing hypothesis: a recent deployment may have contributed.")
        if recovery:
            evidence.append(_ev(recovery[0], "Recovery correlation supports the proposed causal chain"))
            details.append("Recovery timing is consistent with the leading hypothesis.")
        if healthy:
            evidence.append(_ev(healthy[0], "Healthy peer activity limits the incident scope", "context"))
        confidence = max(0.35, min(0.9, leading.confidence - (0.06 if deployments else 0) + (0.06 if recovery else 0)))
        return AgentFinding(
            agent=self.name,
            title="Leading hypothesis survives review" if confidence >= 0.6 else "Evidence remains inconclusive",
            summary=(
                "The causal chain is supported, but deployment contribution is not proven."
                if deployments else "No stronger competing hypothesis was found in the supplied logs."
            ),
            confidence=confidence,
            evidence=evidence,
            details=details or ["Checked for competing triggers, recovery correlation, and healthy peer signals."],
        )
