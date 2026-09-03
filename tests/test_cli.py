from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from log_council.cli import main


INCIDENT = (
    '{"id":"E1","ts":"2026-09-01T10:00:00Z","level":"ERROR",'
    '"service":"cartservice","message":"OverflowException password=private-value"}\n'
    '{"id":"E2","ts":"2026-09-01T10:00:01Z","level":"ERROR",'
    '"service":"frontend","message":"request error Authorization: Bearer abcdefghijkl"}'
)


class CLITests(unittest.TestCase):
    def _run(self, arguments: list[str], stdin: str = "") -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch("sys.stdin", io.StringIO(stdin)),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            result = main(arguments)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_prints_human_readable_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            source = Path(directory_name) / "incident.log"
            source.write_text(INCIDENT, encoding="utf-8")

            code, stdout, stderr = self._run(["analyze", str(source)])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("主要假設：應用程式數值轉換溢位", stdout)
        self.assertIn("建議的下一步：", stdout)
        self.assertNotIn("private-value", stdout)

    def test_json_is_redacted_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            source = Path(directory_name) / "incident.jsonl"
            output = Path(directory_name) / "report.json"
            source.write_text(INCIDENT, encoding="utf-8")

            first_code, _, _ = self._run(["analyze", str(source), "-o", str(output)])
            first = output.read_text(encoding="utf-8")
            second_code, _, _ = self._run([
                "analyze", str(source), "-o", str(output), "--force"
            ])
            second = output.read_text(encoding="utf-8")
            original = source.read_text(encoding="utf-8")

        self.assertEqual((first_code, second_code), (0, 0))
        self.assertEqual(first, second)
        self.assertNotIn("private-value", first)
        self.assertNotIn("abcdefghijkl", first)
        self.assertIn("[REDACTED]", first)
        payload = json.loads(first)
        self.assertNotIn("generated_at", payload)
        self.assertEqual(payload["parse"]["stats"]["event_count"], 2)
        self.assertEqual(len(payload["events"]), 2)
        self.assertIn("private-value", original)

    def test_refuses_to_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            source = Path(directory_name) / "incident.txt"
            output = Path(directory_name) / "report.json"
            source.write_text(INCIDENT, encoding="utf-8")
            output.write_text("keep me", encoding="utf-8")

            code, _, stderr = self._run(["analyze", str(source), "-o", str(output)])

            self.assertEqual(output.read_text(encoding="utf-8"), "keep me")
        self.assertEqual(code, 1)
        self.assertIn("輸出檔案已存在", stderr)

    def test_never_replaces_the_input_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            source = Path(directory_name) / "incident.log"
            source.write_text(INCIDENT, encoding="utf-8")

            code, _, stderr = self._run([
                "analyze", str(source), "-o", str(source), "--force"
            ])

            self.assertEqual(source.read_text(encoding="utf-8"), INCIDENT)
        self.assertEqual(code, 1)
        self.assertIn("輸出路徑不可與輸入 log 路徑相同", stderr)

    def test_requires_json_output_extension(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            source = Path(directory_name) / "incident.log"
            output = Path(directory_name) / "report.txt"
            source.write_text(INCIDENT, encoding="utf-8")

            code, _, stderr = self._run(["analyze", str(source), "-o", str(output)])

        self.assertEqual(code, 1)
        self.assertIn("必須使用 .json 副檔名", stderr)

    def test_accepts_stdin_and_can_omit_events(self) -> None:
        code, stdout, stderr = self._run(
            ["analyze", "-", "--json", "--omit-events"],
            stdin=INCIDENT,
        )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertNotIn("events", json.loads(stdout))

    def test_rejects_empty_or_unsupported_input(self) -> None:
        empty_code, _, empty_error = self._run(["analyze", "-"], stdin="\n")
        unsupported_code, _, unsupported_error = self._run(["analyze", "incident.csv"])

        self.assertEqual((empty_code, unsupported_code), (1, 1))
        self.assertIn("沒有非空白的 log 事件", empty_error)
        self.assertIn("不支援的輸入副檔名", unsupported_error)


if __name__ == "__main__":
    unittest.main()
