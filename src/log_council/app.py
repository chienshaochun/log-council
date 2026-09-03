from __future__ import annotations

import hashlib
from typing import Any

import streamlit as st

from log_council.reporting import build_safe_report, serialize_report


MAX_UPLOAD_BYTES = 50 * 1024 * 1024
AGENTS = (
    ("Pattern Agent", "尋找重複錯誤、burst 與異常模式"),
    ("Timeline Agent", "重建異常出現、擴散與恢復順序"),
    ("Correlation Agent", "依時間、服務與識別碼建立關聯"),
    ("Root Cause Agent", "比較並排序可能根因"),
    ("Reviewer Agent", "尋找反證、替代解釋與缺少的資料"),
)


def decode_upload(data: bytes) -> str:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"檔案超過 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB 上限")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("檔案不是有效的 UTF-8 文字") from exc


def input_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_text_size(text: str, limit: int = MAX_UPLOAD_BYTES) -> None:
    if len(text.encode("utf-8")) > limit:
        raise ValueError(f"輸入內容超過 {limit // (1024 * 1024)} MB 上限")


def cited_event_ids(payload: dict[str, Any]) -> list[str]:
    references: list[str] = []
    for finding in payload.get("findings", []):
        references.extend(item["event_id"] for item in finding.get("evidence", []))
    for hypothesis in payload.get("hypotheses", []):
        references.extend(item["event_id"] for item in hypothesis.get("supporting", []))
        references.extend(item["event_id"] for item in hypothesis.get("contradicting", []))
    for link in payload.get("correlations", []):
        references.extend((link["source_event_id"], link["target_event_id"]))
    for message in payload.get("agent_messages", []):
        references.extend(message.get("evidence_ids", []))
    return list(dict.fromkeys(references))


def _render_overview(payload: dict[str, Any]) -> None:
    summary = payload["summary"]
    stats = payload["parse"]["stats"]
    columns = st.columns(4)
    columns[0].metric("Log events", f"{stats['event_count']:,}")
    columns[1].metric("Parse coverage", f"{stats['coverage']:.1%}")
    columns[2].metric("Council confidence", f"{summary['confidence']:.0%}")
    columns[3].metric("Agent consensus", summary["consensus"])

    st.subheader("分析結論")
    leading = payload["hypotheses"][0]
    if summary["consensus_label"] == "high confidence":
        st.success(f"Leading hypothesis · {leading['title']}")
    elif summary["consensus_label"] == "moderate confidence":
        st.warning(f"Leading hypothesis · {leading['title']}")
    else:
        st.info(f"目前證據不足 · {leading['title']}")
    st.write(summary["root_cause"])
    st.caption(f"Reviewer caveat: {summary['caveat']}")

    st.subheader("Evidence chain")
    st.write(" → ".join(payload["evidence_chain"]))

    st.subheader("建議的下一步")
    for index, action in enumerate(payload["recommended_actions"], start=1):
        st.markdown(f"{index}. {action}")


def _render_evidence(payload: dict[str, Any]) -> None:
    st.subheader("Correlation links")
    correlations = payload.get("correlations", [])
    if correlations:
        st.dataframe(correlations, width="stretch", hide_index=True)
    else:
        st.info("目前沒有足夠資料建立 event-to-event correlation link。")

    st.subheader("Ranked hypotheses")
    for index, hypothesis in enumerate(payload["hypotheses"], start=1):
        with st.expander(
            f"{index}. {hypothesis['title']} · {hypothesis['confidence']:.0%}",
            expanded=index == 1,
        ):
            st.write(hypothesis["explanation"])
            supporting = hypothesis.get("supporting", [])
            contradicting = hypothesis.get("contradicting", [])
            if supporting:
                st.markdown("**Supporting evidence**")
                st.dataframe(supporting, width="stretch", hide_index=True)
            if contradicting:
                st.markdown("**Contradicting evidence**")
                st.dataframe(contradicting, width="stretch", hide_index=True)

    st.subheader("檢視被引用的原始事件")
    references = cited_event_ids(payload)
    events = {event["id"]: event for event in payload.get("events", [])}
    available = [event_id for event_id in references if event_id in events]
    if not available:
        st.info("這份報告沒有可檢視的引用事件。")
        return
    selected = st.selectbox("Evidence event ID", available)
    event = events[selected]
    st.json({key: value for key, value in event.items() if key != "raw"})
    st.code(event.get("raw") or event.get("message", ""), language="text")


def _render_agents(payload: dict[str, Any]) -> None:
    st.subheader("Agent findings")
    for finding in payload["findings"]:
        with st.expander(
            f"{finding['agent']} · {finding['title']} · {finding['confidence']:.0%}",
            expanded=finding["agent"] == "Root Cause Agent",
        ):
            st.write(finding["summary"])
            if finding.get("details"):
                for detail in finding["details"]:
                    st.markdown(f"- {detail}")
            if finding.get("evidence"):
                st.dataframe(finding["evidence"], width="stretch", hide_index=True)


