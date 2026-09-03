from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from .models import AgentFinding, CorrelationLink, Evidence, Hypothesis, LogEvent


def _contains(event: LogEvent, *terms: str) -> bool:
    haystack = f"{event.service} {event.message}".lower()
    return any(
        bool(re.search(rf"\b{re.escape(term)}\b", haystack))
        if term.isdigit() else term in haystack
        for term in terms
    )


def _contains_deployment_signal(event: LogEvent) -> bool:
    haystack = f"{event.service} {event.message}".lower()
    return bool(re.search(r"\b(?:deploy(?:ed|ing|ment)?|release(?:d)?|version)\b", haystack))


def _ev(event: LogEvent, reason: str, stance: str = "supporting") -> Evidence:
    return Evidence(event.id, reason, stance)  # type: ignore[arg-type]


class PatternAgent:
    name = "Pattern Agent"

    def analyze(self, events: list[LogEvent]) -> AgentFinding:
        failures = [e for e in events if e.level in {"ERROR", "CRITICAL", "FATAL"}]
        pool = [e for e in events if _contains(e, "pool", "connection limit", "connections approaching")]
        normalized = Counter(
            re.sub(r"\b\d+(?:\.\d+)?\b", "#", e.message.lower()) for e in failures
        )
        repeated = max(normalized.values(), default=0)
        evidence = [_ev(e, "重複出現的資源壓力或連線異常") for e in pool[:4]]
        if not evidence:
            evidence = [_ev(e, "高嚴重度事件") for e in failures[:4]]
        if pool:
            title = "偵測到連線壓力模式"
            summary = f"找到 {len(pool)} 個連線／連線池訊號，以及 {len(failures)} 個高嚴重度事件。"
        elif failures:
            title = "偵測到錯誤群集"
            summary = f"找到 {len(failures)} 個高嚴重度事件；最大的正規化錯誤模式重複 {repeated} 次。"
        else:
            title = "沒有明顯的主要錯誤模式"
            summary = "樣本中沒有 ERROR／CRITICAL 事件，因此目前只能做初步判斷。"
        confidence = min(0.96, 0.45 + len(evidence) * 0.11 + min(repeated, 3) * 0.04)
        return AgentFinding(
            agent=self.name, title=title, summary=summary, confidence=confidence,
            evidence=evidence,
            details=[
                f"高嚴重度事件：{len(failures)}",
                f"連線／連線池訊號：{len(pool)}",
                f"最大重複錯誤模式次數：{repeated}",
            ],
        )


class TimelineAgent:
    name = "Timeline Agent"

    def analyze(self, events: list[LogEvent]) -> AgentFinding:
        ordered = sorted(events, key=lambda e: (e.timestamp is None, e.timestamp or 0))
        slow = next((e for e in ordered if _contains(e, "slow query", "latency", "took ")), None)
        pressure = next((e for e in ordered if _contains(e, "pool at capacity", "pool exhausted", "connection limit")), None)
        timeout = next((e for e in ordered if _contains(e, "timeout", "timed out", "504")), None)
        recovery = next((e for e in ordered if _contains(e, "recovered", "returned to baseline", "latency normal")), None)
        milestones = [item for item in (slow, pressure, timeout, recovery) if item]
        evidence = [_ev(event, "時間序列中的關鍵事件") for event in milestones]
        if len(milestones) >= 3:
            title = "已建立有順序的劣化鏈"
            summary = "前兆、資源壓力、下游失敗及／或恢復事件依可能的因果順序出現。"
            confidence = 0.87 if recovery else 0.79
        else:
            title = "時間線不完整"
            summary = "可辨識的關鍵事件太少，尚不足以建立可靠的因果順序。"
            confidence = 0.48 + len(milestones) * 0.08
        return AgentFinding(
            agent=self.name, title=title, summary=summary, confidence=min(confidence, 0.9),
            evidence=evidence,
            details=[f"{event.timestamp_text} | {event.service} | {event.message}" for event in milestones],
        )


FAILURE_TERMS = (
    "error",
    "exception",
    "failed",
    "failure",
    "timeout",
    "timed out",
    "refused",
    "unavailable",
    "panic",
    "denied",
    "slow query",
)
IDENTIFIER_KEYS = ("request_id", "request-id", "requestId", "correlation_id", "host")


