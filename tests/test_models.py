from __future__ import annotations

import unittest
from datetime import datetime

from log_council.models import LogEvent, ParsedLog, ParseStats


class ModelTests(unittest.TestCase):
    def test_event_serializes_datetime_as_iso8601(self) -> None:
        event = LogEvent(
            id="EVT-1",
            timestamp=datetime.fromisoformat("2026-09-01T14:02:41+08:00"),
            level="INFO",
            service="checkout",
            message="request started",
        )

        self.assertEqual(event.to_dict()["timestamp"], "2026-09-01T14:02:41+08:00")

    def test_parse_coverage_is_zero_for_empty_input(self) -> None:
        stats = ParseStats(0, 0, 0, 0, 0, 0)
        parsed = ParsedLog((), (), stats)

        self.assertEqual(parsed.stats.coverage, 0.0)


if __name__ == "__main__":
    unittest.main()
