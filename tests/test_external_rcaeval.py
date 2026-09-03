from __future__ import annotations

import unittest
from pathlib import Path

from log_council import CouncilOrchestrator
from log_council.agents import CorrelationAgent
from log_council.datasets import load_manifest, load_rcaeval_case
from log_council.datasets.contracts import validate_dataset_file

try:
    import pyarrow  # noqa: F401
except ImportError:  # pragma: no cover - optional dependency
    pyarrow = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "external" / "rcaeval-re3ob-cartservice-f1-1"
LOGS = DATA_DIR / "logs.parquet"
CASES = DATA_DIR / "cases.parquet"
INJECT_TIME = DATA_DIR / "inject_time.txt"
HAS_OFFICIAL_CASE = (
    pyarrow is not None
    and LOGS.is_file()
    and CASES.is_file()
    and INJECT_TIME.is_file()
)


@unittest.skipUnless(
    HAS_OFFICIAL_CASE,
    "official RCAEval case is optional; run the dataset download script",
)
class OfficialRCAEvalCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.case = load_rcaeval_case(
            LOGS,
            CASES,
            INJECT_TIME,
            case_id="re3ob_cartservice_f1_1",
        )

    def test_downloaded_artifacts_match_pinned_manifest(self) -> None:
        manifest = load_manifest(
            PROJECT_ROOT / "data" / "manifests" / "rcaeval-re3ob-cartservice-f1-1.json"
        )
        for spec in manifest.files:
            validate_dataset_file(DATA_DIR / spec.name, spec)

    def test_official_case_has_expected_logs_and_evaluation_label(self) -> None:
        self.assertEqual(len(self.case.analysis.events), 65_025)
        self.assertEqual(self.case.ground_truth.root_cause_service, "cartservice")
        self.assertEqual(self.case.ground_truth.fault, "f1")
        self.assertTrue(all(
            event.level == "UNKNOWN" for event in self.case.analysis.events
        ))
        self.assertEqual(
            {event.attributes["phase"] for event in self.case.analysis.events},
            {"pre-injection", "post-injection"},
        )

    def test_log_only_evidence_contains_signal_and_distractor(self) -> None:
        post_injection_cart_errors = [
            event for event in self.case.analysis.events
            if event.service == "cartservice"
            and event.attributes["seconds_from_injection"] >= 0
            and "OverflowException" in event.message
        ]
        earlier_payment_distractors = [
            event for event in self.case.analysis.events
            if event.service == "paymentservice"
            and event.attributes["seconds_from_injection"] < 0
            and "UnacceptedCreditCard" in event.message
        ]
        self.assertGreaterEqual(len(post_injection_cart_errors), 300)
        self.assertGreaterEqual(len(earlier_payment_distractors), 1)

    def test_agent_visible_attributes_do_not_contain_evaluation_labels(self) -> None:
        forbidden = {"case_id", "root_cause_service", "fault", "fault_description"}
        for event in self.case.analysis.events:
            self.assertTrue(forbidden.isdisjoint(event.attributes))
            self.assertNotIn("re3ob_cartservice_f1_1", str(event.attributes.values()))

    def test_correlation_agent_finds_log_only_onset_and_propagation(self) -> None:
        finding, links = CorrelationAgent().analyze(list(self.case.analysis.events))
        by_id = {event.id: event for event in self.case.analysis.events}

        onset = by_id[finding.evidence[0].event_id]
        self.assertEqual(onset.service, "cartservice")
        self.assertGreaterEqual(onset.attributes["seconds_from_injection"], 0)
        self.assertTrue(any(
            link.relation == "bounded-time-proximity"
            and by_id[link.target_event_id].service == "frontend"
            for link in links
        ))
        contextual = [
            by_id[evidence.event_id]
            for evidence in finding.evidence
            if evidence.stance == "context"
        ]
        self.assertTrue(any(
            event.service == "paymentservice"
            and event.attributes["seconds_from_injection"] < 0
            for event in contextual
        ))

    def test_full_council_ranks_the_labeled_service_without_label_input(self) -> None:
        report = CouncilOrchestrator().analyze(list(self.case.analysis.events))
        leading = report.hypotheses[0]

        self.assertIn("numeric conversion overflow", leading.title.lower())
        self.assertIn(self.case.ground_truth.root_cause_service, leading.title)
        self.assertIn(self.case.ground_truth.root_cause_service, report.root_cause)
        by_id = {event.id: event for event in self.case.analysis.events}
        self.assertTrue(leading.supporting)
        self.assertTrue(all(
            by_id[evidence.event_id].service == self.case.ground_truth.root_cause_service
            for evidence in leading.supporting
        ))


if __name__ == "__main__":
    unittest.main()
