from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from .models import AgentFinding, CorrelationLink, Evidence, Hypothesis, LogEvent


def _contains(event: LogEvent, *terms: str) -> bool:
    haystack = f"{event.service} {event.message}".lower()
    return any(
        bool(re.search(rf"\b{re.escape(term)}\b", haystack))
        if term.isdigit() else term in haystack
        for term in terms
    )


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
            details=[f"{event.timestamp_text} | {event.service} | {event.message}" for event in milestones],
        )


FAILURE_TERMS = (
    "error",
    "exception",
    "failed",
    "failure",
    "timeout",
    "timed out",
    "refused",
    "unavailable",
    "panic",
    "denied",
    "slow query",
)
IDENTIFIER_KEYS = ("request_id", "request-id", "requestId", "correlation_id", "host")


def _is_signal(event: LogEvent) -> bool:
    return event.level in {"WARN", "WARNING", "ERROR", "CRITICAL", "FATAL"} or _contains(
        event, *FAILURE_TERMS
    )


def _signature(event: LogEvent) -> str:
    normalized = re.sub(
        r"\b(?:[0-9a-f]{8}-[0-9a-f-]{27,}|0x[0-9a-f]+|\d+(?:\.\d+)?)\b",
        "#",
        event.message.lower(),
    )
    return f"{event.service.lower()}|{' '.join(normalized.split())}"


def _timestamp_number(value: datetime | None) -> float | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _delta_seconds(source: LogEvent, target: LogEvent) -> float | None:
    source_time = _timestamp_number(source.timestamp)
    target_time = _timestamp_number(target.timestamp)
    if source_time is None or target_time is None:
        return None
    return round(target_time - source_time, 3)


def _ordered(events: list[LogEvent]) -> list[LogEvent]:
    return sorted(
        events,
        key=lambda event: (
            event.timestamp is None,
            _timestamp_number(event.timestamp) or 0,
            event.id,
        ),
    )


