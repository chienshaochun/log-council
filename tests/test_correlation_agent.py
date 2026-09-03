from __future__ import annotations

import unittest

from log_council.agents import CorrelationAgent
from log_council import parse_log_text


PROPAGATION = """
{"id":"E1","ts":"2026-09-01T10:00:00+00:00","level":"WARN","service":"database","message":"slow query duration=2000ms"}
{"id":"E2","ts":"2026-09-01T10:00:02+00:00","level":"ERROR","service":"checkout","message":"database request failed","trace_id":"trace-1"}
{"id":"E3","ts":"2026-09-01T10:00:03+00:00","level":"ERROR","service":"gateway","message":"upstream request timeout","trace_id":"trace-1"}
"""


class CorrelationAgentTests(unittest.TestCase):
    def test_builds_bounded_cross_service_links(self) -> None:
        finding, links = CorrelationAgent().analyze(parse_log_text(PROPAGATION))

        self.assertEqual(finding.title, "Cross-service propagation candidate detected")
        self.assertEqual(finding.evidence[0].event_id, "E1")
        self.assertTrue(any(
            link.relation == "bounded-time-proximity"
            and link.source_event_id == "E1"
            and link.target_event_id == "E2"
            for link in links
        ))
        self.assertTrue(any(link.relation == "shared-trace_id" for link in links))
        self.assertTrue(all(
            link.delta_seconds is None or link.delta_seconds >= 0 for link in links
        ))

    def test_does_not_claim_a_chain_without_failure_signal(self) -> None:
        events = parse_log_text(
            '{"id":"E1","level":"INFO","service":"api","message":"request completed"}'
        )

        finding, links = CorrelationAgent().analyze(events)

        self.assertEqual(finding.title, "No reliable event correlation")
        self.assertEqual(finding.confidence, 0.3)
        self.assertEqual(links, [])

    def test_uses_post_injection_novelty_and_retains_distractor(self) -> None:
        events = parse_log_text(
            '{"id":"E1","ts":"2026-09-01T09:59:00Z","level":"UNKNOWN",'
            '"service":"payment","message":"card error","phase":"pre-injection"}\n'
            '{"id":"E2","ts":"2026-09-01T10:00:00Z","level":"UNKNOWN",'
            '"service":"cart","message":"OverflowException","phase":"post-injection"}\n'
            '{"id":"E3","ts":"2026-09-01T10:00:01Z","level":"UNKNOWN",'
            '"service":"cart","message":"OverflowException","phase":"post-injection"}\n'
            '{"id":"E4","ts":"2026-09-01T10:00:02Z","level":"UNKNOWN",'
            '"service":"frontend","message":"request error","phase":"post-injection"}'
        )

        finding, links = CorrelationAgent().analyze(events)

        self.assertEqual(finding.evidence[0].event_id, "E2")
        self.assertIn("E1", [
            evidence.event_id for evidence in finding.evidence
            if evidence.stance == "context"
        ])
        self.assertTrue(any(link.relation == "repeated-signature" for link in links))
        self.assertTrue(any(link.target_event_id == "E4" for link in links))


if __name__ == "__main__":
    unittest.main()
