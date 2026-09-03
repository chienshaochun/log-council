from __future__ import annotations

import unittest

from log_council.redaction import REDACTED, redact_text, redact_value


class RedactionTests(unittest.TestCase):
    def test_redacts_common_secret_forms(self) -> None:
        samples = (
            "Authorization: Bearer abcdefghijklmnop",
            "api_key=sk-example-secret",
            "password: hunter2",
            '"client_secret":"very-secret-value"',
            "Cookie: session=private-value",
        )

        for sample in samples:
            with self.subTest(sample=sample):
                result = redact_text(sample)
                self.assertIn(REDACTED, result)
                self.assertNotIn(sample.split()[-1], result)

    def test_redacts_nested_copy_without_mutating_input(self) -> None:
        source = {
            "events": [{
                "message": "password=original-secret",
                "attributes": {"api_key": "key-without-prefix"},
            }],
        }

        result = redact_value(source)

        self.assertEqual(source["events"][0]["message"], "password=original-secret")
        self.assertEqual(result["events"][0]["message"], f"password={REDACTED}")
        self.assertEqual(result["events"][0]["attributes"]["api_key"], REDACTED)


if __name__ == "__main__":
    unittest.main()
