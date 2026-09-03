from __future__ import annotations

import unittest

from log_council import CouncilOrchestrator, parse_log_text


INCIDENT = """
{"id":"EVT-101","ts":"2026-09-01T14:02:42+08:00","level":"WARN","service":"postgres","message":"slow query duration=2184ms"}
{"id":"EVT-102","ts":"2026-09-01T14:02:44+08:00","level":"WARN","service":"checkout","message":"database connection pool at capacity"}
{"id":"EVT-103","ts":"2026-09-01T14:02:45+08:00","level":"ERROR","service":"checkout","message":"timed out waiting for database connection"}
{"id":"EVT-104","ts":"2026-09-01T14:02:46+08:00","level":"ERROR","service":"api-gateway","message":"upstream request timeout status=504"}
{"id":"EVT-105","ts":"2026-09-01T14:03:01+08:00","level":"INFO","service":"deployment","message":"deployment completed 47 minutes before incident"}
{"id":"EVT-106","ts":"2026-09-01T14:04:20+08:00","level":"INFO","service":"checkout","message":"database connection pool recovered"}
"""


class OrchestratorTests(unittest.TestCase):
    def test_challenge_triggers_exactly_one_bounded_revision(self) -> None:
        events = parse_log_text(INCIDENT)

        report = CouncilOrchestrator().analyze(events)

        kinds = [message.kind for message in report.agent_messages]
        self.assertEqual(len(report.agent_messages), 14)
        self.assertEqual(kinds.count("challenge"), 1)
        self.assertEqual(kinds.count("revision_request"), 1)
        self.assertEqual(kinds.count("revision"), 1)
        self.assertEqual(kinds.count("decision"), 1)
        self.assertEqual(report.agent_messages[-1].subject, "Revision accepted with caveat")
        self.assertEqual(report.hypotheses[0].contradicting[0].event_id, "EVT-105")

    def test_every_evidence_reference_resolves_to_source_event(self) -> None:
        report = CouncilOrchestrator().analyze(parse_log_text(INCIDENT))
        event_ids = {event.id for event in report.events}

        for message in report.agent_messages:
            self.assertLessEqual(set(message.evidence_ids), event_ids)
        for finding in report.findings:
            self.assertLessEqual({item.event_id for item in finding.evidence}, event_ids)
        for hypothesis in report.hypotheses:
            references = {
                item.event_id for item in [*hypothesis.supporting, *hypothesis.contradicting]
            }
            self.assertLessEqual(references, event_ids)

    def test_ledger_references_only_earlier_messages(self) -> None:
        report = CouncilOrchestrator().analyze(parse_log_text(INCIDENT))
        seen: set[str] = set()

        for message in report.agent_messages:
            self.assertLessEqual(set(message.payload_refs), seen)
            if message.in_reply_to:
                self.assertIn(message.in_reply_to, seen)
            seen.add(message.message_id)

    def test_run_and_evidence_ids_are_deterministic(self) -> None:
        events = parse_log_text(INCIDENT)

        first = CouncilOrchestrator().analyze(events)
        second = CouncilOrchestrator().analyze(events)

        self.assertEqual(first.run_id, second.run_id)
        self.assertEqual(
            [message.message_id for message in first.agent_messages],
            [message.message_id for message in second.agent_messages],
        )
        self.assertEqual(first.root_cause, second.root_cause)

    def test_no_counter_evidence_finishes_without_revision(self) -> None:
        events = parse_log_text(
            '{"id":"E1","level":"ERROR","service":"auth","message":"token expired"}\n'
            '{"id":"E2","level":"ERROR","service":"api","message":"unauthorized 401"}'
        )

        report = CouncilOrchestrator().analyze(events)

        kinds = [message.kind for message in report.agent_messages]
        self.assertEqual(len(report.agent_messages), 10)
        self.assertNotIn("challenge", kinds)
        self.assertNotIn("revision", kinds)
        self.assertEqual(kinds[-1], "decision")

    def test_correlation_agent_is_auditable_part_of_consensus(self) -> None:
        report = CouncilOrchestrator().analyze(parse_log_text(INCIDENT))

        self.assertEqual(report.agent_count, 5)
        self.assertIn("Correlation Agent", [finding.agent for finding in report.findings])
        root_finding = next(
            finding for finding in report.findings if finding.agent == "Root Cause Agent"
        )
        self.assertIn("Consumed 3 validated specialist findings", root_finding.details[0])
        correlation_messages = [
            message for message in report.agent_messages
            if message.sender == "Correlation Agent"
        ]
        self.assertEqual(len(correlation_messages), 1)
        self.assertTrue(report.correlations)
        event_ids = {event.id for event in report.events}
        for link in report.correlations:
            self.assertIn(link.source_event_id, event_ids)
            self.assertIn(link.target_event_id, event_ids)
            self.assertGreaterEqual(link.delta_seconds or 0, 0)
        serialized = report.to_dict(include_events=False)
        self.assertEqual(len(serialized["correlations"]), len(report.correlations))

    def test_low_evidence_result_is_explicitly_inconclusive(self) -> None:
        events = parse_log_text(
            '{"id":"E1","level":"INFO","service":"api","message":"application started"}'
        )

        report = CouncilOrchestrator().analyze(events)

        self.assertLessEqual(report.confidence, 0.45)
        self.assertEqual(report.evidence_chain, ["Insufficient evidence"])
        self.assertIn("Collect a wider log window", report.recommended_actions[0])

    def test_empty_input_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "At least one log event"):
            CouncilOrchestrator().analyze([])


if __name__ == "__main__":
    unittest.main()
