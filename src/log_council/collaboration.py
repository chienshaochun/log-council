from __future__ import annotations

from collections.abc import Iterable

from .models import AgentFinding, AgentMessage, Evidence, Hypothesis, LogEvent


class ContractError(ValueError):
    """Raised when an Agent exchange violates the collaboration contract."""


class EvidenceRegistry:
    """Read-only allowlist of source events available to all Agents."""

    def __init__(self, events: Iterable[LogEvent]) -> None:
        event_ids = [event.id for event in events]
        if len(event_ids) != len(set(event_ids)):
            raise ContractError("Evidence registry requires unique event IDs")
        self._event_ids = frozenset(event_ids)

    @property
    def event_ids(self) -> frozenset[str]:
        return self._event_ids

    def validate_ids(self, event_ids: Iterable[str]) -> None:
        unknown = sorted(set(event_ids) - self._event_ids)
        if unknown:
            raise ContractError(f"Unknown evidence IDs: {', '.join(unknown)}")

    def validate_evidence(self, evidence: Iterable[Evidence]) -> None:
        self.validate_ids(item.event_id for item in evidence)

    def validate_finding(self, finding: AgentFinding) -> None:
        if not 0 <= finding.confidence <= 1:
            raise ContractError(f"Invalid confidence from {finding.agent}: {finding.confidence}")
        self.validate_evidence(finding.evidence)

    def validate_hypotheses(self, hypotheses: Iterable[Hypothesis]) -> None:
        for hypothesis in hypotheses:
            if not 0 <= hypothesis.confidence <= 1:
                raise ContractError(f"Invalid hypothesis confidence: {hypothesis.confidence}")
            self.validate_evidence(hypothesis.supporting)
            self.validate_evidence(hypothesis.contradicting)


ALLOWED_KINDS: dict[tuple[str, str], frozenset[str]] = {
    ("Coordinator", "Pattern Agent"): frozenset({"task"}),
    ("Pattern Agent", "Coordinator"): frozenset({"finding"}),
    ("Coordinator", "Timeline Agent"): frozenset({"task"}),
    ("Timeline Agent", "Coordinator"): frozenset({"finding"}),
    ("Coordinator", "Root Cause Agent"): frozenset({"task", "revision_request"}),
    ("Root Cause Agent", "Coordinator"): frozenset({"hypothesis", "revision"}),
    ("Coordinator", "Reviewer Agent"): frozenset({"review_request"}),
    ("Reviewer Agent", "Coordinator"): frozenset({"challenge", "decision"}),
}


class HandoffLedger:
    """Append-only, deterministic record of validated Agent exchanges."""

    def __init__(self, run_id: str, evidence: EvidenceRegistry) -> None:
        if not run_id:
            raise ContractError("run_id is required")
        self.run_id = run_id
        self._evidence = evidence
        self._messages: list[AgentMessage] = []
        self._by_id: dict[str, AgentMessage] = {}
        self._reply_ids: set[str] = set()

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        return tuple(self._messages)

    def next_id(self) -> str:
        return f"{self.run_id}-M{len(self._messages) + 1:03d}"

    def append(self, message: AgentMessage) -> None:
        if message.run_id != self.run_id:
            raise ContractError("Message belongs to a different run")
        if message.sequence != len(self._messages) + 1:
            raise ContractError("Message sequence must be contiguous")
        if message.message_id in self._by_id:
            raise ContractError(f"Duplicate message ID: {message.message_id}")
        allowed = ALLOWED_KINDS.get((message.sender, message.recipient), frozenset())
        if message.kind not in allowed:
            raise ContractError(
                f"Illegal handoff route or kind: {message.sender} -> "
                f"{message.recipient} ({message.kind})"
            )
        self._evidence.validate_ids(message.evidence_ids)
        for payload_ref in message.payload_refs:
            if payload_ref not in self._by_id:
                raise ContractError(f"Unknown or future payload reference: {payload_ref}")
        if message.in_reply_to:
            request = self._by_id.get(message.in_reply_to)
            if request is None:
                raise ContractError(f"Unknown reply target: {message.in_reply_to}")
            if message.in_reply_to in self._reply_ids:
                raise ContractError(f"Message already has a reply: {message.in_reply_to}")
            if request.sender != message.recipient or request.recipient != message.sender:
                raise ContractError("Reply route must reverse the request route")
            self._reply_ids.add(message.in_reply_to)
        elif message.kind in {"finding", "hypothesis", "challenge", "revision", "decision"}:
            raise ContractError(f"{message.kind} must reply to an earlier message")
        self._messages.append(message)
        self._by_id[message.message_id] = message

    def add(
        self,
        sender: str,
        recipient: str,
        kind: str,
        subject: str,
        body: str,
        *,
        evidence_ids: Iterable[str] = (),
        payload_refs: Iterable[str] = (),
        in_reply_to: str | None = None,
    ) -> AgentMessage:
        message = AgentMessage(
            message_id=self.next_id(),
            run_id=self.run_id,
            sequence=len(self._messages) + 1,
            sender=sender,
            recipient=recipient,
            kind=kind,  # type: ignore[arg-type]
            subject=subject,
            body=body,
            evidence_ids=tuple(dict.fromkeys(evidence_ids)),
            payload_refs=tuple(dict.fromkeys(payload_refs)),
            in_reply_to=in_reply_to,
        )
        self.append(message)
        return message