def _is_signal(event: LogEvent) -> bool:
    return event.level in {"WARN", "WARNING", "ERROR", "CRITICAL", "FATAL"} or _contains(
        event, *FAILURE_TERMS
    )


def _signature(event: LogEvent) -> str:
    normalized = re.sub(
        r"\b(?:[0-9a-f]{8}-[0-9a-f-]{27,}|0x[0-9a-f]+|\d+(?:\.\d+)?)\b",
        "#",
        event.message.lower(),
    )
    return f"{event.service.lower()}|{' '.join(normalized.split())}"


def _timestamp_number(value: datetime | None) -> float | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _delta_seconds(source: LogEvent, target: LogEvent) -> float | None:
    source_time = _timestamp_number(source.timestamp)
    target_time = _timestamp_number(target.timestamp)
    if source_time is None or target_time is None:
        return None
    return round(target_time - source_time, 3)


def _ordered(events: list[LogEvent]) -> list[LogEvent]:
    return sorted(
        events,
        key=lambda event: (
            event.timestamp is None,
            _timestamp_number(event.timestamp) or 0,
            event.id,
        ),
    )


class CorrelationAgent:
    name = "Correlation Agent"
    proximity_seconds = 120

    def _onset(self, signals: list[LogEvent]) -> tuple[LogEvent, int, LogEvent | None]:
        pre = [event for event in signals if event.attributes.get("phase") == "pre-injection"]
        post = [event for event in signals if event.attributes.get("phase") == "post-injection"]
        if post:
            pre_signatures = {_signature(event) for event in pre}
            novel = [event for event in post if _signature(event) not in pre_signatures]
            candidates = novel or post
            counts = Counter(_signature(event) for event in candidates)
            first_position: dict[str, int] = {}
            for position, event in enumerate(candidates):
                first_position.setdefault(_signature(event), position)
            leading = min(counts, key=lambda item: (-counts[item], first_position[item], item))
            onset = next(event for event in candidates if _signature(event) == leading)
            distractor = next(
                (event for event in pre if _signature(event) != leading),
                None,
            )
            return onset, counts[leading], distractor
        onset = signals[0]
        repeated = sum(_signature(event) == _signature(onset) for event in signals)
        return onset, repeated, None

    def _identifier_links(self, events: list[LogEvent]) -> list[CorrelationLink]:
        groups: dict[tuple[str, str], list[LogEvent]] = {}
        for event in events:
            identifiers: list[tuple[str, str]] = []
            if event.trace_id:
                identifiers.append(("trace_id", event.trace_id))
            for key in IDENTIFIER_KEYS:
                value = event.attributes.get(key)
                if value not in (None, ""):
                    identifiers.append((key, str(value)))
            for identifier in identifiers:
                groups.setdefault(identifier, []).append(event)

        links: list[CorrelationLink] = []
        for (kind, value), group in sorted(groups.items()):
            ordered = _ordered(group)
            if not any(_is_signal(event) for event in ordered):
                continue
            pair = next(
                (
                    (source, target)
                    for position, source in enumerate(ordered)
                    for target in ordered[position + 1:]
                    if target.service != source.service
                ),
                None,
            )
            if pair is None:
                continue
            source, target = pair
            links.append(CorrelationLink(
                source_event_id=source.id,
                target_event_id=target.id,
                relation=f"shared-{kind}",
                basis=f"兩個事件具有相同的 {kind} 值（{value}）。",
                delta_seconds=_delta_seconds(source, target),
            ))
            if len(links) == 3:
                break
        return links

    def analyze(self, events: list[LogEvent]) -> tuple[AgentFinding, list[CorrelationLink]]:
        ordered = _ordered(events)
        signals = [event for event in ordered if _is_signal(event)]
        if not signals:
            return AgentFinding(
                agent=self.name,
                title="沒有可靠的事件關聯",
                summary="未找到足以建立關聯鏈的嚴重度或訊息訊號。",
                confidence=0.3,
                details=["目前不主張存在跨服務的因果順序。"],
            ), []

        onset, repeated_count, distractor = self._onset(signals)
        links: list[CorrelationLink] = []
        same_signature = [
            event for event in signals
            if event.id != onset.id and _signature(event) == _signature(onset)
        ]
        if same_signature:
            target = same_signature[0]
            links.append(CorrelationLink(
                onset.id,
                target.id,
                "repeated-signature",
                "正規化後的訊息特徵在同一服務中重複出現。",
                _delta_seconds(onset, target),
            ))

        downstream_services: set[str] = set()
        for event in signals:
            if event.id == onset.id or event.service == onset.service:
                continue
            delta = _delta_seconds(onset, event)
            if delta is None or delta < 0 or delta > self.proximity_seconds:
                continue
            if event.service in downstream_services:
                continue
            downstream_services.add(event.service)
            links.append(CorrelationLink(
                onset.id,
                event.id,
                "bounded-time-proximity",
                f"另一個服務在 {self.proximity_seconds} 秒的關聯視窗內出現訊號。",
                delta,
            ))
            if len(downstream_services) == 3:
                break

        existing = {
            (link.source_event_id, link.target_event_id, link.relation) for link in links
        }
        for link in self._identifier_links(events):
            key = (link.source_event_id, link.target_event_id, link.relation)
            if key not in existing:
                links.append(link)
                existing.add(key)

        evidence = [_ev(onset, "主要新錯誤特徵的起始候選事件")]
        by_id = {event.id: event for event in events}
        for link in links[:5]:
            target = by_id[link.target_event_id]
            evidence.append(_ev(target, f"透過 {link.relation} 建立關聯"))
        if distractor is not None:
            evidence.append(_ev(
                distractor,
                "既有訊號與注入後的新錯誤特徵不同，因此保留為背景資訊",
                "context",
            ))

        cross_service_count = len({
            by_id[link.target_event_id].service
            for link in links
            if by_id[link.target_event_id].service != onset.service
        })
        shared_identifier_count = sum(link.relation.startswith("shared-") for link in links)
        if cross_service_count:
            title = "偵測到跨服務擴散候選鏈"
            summary = (
                f"起始候選服務為 {onset.service}；另有 {cross_service_count} 個服務在限定的關聯視窗內接續出現訊號。"
            )
        else:
            title = "偵測到單一服務內的錯誤群集"
            summary = (
                f"主要起始候選事件集中在 {onset.service}；目前尚未建立跨服務擴散關係。"
            )
        confidence = min(
            0.92,
            0.48
            + (0.1 if repeated_count > 1 else 0)
            + (0.14 if cross_service_count else 0)
            + (0.12 if shared_identifier_count else 0),
        )
        details = [
            f"起始候選事件：{onset.timestamp_text} | {onset.service} | {onset.id}",
            f"主要正規化特徵出現次數：{repeated_count}",
            f"關聯視窗內的跨服務目標數：{cross_service_count}",
            f"共用識別碼關聯數：{shared_identifier_count}",
        ]
        if distractor is not None:
            details.append(
                f"保留為背景資訊的較早無關候選事件：{distractor.id}（{distractor.service}）"
            )
        return AgentFinding(
            agent=self.name,
            title=title,
            summary=summary,
            confidence=confidence,
            evidence=evidence,
            details=details,
        ), links