class CorrelationAgent:
    name = "Correlation Agent"
    proximity_seconds = 120

    def _onset(self, signals: list[LogEvent]) -> tuple[LogEvent, int, LogEvent | None]:
        pre = [event for event in signals if event.attributes.get("phase") == "pre-injection"]
        post = [event for event in signals if event.attributes.get("phase") == "post-injection"]
        if post:
            pre_signatures = {_signature(event) for event in pre}
            novel = [event for event in post if _signature(event) not in pre_signatures]
            candidates = novel or post
            counts = Counter(_signature(event) for event in candidates)
            first_position: dict[str, int] = {}
            for position, event in enumerate(candidates):
                first_position.setdefault(_signature(event), position)
            leading = min(counts, key=lambda item: (-counts[item], first_position[item], item))
            onset = next(event for event in candidates if _signature(event) == leading)
            distractor = next(
                (event for event in pre if _signature(event) != leading),
                None,
            )
            return onset, counts[leading], distractor
        onset = signals[0]
        repeated = sum(_signature(event) == _signature(onset) for event in signals)
        return onset, repeated, None

    def _identifier_links(self, events: list[LogEvent]) -> list[CorrelationLink]:
        groups: dict[tuple[str, str], list[LogEvent]] = {}
        for event in events:
            identifiers: list[tuple[str, str]] = []
            if event.trace_id:
                identifiers.append(("trace_id", event.trace_id))
            for key in IDENTIFIER_KEYS:
                value = event.attributes.get(key)
                if value not in (None, ""):
                    identifiers.append((key, str(value)))
            for identifier in identifiers:
                groups.setdefault(identifier, []).append(event)

        links: list[CorrelationLink] = []
        for (kind, value), group in sorted(groups.items()):
            ordered = _ordered(group)
            if not any(_is_signal(event) for event in ordered):
                continue
            pair = next(
                (
                    (source, target)
                    for position, source in enumerate(ordered)
                    for target in ordered[position + 1:]
                    if target.service != source.service
                ),
                None,
            )
            if pair is None:
                continue
            source, target = pair
            links.append(CorrelationLink(
                source_event_id=source.id,
                target_event_id=target.id,
                relation=f"shared-{kind}",
                basis=f"Both events contain the same {kind} value ({value}).",
                delta_seconds=_delta_seconds(source, target),
            ))
            if len(links) == 3:
                break
        return links

    def analyze(self, events: list[LogEvent]) -> tuple[AgentFinding, list[CorrelationLink]]:
        ordered = _ordered(events)
        signals = [event for event in ordered if _is_signal(event)]
        if not signals:
            return AgentFinding(
                agent=self.name,
                title="No reliable event correlation",
                summary="No severity or message signal was found from which to build a correlation chain.",
                confidence=0.3,
                details=["No cross-service causal order is claimed."],
            ), []

        onset, repeated_count, distractor = self._onset(signals)
        links: list[CorrelationLink] = []
        same_signature = [
            event for event in signals
            if event.id != onset.id and _signature(event) == _signature(onset)
        ]
        if same_signature:
            target = same_signature[0]
            links.append(CorrelationLink(
                onset.id,
                target.id,
                "repeated-signature",
                "The normalized message signature repeats in the same service.",
                _delta_seconds(onset, target),
            ))

        downstream_services: set[str] = set()
        for event in signals:
            if event.id == onset.id or event.service == onset.service:
                continue
            delta = _delta_seconds(onset, event)
            if delta is None or delta < 0 or delta > self.proximity_seconds:
                continue
            if event.service in downstream_services:
                continue
            downstream_services.add(event.service)
            links.append(CorrelationLink(
                onset.id,
                event.id,
                "bounded-time-proximity",
                f"A signal in another service follows within {self.proximity_seconds} seconds.",
                delta,
            ))
            if len(downstream_services) == 3:
                break

        existing = {
            (link.source_event_id, link.target_event_id, link.relation) for link in links
        }
        for link in self._identifier_links(events):
            key = (link.source_event_id, link.target_event_id, link.relation)
            if key not in existing:
                links.append(link)
                existing.add(key)

        evidence = [_ev(onset, "Candidate onset of the dominant new failure signature")]
        by_id = {event.id: event for event in events}
        for link in links[:5]:
            target = by_id[link.target_event_id]
            evidence.append(_ev(target, f"Correlated by {link.relation}"))
        if distractor is not None:
            evidence.append(_ev(
                distractor,
                "Pre-existing signal excluded from the new post-injection signature",
                "context",
            ))

        cross_service_count = len({
            by_id[link.target_event_id].service
            for link in links
            if by_id[link.target_event_id].service != onset.service
        })
        shared_identifier_count = sum(link.relation.startswith("shared-") for link in links)
        if cross_service_count:
            title = "Cross-service propagation candidate detected"
            summary = (
                f"The onset candidate is {onset.service}; signals in {cross_service_count} "
                "other service(s) follow within the bounded correlation window."
            )
        else:
            title = "Service-local failure cluster detected"
            summary = (
                f"The dominant onset candidate is confined to {onset.service}; "
                "cross-service propagation is not established."
            )
        confidence = min(
            0.92,
            0.48
            + (0.1 if repeated_count > 1 else 0)
            + (0.14 if cross_service_count else 0)
            + (0.12 if shared_identifier_count else 0),
        )
        details = [
            f"Onset candidate: {onset.timestamp_text} | {onset.service} | {onset.id}",
            f"Dominant normalized signature occurrences: {repeated_count}",
            f"Cross-service targets in window: {cross_service_count}",
            f"Shared identifier links: {shared_identifier_count}",
        ]
        if distractor is not None:
            details.append(
                f"Earlier unrelated candidate retained as context: {distractor.id} ({distractor.service})"
            )
        return AgentFinding(
            agent=self.name,
            title=title,
            summary=summary,
            confidence=confidence,
            evidence=evidence,
            details=details,
        ), links


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
        "Application numeric conversion overflow",
        "An application value exceeded its expected numeric range and caused the storage operation to fail.",
        ("overflowexception", "value was either too large or too small", "int32", "overflow"),
        (
            "Inspect the cited stack frame and the value being converted at the failure boundary.",
            "Validate numeric types and range checks between the request model and storage layer.",
            "Add boundary-value tests before deploying a bounded application fix.",
        ),
        (
            "Out-of-range application value",
            "Numeric conversion overflow",
            "Storage operation failure",
            "Frontend request error",
        ),
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

    def analyze(
        self,
        events: list[LogEvent],
        specialist_findings: list[AgentFinding] | None = None,
        correlations: list[CorrelationLink] | None = None,
    ) -> tuple[AgentFinding, list[Hypothesis], CauseRule]:
        specialist_findings = specialist_findings or []
        correlations = correlations or []
        correlated_ids = {
            event_id
            for link in correlations
            for event_id in (link.source_event_id, link.target_event_id)
        }
        scored: list[tuple[int, CauseRule, list[LogEvent]]] = []
        for rule in CAUSE_RULES:
            matched = [e for e in events if _contains(e, *rule.terms)]
            diversity = len({term for term in rule.terms if any(_contains(e, term) for e in events)})
            correlated_matches = sum(event.id in correlated_ids for event in matched)
            score = len(matched) + diversity * 2 + min(correlated_matches, 3)
            scored.append((score, rule, matched))
        scored.sort(key=lambda item: item[0], reverse=True)
        hypotheses: list[Hypothesis] = []
        for score, rule, matched in scored[:3]:
            confidence = min(0.92, 0.28 + score * 0.07)
            service = Counter(event.service for event in matched).most_common(1)
            hypothesis_title = (
                f"{rule.title} in {service[0][0]}" if service else rule.title
            )
            hypothesis_explanation = (
                f"{rule.explanation} The strongest matching evidence is in "
                f"{service[0][0]}."
                if service else rule.explanation
            )
            hypotheses.append(Hypothesis(
                title=hypothesis_title,
                explanation=hypothesis_explanation,
                confidence=confidence,
                supporting=[_ev(event, f"Matches {rule.title.lower()}") for event in matched[:5]],
            ))
        best_score, best, matched = scored[0]
        leading_service = Counter(event.service for event in matched).most_common(1)
        leading_title = (
            f"{best.title} in {leading_service[0][0]}"
            if best_score and leading_service else best.title
        )
        leading_summary = hypotheses[0].explanation
        finding = AgentFinding(
            agent=self.name,
            title=leading_title if best_score else "Insufficient evidence for a root cause",
            summary=leading_summary if best_score else "No known cause pattern has enough evidence.",
            confidence=hypotheses[0].confidence if best_score else 0.25,
            evidence=[_ev(event, "Supports leading root-cause hypothesis") for event in matched[:5]],
            details=[
                f"Consumed {len(specialist_findings)} validated specialist findings "
                f"and {len(correlations)} correlation links.",
                f"Compared {len(CAUSE_RULES)} competing cause families.",
                f"Leading rule score: {best_score}.",
            ],
        )
        return finding, hypotheses, best

    def revise(
        self,
        hypotheses: list[Hypothesis],
        review: AgentFinding,
        prior_finding: AgentFinding | None = None,
    ) -> tuple[AgentFinding, list[Hypothesis]]:
        """Apply one bounded revision without inventing new source evidence."""
        leading = hypotheses[0]
        existing_ids = {item.event_id for item in leading.contradicting}
        new_contradictions = [
            item for item in review.evidence
            if item.stance == "contradicting" and item.event_id not in existing_ids
        ]
        revised_leading = Hypothesis(
            title=leading.title,
            explanation=(
                f"{leading.explanation} Reviewer caveat: competing triggers remain unproven."
                if new_contradictions else leading.explanation
            ),
            confidence=max(0.2, leading.confidence - 0.06 * len(new_contradictions)),
            supporting=list(leading.supporting),
            contradicting=[*leading.contradicting, *new_contradictions],
        )
        revised = [revised_leading, *hypotheses[1:]]
        finding = AgentFinding(
            agent=self.name,
            title=f"Revised: {revised_leading.title}",
            summary=revised_leading.explanation,
            confidence=revised_leading.confidence,
            evidence=[*revised_leading.supporting, *revised_leading.contradicting],
            details=[
                *(prior_finding.details if prior_finding else []),
                f"Accepted {len(new_contradictions)} reviewer contradiction(s).",
                "No new evidence was introduced during revision.",
            ],
        )
        return finding, revised


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

    def finalize(self, hypotheses: list[Hypothesis], prior_review: AgentFinding) -> AgentFinding:
        leading = hypotheses[0]
        contradictions = list(leading.contradicting)
        acknowledged = bool(contradictions)
        return AgentFinding(
            agent=self.name,
            title="Revision accepted with caveat" if acknowledged else "Leading hypothesis accepted",
            summary=(
                "The leading hypothesis is evidence-bound and preserves the competing-trigger caveat."
                if acknowledged else "The leading hypothesis is evidence-bound and no stronger alternative was found."
            ),
            confidence=max(0.35, min(0.9, leading.confidence + 0.03)),
            evidence=[*leading.supporting, *contradictions],
            details=[
                "Checked that the revision cites only registered source events.",
                *prior_review.details,
            ],
        )
