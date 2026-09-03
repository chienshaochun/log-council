from __future__ import annotations

import tempfile
import unittest
from datetime import timezone
from pathlib import Path

from log_council.datasets import DatasetError, load_rcaeval_case

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover - optional dependency
    pa = None
    pq = None


CASE_ID = "re3ob_cartservice_f1_1"


@unittest.skipUnless(pa is not None and pq is not None, "pyarrow dataset extra is optional")
class RCAEvalAdapterTests(unittest.TestCase):
    def _write_fixture(self, directory: Path) -> tuple[Path, Path, Path]:
        logs_path = directory / "logs.parquet"
        cases_path = directory / "cases.parquet"
        inject_path = directory / "inject_time.txt"
        pq.write_table(pa.table({
            "timestamp": [99, 100, 101],
            "container_name": ["frontend", "cartservice", "frontend"],
            "message": ["request started", "OverflowException", "request error"],
        }), logs_path)
        pq.write_table(pa.table({
            "case": [CASE_ID],
            "dataset": ["RE3-OB"],
            "system_name": ["Online Boutique"],
            "root_cause_service": ["cartservice"],
            "fault": ["f1"],
            "fault_description": ["code-level fault F1"],
            "repetition": [1],
            "inject_time": [100],
            "time_start": [90],
            "time_end": [110],
            "n_logs": [3],
            "has_logs": [True],
        }), cases_path)
        inject_path.write_text("100\n", encoding="utf-8")
        return logs_path, cases_path, inject_path

    def test_loads_agent_input_and_keeps_ground_truth_separate(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            paths = self._write_fixture(Path(directory_name))
            case = load_rcaeval_case(*paths, case_id=CASE_ID)

        self.assertEqual(case.dataset, "RE3-OB")
        self.assertEqual(case.ground_truth.root_cause_service, "cartservice")
        self.assertEqual(case.ground_truth.fault, "f1")
        self.assertEqual(len(case.analysis.events), 3)
        self.assertEqual(case.analysis.incident_anchor.tzinfo, timezone.utc)

        before, anchor, after = case.analysis.events
        self.assertEqual(before.attributes["phase"], "pre-injection")
        self.assertEqual(anchor.attributes["phase"], "post-injection")
        self.assertEqual(after.attributes["seconds_from_injection"], 1)
        self.assertTrue(all(event.level == "UNKNOWN" for event in case.analysis.events))
        self.assertEqual(anchor.id, "RCA-000002")

        forbidden = {"case_id", "root_cause_service", "fault", "fault_description"}
        self.assertTrue(all(
            forbidden.isdisjoint(event.attributes)
            for event in case.analysis.events
        ))
        self.assertTrue(all(
            CASE_ID not in str(event.attributes.values())
            for event in case.analysis.events
        ))

    def test_rejects_injection_time_that_disagrees_with_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            logs_path, cases_path, inject_path = self._write_fixture(directory)
            inject_path.write_text("101\n", encoding="utf-8")

            with self.assertRaisesRegex(DatasetError, "injection time does not match"):
                load_rcaeval_case(logs_path, cases_path, inject_path, CASE_ID)

    def test_rejects_logs_with_missing_required_column(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            logs_path, cases_path, inject_path = self._write_fixture(directory)
            pq.write_table(pa.table({
                "timestamp": [100],
                "container_name": ["cartservice"],
            }), logs_path)

            with self.assertRaisesRegex(DatasetError, "missing columns: message"):
                load_rcaeval_case(logs_path, cases_path, inject_path, CASE_ID)

    def test_rejects_unknown_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            paths = self._write_fixture(Path(directory_name))
            with self.assertRaisesRegex(DatasetError, "found 0"):
                load_rcaeval_case(*paths, case_id="missing-case")


if __name__ == "__main__":
    unittest.main()
