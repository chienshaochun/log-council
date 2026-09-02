from __future__ import annotations

import csv
import unittest
from pathlib import Path

from log_council.datasets import load_manifest, parse_openstack_file
from log_council.datasets.contracts import validate_dataset_file


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "external" / "loghub-openstack-2k"
RAW_LOG = DATA_DIR / "OpenStack_2k.log"
REFERENCE_CSV = DATA_DIR / "OpenStack_2k.log_structured.csv"
HAS_OFFICIAL_SAMPLE = RAW_LOG.is_file() and REFERENCE_CSV.is_file()


@unittest.skipUnless(
    HAS_OFFICIAL_SAMPLE,
    "official Loghub sample is optional; run scripts/download_dataset.py loghub-openstack-2k",
)
class OfficialOpenStackSampleTests(unittest.TestCase):
    def test_downloaded_artifacts_match_manifest(self) -> None:
        manifest = load_manifest(
            PROJECT_ROOT / "data" / "manifests" / "loghub-openstack-2k.json"
        )

        for spec in manifest.files:
            validate_dataset_file(DATA_DIR / spec.name, spec)

    def test_all_raw_lines_match_official_parser_reference_fields(self) -> None:
        parsed = parse_openstack_file(RAW_LOG)
        with REFERENCE_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
            reference = list(csv.DictReader(handle))

        self.assertEqual(parsed.stats.event_count, 2000)
        self.assertEqual(parsed.stats.structured_count, 2000)
        self.assertEqual(parsed.stats.fallback_count, 0)
        self.assertEqual(len(reference), len(parsed.events))

        for event, expected in zip(parsed.events, reference, strict=True):
            self.assertEqual(event.level, expected["Level"])
            self.assertEqual(event.attributes["log_file"], expected["Logrecord"])
            self.assertEqual(event.attributes["process_id"], int(expected["Pid"]))
            self.assertEqual(event.attributes["component"], expected["Component"])
            self.assertEqual(event.attributes["context"], expected["ADDR"])
            self.assertEqual(event.message, expected["Content"])


if __name__ == "__main__":
    unittest.main()
