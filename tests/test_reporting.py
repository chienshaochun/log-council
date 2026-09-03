from __future__ import annotations

import unittest

from log_council.reporting import build_safe_report, serialize_report


class ReportingTests(unittest.TestCase):
    def test_safe_report_is_replay_stable_and_redacted(self) -> None:
        text = (
            '{"id":"E1","level":"ERROR","service":"auth",'
            '"message":"token expired password=do-not-export"}'
        )

        first = serialize_report(build_safe_report(text))
        second = serialize_report(build_safe_report(text))

        self.assertEqual(first, second)
        self.assertNotIn("do-not-export", first)
        self.assertIn("[REDACTED]", first)
        self.assertNotIn("generated_at", first)

    def test_empty_log_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "no non-empty log events"):
            build_safe_report("\n")


if __name__ == "__main__":
    unittest.main()
