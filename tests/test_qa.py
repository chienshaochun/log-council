from __future__ import annotations

import json
import unittest
from pathlib import Path
from urllib.error import URLError

from log_council.qa import (
    ANSWER_SCHEMA,
    LogAnswer,
    OllamaProvider,
    OllamaResponseError,
    OllamaUnavailableError,
    build_evidence_packet,
)
from log_council.reporting import build_safe_report


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def sample_report() -> dict[str, object]:
    return {
        "run_id": "RUN-test",
        "summary": {"root_cause": "證據不足", "confidence": 0.4},
        "findings": [
            {
                "agent": "Pattern Agent",
                "title": "偵測到連線壓力",
                "summary": "連線池達到 100%",
                "confidence": 0.6,
                "evidence": [{"event_id": "EVT-002"}],
            }
        ],
        "hypotheses": [],
        "correlations": [],
        "events": [
            {
                "id": "EVT-001",
                "timestamp": "2026-09-03T10:15:01",
                "level": "INFO",
                "service": "api",
                "message": "request started password=secret-value",
                "trace_id": None,
            },
            {
                "id": "EVT-002",
                "timestamp": "2026-09-03T10:15:02",
                "level": "WARN",
                "service": "api",
                "message": "database connection pool usage=100%",
                "trace_id": None,
            },
            {
                "id": "EVT-003",
                "timestamp": "2026-09-03T10:15:05",
                "level": "ERROR",
                "service": "api",
                "message": "unable to acquire database connection",
                "trace_id": None,
            },
        ],
    }


def valid_answer() -> dict[str, object]:
    return {
        "summary": "資料庫連線出現壓力，但目前不足以確認根因。",
        "evidence_ids": ["EVT-002"],
        "hypotheses": [
            {
                "statement": "連線池可能因長時間占用而耗盡。",
                "evidence_ids": ["EVT-002", "EVT-003"],
                "confidence": "medium",
            }
        ],
        "next_actions": [
            {
                "action": "檢查連線池使用指標。",
                "reason": "確認連線是否能正常釋放。",
            }
        ],
        "limitations": ["目前沒有資料庫端的查詢與連線明細。"],
    }


class EvidencePacketTests(unittest.TestCase):
    def test_packet_is_redacted_and_omits_raw_log(self) -> None:
        packet = build_evidence_packet(sample_report())
        serialized = json.dumps(packet, ensure_ascii=False)

        self.assertNotIn("secret-value", serialized)
        self.assertIn("[REDACTED]", serialized)
        self.assertNotIn("raw", packet["events"][0])

    def test_packet_prioritizes_citations_and_high_severity_events(self) -> None:
        report = sample_report()

        packet = build_evidence_packet(report, max_events=2)

        self.assertEqual(
            [event["id"] for event in packet["events"]],
            ["EVT-002", "EVT-003"],
        )

    def test_committed_demo_log_has_expected_analysis_and_safe_packet(self) -> None:
        text = (PROJECT_ROOT / "examples" / "local-llm-qa-demo.log").read_text(
            encoding="utf-8"
        )

        report = build_safe_report(text)
        packet = build_evidence_packet(report)
        serialized = json.dumps(packet, ensure_ascii=False)

        self.assertEqual(report["parse"]["stats"]["event_count"], 7)
        self.assertEqual(report["parse"]["stats"]["coverage"], 1.0)
        self.assertEqual(report["hypotheses"][0]["title"], "資料庫連線池耗盡（服務：checkout）")
        self.assertNotIn("demo@example.com", serialized)
        self.assertIn("[REDACTED]", serialized)


class LogAnswerTests(unittest.TestCase):
    def test_answer_accepts_only_known_evidence_ids(self) -> None:
        answer = LogAnswer.from_mapping(
            valid_answer(),
            evidence_events={
                event["id"]: event for event in sample_report()["events"]
            },
            model="test-model",
        )

        self.assertEqual(answer.facts[0].event_id, "EVT-002")
        self.assertEqual(answer.facts[0].message, "database connection pool usage=100%")
        self.assertEqual(answer.hypotheses[0].confidence, "medium")

    def test_answer_rejects_unknown_evidence_id(self) -> None:
        payload = valid_answer()
        payload["evidence_ids"] = ["EVT-999"]

        with self.assertRaisesRegex(OllamaResponseError, "EVT-999"):
            LogAnswer.from_mapping(
                payload,
                evidence_events={
                    event["id"]: event for event in sample_report()["events"]
                },
                model="test-model",
            )

    def test_answer_rejects_uncited_fact(self) -> None:
        payload = valid_answer()
        payload["evidence_ids"] = []

        with self.assertRaisesRegex(OllamaResponseError, "至少一個事件 ID"):
            LogAnswer.from_mapping(
                payload,
                evidence_events={
                    event["id"]: event for event in sample_report()["events"]
                },
                model="test-model",
            )


class OllamaProviderTests(unittest.TestCase):
    def test_provider_rejects_non_local_endpoint(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            OllamaProvider(base_url="https://example.com")

    def test_provider_sends_bounded_structured_request(self) -> None:
        captured: dict[str, object] = {}

        def opener(request: object, *, timeout: float) -> FakeResponse:
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse(
                {
                    "model": "qwen3.5:2b-q4_K_M",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(valid_answer(), ensure_ascii=False),
                    },
                }
            )

        provider = OllamaProvider(opener=opener, timeout_seconds=15)
        answer = provider.answer("發生了什麼問題？", sample_report())

        body = captured["body"]
        self.assertEqual(captured["url"], "http://localhost:11434/api/chat")
        self.assertEqual(captured["timeout"], 15)
        self.assertFalse(body["stream"])
        self.assertFalse(body["think"])
        self.assertEqual(body["format"], ANSWER_SCHEMA)
        self.assertEqual(body["options"]["temperature"], 0)
        self.assertEqual(body["options"]["num_ctx"], 4096)
        self.assertNotIn("secret-value", body["messages"][1]["content"])
        self.assertEqual(answer.model, "qwen3.5:2b-q4_K_M")

    def test_healthcheck_returns_version(self) -> None:
        def opener(request: object, *, timeout: float) -> FakeResponse:
            return FakeResponse({"version": "0.33.2"})

        self.assertEqual(OllamaProvider(opener=opener).healthcheck(), "0.33.2")

    def test_connection_failure_has_actionable_error(self) -> None:
        def opener(request: object, *, timeout: float) -> FakeResponse:
            raise URLError("connection refused")

        with self.assertRaisesRegex(OllamaUnavailableError, "Ollama 已啟動"):
            OllamaProvider(opener=opener).healthcheck()


if __name__ == "__main__":
    unittest.main()
