from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor

from .agents import (
    CorrelationAgent,
    PatternAgent,
    ReviewerAgent,
    RootCauseAgent,
    TimelineAgent,
)
from .collaboration import EvidenceRegistry, HandoffLedger
from .models import Activity, AgentFinding, AnalysisReport, Evidence, Handoff, LogEvent


def _run_id(events: list[LogEvent]) -> str:
    digest = hashlib.sha256()
    for event in events:
        digest.update(event.id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(event.raw.encode("utf-8"))
        digest.update(b"\n")
    return f"RUN-{digest.hexdigest()[:12]}"


def _evidence_ids(evidence: list[Evidence]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.event_id for item in evidence))


class CouncilOrchestrator:
    """Coordinate specialists through evidence-bound, inspectable handoffs."""

    def __init__(self) -> None:
        self.pattern = PatternAgent()
        self.timeline = TimelineAgent()
        self.correlation = CorrelationAgent()
        self.root_cause = RootCauseAgent()
        self.reviewer = ReviewerAgent()

    def analyze(self, events: list[LogEvent]) -> AnalysisReport:
        if not events:
            raise ValueError("至少需要一筆 log 事件")

        run_id = _run_id(events)
        registry = EvidenceRegistry(events)
        ledger = HandoffLedger(run_id, registry)

        pattern_task = ledger.add(
            "Coordinator", "Pattern Agent", "task", "尋找異常 log 模式",
            "偵測重複模板、嚴重度群集、重試與資源壓力訊號。",
        )
        timeline_task = ledger.add(
            "Coordinator", "Timeline Agent", "task", "重建事故時間線",
            "尋找最早前兆、擴散症狀、失敗點與恢復證據。",
        )
        correlation_task = ledger.add(
            "Coordinator", "Correlation Agent", "task", "關聯相關事件",
            "依服務、識別碼與限定的時間鄰近性連結訊號，同時保留可能的干擾事件。",
        )

        # Specialists run concurrently, while ledger insertion stays deterministic.
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="log-council") as executor:
            pattern_future = executor.submit(self.pattern.analyze, events)
            timeline_future = executor.submit(self.timeline.analyze, events)
            correlation_future = executor.submit(self.correlation.analyze, events)
            pattern = pattern_future.result()
            timeline = timeline_future.result()
            correlation, correlations = correlation_future.result()

        registry.validate_finding(pattern)
        registry.validate_finding(timeline)
        registry.validate_finding(correlation)
        registry.validate_correlations(correlations)
        pattern_message = ledger.add(
            "Pattern Agent", "Coordinator", "finding", pattern.title, pattern.summary,
            evidence_ids=_evidence_ids(pattern.evidence), in_reply_to=pattern_task.message_id,
        )
        timeline_message = ledger.add(
            "Timeline Agent", "Coordinator", "finding", timeline.title, timeline.summary,
            evidence_ids=_evidence_ids(timeline.evidence), in_reply_to=timeline_task.message_id,
        )
        correlation_message = ledger.add(
            "Correlation Agent", "Coordinator", "finding", correlation.title,
            correlation.summary, evidence_ids=_evidence_ids(correlation.evidence),
            in_reply_to=correlation_task.message_id,
        )

        specialist_evidence = _evidence_ids([
            *pattern.evidence,
            *timeline.evidence,
            *correlation.evidence,
        ])
        cause_task = ledger.add(
            "Coordinator", "Root Cause Agent", "task", "比較根因假設",
            "使用各專業 Agent 的發現排序解釋，且不得超出提供的 log 證據。",
            evidence_ids=specialist_evidence,
            payload_refs=(
                pattern_message.message_id,
                timeline_message.message_id,
                correlation_message.message_id,
            ),
        )
        root_finding, hypotheses, rule = self.root_cause.analyze(
            events,
            specialist_findings=[pattern, timeline, correlation],
            correlations=correlations,
        )
        registry.validate_finding(root_finding)
        registry.validate_hypotheses(hypotheses)
        cause_message = ledger.add(
            "Root Cause Agent", "Coordinator", "hypothesis", root_finding.title,
            root_finding.summary, evidence_ids=_evidence_ids(root_finding.evidence),
            in_reply_to=cause_task.message_id,
        )

        review_task = ledger.add(
            "Coordinator", "Reviewer Agent", "review_request", "挑戰主要假設",
            "檢查缺乏支持的主張、競爭觸發因素、反證與缺少的資料範圍。",
            evidence_ids=_evidence_ids(root_finding.evidence),
            payload_refs=(cause_message.message_id,),
        )
        initial_review = self.reviewer.analyze(events, hypotheses)
        registry.validate_finding(initial_review)
        has_challenge = any(item.stance == "contradicting" for item in initial_review.evidence)
        review_message = ledger.add(
            "Reviewer Agent", "Coordinator", "challenge" if has_challenge else "decision",
            initial_review.title, initial_review.summary,
            evidence_ids=_evidence_ids(initial_review.evidence),
            in_reply_to=review_task.message_id,
        )

        revision_count = 0
        final_root = root_finding
        final_review = initial_review
        if has_challenge:
            revision_count = 1
            revision_task = ledger.add(
                "Coordinator", "Root Cause Agent", "revision_request",
                "處理 Reviewer 提出的反證",
                "修訂主要假設一次；保留矛盾證據，且不可加入沒有引用來源的事實。",
                evidence_ids=_evidence_ids(initial_review.evidence),
                payload_refs=(cause_message.message_id, review_message.message_id),
            )
            final_root, hypotheses = self.root_cause.revise(
                hypotheses,
                initial_review,
                prior_finding=root_finding,
            )
            registry.validate_finding(final_root)
            registry.validate_hypotheses(hypotheses)
            revision_message = ledger.add(
                "Root Cause Agent", "Coordinator", "revision", final_root.title,
                final_root.summary, evidence_ids=_evidence_ids(final_root.evidence),
                in_reply_to=revision_task.message_id,
            )
            final_review_task = ledger.add(
                "Coordinator", "Reviewer Agent", "review_request", "驗證範圍受限的修訂",
                "只有在矛盾證據仍清楚可見，且每項主張都有證據約束時才能接受。",
                evidence_ids=_evidence_ids(final_root.evidence),
                payload_refs=(revision_message.message_id,),
            )
            final_review = self.reviewer.finalize(hypotheses, initial_review)
            registry.validate_finding(final_review)
            ledger.add(
                "Reviewer Agent", "Coordinator", "decision", final_review.title,
                final_review.summary, evidence_ids=_evidence_ids(final_review.evidence),
                in_reply_to=final_review_task.message_id,
            )

        findings: list[AgentFinding] = [
            pattern,
            timeline,
            correlation,
            final_root,
            final_review,
        ]
        handoffs = [
            Handoff("Pattern Agent", "Root Cause Agent", "哪一種錯誤模式最能解釋這次事故？", "重複症狀需要因果解釋。"),
            Handoff("Timeline Agent", "Root Cause Agent", "疑似觸發因素是否早於下游失敗？", "必須先確認事件順序，才能主張因果關係。"),
            Handoff("Correlation Agent", "Root Cause Agent", "哪些訊號構成受證據約束的服務擴散鏈？", "不能只憑時間接近就宣稱已確認因果關係。"),
            Handoff("Root Cause Agent", "Reviewer Agent", "競爭假設能否解釋相同證據？", "主要原因需要接受反向審查。"),
        ]
        if has_challenge:
            handoffs.append(Handoff(
                "Reviewer Agent", "Root Cause Agent", "形成共識前先處理最強的矛盾證據。",
                "競爭觸發因素會削弱最初的主張。",
            ))
        activities = [
            Activity(1, pattern.agent, "模式掃描", pattern.summary),
            Activity(1, timeline.agent, "時間線重建", timeline.summary),
            Activity(1, correlation.agent, "事件關聯", correlation.summary),
            Activity(2, "Coordinator", "已驗證專業 Agent 發現", "已使用來源事件登錄表檢查 Pattern、Timeline 與 Correlation 的證據。"),
            Activity(3, root_finding.agent, "假設比較", root_finding.summary),
            Activity(4, initial_review.agent, "反向審查", initial_review.summary),
        ]
        if has_challenge:
            activities.append(Activity(5, final_root.agent, "範圍受限的修訂", final_root.summary))
            activities.append(Activity(6, final_review.agent, "修訂決策", final_review.summary))
        activities.append(Activity(
            7 if has_challenge else 5,
            "Coordinator", "形成共識",
            f"已驗證 {len(ledger.messages)} 則訊息，並完成 {revision_count} 輪修訂。",
        ))

        confidence = round(sum(item.confidence for item in findings) / len(findings), 3)
        if not final_root.evidence:
            confidence = min(confidence, 0.45)
        consensus_count = sum(item.confidence >= 0.55 for item in findings)
        caveat = initial_review.summary if has_challenge else "提供的 log 中沒有發現具實質影響的競爭觸發因素。"
        return AnalysisReport(
            events=events,
            findings=findings,
            handoffs=handoffs,
            activities=activities,
            hypotheses=hypotheses,
            root_cause=final_root.summary,
            confidence=confidence,
            consensus_count=consensus_count,
            agent_count=len(findings),
            caveat=caveat,
            evidence_chain=list(rule.chain) if final_root.evidence else ["證據不足"],
            recommended_actions=list(rule.actions) if final_root.evidence else [
                "收集第一次失敗前後更完整的 log 時間窗。",
                "加入受影響服務及其直接相依服務的 log。",
                "保留 request ID、trace ID、服務名稱與原始時間戳記。",
            ],
            correlations=correlations,
            run_id=run_id,
            agent_messages=list(ledger.messages),
        )
