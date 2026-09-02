from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from log_council.parser import parse_log_document, parse_log_file, parse_log_text


class ParserTests(unittest.TestCase):
    def test_parses_jsonl_and_preserves_extra_attributes(self) -> None:
        text = (
            '{"id":"EVT-101","ts":"2026-09-01T14:02:41+08:00",'
            '"level":"WARN","service":"checkout","trace_id":"tr-1",'
            '"duration_ms":2184,"message":"slow query"}'
        )

        event = parse_log_text(text)[0]

        self.assertEqual(event.id, "EVT-101")
        self.assertEqual(event.level, "WARN")
        self.assertEqual(event.service, "checkout")
        self.assertEqual(event.trace_id, "tr-1")
        self.assertEqual(event.attributes["duration_ms"], 2184)
        self.assertEqual(event.timestamp.isoformat(), "2026-09-01T14:02:41+08:00")

    def test_parses_common_text_log_and_trace_id(self) -> None:
        event = parse_log_text(
            "2026-09-01 14:02:45 ERROR [checkout] timed out trace_id=tr-8f44"
        )[0]

        self.assertEqual(event.level, "ERROR")
        self.assertEqual(event.service, "checkout")
        self.assertEqual(event.trace_id, "tr-8f44")
        self.assertIsNotNone(event.timestamp)

    def test_unknown_line_is_preserved_and_reported(self) -> None:
        parsed = parse_log_document("something happened but format is unknown")

        self.assertEqual(len(parsed.events), 1)
        self.assertEqual(parsed.events[0].message, "something happened but format is unknown")
        self.assertEqual(parsed.stats.fallback_count, 1)
        self.assertEqual(parsed.issues[0].code, "unrecognized_format")

    def test_invalid_json_timestamp_is_visible_as_quality_issue(self) -> None:
        parsed = parse_log_document(
            '{"timestamp":"not-a-time","level":"ERROR","message":"failed"}'
        )

        self.assertIsNone(parsed.events[0].timestamp)
        self.assertEqual(parsed.stats.invalid_timestamp_count, 1)
        self.assertEqual(parsed.issues[0].code, "invalid_timestamp")

    def test_duplicate_ids_are_made_unique_without_dropping_events(self) -> None:
        parsed = parse_log_document(
            '{"id":"same","message":"first"}\n'
            '{"id":"same","message":"second"}'
        )

        self.assertEqual([event.id for event in parsed.events], ["same", "same#2"])
        self.assertEqual(parsed.stats.duplicate_id_count, 1)
        self.assertEqual(parsed.issues[0].code, "duplicate_event_id")

    def test_blank_lines_are_ignored_in_quality_counts(self) -> None:
        parsed = parse_log_document("\n{\"message\":\"ok\"}\n\n")

        self.assertEqual(parsed.stats.input_lines, 1)
        self.assertEqual(parsed.stats.event_count, 1)
        self.assertEqual(parsed.stats.coverage, 1.0)

    def test_file_reader_accepts_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.jsonl"
            path.write_text('{"message":"ok"}\n', encoding="utf-8-sig")

            events = parse_log_file(path)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].message, "ok")


if __name__ == "__main__":
    unittest.main()
