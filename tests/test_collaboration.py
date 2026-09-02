from __future__ import annotations

import unittest

from log_council.collaboration import ContractError, EvidenceRegistry, HandoffLedger
from log_council.models import AgentFinding, Evidence, LogEvent


def event(event_id: str = "EVT-001") -> LogEvent:
    return LogEvent(event_id, None, "ERROR", "checkout", "request failed")


class EvidenceRegistryTests(unittest.TestCase):
    def test_rejects_duplicate_source_event_ids(self) -> None:
        with self.assertRaisesRegex(ContractError, "unique event IDs"):
            EvidenceRegistry([event(), event()])

    def test_rejects_finding_with_unknown_evidence(self) -> None:
        registry = EvidenceRegistry([event()])
        finding = AgentFinding(
            "Pattern Agent", "title", "summary", 0.8,
            evidence=[Evidence("EVT-999", "not in input")],
        )

        with self.assertRaisesRegex(ContractError, "EVT-999"):
            registry.validate_finding(finding)

    def test_rejects_confidence_outside_unit_interval(self) -> None:
        registry = EvidenceRegistry([event()])
        finding = AgentFinding("Pattern Agent", "title", "summary", 1.2)

        with self.assertRaisesRegex(ContractError, "Invalid confidence"):
            registry.validate_finding(finding)


class HandoffLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = HandoffLedger("RUN-test", EvidenceRegistry([event()]))

    def test_records_valid_request_and_response(self) -> None:
        task = self.ledger.add(
            "Coordinator", "Pattern Agent", "task", "scan", "find patterns"
        )
        response = self.ledger.add(
            "Pattern Agent", "Coordinator", "finding", "found", "one error",
            evidence_ids=("EVT-001",), in_reply_to=task.message_id,
        )

        self.assertEqual([item.sequence for item in self.ledger.messages], [1, 2])
        self.assertEqual(response.in_reply_to, task.message_id)

    def test_rejects_illegal_direct_agent_route(self) -> None:
        with self.assertRaisesRegex(ContractError, "Illegal handoff"):
            self.ledger.add(
                "Pattern Agent", "Root Cause Agent", "finding", "found", "details"
            )

    def test_rejects_unknown_payload_reference(self) -> None:
        with self.assertRaisesRegex(ContractError, "payload reference"):
            self.ledger.add(
                "Coordinator", "Root Cause Agent", "task", "compare", "details",
                payload_refs=("RUN-test-M999",),
            )

    def test_rejects_response_without_reply_target(self) -> None:
        with self.assertRaisesRegex(ContractError, "must reply"):
            self.ledger.add(
                "Pattern Agent", "Coordinator", "finding", "found", "details"
            )

    def test_request_can_only_receive_one_reply(self) -> None:
        task = self.ledger.add(
            "Coordinator", "Pattern Agent", "task", "scan", "find patterns"
        )
        self.ledger.add(
            "Pattern Agent", "Coordinator", "finding", "found", "one error",
            in_reply_to=task.message_id,
        )

        with self.assertRaisesRegex(ContractError, "already has a reply"):
            self.ledger.add(
                "Pattern Agent", "Coordinator", "finding", "again", "duplicate",
                in_reply_to=task.message_id,
            )


if __name__ == "__main__":
    unittest.main()
