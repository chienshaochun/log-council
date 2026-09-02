from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from log_council.datasets.contracts import (
    DatasetError,
    DatasetFile,
    load_manifest,
    validate_dataset_file,
)
from log_council.datasets.loghub_openstack import parse_openstack_text


# Synthetic fixture matching the public Loghub OpenStack field layout.
OPENSTACK_FORMAT_FIXTURE = """
nova-api.log.1.2017-05-16_13:53:08 2017-05-16 00:00:00.008 25746 INFO nova.osapi_compute.wsgi.server [req-38101a0b-2096-447d-96ea-a692162415ae user project - - -] 10.11.10.1 GET /servers status: 200
nova-compute.log.1.2017-05-16_13:55:31 2017-05-16 00:00:04.500 2931 ERROR nova.compute.manager [req-3ea4052c-895d-4b64-9e2d-04d64c4d94ab - - - - -] Instance failed to start
"""


class OpenStackAdapterTests(unittest.TestCase):
    def test_parses_openstack_fields_without_discarding_context(self) -> None:
        parsed = parse_openstack_text(OPENSTACK_FORMAT_FIXTURE)

        self.assertEqual(parsed.stats.event_count, 2)
        self.assertEqual(parsed.stats.coverage, 1.0)
        first, second = parsed.events
        self.assertEqual(first.id, "OS-000001")
        self.assertEqual(first.service, "nova-api")
        self.assertEqual(first.level, "INFO")
        self.assertEqual(first.trace_id, "req-38101a0b-2096-447d-96ea-a692162415ae")
        self.assertEqual(first.attributes["component"], "nova.osapi_compute.wsgi.server")
        self.assertEqual(first.attributes["process_id"], 25746)
        self.assertEqual(second.service, "nova-compute")
        self.assertEqual(second.level, "ERROR")

    def test_preserves_unrecognized_line_as_visible_fallback(self) -> None:
        parsed = parse_openstack_text("not an openstack log line")

        self.assertEqual(parsed.events[0].raw, "not an openstack log line")
        self.assertEqual(parsed.stats.fallback_count, 1)
        self.assertEqual(parsed.issues[0].code, "unrecognized_openstack_format")


class DatasetContractTests(unittest.TestCase):
    def test_manifest_pins_repository_revision_and_file_limits(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        manifest = load_manifest(
            project_root / "data" / "manifests" / "loghub-openstack-2k.json"
        )

        self.assertEqual(manifest.dataset_id, "loghub-openstack-2k")
        self.assertEqual(len(manifest.source_revision), 40)
        self.assertNotIn("/master/", manifest.files[0].url)
        self.assertTrue(all(item.max_bytes > 0 for item in manifest.files))

    def test_file_validation_checks_hash_and_line_count(self) -> None:
        content = b"first\nsecond\n"
        digest = hashlib.sha256(content).hexdigest()
        spec = DatasetFile(
            name="sample.log",
            role="raw_logs",
            url="https://example.invalid/sample.log",
            sha256=digest,
            expected_lines=2,
            max_bytes=100,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / spec.name
            path.write_bytes(content)

            validate_dataset_file(path, spec)

            wrong = DatasetFile(**{**spec.__dict__, "sha256": "0" * 64})
            with self.assertRaisesRegex(DatasetError, "SHA-256 mismatch"):
                validate_dataset_file(path, wrong)


if __name__ == "__main__":
    unittest.main()
