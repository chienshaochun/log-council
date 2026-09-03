from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor

from .agents import (
    CorrelationAgent,
    PatternAgent,
    ReviewerAgent,
    RootCauseAgent,
    TimelineAgent,
)
from .collaboration import EvidenceRegistry, HandoffLedger
from .models import Activity, AgentFinding, AnalysisReport, Evidence, Handoff, LogEvent


def _run_id(events: list[LogEvent]) -> str:
    digest = hashlib.sha256()
    for event in events:
        digest.update(event.id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(event.raw.encode("utf-8"))
        digest.update(b"\n")
    return f"RUN-{digest.hexdigest()[:12]}"


def _evidence_ids(evidence: list[Evidence]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.event_id for item in evidence))


class CouncilOrchestrator:
    """Coordinate specialists through evidence-bound, inspectable handoffs."""

    def __init__(self) -> None:
        self.pattern = PatternAgent()
        self.timeline = TimelineAgent()
        self.correlation = CorrelationAgent()
        self.root_cause = RootCauseAgent()
        self.reviewer = ReviewerAgent()

    def analyze(self, events: list[LogEvent]) -> AnalysisReport:
        if not events:
            raise ValueError("At least one log event is required")

        run_id = _run_id(events)
        registry = EvidenceRegistry(events)
        ledger = HandoffLedger(run_id, registry)

        pattern_task = ledger.add(
            "Coordinator", "Pattern Agent", "task", "Find abnormal log patterns",
            "Detect repeated templates, severity clusters, retries, and resource-pressure signals.",
        )
        timeline_task = ledger.add(
            "Coordinator", "Timeline Agent", "task", "Reconstruct the incident timeline",
            "Find the earliest precursor, propagation symptoms, failure point, and recovery evidence.",
        )
        correlation_task = ledger.add(
            "Coordinator", "Correlation Agent", "task", "Correlate related events",
            "Connect signals by service, identifiers, and bounded time proximity while retaining distractors.",
        )

        # Specialists run concurrently, while ledger insertion stays deterministic.
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="log-council") as executor:
            pattern_future = executor.submit(self.pattern.analyze, events)
            timeline_future = executor.submit(self.timeline.analyze, events)
            correlation_future = executor.submit(self.correlation.analyze, events)
            pattern = pattern_future.result()
            timeline = timeline_future.result()
            correlation, correlations = correlation_future.result()

        registry.validate_finding(pattern)
        registry.validate_finding(timeline)
        registry.validate_finding(correlation)
        registry.validate_correlations(correlations)
        pattern_message = ledger.add(
            "Pattern Agent", "Coordinator", "finding", pattern.title, pattern.summary,
            evidence_ids=_evidence_ids(pattern.evidence), in_reply_to=pattern_task.message_id,
        )
        timeline_message = ledger.add(
            "Timeline Agent", "Coordinator", "finding", timeline.title, timeline.summary,
            evidence_ids=_evidence_ids(timeline.evidence), in_reply_to=timeline_task.message_id,
        )
        correlation_message = ledger.add(
            "Correlation Agent", "Coordinator", "finding", correlation.title,
            correlation.summary, evidence_ids=_evidence_ids(correlation.evidence),
            in_reply_to=correlation_task.message_id,
        )

        specialist_evidence = _evidence_ids([
            *pattern.evidence,
            *timeline.evidence,
            *correlation.evidence,
        ])
        cause_task = ledger.add(
            "Coordinator", "Root Cause Agent", "task", "Compare root-cause hypotheses",
            "Use the specialist findings to rank explanations without exceeding the supplied logs.",
            evidence_ids=specialist_evidence,
            payload_refs=(
                pattern_message.message_id,
                timeline_message.message_id,
                correlation_message.message_id,
            ),
        )
        root_finding, hypotheses, rule = self.root_cause.analyze(
            events,
            specialist_findings=[pattern, timeline, correlation],
            correlations=correlations,
        )
        registry.validate_finding(root_finding)
        registry.validate_hypotheses(hypotheses)
        cause_message = ledger.add(
            "Root Cause Agent", "Coordinator", "hypothesis", root_finding.title,
            root_finding.summary, evidence_ids=_evidence_ids(root_finding.evidence),
            in_reply_to=cause_task.message_id,
        )

        review_task = ledger.add(
            "Coordinator", "Reviewer Agent", "review_request", "Challenge the leading hypothesis",
            "Check unsupported claims, competing triggers, counter-evidence, and missing coverage.",
            evidence_ids=_evidence_ids(root_finding.evidence),
            payload_refs=(cause_message.message_id,),
        )
        initial_review = self.reviewer.analyze(events, hypotheses)
        registry.validate_finding(initial_review)
        has_challenge = any(item.stance == "contradicting" for item in initial_review.evidence)
        review_message = ledger.add(
            "Reviewer Agent", "Coordinator", "challenge" if has_challenge else "decision",
            initial_review.title, initial_review.summary,
            evidence_ids=_evidence_ids(initial_review.evidence),
            in_reply_to=review_task.message_id,
        )

        revision_count = 0
        final_root = root_finding
        final_review = initial_review
        if has_challenge:
            revision_count = 1
            revision_task = ledger.add(
                "Coordinator", "Root Cause Agent", "revision_request",
                "Address reviewer counter-evidence",
                "Revise the leading hypothesis once; preserve the contradiction and add no uncited facts.",
                evidence_ids=_evidence_ids(initial_review.evidence),
                payload_refs=(cause_message.message_id, review_message.message_id),
            )
            final_root, hypotheses = self.root_cause.revise(
                hypotheses,
                initial_review,
                prior_finding=root_finding,
            )
            registry.validate_finding(final_root)
            registry.validate_hypotheses(hypotheses)
            revision_message = ledger.add(
                "Root Cause Agent", "Coordinator", "revision", final_root.title,
                final_root.summary, evidence_ids=_evidence_ids(final_root.evidence),
                in_reply_to=revision_task.message_id,
            )
            final_review_task = ledger.add(
                "Coordinator", "Reviewer Agent", "review_request", "Verify the bounded revision",
                "Approve only if contradictions remain visible and every claim is evidence-bound.",
                evidence_ids=_evidence_ids(final_root.evidence),
                payload_refs=(revision_message.message_id,),
            )
            final_review = self.reviewer.finalize(hypotheses, initial_review)
            registry.validate_finding(final_review)
            ledger.add(
                "Reviewer Agent", "Coordinator", "decision", final_review.title,
                final_review.summary, evidence_ids=_evidence_ids(final_review.evidence),
                in_reply_to=final_review_task.message_id,
            )

        findings: list[AgentFinding] = [
            pattern,
            timeline,
            correlation,
            final_root,
            final_review,
        ]
        handoffs = [
            Handoff("Pattern Agent", "Root Cause Agent", "Which failure pattern best explains the incident?", "Repeated symptoms need a causal explanation."),
            Handoff("Timeline Agent", "Root Cause Agent", "Did the suspected trigger precede downstream failures?", "Sequence is required before claiming causality."),
            Handoff("Correlation Agent", "Root Cause Agent", "Which signals form an evidence-bound service propagation chain?", "Time proximity alone must not be presented as confirmed causality."),
            Handoff("Root Cause Agent", "Reviewer Agent", "Can a competing hypothesis explain the same evidence?", "The leading cause needs adversarial review."),
        ]
        if has_challenge:
            handoffs.append(Handoff(
                "Reviewer Agent", "Root Cause Agent", "Address the strongest contradiction before consensus.",
                "A competing trigger weakens the initial claim.",
            ))
        activities = [
            Activity(1, pattern.agent, "Pattern scan", pattern.summary),
            Activity(1, timeline.agent, "Timeline reconstruction", timeline.summary),
            Activity(1, correlation.agent, "Event correlation", correlation.summary),
            Activity(2, "Coordinator", "Specialist findings validated", "Pattern, Timeline, and Correlation evidence was checked against the source-event registry."),
            Activity(3, root_finding.agent, "Hypothesis comparison", root_finding.summary),
            Activity(4, initial_review.agent, "Adversarial review", initial_review.summary),
        ]
        if has_challenge:
            activities.append(Activity(5, final_root.agent, "Bounded revision", final_root.summary))
            activities.append(Activity(6, final_review.agent, "Revision decision", final_review.summary))
        activities.append(Activity(
            7 if has_challenge else 5,
            "Coordinator", "Consensus formed",
            f"Validated {len(ledger.messages)} messages with {revision_count} revision round(s).",
        ))

        confidence = round(sum(item.confidence for item in findings) / len(findings), 3)
        if not final_root.evidence:
            confidence = min(confidence, 0.45)
        consensus_count = sum(item.confidence >= 0.55 for item in findings)
        caveat = initial_review.summary if has_challenge else "No material competing trigger was found in the supplied logs."
        return AnalysisReport(
            events=events,
            findings=findings,
            handoffs=handoffs,
            activities=activities,
            hypotheses=hypotheses,
            root_cause=final_root.summary,
            confidence=confidence,
            consensus_count=consensus_count,
            agent_count=len(findings),
            caveat=caveat,
            evidence_chain=list(rule.chain) if final_root.evidence else ["Insufficient evidence"],
            recommended_actions=list(rule.actions) if final_root.evidence else [
                "Collect a wider log window around the first failure.",
                "Include logs from the affected service and its direct dependencies.",
                "Preserve request IDs, trace IDs, service names, and original timestamps.",
            ],
            correlations=correlations,
            run_id=run_id,
            agent_messages=list(ledger.messages),
        )