@dataclass(frozen=True)
class CauseRule:
    title: str
    explanation: str
    terms: tuple[str, ...]
    actions: tuple[str, ...]
    chain: tuple[str, ...]


CAUSE_RULES = (
    CauseRule(
        "資料庫連線池耗盡",
        "資料庫操作長時間占用連線，導致應用程式連線池耗盡、請求排隊，並觸發上游逾時。",
        ("slow query", "pool at capacity", "pool exhausted", "timed out waiting for database", "connection limit"),
        ("檢查最慢的資料庫查詢及其執行計畫。", "針對連線池等待時間與使用率設定告警。", "先進行範圍明確的查詢／索引修正，再考慮增加連線池大小。"),
        ("資料庫操作變慢", "連線池飽和", "請求開始排隊", "上游請求逾時"),
    ),
    CauseRule(
        "應用程式數值轉換溢位",
        "應用程式中的數值超出預期範圍，導致儲存操作失敗。",
        ("overflowexception", "value was either too large or too small", "int32", "overflow"),
        (
            "檢查引用事件中的堆疊位置，以及失敗邊界正在轉換的數值。",
            "確認請求模型與儲存層之間的數值型別和範圍檢查。",
            "部署範圍明確的修正前，先加入邊界值測試。",
        ),
        (
            "應用程式數值超出範圍",
            "數值轉換發生溢位",
            "儲存操作失敗",
            "前端請求失敗",
        ),
    ),
    CauseRule(
        "記憶體耗盡或程序資源壓力",
        "記憶體壓力造成配置失敗、程序終止或反覆重新啟動。",
        ("out of memory", "oom", "killed process", "heap", "memory limit"),
        ("擷取事故時間窗前後的記憶體剖析資料。", "檢查容器資源限制與重新啟動次數。", "新增記憶體飽和告警。"),
        ("記憶體持續成長", "達到資源上限", "程序中斷", "請求失敗"),
    ),
    CauseRule(
        "網路或上游相依服務故障",
        "連線或上游回應失敗進一步擴散，最終造成請求逾時。",
        ("connection refused", "dns", "network unreachable", "upstream timeout", "tls handshake"),
        ("檢查相依服務健康狀態與網路遙測資料。", "使用 trace ID 關聯錯誤事件。", "確認逾時與重試預算是否合理。"),
        ("相依服務劣化", "連線失敗", "重試／佇列壓力", "請求逾時"),
    ),
    CauseRule(
        "身分驗證或憑證失敗",
        "憑證遭拒絕或已過期，導致服務之間無法正常存取。",
        ("unauthorized", "forbidden", "token expired", "invalid credential", "401", "403"),
        ("確認憑證輪替與到期時間。", "稽核授權政策異動。", "新增憑證到期視窗告警。"),
        ("憑證或政策變更", "授權遭拒絕", "相依服務無法存取", "請求失敗"),
    ),
)


