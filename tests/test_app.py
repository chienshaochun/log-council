from __future__ import annotations

import unittest
from pathlib import Path

from log_council.app import (
    cited_event_ids,
    decode_upload,
    input_digest,
    validate_text_size,
)
from log_council.reporting import build_safe_report
from streamlit.testing.v1 import AppTest


INCIDENT = (
    '{"id":"E1","ts":"2026-09-01T10:00:00Z","level":"ERROR",'
    '"service":"cartservice","message":"OverflowException converting Int32"}\n'
    '{"id":"E2","ts":"2026-09-01T10:00:01Z","level":"ERROR",'
    '"service":"frontend","message":"request error"}'
)
APP_PATH = Path(__file__).resolve().parents[1] / "src" / "log_council" / "app.py"


class UIHelperTests(unittest.TestCase):
    def test_upload_decoder_accepts_utf8_bom_and_rejects_invalid_bytes(self) -> None:
        self.assertEqual(decode_upload(b"\xef\xbb\xbflog line"), "log line")
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            decode_upload(b"\xff\xfe\x00")

    def test_input_digest_is_stable_and_content_sensitive(self) -> None:
        self.assertEqual(input_digest(INCIDENT), input_digest(INCIDENT))
        self.assertNotEqual(input_digest(INCIDENT), input_digest(INCIDENT + "\n"))

    def test_pasted_text_size_limit_uses_utf8_bytes(self) -> None:
        validate_text_size("ab", limit=2)
        with self.assertRaisesRegex(ValueError, "上限"):
            validate_text_size("台", limit=2)

    def test_cited_event_index_resolves_report_evidence(self) -> None:
        payload = build_safe_report(INCIDENT)

        references = cited_event_ids(payload)

        self.assertIn("E1", references)
        self.assertIn("E2", references)
        self.assertEqual(len(references), len(set(references)))

    def test_cited_event_index_includes_message_ledger_references(self) -> None:
        payload = {"agent_messages": [{"evidence_ids": ["E-ledger"]}]}

        self.assertEqual(cited_event_ids(payload), ["E-ledger"])


class StreamlitAppTests(unittest.TestCase):
    def test_initial_screen_renders_without_analysis(self) -> None:
        app = AppTest.from_file(str(APP_PATH)).run(timeout=20)

        self.assertEqual(app.exception, [])
        self.assertEqual(app.title[0].value, "LogCouncil")
        self.assertEqual(app.radio[0].value, "貼上 log")
        self.assertEqual(app.button[0].label, "開始分析")

    def test_pasted_log_renders_complete_council_report(self) -> None:
        app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
        app.text_area[0].set_value(INCIDENT)
        app.button[0].click()
        app.run(timeout=20)

        self.assertEqual(app.exception, [])
        self.assertEqual(app.error, [])
        self.assertEqual(
            [metric.label for metric in app.metric],
            ["Log events", "Parse coverage", "Council confidence", "Agent consensus"],
        )
        self.assertEqual(
            [tab.label for tab in app.tabs],
            ["Overview", "Evidence", "Agents", "Handoffs", "Data quality"],
        )
        self.assertGreaterEqual(len(app.dataframe), 5)
        self.assertEqual(len(app.get("download_button")), 1)
        self.assertIn("analysis_payload", app.session_state)

    def test_empty_input_is_a_visible_user_error(self) -> None:
        app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
        app.button[0].click()
        app.run(timeout=20)

        self.assertEqual(app.exception, [])
        self.assertIn("請貼上 log", app.error[0].value)


if __name__ == "__main__":
    unittest.main()
