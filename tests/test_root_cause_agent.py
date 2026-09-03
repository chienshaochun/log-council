from __future__ import annotations

import unittest

from log_council import parse_log_text
from log_council.agents import RootCauseAgent


class RootCauseAgentTests(unittest.TestCase):
    def test_numeric_substrings_do_not_become_http_auth_errors(self) -> None:
        events = parse_log_text(
            '{"id":"E1","level":"INFO","service":"paymentservice",'
            '"message":"charge amount USD401.89 card 4034577503096512"}'
        )

        finding, _, _ = RootCauseAgent().analyze(events)

        self.assertEqual(finding.title, "Insufficient evidence for a root cause")
        self.assertEqual(finding.evidence, [])

    def test_attributes_application_overflow_to_matching_service(self) -> None:
        events = parse_log_text(
            '{"id":"E1","level":"UNKNOWN","service":"cartservice",'
            '"message":"System.OverflowException: Value was either too large or too small for an Int32"}\n'
            '{"id":"E2","level":"UNKNOWN","service":"frontend",'
            '"message":"request error"}'
        )

        finding, hypotheses, _ = RootCauseAgent().analyze(events)

        self.assertIn("Application numeric conversion overflow", finding.title)
        self.assertIn("cartservice", finding.title)
        self.assertEqual(hypotheses[0].supporting[0].event_id, "E1")


if __name__ == "__main__":
    unittest.main()