class RootCauseAgent:
    name = "Root Cause Agent"

    def analyze(
        self,
        events: list[LogEvent],
        specialist_findings: list[AgentFinding] | None = None,
        correlations: list[CorrelationLink] | None = None,
    ) -> tuple[AgentFinding, list[Hypothesis], CauseRule]:
        specialist_findings = specialist_findings or []
        correlations = correlations or []
        correlated_ids = {
            event_id
            for link in correlations
            for event_id in (link.source_event_id, link.target_event_id)
        }
        scored: list[tuple[int, CauseRule, list[LogEvent]]] = []
        for rule in CAUSE_RULES:
            matched = [e for e in events if _contains(e, *rule.terms)]
            diversity = len({term for term in rule.terms if any(_contains(e, term) for e in events)})
            correlated_matches = sum(event.id in correlated_ids for event in matched)
            score = len(matched) + diversity * 2 + min(correlated_matches, 3)
            scored.append((score, rule, matched))
        scored.sort(key=lambda item: item[0], reverse=True)
        hypotheses: list[Hypothesis] = []
        for score, rule, matched in scored[:3]:
            confidence = min(0.92, 0.28 + score * 0.07)
            service = Counter(event.service for event in matched).most_common(1)
            hypothesis_title = (
                f"{rule.title}（服務：{service[0][0]}）" if service else rule.title
            )
            hypothesis_explanation = (
                f"{rule.explanation} 最強的匹配證據來自 {service[0][0]}。"
                if service else rule.explanation
            )
            hypotheses.append(Hypothesis(
                title=hypothesis_title,
                explanation=hypothesis_explanation,
                confidence=confidence,
                supporting=[_ev(event, f"符合「{rule.title}」模式") for event in matched[:5]],
            ))
        best_score, best, matched = scored[0]
        leading_service = Counter(event.service for event in matched).most_common(1)
        leading_title = (
            f"{best.title}（服務：{leading_service[0][0]}）"
            if best_score and leading_service else best.title
        )
        leading_summary = hypotheses[0].explanation
        finding = AgentFinding(
            agent=self.name,
            title=leading_title if best_score else "根因證據不足",
            summary=leading_summary if best_score else "目前沒有任何已知原因模式具備足夠證據。",
            confidence=hypotheses[0].confidence if best_score else 0.25,
            evidence=[_ev(event, "支持主要根因假設") for event in matched[:5]],
            details=[
                f"使用了 {len(specialist_findings)} 個已驗證的專業 Agent 發現，以及 {len(correlations)} 條事件關聯。",
                f"已比較 {len(CAUSE_RULES)} 類可能原因。",
                f"主要規則分數：{best_score}。",
            ],
        )
        return finding, hypotheses, best

    def revise(
        self,
        hypotheses: list[Hypothesis],
        review: AgentFinding,
        prior_finding: AgentFinding | None = None,
    ) -> tuple[AgentFinding, list[Hypothesis]]:
        """Apply one bounded revision without inventing new source evidence."""
        leading = hypotheses[0]
        existing_ids = {item.event_id for item in leading.contradicting}
        new_contradictions = [
            item for item in review.evidence
            if item.stance == "contradicting" and item.event_id not in existing_ids
        ]
        revised_leading = Hypothesis(
            title=leading.title,
            explanation=(
                f"{leading.explanation} Reviewer 提醒：其他可能觸發因素仍未獲得證實。"
                if new_contradictions else leading.explanation
            ),
            confidence=max(0.2, leading.confidence - 0.06 * len(new_contradictions)),
            supporting=list(leading.supporting),
            contradicting=[*leading.contradicting, *new_contradictions],
        )
        revised = [revised_leading, *hypotheses[1:]]
        finding = AgentFinding(
            agent=self.name,
            title=f"修訂後：{revised_leading.title}",
            summary=revised_leading.explanation,
            confidence=revised_leading.confidence,
            evidence=[*revised_leading.supporting, *revised_leading.contradicting],
            details=[
                *(prior_finding.details if prior_finding else []),
                f"已納入 {len(new_contradictions)} 個 Reviewer 提出的反證。",
                "修訂過程沒有加入新的來源證據。",
            ],
        )
        return finding, revised


