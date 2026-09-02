from __future__ import annotations

from .agents import PatternAgent, ReviewerAgent, RootCauseAgent, TimelineAgent
from .models import Activity, AnalysisReport, Handoff, LogEvent


class CouncilOrchestrator:
    """Coordinate specialist agents through explicit, inspectable handoffs."""

    def __init__(self) -> None:
        self.pattern = PatternAgent()
        self.timeline = TimelineAgent()
        self.root_cause = RootCauseAgent()
        self.reviewer = ReviewerAgent()

    def analyze(self, events: list[LogEvent]) -> AnalysisReport:
        if not events:
            raise ValueError("At least one log event is required")

        pattern = self.pattern.analyze(events)
        timeline = self.timeline.analyze(events)
        root_cause, hypotheses, rule = self.root_cause.analyze(events)
        reviewer = self.reviewer.analyze(events, hypotheses)
        findings = [pattern, timeline, root_cause, reviewer]

        handoffs = [
            Handoff("Pattern Agent", "Root Cause Agent", "Which failure pattern best explains the incident?", "Repeated symptoms need a causal explanation."),
            Handoff("Timeline Agent", "Root Cause Agent", "Did the suspected trigger precede downstream failures?", "Sequence is required before claiming causality."),
            Handoff("Root Cause Agent", "Reviewer Agent", "Can a competing hypothesis explain the same evidence?", "The leading cause needs adversarial review."),
            Handoff("Reviewer Agent", "Root Cause Agent", "Address the strongest contradiction before consensus.", "A recent change or healthy peer may weaken the claim."),
        ]
        activities = [
            Activity(1, pattern.agent, "Pattern scan", pattern.summary),
            Activity(1, timeline.agent, "Timeline reconstruction", timeline.summary),
            Activity(2, "Council", "Parallel findings handed off", "Pattern and Timeline agents sent evidence to Root Cause Agent."),
            Activity(3, root_cause.agent, "Hypothesis comparison", root_cause.summary),
            Activity(4, reviewer.agent, "Adversarial review", reviewer.summary),
            Activity(5, "Council", "Consensus formed", "Specialist findings were reconciled with the reviewer caveat."),
        ]

        confidence = round(sum(item.confidence for item in findings) / len(findings), 3)
        if not root_cause.evidence:
            confidence = min(confidence, 0.45)
        consensus_count = sum(item.confidence >= 0.55 for item in findings)
        caveat = reviewer.summary if reviewer.details else "No material caveat identified."
        return AnalysisReport(
            events=events,
            findings=findings,
            handoffs=handoffs,
            activities=activities,
            hypotheses=hypotheses,
            root_cause=root_cause.summary,
            confidence=confidence,
            consensus_count=consensus_count,
            agent_count=len(findings),
            caveat=caveat,
            evidence_chain=list(rule.chain) if root_cause.evidence else ["Insufficient evidence"],
            recommended_actions=list(rule.actions) if root_cause.evidence else [
                "Collect a wider incident time window.",
                "Include dependency, deployment, and recovery logs.",
                "Preserve trace IDs and structured service fields.",
            ],
        )

