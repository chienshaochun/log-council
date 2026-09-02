from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal


Stance = Literal["supporting", "contradicting", "context"]


@dataclass(frozen=True)
class LogEvent:
    id: str
    timestamp: datetime | None
    level: str
    service: str
    message: str
    trace_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    raw: str = ""

    @property
    def timestamp_text(self) -> str:
        return self.timestamp.isoformat() if self.timestamp else "unknown"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp_text
        return data


@dataclass(frozen=True)
class ParseIssue:
    line_number: int
    code: str
    detail: str
    raw: str


@dataclass(frozen=True)
class ParseStats:
    input_lines: int
    event_count: int
    structured_count: int
    fallback_count: int
    invalid_timestamp_count: int
    duplicate_id_count: int

    @property
    def coverage(self) -> float:
        if self.event_count == 0:
            return 0.0
        return self.structured_count / self.event_count


@dataclass(frozen=True)
class ParsedLog:
    events: tuple[LogEvent, ...]
    issues: tuple[ParseIssue, ...]
    stats: ParseStats


@dataclass(frozen=True)
class Evidence:
    event_id: str
    reason: str
    stance: Stance = "supporting"


@dataclass
class AgentFinding:
    agent: str
    title: str
    summary: str
    confidence: float
    evidence: list[Evidence] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
    status: str = "completed"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Handoff:
    source: str
    target: str
    question: str
    reason: str


@dataclass(frozen=True)
class Activity:
    step: int
    agent: str
    action: str
    detail: str
    status: str = "completed"


@dataclass
class Hypothesis:
    title: str
    explanation: str
    confidence: float
    supporting: list[Evidence] = field(default_factory=list)
    contradicting: list[Evidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisReport:
    events: list[LogEvent]
    findings: list[AgentFinding]
    handoffs: list[Handoff]
    activities: list[Activity]
    hypotheses: list[Hypothesis]
    root_cause: str
    confidence: float
    consensus_count: int
    agent_count: int
    caveat: str
    evidence_chain: list[str]
    recommended_actions: list[str]
    generated_at: datetime = field(default_factory=datetime.now)

    @property
    def consensus_label(self) -> str:
        if self.confidence >= 0.8:
            return "high confidence"
        if self.confidence >= 0.6:
            return "moderate confidence"
        return "no reliable consensus"

    def to_dict(self, include_events: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "generated_at": self.generated_at.isoformat(),
            "summary": {
                "root_cause": self.root_cause,
                "confidence": round(self.confidence, 3),
                "consensus": f"{self.consensus_count}/{self.agent_count}",
                "consensus_label": self.consensus_label,
                "caveat": self.caveat,
            },
            "evidence_chain": self.evidence_chain,
            "recommended_actions": self.recommended_actions,
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "findings": [item.to_dict() for item in self.findings],
            "handoffs": [asdict(item) for item in self.handoffs],
            "activities": [asdict(item) for item in self.activities],
            "stats": {
                "event_count": len(self.events),
                "error_count": sum(e.level == "ERROR" for e in self.events),
                "warning_count": sum(e.level in {"WARN", "WARNING"} for e in self.events),
                "services": sorted({e.service for e in self.events}),
            },
        }
        if include_events:
            data["events"] = [event.to_dict() for event in self.events]
        return data