class ReviewerAgent:
    name = "Reviewer Agent"

    def analyze(self, events: list[LogEvent], hypotheses: list[Hypothesis]) -> AgentFinding:
        leading = hypotheses[0]
        deployments = [e for e in events if _contains_deployment_signal(e)]
        recovery = [e for e in events if _contains(e, "recovered", "returned to baseline", "latency normal")]
        healthy = [e for e in events if e.level == "INFO" and _contains(e, "completed", "healthy", "baseline")]
        evidence: list[Evidence] = []
        details: list[str] = []
        if deployments:
            event = deployments[0]
            evidence.append(_ev(event, "以部署時間挑戰主要原因", "contradicting"))
            details.append("競爭假設：近期部署可能也是影響因素。")
        if recovery:
            evidence.append(_ev(recovery[0], "恢復時間的關聯支持所提出的因果鏈"))
            details.append("恢復時間與主要假設一致。")
        if healthy:
            evidence.append(_ev(healthy[0], "其他服務的正常活動限制了事故影響範圍", "context"))
        confidence = max(0.35, min(0.9, leading.confidence - (0.06 if deployments else 0) + (0.06 if recovery else 0)))
        return AgentFinding(
            agent=self.name,
            title="主要假設通過審查" if confidence >= 0.6 else "證據仍不足以下結論",
            summary=(
                "因果鏈獲得證據支持，但部署是否造成影響仍未證實。"
                if deployments else "提供的 log 中沒有找到更強的競爭假設。"
            ),
            confidence=confidence,
            evidence=evidence,
            details=details or ["已檢查其他可能觸發因素、恢復時間關聯與正常服務訊號。"],
        )

    def finalize(self, hypotheses: list[Hypothesis], prior_review: AgentFinding) -> AgentFinding:
        leading = hypotheses[0]
        contradictions = list(leading.contradicting)
        acknowledged = bool(contradictions)
        return AgentFinding(
            agent=self.name,
            title="附帶提醒後接受修訂" if acknowledged else "接受主要假設",
            summary=(
                "主要假設受到證據約束，並保留其他可能觸發因素的提醒。"
                if acknowledged else "主要假設受到證據約束，且未找到更強的替代解釋。"
            ),
            confidence=max(0.35, min(0.9, leading.confidence + 0.03)),
            evidence=[*leading.supporting, *contradictions],
            details=[
                "已確認修訂內容只引用登錄過的來源事件。",
                *prior_review.details,
            ],
        )