def _render_handoffs(payload: dict[str, Any]) -> None:
    st.subheader("Agent message ledger")
    st.caption("訊息順序、回覆對象、payload 與 evidence references 都經過合約驗證。")
    st.dataframe(payload["agent_messages"], width="stretch", hide_index=True)

    st.subheader("Coordinator activities")
    st.dataframe(payload["activities"], width="stretch", hide_index=True)

    st.subheader("Reasoning handoffs")
    st.dataframe(payload["handoffs"], width="stretch", hide_index=True)


def _render_data_quality(payload: dict[str, Any]) -> None:
    parse = payload["parse"]
    stats = parse["stats"]
    st.subheader("Parse quality")
    st.json(stats)
    issues = parse["issues"]
    if issues:
        st.warning(f"保留了 {len(issues)} 個資料品質問題；沒有任何非空白行被靜默丟棄。")
        st.dataframe(issues, width="stretch", hide_index=True)
    else:
        st.success("所有非空白行都已解析，沒有資料品質問題。")

    events = payload.get("events", [])
    st.subheader("Redacted event preview")
    if len(events) > 500:
        st.caption(f"共 {len(events):,} 筆；畫面僅顯示前 500 筆，下載報告仍包含全部事件。")
    preview = [
        {
            "id": event["id"],
            "timestamp": event["timestamp"],
            "level": event["level"],
            "service": event["service"],
            "message": event["message"],
        }
        for event in events[:500]
    ]
    st.dataframe(preview, width="stretch", hide_index=True)


def _render_report(payload: dict[str, Any]) -> None:
    st.divider()
    st.caption(f"Run ID · {payload['run_id']}")
    overview, evidence, agents, handoffs, quality = st.tabs([
        "Overview",
        "Evidence",
        "Agents",
        "Handoffs",
        "Data quality",
    ])
    with overview:
        _render_overview(payload)
    with evidence:
        _render_evidence(payload)
    with agents:
        _render_agents(payload)
    with handoffs:
        _render_handoffs(payload)
    with quality:
        _render_data_quality(payload)

    st.download_button(
        "下載安全 JSON 報告",
        data=serialize_report(payload),
        file_name=f"log-council-{payload['run_id']}.json",
        mime="application/json",
        width="stretch",
    )


def main() -> None:
    st.set_page_config(
        page_title="LogCouncil",
        page_icon="🔎",
        layout="wide",
    )
    st.title("LogCouncil")
    st.markdown("**把 log 交給一組可稽核的 Agents，取得證據導向的事故解釋與下一步。**")
    st.caption("Local-first · logs only · read-only recommendations · no API key required")

    with st.sidebar:
        st.header("分析團隊")
        for name, responsibility in AGENTS:
            st.markdown(f"**{name}**  \n{responsibility}")
        st.divider()
        st.info("分析在本機執行。畫面與下載報告會遮蔽常見秘密；原始輸入不會被修改。")

    mode = st.radio("輸入方式", ("貼上 log", "上傳檔案"), horizontal=True)
    input_text = ""
    input_error: str | None = None
    if mode == "貼上 log":
        input_text = st.text_area(
            "Log 內容",
            height=220,
            placeholder=(
                '{"ts":"2026-09-03T10:00:00Z","level":"ERROR",'
                '"service":"checkout","message":"request timeout"}'
            ),
        )
    else:
        upload = st.file_uploader(
            "選擇 UTF-8 log",
            type=("log", "txt", "jsonl"),
            help="最大 50 MB；檔案只在本機分析。",
        )
        if upload is not None:
            try:
                input_text = decode_upload(upload.getvalue())
            except ValueError as exc:
                input_error = str(exc)
                st.error(input_error)

    analyze = st.button("開始分析", type="primary", width="stretch")
    if analyze:
        if input_error:
            st.error("請先修正輸入檔案。")
        elif not input_text.strip():
            st.error("請貼上 log 或選擇一個 log 檔案。")
        else:
            try:
                validate_text_size(input_text)
            except ValueError as exc:
                st.error(str(exc))
            else:
                with st.spinner("五個 Agents 正在比對證據…"):
                    try:
                        payload = build_safe_report(input_text, include_events=True)
                    except Exception as exc:  # UI boundary: failures must remain visible
                        st.session_state.pop("analysis_payload", None)
                        st.error(f"分析失敗：{exc}")
                    else:
                        st.session_state["analysis_payload"] = payload
                        st.session_state["analysis_digest"] = input_digest(input_text)

    payload = st.session_state.get("analysis_payload")
    if payload is not None:
        if input_digest(input_text) != st.session_state.get("analysis_digest"):
            st.warning("輸入內容已變更；請重新按「開始分析」以更新結果。")
        else:
            _render_report(payload)


if __name__ == "__main__":
    main()
